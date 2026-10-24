import threading
import unittest
from nightweaver_head.bundle import inspect
from nightweaver_head.engine import BundlePlayer
from head_support import bundle, wav, FakeClock, Ports


class EngineTests(unittest.TestCase):
    def test_positive_delay_withholds_zero_frame(self):
        clock, ports, cancel = FakeClock(), Ports(), threading.Event()
        player = BundlePlayer(ports, clock)
        def before():
            if clock.now() < 1005000:
                self.assertFalse(any(e[0] == 'frame' for e in ports.events))
        clock.hook = before
        self.assertIsNone(player.run(inspect(bundle()), cancel, 5000))
        self.assertIn(('frame', 0, (100,)), ports.events)
        self.assertEqual(ports.events[-2:], [('auto', True), ('dispose',)])

    def test_audio_sentinel_tail_and_final_sample(self):
        clock, ports = FakeClock(), Ports()
        ports.positions = [0, 5000, -1]
        b = inspect(bundle(['12,mouth,None,None,None,None,None,255'], wav()))
        self.assertIsNone(BundlePlayer(ports, clock).run(b, threading.Event(), 4000))
        self.assertIn(('frame', 12000, (255,)), ports.events)
        self.assertGreaterEqual(clock.now(), 1013000)

    def test_no_valid_decoder_sample_fails(self):
        ports = Ports()
        self.assertEqual(BundlePlayer(ports, FakeClock()).run(inspect(bundle(audio=wav())), threading.Event()), 'worker_failure')
        self.assertFalse(any(e[0] == 'frame' for e in ports.events))

    def test_stop_preroll_loop_and_tail(self):
        for loop, audio in [(False, None), (True, None), (False, wav())]:
            clock, ports, cancel = FakeClock(), Ports(), threading.Event()
            ports.positions = [0]
            clock.hook = lambda: cancel.set()
            self.assertIsNone(BundlePlayer(ports, clock).run(inspect(bundle(audio=audio)), cancel, 10000, loop=loop))
            self.assertFalse(any(e[0] == 'frame' for e in ports.events))
            self.assertEqual(sum(e[0] == 'play' for e in ports.events), int(audio is not None))

    def test_pre_cancel_does_not_start(self):
        ports, cancel = Ports(), threading.Event()
        cancel.set()
        BundlePlayer(ports, FakeClock()).run(inspect(bundle()), cancel)
        self.assertFalse(any(e[0] in ('load', 'play', 'frame') for e in ports.events))

    def test_final_lateness_fence_after_load(self):
        from nightweaver_head.wire import Refusal
        ports, clock = Ports(), FakeClock()
        checks = []
        def fence():
            checks.append(True)
            raise Refusal('late', 422)
        failure = BundlePlayer(ports, clock).run(inspect(bundle(audio=wav())), threading.Event(), fence=fence)
        self.assertEqual(failure, 'late')
        self.assertFalse(any(e[0] in ('play', 'frame') for e in ports.events))
        self.assertTrue(checks)

    def test_transient_negative_busy_is_not_completion(self):
        clock, ports, cancel = FakeClock(), Ports(), threading.Event()
        ports.is_busy = True
        ports.positions = [-1, -1, 0, -1]
        def progress():
            if clock.now() > 1004000:
                ports.is_busy = False
        clock.hook = progress
        self.assertIsNone(BundlePlayer(ports, clock).run(inspect(bundle(audio=wav())), cancel))
        self.assertIn(('frame', 0, (100,)), ports.events)
