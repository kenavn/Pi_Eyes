import copy
import io
import json
import tempfile
import threading
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from nightweaver_head.program import inspect_program, compile_source
from nightweaver_head.engine import ProgramPlayer, PygamePorts
from nightweaver_head.service import Service
from nightweaver_head.wire import Refusal, validate
from head_support import (program, archive_program, wav, FakeClock, Ports, opened,
                          authority, activity, program_content, time_at, until, bundle)


class ProgramTests(unittest.TestCase):
    def mutate(self, change):
        data = program()
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            manifest = json.loads(archive.read('manifest.json'))
            events = [json.loads(line) for line in archive.read('events.jsonl').splitlines()]
        change(manifest, events)
        return archive_program(manifest, events)

    def test_closed_manifest_events_order_extents_and_source_identity(self):
        changes = [lambda m, e: m.update(extra=1), lambda m, e: m.update(duration_us='1'),
                   lambda m, e: m['uses'][1].update(id='0'),
                   lambda m, e: m['uses'][1].update(occurrence=m['uses'][0]['occurrence']),
                   lambda m, e: e[1]['event'].update(position=256),
                   lambda m, e: e[1]['event'].update(position=float('nan')),
                   lambda m, e: e[1].update(use_id='9'),
                   lambda m, e: e[1].update(at=time_at(0, 1, 1)),
                   lambda m, e: e.reverse(), lambda m, e: e.pop(),
                   lambda m, e: e[0]['event'].update(kind='other'),
                   lambda m, e: e[1]['event'].update(source_index='01'),
                   lambda m, e: e[1]['event'].update(source_index='2'),
                   lambda m, e: m['uses'][0].update(source_movement_extent_us='1002'),
                   lambda m, e: e[1].update(at=time_at(999, 1, 3))]
        for change in changes:
            with self.subTest(change=change), self.assertRaises(Refusal):
                inspect_program(self.mutate(change))

    def test_captured_delay_and_role_occurrence_identity(self):
        data = program(delay=250)
        parsed = inspect_program(data, local_output_delay_us=250)
        self.assertEqual(parsed.events[1][1]['use_id'], '0')
        self.assertEqual(parsed.events[1][1]['event']['source_index'], '0')
        self.assertNotEqual(parsed.manifest['uses'][0]['occurrence'], parsed.manifest['uses'][1]['occurrence'])
        with self.assertRaises(Refusal):
            inspect_program(data, local_output_delay_us=0)

    def test_archive_paths_duplicates_and_missing_audio(self):
        for name in ('../escape', '/tmp/escape', 'animation.csv', 'manifest.json'):
            data = io.BytesIO(program())
            with zipfile.ZipFile(data, 'a') as archive:
                archive.writestr(name, '{}')
            with self.assertRaises(Refusal):
                inspect_program(data.getvalue())
        with self.assertRaises(Refusal):
            inspect_program(self.mutate(lambda m, e: m.update(audio={
                'encoding': 'pcm_s16_le', 'frames': '8', 'sample_rate': 8000, 'channels': 1})))

    def test_native_formats_and_audio_less_have_distinct_facts(self):
        for encoding in (1, 3):
            parsed = inspect_program(program(audio=wav(frames=48, encoding=encoding)))
            self.assertEqual(parsed.facts['audio']['frames'], '48')
        self.assertIsNone(inspect_program(program()).facts['audio'])

    def test_gaps_and_abutting_order_with_fractional_cursor(self):
        for gap in (0, 1000):
            ports, clock = Ports(), FakeClock()
            parsed = inspect_program(program(gap=gap))
            result = ProgramPlayer(ports, clock).run(parsed, None, threading.Event())
            self.assertIsNone(result)
            self.assertEqual([event for event in ports.events if event[0] == 'auto'],
                             [('auto', False), ('auto', True), ('auto', False), ('auto', True)])
            self.assertEqual([e[2] for e in ports.events if e[0] == 'frame'], [(100,), (101,)])
            self.assertFalse(any(e[0] in ('load', 'dispose', 'play') for e in ports.events))
        parsed = inspect_program(self.mutate(lambda m, e: (m['uses'][0].update(start=time_at(0, 1, 3)), e[0].update(at=time_at(0, 1, 3)), e[1].update(at=time_at(1000, 1, 3)))))
        ports, clock = Ports(), FakeClock()
        ProgramPlayer(ports, clock).run(parsed, None, threading.Event())
        self.assertEqual(next(e[1] for e in ports.events if e[0] == 'frame'), 2000)

    def test_decoder_cursor_and_sentinel_final_events_once(self):
        ports, clock = Ports(), FakeClock()
        ports.positions = [0, 1000, -1]
        parsed = inspect_program(program(audio=wav(frames=48)))
        self.assertIsNone(ProgramPlayer(ports, clock).run(parsed, object(), threading.Event()))
        self.assertEqual(len([e for e in ports.events if e[0] == 'play']), 1)
        self.assertEqual(len([e for e in ports.events if e[0] == 'frame']), 2)
        self.assertEqual(len([e for e in ports.events if e == ('auto', True)]), 2)
        ports.positions = [-1]
        self.assertEqual(ProgramPlayer(ports, FakeClock()).run(parsed, object(), threading.Event()), 'worker_failure')

    def test_faithful_old_pygame_prepare_selects_parent_without_play_or_udp(self):
        music = Mock(spec=['load', 'play', 'stop', 'get_pos', 'get_busy'])
        mixer = SimpleNamespace(music=music, get_init=lambda: (48000, -16, 2), quit=Mock())
        route = Mock()
        ports = PygamePorts('synthetic', route_check=route)
        ports.pg, ports.ready, ports.sock = SimpleNamespace(mixer=mixer), True, Mock()
        resource = ports.prepare_audio(wav(frames=48))
        try:
            self.assertEqual(music.load.call_count, 1)
            route.assert_called_once()
            music.play.assert_not_called()
            music.get_pos.assert_not_called()
            ports.sock.sendto.assert_not_called()
            music.get_pos.side_effect = [0, 1, 6, 0, 1, 6]
            music.get_busy.return_value = False
            parsed = inspect_program(program(audio=wav(frames=48)))
            for _ in range(2):
                self.assertIsNone(ProgramPlayer(ports, FakeClock()).run(parsed, resource, threading.Event()))
            self.assertEqual(music.load.call_count, 1)
            ports.dispose()
            self.assertEqual(music.load.call_count, 2)
        finally:
            ports.close()
            resource.close()

    def test_local_authoring_source_compiles_once_with_preserved_delay_policy(self):
        from nightweaver_head.bundle import inspect
        source = inspect(bundle(['0,mouth,None,None,None,None,None,100'], audio=wav()))
        compiled = compile_source(source, delay_us=15000, resume_auto=False)
        self.assertEqual(compiled.audio, source.audio)
        self.assertEqual(compiled.manifest['uses'][0]['resume_auto'], False)
        self.assertEqual(compiled.events[1][0], 15000)
        self.assertEqual(compiled.facts['duration_us'], '15001')
        ports, clock = Ports(), FakeClock()
        ports.positions = [0, 10000, -1]
        self.assertIsNone(ProgramPlayer(ports, clock).run(compiled, object(), threading.Event()))
        self.assertEqual([event for event in ports.events if event[0] == 'auto'], [('auto', False)])
        self.assertEqual(sum(e[0] == 'frame' for e in ports.events), 1)

    def test_every_authored_native_packet_checks_cancellation(self):
        from nightweaver_head.bundle import Frame
        ports = PygamePorts('synthetic')
        cancel = threading.Event()
        ports.bind_cancellation(cancel)
        ports.sock = Mock()
        ports.sock.sendto.side_effect = lambda *_: cancel.set()
        ports.frame(Frame(0, 'eye', (0.5, 0.5, True, True, False)))
        self.assertEqual(ports.sock.sendto.call_count, 1)
        ports.auto(True)  # Explicit authored idle restoration remains permitted.
        self.assertEqual(ports.sock.sendto.call_count, 6)


class ServiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ports, self.clock = Ports(), FakeClock()
        self.service = Service(self.tmp.name, self.ports, self.clock)
        _, self.lease, self.owner = opened(self.service)
        self.data = program(self.owner['role_ids'][0], delay=250)
        self.content = program_content(self.data, self.owner)
        Path(self.tmp.name, self.content['identity']['sha256']).write_bytes(self.data)
        self.rev = 0

    async def asyncTearDown(self):
        self.assertTrue(await self.service.shutdown())
        self.tmp.cleanup()

    def auth(self):
        self.rev += 1
        return authority(self.lease, self.owner, self.rev)

    async def prepare(self):
        request = {'authority': self.auth(), 'content': self.content,
                   'expected_facts': inspect_program(self.data).facts, 'local_output_delay_us': 250}
        status, result = await self.service.dispatch('POST', '/head-control/v1/prepare', request)
        self.assertEqual(status, 202)
        await until(lambda: self.service.ordinary is None)
        result = self.service.lookup(result['operation'])
        validate('result', result)
        self.assertEqual(result['phase'], 'prepared')
        return result['prepared'], request

    async def start(self, prepared, run=None):
        run = run or activity(self.owner)
        request = {'authority': self.auth(), 'activity': run, 'prepared_handle_id': prepared['handle_id'],
                   'at': None, 'lateness_allowance_us': '100000', 'local_output_delay_us': 250}
        _, result = await self.service.dispatch('POST', '/head-control/v1/start', request)
        await until(lambda: self.service.ordinary is None)
        while self.service.worker_future and not self.service.worker_future.done():
            await until(lambda: self.service.worker_future.done())
        self.service.tick()
        return run, result

    async def test_prepare_repeat_stop_new_run_stale_stop_and_disarm(self):
        prepared, request = await self.prepare()
        self.assertEqual(prepared['physical_occupancy_us'], '6000')  # Compiler already captured delay.
        self.assertEqual((await self.service.dispatch('POST', '/head-control/v1/prepare', request))[0], 200)
        run_a, result_a = await self.start(prepared)
        repeat = copy.deepcopy(run_a)
        repeat['root_repeat_index'] = '1'
        _, result_repeat = await self.start(prepared, repeat)
        stop = {'authority': self.auth(), 'activity': repeat}
        self.assertEqual(self.service.stop(stop)[1]['settlement'], 'settled')
        self.assertFalse(self.service.retired)
        with self.assertRaisesRegex(Refusal, 'wrong_activity'):
            await self.start(prepared, dict(repeat, root_repeat_index='2'))
        run_b, _ = await self.start(prepared)
        with self.assertRaisesRegex(Refusal, 'wrong_activity'):
            self.service.stop({'authority': self.auth(), 'activity': repeat})
        _, result = await self.service.dispatch('POST', '/head-control/v1/disarm', {'authority': self.auth()})
        await until(lambda: self.service.cleanup_task is None)
        self.assertEqual(result['settlement'], 'pending')  # Dispatch returns an immutable observation.
        self.assertFalse(self.service.prepared)
        with self.assertRaisesRegex(Refusal, 'owner_retired'):
            await self.start(prepared)
        self.assertFalse(any(e[0] == 'load' for e in self.ports.events))  # Audio-less no native contribution.

    async def test_content_owner_facts_refusals_and_receipt_conflict(self):
        prepared, request = await self.prepare()
        wrong = copy.deepcopy(request)
        wrong['local_output_delay_us'] = 2
        with self.assertRaisesRegex(Refusal, 'revision_conflict'):
            self.service.prepare(wrong)
        foreign = copy.deepcopy(request)
        foreign['authority'] = self.auth()
        foreign['content']['device_id'] = self.owner['stage_id']
        with self.assertRaises(Refusal):
            self.service.prepare(foreign)
        self.service.receipts.clear()
        with self.assertRaisesRegex(Refusal, 'stale_revision'):
            self.service.prepare(request)

    async def test_wrong_facts_fail_before_native_selection(self):
        facts = inspect_program(self.data).facts
        facts['duration_us'] = '7'
        _, result = self.service.prepare({'authority': self.auth(), 'content': self.content,
            'expected_facts': facts, 'local_output_delay_us': 250})
        await until(lambda: self.service.ordinary is None)
        observed = self.service.lookup(result['operation'])
        self.assertEqual(observed['failure'], 'extent_mismatch')
        self.assertFalse(self.service.prepared)
        self.assertFalse(self.ports.resources)
        await self.prepare()

    async def test_expiry_disposes_preparation_and_never_resurrects(self):
        await self.prepare()
        self.clock.value = self.service.lease_until
        self.service.tick()
        await until(lambda: self.service.cleanup_task is None)
        self.assertFalse(self.service.prepared)
        self.assertTrue(self.service.retired)
        with self.assertRaisesRegex(Refusal, 'expired_session'):
            self.service.disarm({'authority': self.auth()})
        closed = self.service.close({k: self.lease[k] for k in ('session', 'lease_token')})
        self.assertEqual(closed['session'], self.lease['session'])

    async def test_stop_during_active_use_joins_before_settlement_and_retains(self):
        prepared, _ = await self.prepare()
        gate = threading.Event()
        self.ports.cleanup_gate = gate
        cancelled = threading.Event()
        original_frame = self.ports.frame
        def frame(value):
            original_frame(value)
            cancelled.set()
        self.ports.frame = frame
        # Stop arrives while the worker's restoration is deliberately held.
        run = activity(self.owner)
        request = {'authority': self.auth(), 'activity': run, 'prepared_handle_id': prepared['handle_id'],
                   'at': None, 'lateness_allowance_us': '100000', 'local_output_delay_us': 250}
        _, result = await self.service.dispatch('POST', '/head-control/v1/start', request)
        await until(self.ports.entered.is_set)
        stop = {'authority': self.auth(), 'activity': run}
        try:
            self.assertEqual(self.service.stop(stop)[1]['settlement'], 'pending')
            self.assertFalse(self.service.quiet())
            self.service.lease_until += 10000000
            self.clock.value += 5000001
            self.service.tick()
            self.assertEqual(self.service.stop(stop)[1]['settlement'], 'unknown')
            self.assertIn(prepared['handle_id'], self.service.prepared)
            self.assertFalse(any(e[0] == 'dispose' for e in self.ports.events))
        finally:
            gate.set()
        await until(lambda: self.service.worker_future.done())
        self.service.tick()
        self.assertEqual(self.service.stop(stop)[1]['settlement'], 'settled')
        self.assertIn(prepared['handle_id'], self.service.prepared)
        self.assertEqual(sum(e[0] == 'frame' for e in self.ports.events), 1)

    async def test_voice_prepare_loads_once_repeats_reuse_and_disarm_disposes(self):
        self.data = program(self.owner['role_ids'][0], audio=wav(frames=48), delay=250)
        self.content = program_content(self.data, self.owner)
        Path(self.tmp.name, self.content['identity']['sha256']).write_bytes(self.data)
        prepared, _ = await self.prepare()
        self.assertEqual(sum(e[0] == 'load' for e in self.ports.events), 1)
        _, duplicate = self.service.prepare({'authority': self.auth(), 'content': self.content,
            'expected_facts': inspect_program(self.data).facts, 'local_output_delay_us': 250})
        await until(lambda: self.service.ordinary is None)
        self.assertEqual(self.service.lookup(duplicate['operation'])['prepared']['handle_id'], prepared['handle_id'])
        self.assertEqual(sum(e[0] == 'load' for e in self.ports.events), 1)
        self.assertFalse(any(e[0] in ('play', 'auto', 'frame') for e in self.ports.events))
        self.ports.positions = [0, 1000, 6000]
        run, _ = await self.start(prepared)
        self.service.stop({'authority': self.auth(), 'activity': run})
        self.ports.positions = [0, 1000, 6000]
        await self.start(prepared)
        self.assertEqual(sum(e[0] == 'load' for e in self.ports.events), 1)
        self.assertFalse(any(e[0] == 'dispose' for e in self.ports.events))
        _, result = self.service.disarm({'authority': self.auth()})
        await until(lambda: self.service.cleanup_task is None)
        self.assertTrue(self.ports.resources[0].closed)
        self.assertEqual(sum(e[0] == 'dispose' for e in self.ports.events), 1)

    async def test_disarm_waits_for_native_disposal_join(self):
        prepared, _ = await self.prepare()
        gate, entered = threading.Event(), threading.Event()
        original = self.ports.dispose
        def dispose():
            entered.set()
            gate.wait()
            original()
        self.ports.dispose = dispose
        request = {'authority': self.auth()}
        _, result = self.service.disarm(request)
        await until(entered.is_set)
        try:
            self.clock.value += 5000001
            self.service.tick()
            self.assertIn(prepared['handle_id'], self.service.prepared)
            with self.assertRaisesRegex(Refusal, 'prior_worker_unsettled'):
                self.service.close({k: self.lease[k] for k in ('session', 'lease_token')})
        finally:
            gate.set()
        await until(lambda: self.service.cleanup_task is None)
        self.assertFalse(self.service.prepared)

    async def test_disarm_pending_native_prepare_does_not_publish_ready(self):
        self.data = program(self.owner['role_ids'][0], audio=wav(frames=48), delay=250)
        self.content = program_content(self.data, self.owner)
        Path(self.tmp.name, self.content['identity']['sha256']).write_bytes(self.data)
        gate = threading.Event()
        self.ports.prepare_gate = gate
        request = {'authority': self.auth(), 'content': self.content,
                   'expected_facts': inspect_program(self.data).facts, 'local_output_delay_us': 250}
        _, result = self.service.prepare(request)
        await until(self.ports.prepare_entered.is_set)
        _, disarmed = self.service.disarm({'authority': self.auth()})
        try:
            self.assertEqual(disarmed['settlement'], 'pending')
            self.assertEqual(result['settlement'], 'pending')
            self.assertFalse(self.service.prepared)
            self.assertFalse(self.service.quiet())
        finally:
            gate.set()
        await until(lambda: self.service.ordinary is None)
        self.service.tick()
        self.assertEqual(self.service.lookup(disarmed['operation'])['settlement'], 'settled')
        self.assertFalse(self.service.prepared)
        self.assertTrue(self.ports.resources[0].closed)


class UnknownCleanupTests(unittest.IsolatedAsyncioTestCase):
    async def test_failed_restoration_keeps_worker_claim_after_actual_return(self):
        with tempfile.TemporaryDirectory() as root:
            ports, clock = Ports(), FakeClock()
            service = Service(root, ports, clock)
            _, lease, owner = opened(service)
            data = program(owner['role_ids'][0])
            ref = program_content(data, owner)
            Path(root, ref['identity']['sha256']).write_bytes(data)
            _, prepared_result = service.prepare({'authority': authority(lease, owner, 1), 'content': ref,
                'expected_facts': inspect_program(data).facts, 'local_output_delay_us': 0})
            await until(lambda: service.ordinary is None)
            prepared_result = service.lookup(prepared_result['operation'])
            original_auto = ports.auto
            def fail_restore(enabled):
                if enabled:
                    raise RuntimeError('synthetic uncertain restoration')
                original_auto(enabled)
            ports.auto = fail_restore
            service.start({'authority': authority(lease, owner, 2), 'activity': activity(owner),
                'prepared_handle_id': prepared_result['prepared']['handle_id'], 'at': None,
                'lateness_allowance_us': '100000', 'local_output_delay_us': 0})
            await until(lambda: service.worker_future is not None and service.worker_future.done())
            service.tick()
            self.assertEqual(service.worker['settlement'], 'unknown')
            self.assertFalse(service.quiet())
            self.assertTrue(service.prepared)
            self.assertFalse(await service.shutdown())
            # All fake calls have returned. Test-only executor reclamation is not settlement.
            service.output.shutdown(wait=True)
            service.inspector.shutdown(wait=True)
            service.disk.shutdown(wait=True)
