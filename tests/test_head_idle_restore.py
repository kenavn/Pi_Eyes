"""Exercise production restoration against the repository's real UDP consumer."""
import ast
from pathlib import Path
import queue
import struct
import threading
import unittest
from unittest.mock import Mock

from nightweaver_head.engine import ProgramPlayer, PygamePorts
from nightweaver_head.program import inspect_program
from head_support import FakeClock, program


class EyeConsumer:
    def __init__(self):
        path = Path(__file__).resolve().parents[1] / 'eyes.py'
        tree = ast.parse(path.read_text())
        functions = [node for node in tree.body if isinstance(node, ast.FunctionDef)
                     and node.name in ('decode_message', 'process_udp_messages')]
        if len(functions) != 2:
            raise AssertionError('expected real eye decoder and queue consumer')
        self.state = dict(struct=struct, Empty=queue.Empty, message_queue=queue.Queue(),
                          joystick_connected=False, blink_left_active=False,
                          blink_right_active=False)
        for name in ('auto_movement', 'auto_blink', 'auto_pupil',
                     'prev_auto_movement', 'prev_auto_blink', 'prev_auto_pupil'):
            self.state[name] = True
        exec(compile(ast.Module(body=functions, type_ignores=[]), str(path), 'exec'), self.state)

    def receive(self, payload):
        self.state['message_queue'].put(self.state['decode_message'](payload))
        self.state['process_udp_messages']()

    def latches(self):
        return self.state['blink_left_active'], self.state['blink_right_active']


class IdleRestoreTests(unittest.TestCase):
    def ports(self, consumer):
        ports = PygamePorts('unused')
        ports.sock = Mock()
        ports.sock.sendto.side_effect = lambda payload, address: consumer.receive(payload)
        return ports

    def assert_idle(self, consumer):
        self.assertEqual(consumer.latches(), (False, False))
        self.assertFalse(consumer.state['joystick_connected'])
        for mode in ('auto_movement', 'auto_blink', 'auto_pupil'):
            self.assertTrue(consumer.state[mode], mode)

    def test_real_auto_releases_each_hold_before_automatic_modes_resume(self):
        for hold in (b'\x40', b'\x42', b'\x44'):
            with self.subTest(hold=hold):
                consumer = EyeConsumer()
                ports = self.ports(consumer)
                ports.auto(False)
                consumer.receive(hold)
                self.assertTrue(any(consumer.latches()))
                observations = []
                def receive(payload, address):
                    consumer.receive(payload)
                    observations.append((consumer.latches(), consumer.state['joystick_connected']))
                    self.assertEqual(address, ('127.0.0.1', ports.eye_port))
                ports.sock.sendto.side_effect = receive
                ports.auto(True)
                self.assert_idle(consumer)
                # Even the first restoration packet clears holds while playback still owns eyes.
                self.assertEqual(observations[0], ((False, False), True))
                ports.auto(True)
                self.assert_idle(consumer)

    def test_player_cleanup_restores_default_but_preserves_disabled_policy(self):
        for resume in (True, False):
            with self.subTest(resume=resume):
                consumer = EyeConsumer()
                ports = self.ports(consumer)
                cancelled = threading.Event()
                # Cancel only after the authored frame has reached the actual decoder.
                original_frame = ports.frame
                def frame(value):
                    original_frame(value)
                    cancelled.set()
                ports.frame = frame
                animation = inspect_program(program(resume=resume, eye=True))
                consumer.receive(b'\x44')
                failure = ProgramPlayer(ports, FakeClock()).run(animation, None, cancelled)
                self.assertIsNone(failure)
                if resume:
                    self.assert_idle(consumer)
                else:
                    self.assertEqual(consumer.latches(), (True, True))
                    self.assertTrue(consumer.state['joystick_connected'])
                    self.assertFalse(consumer.state['prev_auto_blink'])


if __name__ == '__main__':
    unittest.main()
