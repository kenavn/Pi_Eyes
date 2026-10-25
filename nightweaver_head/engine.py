"""One synchronous output owner. Cancellation fences every authored send and loop."""
import io
import logging
import os
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time
import wave
from .wire import Refusal


AUDIO_VERIFY_TIMEOUT_SECONDS = 8
_LOG = logging.getLogger(__name__)


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


class BundlePlayer:
    """Reusable engine; preparing immutable bundles never selects the music slot."""
    def __init__(self, ports, clock=None):
        self.ports = ports
        self.clock = clock or Clock()
        self.audio_position_us = None

    def run(self, bundle, audio, cancelled, delay_us=0, resume_auto=True, loop=False, started=None, fence=None, target=None):
        failure = None
        try:
            while not cancelled.is_set():
                if fence:
                    fence()
                if bundle.audio:
                    self.ports.load(audio)
                if cancelled.is_set():
                    break
                if fence:
                    fence()
                if target is not None:
                    while not cancelled.is_set() and self.clock.now() < target:
                        self.clock.wait(cancelled, min(1000, target - self.clock.now()))
                        if fence:
                            fence()
                    target = None
                if cancelled.is_set():
                    break
                if fence:
                    fence()
                self.ports.auto(False)
                if cancelled.is_set():
                    break
                if fence:
                    fence()
                origin = self.clock.now()
                if bundle.audio:
                    self.ports.play()
                if started:
                    started()
                index, last_position, last_observed = 0, None, None
                physical = max(int(bundle.facts['audio_extent_us']),
                               int(bundle.facts['movement_extent_us']) + max(0, delay_us)
                               if bundle.frames else 0)
                while not cancelled.is_set():
                    now = self.clock.now()
                    elapsed = now - origin
                    if elapsed > physical + 5000000:
                        raise Refusal('worker_failure', 503)
                    if bundle.audio:
                        position = self.ports.position()
                        busy = self.ports.busy()
                        if position >= 0:
                            # Decoder observations must never move source motion backwards.
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
                            # A transient -1 while busy is not decoder completion.
                            self.clock.wait(cancelled, 1000)
                            continue
                        else:
                            progress = last_position + now - last_observed
                    else:
                        busy = False
                        progress = elapsed
                    if progress >= max(0, delay_us):
                        source = progress - max(0, delay_us)
                        while index < len(bundle.frames) and bundle.frames[index].at_us <= source:
                            if cancelled.is_set():
                                break
                            self.ports.frame(bundle.frames[index])
                            index += 1
                    if progress >= physical and not busy and index == len(bundle.frames):
                        break
                    self.clock.wait(cancelled, 1000)
                if not loop or cancelled.is_set():
                    break
                self.ports.stop()
        except Refusal as error:
            failure = error.reason
        except Exception:
            failure = 'worker_failure'
        finally:
            # Return only after stop, restoration and disposal have actually returned.
            try:
                self.ports.stop()
                if resume_auto:
                    self.ports.auto(True)
                self.ports.dispose()
            except Exception:
                failure = 'unknown_outcome'
        return failure


class PygamePorts:
    """Lazy production adapter; only the worker touches process-global music."""
    def __init__(self, sink_name, eye_port=5005, mouth_port=5006):
        self.sink_name, self.eye_port, self.mouth_port = sink_name, eye_port, mouth_port
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
        """Write and verify once without touching the active music selection."""
        if not self.ready:
            raise Refusal('audio_unavailable', 503)
        fd, path = tempfile.mkstemp(suffix='.wav')
        resource = PreparedAudio(path)
        try:
            with os.fdopen(fd, 'wb') as stream:
                stream.write(audio)
            read_fd = write_fd = -1
            try:
                try:
                    read_fd, write_fd = os.pipe()
                    os.set_blocking(read_fd, False)
                except OSError:
                    for diagnostic_fd in (read_fd, write_fd):
                        if diagnostic_fd >= 0:
                            os.close(diagnostic_fd)
                    read_fd = write_fd = -1
                code = """import os, sys
fd = int(sys.argv[2])
def mark(stage):
    try:
        os.write(fd, (stage + '\\n').encode('ascii'))
    except OSError:
        pass
mark('bootstrap')
mark('import_begin')
import pygame
mark('import_done')
mark('init_begin')
pygame.mixer.init(frequency=48000, size=-16, channels=2)
mark('init_done')
mark('load_begin')
pygame.mixer.music.load(sys.argv[1])
mark('load_done')
mark('quit_begin')
pygame.mixer.quit()
mark('quit_done')
"""
                started = time.monotonic()
                try:
                    subprocess.run([sys.executable, '-c', code, path, str(write_fd)],
                                   timeout=AUDIO_VERIFY_TIMEOUT_SECONDS, check=True,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                   pass_fds=(write_fd,) if write_fd >= 0 else ())
                except (subprocess.SubprocessError, OSError) as error:
                    # run has joined the child, including after timeout: never wait for EOF.
                    last_stage = 'unknown'
                    if read_fd >= 0:
                        try:
                            records = os.read(read_fd, 1024).split(b'\n')[:-1]
                        except OSError:
                            records = ()
                        stages = {b'bootstrap', b'import_begin', b'import_done', b'init_begin',
                                  b'init_done', b'load_begin', b'load_done', b'quit_begin',
                                  b'quit_done'}
                        for record in records:
                            if record in stages:
                                last_stage = record.decode('ascii')
                    category = ('timeout' if isinstance(error, subprocess.TimeoutExpired) else
                                'nonzero' if isinstance(error, subprocess.CalledProcessError) else 'spawn')
                    status = (max(-255, min(255, error.returncode))
                              if isinstance(error, subprocess.CalledProcessError) else None)
                    elapsed = min(86400.0, max(0.0, time.monotonic() - started))
                    _LOG.warning('audio_verify_failed category=%s elapsed_seconds=%.3f exit_status=%s '
                                 'last_stage=%s', category, elapsed, status, last_stage)
                    raise Refusal('audio_unavailable', 503) from None
            finally:
                for diagnostic_fd in (read_fd, write_fd):
                    if diagnostic_fd >= 0:
                        os.close(diagnostic_fd)
            return resource
        except BaseException as error:
            try:
                resource.close()
            except Exception:
                # Preserve ownership when unlink cannot be proven; never advertise quiet.
                error.prepared_audio = resource
            raise

    def load(self, audio):
        self.pg.mixer.music.load(audio.path)
        if self.idle_audio is not None:
            self.idle_audio.close()
            self.idle_audio = None
        self.path = audio.path

    def play(self):
        self.pg.mixer.music.play()

    def position(self):
        return self.pg.mixer.music.get_pos() * 1000

    def busy(self):
        return self.pg.mixer.music.get_busy()

    def stop(self):
        if self.pg is not None:
            self.pg.mixer.music.stop()

    def send(self, payload, port):
        self.sock.sendto(payload, ('127.0.0.1', port))

    def auto(self, enabled):
        # Release playback-held blink latches before automatic idle modes resume.
        for command in ((b'\x45', b'\x00', b'\x11', b'\x13', b'\x15') if enabled
                        else (b'\x01', b'\x10', b'\x12', b'\x14')):
            self.send(command, self.eye_port)

    def frame(self, frame):
        if frame.kind == 'mouth':
            self.send(b'\x50' + struct.pack('B', *frame.values), self.mouth_port)
        else:
            x, y, left, right, both = frame.values
            self.send(b'\x20' + struct.pack('BB', int(x * 255), int(y * 255)), self.eye_port)
            self.send(b'\x40' if left or both else b'\x41', self.eye_port)
            self.send(b'\x42' if right or both else b'\x43', self.eye_port)

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
