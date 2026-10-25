"""One synchronous output owner. Cancellation fences every authored send and loop."""
import logging
import os
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time
from .wire import Refusal


AUDIO_VERIFY_TIMEOUT_SECONDS = 8
_LOG = logging.getLogger(__name__)


class Clock:
    def now(self):
        return time.clock_gettime_ns(time.CLOCK_MONOTONIC_RAW) // 1000

    def wait(self, cancelled, us):
        cancelled.wait(max(0, us) / 1000000)


class BundlePlayer:
    """Reusable engine; preparing immutable bundles never selects the music slot."""
    def __init__(self, ports, clock=None):
        self.ports = ports
        self.clock = clock or Clock()
        self.audio_position_us = None

    def run(self, bundle, cancelled, delay_us=0, resume_auto=True, loop=False, started=None, fence=None):
        failure = None
        try:
            while not cancelled.is_set():
                if bundle.audio:
                    self.ports.load(bundle.audio)
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

    def verify(self, audio):
        """Separate bounded process cannot replace active pygame.music selection."""
        if not self.ready:
            raise Refusal('audio_unavailable', 503)
        with tempfile.NamedTemporaryFile(suffix='.wav') as stream:
            stream.write(audio)
            stream.flush()
            code = ('import pygame,sys;pygame.mixer.init(frequency=48000,size=-16,channels=2);'
                    'pygame.mixer.music.load(sys.argv[1]);pygame.mixer.quit()')
            started = time.monotonic()
            try:
                subprocess.run([sys.executable, '-c', code, stream.name], timeout=AUDIO_VERIFY_TIMEOUT_SECONDS,
                               check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except (subprocess.SubprocessError, OSError) as error:
                category = ('timeout' if isinstance(error, subprocess.TimeoutExpired) else
                            'nonzero' if isinstance(error, subprocess.CalledProcessError) else 'spawn')
                status = (max(-255, min(255, error.returncode))
                          if isinstance(error, subprocess.CalledProcessError) else None)
                elapsed = min(86400.0, max(0.0, time.monotonic() - started))
                # Local diagnostics deliberately exclude exception text, child output and paths.
                _LOG.warning('audio_verify_failed category=%s elapsed_seconds=%.3f exit_status=%s',
                             category, elapsed, status)
                raise Refusal('audio_unavailable', 503) from None

    def load(self, audio):
        fd, self.path = tempfile.mkstemp(suffix='.wav')
        with os.fdopen(fd, 'wb') as stream:
            stream.write(audio)
        self.pg.mixer.music.load(self.path)

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
        for command in ((b'\x00', b'\x11', b'\x13', b'\x15') if enabled
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
        if self.path:
            os.unlink(self.path)
            self.path = None

    def close(self):
        self.stop()
        self.dispose()
        if self.sock:
            self.sock.close()
        if self.pg:
            self.pg.mixer.quit()
        self.ready = False
