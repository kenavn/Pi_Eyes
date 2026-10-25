"""Load-only verification stays isolated, bounded and private on failure."""
import ast
import os
import io
import wave
from pathlib import Path
from types import SimpleNamespace
import subprocess
import sys
import unittest
from unittest.mock import patch

from nightweaver_head.engine import PygamePorts
from nightweaver_head.wire import Refusal


class Music196:
    """Only the target's music surface; successful load replaces its RWops owner."""
    def __init__(self):
        self.selected = None
        self.fail = False
        self.events = []

    def load(self, source):
        self.events.append(('load', source))
        if self.fail:
            raise RuntimeError('decoder held')
        self.selected = source

    def stop(self):
        self.events.append(('stop',))


class Mixer196:
    def __init__(self, music):
        self.music = music

    def quit(self):
        if isinstance(self.music.selected, io.BytesIO):
            assert not self.music.selected.closed
        self.music.events.append(('quit',))
        self.music.selected = None


class AudioVerifyTests(unittest.TestCase):
    def setUp(self):
        self.ports = PygamePorts('private-sink')
        self.ports.ready = True

    @patch('nightweaver_head.engine.subprocess.run')
    def test_success_has_eight_second_guard_and_only_loads_audio(self, run):
        resource = self.ports.prepare_audio(b'private-audio')
        run.assert_called_once()
        args, kwargs = run.call_args
        self.assertEqual(args[0][:2], [sys.executable, '-c'])
        self.assertEqual(kwargs, dict(timeout=8, check=True, stdout=subprocess.DEVNULL,
                                     stderr=subprocess.DEVNULL, pass_fds=(int(args[0][4]),)))
        calls = [ast.unparse(node.func) for node in ast.walk(ast.parse(args[0][2]))
                 if isinstance(node, ast.Call) and ast.unparse(node.func).startswith('pygame.')]
        self.assertEqual(calls, ['pygame.mixer.init', 'pygame.mixer.music.load',
                                 'pygame.mixer.quit'])
        self.assertIsNone(self.ports.pg)
        self.assertIsNone(self.ports.path)
        self.assertEqual(Path(resource.path).read_bytes(), b'private-audio')
        music = Music196()
        self.ports.pg = SimpleNamespace(mixer=Mixer196(music))
        self.ports.load(resource)
        self.assertEqual(music.selected, resource.path)
        self.ports.dispose()
        self.assertTrue(os.path.exists(resource.path))
        path = resource.path
        resource.close()
        resource.close()
        self.assertFalse(os.path.exists(path))
        self.ports.close()

    def test_failures_refuse_with_only_sanitized_local_diagnostics(self):
        failures = [
            (subprocess.TimeoutExpired('private-command', 8, output=b'private-output',
                                       stderr=b'private-stderr'), 'timeout', 'None'),
            (subprocess.CalledProcessError(999999, 'private-command', output=b'private-output',
                                          stderr=b'private-stderr'), 'nonzero', '255'),
            (OSError('private-path private-credential'), 'spawn', 'None'),
            (subprocess.CalledProcessError(-9, 'private-command'), 'nonzero', '-9'),
        ]
        for error, category, status in failures:
            with self.subTest(category=category), \
                    patch('nightweaver_head.engine.subprocess.run', side_effect=error), \
                    patch('nightweaver_head.engine.time.monotonic', side_effect=[10.0, 14.456]), \
                    self.assertLogs('nightweaver_head.engine', level='WARNING') as logs:
                with self.assertRaises(Refusal) as refused:
                    self.ports.prepare_audio(b'private-audio')
            self.assertEqual((refused.exception.reason, refused.exception.status),
                             ('audio_unavailable', 503))
            self.assertEqual(logs.output, [
                'WARNING:nightweaver_head.engine:audio_verify_failed category=%s '
                'elapsed_seconds=4.456 exit_status=%s last_stage=unknown' % (category, status)])
            self.assertNotIn('private', ''.join(logs.output))

    @patch('nightweaver_head.engine.subprocess.run')
    def test_child_marks_actual_import_init_load_and_quit_without_play(self, run):
        resource = self.ports.prepare_audio(b'audio')
        code = run.call_args.args[0][2]
        read_fd, write_fd = os.pipe()
        events = []
        mixer = SimpleNamespace(
            init=lambda **kwargs: events.append(('init', kwargs)),
            music=SimpleNamespace(load=lambda path: events.append(('load', path))),
            quit=lambda: events.append(('quit',)))
        try:
            with patch.dict(sys.modules, pygame=SimpleNamespace(mixer=mixer)), \
                    patch.object(sys, 'argv', ['-c', resource.path, str(write_fd)]):
                exec(code, {})
            self.assertEqual(os.read(read_fd, 1024).decode('ascii').splitlines(), [
                'bootstrap', 'import_begin', 'import_done', 'init_begin', 'init_done',
                'load_begin', 'load_done', 'quit_begin', 'quit_done'])
            self.assertEqual(events, [('init', dict(frequency=48000, size=-16, channels=2)),
                                      ('load', resource.path), ('quit',)])
            # A missing diagnostic FD cannot make a valid decoder verification fail.
            with patch.dict(sys.modules, pygame=SimpleNamespace(mixer=mixer)), \
                    patch.object(sys, 'argv', ['-c', resource.path, '-1']):
                exec(code, {})
        finally:
            os.close(read_fd)
            os.close(write_fd)
            resource.close()

    def test_stage_records_are_bounded_whitelisted_and_complete(self):
        cases = [(b'bootstrap\ninit_begin\n', 'init_begin'),
                 (b'load_done\nprivate-secret\nquit_beg', 'load_done'),
                 (b'unknown\n' + b'x' * 1100 + b'\nquit_done\n', 'unknown'),
                 (b'', 'unknown')]
        for payload, expected in cases:
            descriptors = []
            def fail(args, **kwargs):
                fd = kwargs['pass_fds'][0]
                descriptors.append(fd)
                os.write(fd, payload)
                # The verifier input must remain owned until run has returned.
                self.assertTrue(Path(args[3]).exists())
                raise subprocess.TimeoutExpired('private-command', 8)
            with self.subTest(expected=expected), \
                    patch('nightweaver_head.engine.subprocess.run', side_effect=fail), \
                    self.assertLogs('nightweaver_head.engine', level='WARNING') as logs:
                with self.assertRaises(Refusal):
                    self.ports.prepare_audio(b'private-audio')
            self.assertTrue(logs.output[0].endswith('last_stage=' + expected))
            self.assertNotIn('private', logs.output[0])
            for fd in descriptors:
                with self.assertRaises(OSError):
                    os.fstat(fd)

    def test_pipe_descriptors_close_on_every_subprocess_outcome(self):
        real_pipe = os.pipe
        for error in (None, OSError('spawn'), subprocess.CalledProcessError(-9, 'cmd'),
                      subprocess.TimeoutExpired('cmd', 8)):
            descriptors = []
            def allocate():
                pair = real_pipe()
                descriptors.extend(pair)
                return pair
            with self.subTest(error=error), \
                    patch('nightweaver_head.engine.os.pipe', side_effect=allocate), \
                    patch('nightweaver_head.engine.subprocess.run', side_effect=error):
                if error:
                    with self.assertLogs('nightweaver_head.engine', level='WARNING'), \
                            self.assertRaises(Refusal):
                        self.ports.prepare_audio(b'audio')
                else:
                    self.ports.prepare_audio(b'audio').close()
            for fd in descriptors:
                with self.assertRaises(OSError):
                    os.fstat(fd)

    def test_diagnostic_setup_failure_does_not_change_success(self):
        real_pipe = os.pipe
        for failing_operation in ('pipe', 'set_blocking'):
            descriptors = []
            def allocate():
                pair = real_pipe()
                descriptors.extend(pair)
                return pair
            with self.subTest(operation=failing_operation), \
                    patch('nightweaver_head.engine.os.pipe', side_effect=(
                        OSError('private') if failing_operation == 'pipe' else allocate)), \
                    patch('nightweaver_head.engine.os.set_blocking', side_effect=OSError('private')), \
                    patch('nightweaver_head.engine.subprocess.run') as run:
                self.ports.prepare_audio(b'audio').close()
            self.assertEqual(run.call_args.kwargs['pass_fds'], ())
            for fd in descriptors:
                with self.assertRaises(OSError):
                    os.fstat(fd)

    def test_diagnostic_read_failure_keeps_original_refusal_and_closes_fds(self):
        descriptors = []
        real_pipe = os.pipe
        def allocate():
            pair = real_pipe()
            descriptors.extend(pair)
            return pair
        with patch('nightweaver_head.engine.os.pipe', side_effect=allocate), \
                patch('nightweaver_head.engine.os.read', side_effect=OSError('private')), \
                patch('nightweaver_head.engine.subprocess.run',
                      side_effect=subprocess.CalledProcessError(-9, 'private')), \
                self.assertLogs('nightweaver_head.engine', level='WARNING') as logs:
            with self.assertRaises(Refusal) as refused:
                self.ports.prepare_audio(b'audio')
        self.assertEqual(refused.exception.reason, 'audio_unavailable')
        self.assertTrue(logs.output[0].endswith('exit_status=-9 last_stage=unknown'))
        for fd in descriptors:
            with self.assertRaises(OSError):
                os.fstat(fd)

    @patch('nightweaver_head.engine.subprocess.run')
    def test_not_ready_refuses_without_spawning(self, run):
        self.ports.ready = False
        with self.assertRaises(Refusal) as refused:
            self.ports.prepare_audio(b'private-audio')
        self.assertEqual((refused.exception.reason, refused.exception.status),
                         ('audio_unavailable', 503))
        run.assert_not_called()

    @patch('nightweaver_head.engine.subprocess.run')
    def test_target_cleanup_replaces_with_unplayed_pcm_and_keeps_buffer_until_quit(self, run):
        music = Music196()
        self.ports.pg = SimpleNamespace(mixer=Mixer196(music))
        resource = self.ports.prepare_audio(b'original')
        self.ports.load(resource)
        self.ports.dispose()
        idle = self.ports.idle_audio
        self.assertEqual(music.events[-2:], [('stop',), ('load', idle)])
        self.assertIs(music.selected, idle)
        self.assertFalse(idle.closed)
        with wave.open(idle, 'rb') as stream:
            self.assertEqual((stream.getnchannels(), stream.getsampwidth(), stream.getframerate(),
                              stream.getnframes(), stream.readframes(1)), (2, 2, 48000, 1, b'\0' * 4))
        resource.close()
        self.ports.close()
        self.assertTrue(idle.closed)
        self.assertEqual(music.events[-2:], [('stop',), ('quit',)])

    @patch('nightweaver_head.engine.subprocess.run')
    def test_failed_idle_replacement_retains_selected_prepared_resource(self, run):
        music = Music196()
        self.ports.pg = SimpleNamespace(mixer=Mixer196(music))
        resource = self.ports.prepare_audio(b'original')
        self.ports.load(resource)
        music.fail = True
        with self.assertRaises(RuntimeError):
            self.ports.dispose()
        self.assertEqual(music.selected, resource.path)
        self.assertEqual(self.ports.path, resource.path)
        self.assertTrue(os.path.exists(resource.path))
        self.assertTrue(music.events[-1][1].closed)
        self.assertIsNone(self.ports.idle_audio)
        self.ports.close()
        resource.close()

    @patch('nightweaver_head.engine.subprocess.run')
    def test_next_load_releases_idle_buffer_only_after_success(self, run):
        music = Music196()
        self.ports.pg = SimpleNamespace(mixer=Mixer196(music))
        resource = self.ports.prepare_audio(b'original')
        self.ports.load(resource)
        self.ports.dispose()
        first = self.ports.idle_audio
        music.fail = True
        with self.assertRaises(RuntimeError):
            self.ports.load(resource)
        self.assertIs(music.selected, first)
        self.assertFalse(first.closed)
        music.fail = False
        self.ports.load(resource)
        self.assertTrue(first.closed)
        self.assertIsNone(self.ports.idle_audio)
        self.ports.dispose()
        second = self.ports.idle_audio
        self.assertIsNot(second, first)
        self.assertFalse(second.closed)
        self.ports.close()
        self.assertTrue(second.closed)
        resource.close()
