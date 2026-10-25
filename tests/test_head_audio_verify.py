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
                                     stderr=subprocess.DEVNULL))
        calls = [ast.unparse(node.func) for node in ast.walk(ast.parse(args[0][2]))
                 if isinstance(node, ast.Call)]
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
                'elapsed_seconds=4.456 exit_status=%s' % (category, status)])
            self.assertNotIn('private', ''.join(logs.output))

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
