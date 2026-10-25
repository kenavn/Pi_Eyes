"""Load-only verification stays isolated, bounded and private on failure."""
import ast
import os
from pathlib import Path
from types import SimpleNamespace
import subprocess
import sys
import unittest
from unittest.mock import patch

from nightweaver_head.engine import PygamePorts
from nightweaver_head.wire import Refusal


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
        self.ports.pg = SimpleNamespace(mixer=SimpleNamespace(music=SimpleNamespace(
            load=lambda path: self.assertEqual(path, resource.path), unload=lambda: None)))
        self.ports.load(resource)
        self.ports.dispose()
        self.assertTrue(os.path.exists(resource.path))
        path = resource.path
        resource.close()
        resource.close()
        self.assertFalse(os.path.exists(path))

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
