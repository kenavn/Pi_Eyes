"""One synchronous output owner. Cancellation fences every authored send and loop."""
import io
import os
import socket
import struct
import tempfile
import time
import wave
from .wire import Refusal
from .bundle import Frame


class Clock:
    def now(self):
        return time.clock_gettime_ns(time.CLOCK_MONOTONIC_RAW) // 1000

    def wait(self, cancelled, us):
        cancelled.wait(max(0, us) / 1000000)


class PreparedAudio:
    """Session-owned decoder input; output workers only borrow its retained file."""
    def __init__(self, path):
        self.path = path

    def close(self):
        if self.path is not None:
            os.unlink(self.path)
            self.path = None


class ProgramPlayer:
    """A whole immutable program borrows the already-selected native decoder."""
    def __init__(self, ports, clock=None):
        self.ports = ports
        self.clock = clock or Clock()
        self.audio_position_us = None

    def run(self, program, audio, cancelled, started=None, fence=None, target=None):
        failure, active_use = None, None
        if hasattr(self.ports, 'bind_cancellation'):
            self.ports.bind_cancellation(cancelled)
        try:
            while target is not None and self.clock.now() < target and not cancelled.is_set():
                if fence:
                    fence()
                self.clock.wait(cancelled, min(1000, target - self.clock.now()))
            if cancelled.is_set():
                return None
            if fence:
                fence()
            if program.audio and audio is None:
                raise Refusal('audio_unavailable', 503)
            origin = self.clock.now()
            if program.audio:
                self.ports.play()
            if started:
                started()
            index, last_position, last_observed = 0, None, None
            physical = int(program.facts['duration_us'])
            if program.facts['audio'] is not None:
                facts = program.facts['audio']
                physical = max(physical, (int(facts['frames']) * 1000000 + facts['sample_rate'] - 1) // facts['sample_rate'])
            while not cancelled.is_set():
                now = self.clock.now()
                elapsed = now - origin
                if elapsed > physical + 5000000:
                    raise Refusal('worker_failure', 503)
                if program.audio:
                    position, busy = self.ports.position(), self.ports.busy()
                    if position >= 0:
                        last_position = max(position, last_position or 0)
                        last_observed = now
                        self.audio_position_us = last_position
                        progress = last_position
                    elif last_position is None:
                        if not busy or elapsed >= 5000000:
                            raise Refusal('worker_failure', 503)
                        self.clock.wait(cancelled, 1000)
                        continue
                    elif busy:
                        self.clock.wait(cancelled, 1000)
                        continue
                    else:
                        progress = last_position + now - last_observed
                else:
                    progress, busy = elapsed, False
                while index < len(program.events) and program.events[index][0] <= progress:
                    if cancelled.is_set():
                        break
                    _, event = program.events[index]
                    use = program.manifest['uses'][int(event['use_id'])]
                    kind = event['event']['kind']
                    if kind == 'begin':
                        active_use = use
                        self.ports.auto(False)
                    elif kind == 'end':
                        if use['resume_auto']:
                            self.ports.auto(True)
                        active_use = None
                    else:
                        payload = event['event']
                        values = ((payload['position'],) if kind == 'mouth' else
                                  (payload['x'], payload['y'], payload['left_closed'],
                                   payload['right_closed'], payload['both_closed']))
                        self.ports.frame(Frame(progress, kind, values))
                    index += 1
                if progress >= physical and not busy and index == len(program.events):
                    break
                self.clock.wait(cancelled, 1000)
        except Refusal as error:
            failure = error.reason
        except Exception:
            failure = 'worker_failure'
        finally:
            try:
                self.ports.stop()
                if active_use is not None and active_use['resume_auto']:
                    self.ports.auto(True)
            except Exception:
                failure = 'unknown_outcome'
        return failure


class PygamePorts:
    """Lazy production adapter; sole output owner selects during quiet setup."""
    def __init__(self, sink_name, eye_port=5005, mouth_port=5006, route_check=None):
        self.sink_name, self.eye_port, self.mouth_port = sink_name, eye_port, mouth_port
        self.route_check = route_check
        self.pg = self.sock = self.path = None
        self.idle_audio = None
        self.ready = False

    def initialize(self):
        os.environ['PULSE_SINK'] = self.sink_name
        import pygame
        self.pg = pygame
        if not pygame.mixer.get_init():
            pygame.mixer.init(frequency=48000, size=-16, channels=2)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.settimeout(0.25)
        self.ready = True

    def prepare_audio(self, audio):
        """Select on this process's initialized mixer, only during quiet Prepare."""
        if not self.ready or not self.pg.mixer.get_init():
            raise Refusal('audio_unavailable', 503)
        if self.route_check is not None:
            try:
                self.route_check()
            except Exception:
                raise Refusal('audio_unavailable', 503) from None
        fd, path = tempfile.mkstemp(suffix='.wav')
        resource = PreparedAudio(path)
        try:
            with os.fdopen(fd, 'wb') as stream:
                stream.write(audio)
            self.load(resource)
            return resource
        except Exception as error:
            # Failed SDL selection can still own the input until quiet disposal joins.
            refusal = Refusal('audio_unavailable', 503)
            refusal.prepared_audio = resource
            raise refusal from error

    def load(self, audio):
        self.path = audio.path
        self.pg.mixer.music.load(audio.path)
        if self.idle_audio is not None:
            self.idle_audio.close()
            self.idle_audio = None

    def play(self):
        self.pg.mixer.music.play()

    def position(self):
        return self.pg.mixer.music.get_pos() * 1000

    def busy(self):
        return self.pg.mixer.music.get_busy()

    def stop(self):
        if self.pg is not None:
            self.pg.mixer.music.stop()

    def bind_cancellation(self, cancelled):
        self.cancelled = cancelled

    def send(self, payload, port, authored=False):
        if authored and getattr(self, 'cancelled', None) is not None and self.cancelled.is_set():
            return
        self.sock.sendto(payload, ('127.0.0.1', port))

    def auto(self, enabled):
        # Release playback-held blink latches before automatic idle modes resume.
        for command in ((b'\x45', b'\x00', b'\x11', b'\x13', b'\x15') if enabled
                        else (b'\x01', b'\x10', b'\x12', b'\x14')):
            self.send(command, self.eye_port, authored=not enabled)

    def frame(self, frame):
        if frame.kind == 'mouth':
            self.send(b'\x50' + struct.pack('B', *frame.values), self.mouth_port, authored=True)
        else:
            x, y, left, right, both = frame.values
            self.send(b'\x20' + struct.pack('BB', int(x * 255), int(y * 255)), self.eye_port, authored=True)
            self.send(b'\x40' if left or both else b'\x41', self.eye_port, authored=True)
            self.send(b'\x42' if right or both else b'\x43', self.eye_port, authored=True)

    def dispose(self):
        if self.pg is not None and self.path is not None:
            self.stop()
            # pygame 1.9.6 frees the old decoder only on successful replacement.
            # Keep this unplayed file object alive while SDL owns its RWops.
            idle = io.BytesIO()
            with wave.open(idle, 'wb') as stream:
                stream.setnchannels(2)
                stream.setsampwidth(2)
                stream.setframerate(48000)
                stream.writeframes(b'\0' * 4)
            idle.seek(0)
            try:
                self.pg.mixer.music.load(idle)
            except Exception:
                idle.close()
                raise
            if self.idle_audio is not None:
                self.idle_audio.close()
            self.idle_audio = idle
        self.path = None

    def close(self):
        self.stop()
        if self.pg:
            self.pg.mixer.quit()
        # Mixer shutdown must release RWops before its Python buffer is closed.
        self.path = None
        if self.idle_audio is not None:
            self.idle_audio.close()
            self.idle_audio = None
        if self.sock:
            self.sock.close()
        self.ready = False
