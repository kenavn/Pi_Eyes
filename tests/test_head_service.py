import asyncio
import copy
import tempfile
import threading
import unittest
from pathlib import Path
from nightweaver_head.bundle import inspect
from nightweaver_head.service import Service
from nightweaver_head.wire import Refusal, validate
from head_support import Ports, FakeClock, bundle, wav, opened, authority, activity, content, uid, until


class ServiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ports, self.clock = Ports(), FakeClock()
        self.s = Service(self.tmp.name, self.ports, self.clock)
        self.open, self.lease, self.owner = opened(self.s)
        validate('open', self.open)
        validate('lease', self.lease)
        self.data = bundle()
        self.content = content(self.data)
        Path(self.tmp.name, self.content['identity']['sha256']).write_bytes(self.data)

    async def asyncTearDown(self):
        if self.ports.cleanup_gate:
            self.ports.cleanup_gate.set()
        await self.s.shutdown()
        self.tmp.cleanup()

    def auth(self, rev):
        return authority(self.lease, self.owner, rev)

    async def prepare(self, rev=1, data=None):
        data = self.data if data is None else data
        managed = self.content if data is self.data else content(data)
        Path(self.tmp.name, managed['identity']['sha256']).write_bytes(data)
        request = {'authority': self.auth(rev), 'content': managed, 'expected_facts': inspect(data).facts,
                   'resume_auto': True, 'local_output_delay_us': 0}
        validate('prepare', request)
        status, result = self.s.prepare(request)
        self.assertEqual(status, 202)
        await until(lambda: self.s.ordinary is None)
        result = self.s.lookup(result['operation'])
        validate('result', result)
        self.assertIsNone(result['failure'])
        return request, result['prepared']

    def start_request(self, prepared, rev=2, act=None):
        return {'authority': self.auth(rev), 'activity': act or activity(self.owner),
                'prepared_handle_id': prepared['handle_id'], 'at': None,
                'lateness_allowance_us': '1000000', 'local_output_delay_us': 0}

    async def test_role_scope_rejects_noncanonical_and_foreign_before_effects(self):
        self.owner['role_ids'] = sorted([uid(), uid()])
        request = {'authority': self.auth(1), 'content': self.content,
                   'expected_facts': inspect(self.data).facts, 'resume_auto': True,
                   'local_output_delay_us': 0}
        for roles in ([], [self.owner['role_ids'][0]] * 2,
                      list(reversed(self.owner['role_ids'])), [uid()] * 1025,
                      ['00000000-0000-0000-0000-000000000000']):
            invalid = copy.deepcopy(request)
            invalid['authority']['owner']['role_ids'] = roles
            with self.assertRaises(Refusal):
                validate('prepare', invalid)
        _, prepared = await self.prepare()
        invalid = self.start_request(prepared)
        invalid['activity']['role_id'] = uid()
        before = list(self.ports.events)
        with self.assertRaisesRegex(Refusal, 'wrong_activity'):
            validate('start', invalid)
        with self.assertRaisesRegex(Refusal, 'identity_conflict'):
            self.s.start(invalid)
        self.assertEqual(self.ports.events, before)
        self.assertIsNone(self.s.worker_future)

    async def test_duplicate_conflict_stale_tombstone(self):
        request, prepared = await self.prepare()
        self.assertEqual(self.s.prepare(request)[1]['prepared'], prepared)
        changed = copy.deepcopy(request)
        changed['resume_auto'] = False
        with self.assertRaisesRegex(Refusal, 'revision_conflict'):
            self.s.prepare(changed)
        start = self.start_request(prepared)
        validate('start', start)
        _, result = self.s.start(start)
        await until(lambda: self.s.ordinary is None)
        await until(lambda: self.s.worker_future.done())
        self.s.tick()
        self.assertEqual(self.s.start(start)[0], 200)
        self.assertEqual(sum(e[0] == 'frame' for e in self.ports.events), 1)
        retry = copy.deepcopy(start)
        retry['authority']['operation_revision'] = '3'
        with self.assertRaisesRegex(Refusal, 'identity_conflict'):
            self.s.start(retry)
        self.s.receipts.pop(1)
        with self.assertRaisesRegex(Refusal, 'stale_revision'):
            self.s.prepare(request)

    async def test_pending_stop_retires_owner(self):
        _, prepared = await self.prepare()
        start = self.start_request(prepared)
        self.s.mapping = {'state': 'ready', 'ref_local_us': str(self.clock.now()), 'ref_host_us': '0',
                          'rate_ppb': 0, 'mapping_seq': '1', 'epoch': self.open['coordinator_epoch'], 'uncertainty_us': 0}
        start['at'] = {'epoch': self.open['coordinator_epoch'], 'host_us': '2000000'}
        self.s.start(start)
        stop = {'authority': self.auth(3), 'activity': start['activity']}
        self.s.stop(stop)
        await until(lambda: self.s.ordinary is None)
        result = self.s.stop(stop)[1]
        self.assertEqual(result['settlement'], 'settled')
        self.assertFalse(any(e[0] == 'frame' for e in self.ports.events))
        with self.assertRaisesRegex(Refusal, 'owner_retired'):
            self.s.start(self.start_request(prepared, 4))

    async def test_prestart_stop_and_stale_stop_a_after_b(self):
        _, prepared = await self.prepare()
        a = self.start_request(prepared)
        self.s.start(a)
        await until(lambda: self.s.ordinary is None)
        await until(lambda: self.s.worker_future.done())
        self.s.tick()
        b = self.start_request(prepared, 3)
        self.s.start(b)
        with self.assertRaisesRegex(Refusal, 'wrong_activity'):
            self.s.stop({'authority': self.auth(4), 'activity': a['activity']})
        self.assertFalse(self.s.retired)
        self.s.stop({'authority': self.auth(5), 'activity': b['activity']})
        await until(lambda: self.s.ordinary is None)
        await until(lambda: self.s.quiet())
        self.s.close({k: self.lease[k] for k in ('session', 'lease_token')})
        self.open, self.lease, self.owner = opened(self.s)
        _, prepared = await self.prepare()
        self.assertEqual(self.s.stop({'authority': self.auth(2), 'activity': activity(self.owner)})[1]['settlement'], 'settled')

    async def test_held_restoration_not_quiet_prepare_b_no_music_selection(self):
        _, prepared = await self.prepare()
        self.ports.cleanup_gate = threading.Event()
        a = self.start_request(prepared)
        self.s.start(a)
        await until(lambda: self.ports.entered.is_set())
        _, b = await self.prepare(3, bundle(audio=wav()))
        self.assertNotEqual(b['handle_id'], prepared['handle_id'])
        self.assertFalse(any(e[0] == 'load' for e in self.ports.events))
        stop = {'authority': self.auth(4), 'activity': a['activity']}
        self.assertEqual(self.s.stop(stop)[0], 202)
        self.clock.value += 5000001
        self.assertEqual(self.s.lookup(self.s.stop_receipt[-1]['operation'])['settlement'], 'unknown')
        self.assertFalse(self.s.quiet())
        self.ports.cleanup_gate.set()
        await until(lambda: self.s.worker_future.done())
        self.s.tick()
        self.assertEqual(self.s.lookup(self.s.stop_receipt[-1]['operation'])['settlement'], 'settled')

    async def test_lease_expiry_and_renewal_duplicate_no_extension(self):
        renew = {'session': self.lease['session'], 'lease_token': self.lease['lease_token'],
                 'renewal_sequence': '1', 'time_probe': self.open['time_probe'], 'clock_mapping': None}
        old = self.s.renew(renew)
        deadline = self.s.lease_until
        self.clock.value += 10
        self.assertEqual(self.s.renew(renew), old)
        self.assertEqual(self.s.lease_until, deadline)
        self.clock.value = deadline
        self.s.tick()
        with self.assertRaisesRegex(Refusal, 'expired_session'):
            self.s.renew(renew)
        with self.assertRaisesRegex(Refusal, 'output_owned'):
            self.s.open(self.open)

    async def test_identity_strict(self):
        for mutation in ('nil', 'number', 'unknown', 'owner'):
            _, prepared = await self.prepare(1 if not self.s.high else self.s.high + 1)
            request = self.start_request(prepared, self.s.high + 1)
            if mutation == 'nil':
                request['activity']['occurrence']['use_id'] = '00000000-0000-0000-0000-000000000000'
            elif mutation == 'number':
                request['authority']['operation_revision'] = 1
            elif mutation == 'unknown':
                request['bogus'] = True
            else:
                request['activity'] = copy.deepcopy(request['activity'])
                request['activity']['owner']['run_id'] = uid()
                with self.assertRaisesRegex(Refusal, 'identity_conflict'):
                    self.s.start(request)
                continue
            with self.assertRaises(Refusal):
                validate('start', request)

    async def test_lease_expiry_cancels_held_worker_and_prevents_restart(self):
        _, prepared = await self.prepare()
        self.ports.cleanup_gate = threading.Event()
        start = self.start_request(prepared)
        self.s.start(start)
        await until(lambda: self.ports.entered.is_set())
        self.clock.value = self.s.lease_until
        self.s.tick()
        self.assertTrue(self.s.cancelled.is_set())
        self.assertFalse(self.s.quiet())
        self.ports.cleanup_gate.set()
        await until(lambda: self.s.worker_future.done())
        self.s.tick()
        result = self.s.lookup({k: start['authority'][k] for k in ('session', 'owner', 'operation_revision')})
        self.assertEqual(result['terminal_reason'], 'lease_expired')
        with self.assertRaisesRegex(Refusal, 'expired_session'):
            self.s.start(self.start_request(prepared, 3))

    async def test_unknown_clock_fallback_and_epoch_refusal(self):
        _, prepared = await self.prepare()
        start = self.start_request(prepared)
        start['at'] = {'epoch': uid(), 'host_us': '9223372036854775807'}
        with self.assertRaisesRegex(Refusal, 'timebase_epoch_mismatch'):
            self.s.start(start)
        start['at']['epoch'] = self.open['coordinator_epoch']
        _, result = self.s.start(start)
        self.assertEqual(result['clock_use'], 'no_clock')
        await until(lambda: self.s.worker_future is not None and self.s.worker_future.done())
        self.s.tick()
        self.assertEqual(self.s.lookup(result['operation'])['terminal_reason'], 'completed')

    async def test_worker_watchdog_truthfully_unknown_until_disposal(self):
        _, prepared = await self.prepare()
        self.ports.cleanup_gate = threading.Event()
        start = self.start_request(prepared)
        _, result = self.s.start(start)
        await until(lambda: self.ports.entered.is_set())
        self.s.lease_until = self.clock.now() + 10000000
        self.clock.value = self.s.worker_deadline
        self.s.tick()
        observed = self.s.lookup(result['operation'])
        self.assertEqual(observed['settlement'], 'unknown')
        self.assertEqual(observed['failure'], 'unknown_outcome')
        self.assertFalse(self.s.quiet())
        self.ports.cleanup_gate.set()
        await until(lambda: self.s.worker_future.done())
        self.s.tick()
        observed = self.s.lookup(result['operation'])
        self.assertEqual(observed['settlement'], 'settled')
        self.assertEqual(observed['failure'], 'worker_failure')

    async def test_prepared_file_lives_across_natural_a_b_and_deduplicates(self):
        request, prepared = await self.prepare(data=bundle(audio=wav()))
        resource = self.ports.resources[0]
        self.assertEqual([e[0] for e in self.ports.events], ['prepare_audio'])
        duplicate = copy.deepcopy(request)
        duplicate['authority']['operation_revision'] = '2'
        self.s.prepare(duplicate)
        await until(lambda: self.s.ordinary is None)
        self.assertEqual(len(self.ports.resources), 1)
        self.assertEqual(len(self.s.prepared), 1)
        entry = self.s.prepared[prepared['handle_id']]
        self.assertEqual(entry.reservation, entry.bundle.reservation + len(entry.bundle.audio))
        for revision in (3, 4):
            self.ports.positions = [10000]
            self.s.start(self.start_request(prepared, revision))
            await until(lambda: self.s.worker_future is not None and self.s.worker_future.done())
            self.s.tick()
            self.assertFalse(resource.closed)
        self.assertEqual([e[1] for e in self.ports.events if e[0] == 'load'], [resource, resource])
        self.s.close({k: self.lease[k] for k in ('session', 'lease_token')})
        self.assertTrue(resource.closed)
        self.assertEqual(resource.close_count, 1)

    async def test_cancel_prepare_keeps_claim_until_native_job_and_cleanup_return(self):
        self.ports.prepare_gate = threading.Event()
        data = bundle(audio=wav())
        managed = content(data)
        Path(self.tmp.name, managed['identity']['sha256']).write_bytes(data)
        request = {'authority': self.auth(1), 'content': managed, 'expected_facts': inspect(data).facts,
                   'resume_auto': True, 'local_output_delay_us': 0}
        _, result = self.s.prepare(request)
        await until(self.ports.prepare_entered.is_set)
        task = self.s.control_task
        task.cancel()
        await asyncio.sleep(0)
        self.assertFalse(task.done())
        with self.assertRaisesRegex(Refusal, 'prior_worker_unsettled'):
            self.s.close({k: self.lease[k] for k in ('session', 'lease_token')})
        self.assertFalse(self.ports.resources)
        self.ports.prepare_gate.set()
        await task
        self.assertTrue(self.ports.resources[0].closed)
        self.assertFalse(self.s.prepared)
        self.assertTrue(self.s.quiet())
        self.assertEqual(self.s.lookup(result['operation'])['failure'], 'cancelled')

    async def test_failed_prepare_releases_claim_and_resource(self):
        self.ports.failed_verify = True
        data = bundle(audio=wav())
        managed = content(data)
        Path(self.tmp.name, managed['identity']['sha256']).write_bytes(data)
        request = {'authority': self.auth(1), 'content': managed, 'expected_facts': inspect(data).facts,
                   'resume_auto': True, 'local_output_delay_us': 0}
        _, result = self.s.prepare(request)
        await until(lambda: self.s.ordinary is None)
        self.assertFalse(self.s.prepared)
        self.assertFalse(self.ports.resources)
        self.assertEqual(self.s.lookup(result['operation'])['failure'], 'worker_failure')

    async def test_stop_and_expiry_during_load_cannot_emit_authored_output(self):
        for expire in (False, True):
            if expire:
                self.s.close({k: self.lease[k] for k in ('session', 'lease_token')})
                self.open, self.lease, self.owner = opened(self.s)
            _, prepared = await self.prepare(data=bundle(audio=wav()))
            self.ports.events.clear()
            self.ports.load_entered.clear()
            self.ports.load_gate = threading.Event()
            request = self.start_request(prepared)
            self.s.start(request)
            await until(self.ports.load_entered.is_set)
            self.assertFalse(any(e[0] in ('play', 'frame') for e in self.ports.events))
            if expire:
                self.clock.value = self.s.lease_until
                self.s.tick()
            else:
                self.s.stop({'authority': self.auth(3), 'activity': request['activity']})
            self.ports.load_gate.set()
            await until(lambda: self.s.worker_future.done())
            self.s.tick()
            self.assertFalse(any(e[0] in ('play', 'frame') or e == ('auto', False) for e in self.ports.events))

    async def test_far_mapped_start_preloads_and_does_not_hit_startup_watchdog(self):
        _, prepared = await self.prepare(data=bundle(audio=wav()))
        self.s.mapping = {'state': 'ready', 'ref_local_us': str(self.clock.now()), 'ref_host_us': '0',
                          'rate_ppb': 0, 'mapping_seq': '1', 'epoch': self.open['coordinator_epoch'], 'uncertainty_us': 0}
        request = self.start_request(prepared)
        request['at'] = {'epoch': self.open['coordinator_epoch'], 'host_us': '6000000'}
        self.s.lease_until = self.clock.now() + 20000000
        self.ports.load_gate = threading.Event()
        _, result = self.s.start(request)
        await until(self.ports.load_entered.is_set)
        self.assertEqual(self.s.worker_deadline, 12000000)
        self.clock.value += 5500000
        self.s.tick()
        self.assertFalse(self.s.worker_timed_out)
        self.assertEqual(self.s.lookup(result['operation'])['phase'], 'starting')
        self.s.stop({'authority': self.auth(3), 'activity': request['activity']})
        self.assertEqual(self.s.worker_deadline, 11500000)
        self.ports.load_gate.set()
        await until(lambda: self.s.worker_future.done())
        self.s.tick()
        self.assertFalse(any(e[0] in ('play', 'frame') for e in self.ports.events))

    async def test_unknown_provisional_cleanup_retains_claim(self):
        self.ports.prepare_gate = threading.Event()
        original = self.ports.prepare_audio
        def prepare_audio(data):
            audio = original(data)
            def fail_close():
                raise OSError('held resource')
            audio.close = fail_close
            return audio
        self.ports.prepare_audio = prepare_audio
        data = bundle(audio=wav())
        managed = content(data)
        Path(self.tmp.name, managed['identity']['sha256']).write_bytes(data)
        request = {'authority': self.auth(1), 'content': managed, 'expected_facts': inspect(data).facts,
                   'resume_auto': True, 'local_output_delay_us': 0}
        _, result = self.s.prepare(request)
        await until(self.ports.prepare_entered.is_set)
        task = self.s.control_task
        task.cancel()
        self.ports.prepare_gate.set()
        await task
        self.assertEqual(self.s.lookup(result['operation'])['settlement'], 'unknown')
        self.assertIs(self.s.provisional_audio, self.ports.resources[0])
        self.assertFalse(self.s.quiet())
        with self.assertRaisesRegex(Refusal, 'prior_worker_unsettled'):
            self.s.close({k: self.lease[k] for k in ('session', 'lease_token')})
        self.assertFalse(await self.s.shutdown())

    async def test_unknown_worker_disposal_retains_prepared_resource(self):
        _, prepared = await self.prepare(data=bundle(audio=wav()))
        resource = self.ports.resources[0]
        self.ports.positions = [10000]
        def fail_dispose():
            raise OSError('held selection')
        self.ports.dispose = fail_dispose
        _, result = self.s.start(self.start_request(prepared))
        await until(lambda: self.s.worker_future is not None and self.s.worker_future.done())
        self.s.tick()
        self.assertEqual(self.s.lookup(result['operation'])['settlement'], 'unknown')
        self.assertFalse(self.s.quiet())
        self.assertFalse(resource.closed)
        self.assertFalse(await self.s.shutdown())
        self.assertFalse(resource.closed)

    async def test_session_close_failure_keeps_pins_session_and_entry(self):
        _, prepared = await self.prepare(data=bundle(audio=wav()))
        resource = self.ports.resources[0]
        original = resource.close
        def fail_close():
            raise OSError('held prepared file')
        resource.close = fail_close
        with self.assertRaisesRegex(Refusal, 'unknown_outcome'):
            self.s.close({k: self.lease[k] for k in ('session', 'lease_token')})
        self.assertIsNotNone(self.s.session)
        self.assertIn(prepared['handle_id'], self.s.prepared)
        self.assertTrue(self.s.store.pins)
        self.assertTrue(self.s.retired)
        self.assertFalse(resource.closed)
        resource.close = original

    async def test_retirement_during_prepare_closes_unpublished_resource(self):
        self.ports.prepare_gate = threading.Event()
        data = bundle(audio=wav())
        managed = content(data)
        Path(self.tmp.name, managed['identity']['sha256']).write_bytes(data)
        request = {'authority': self.auth(1), 'content': managed, 'expected_facts': inspect(data).facts,
                   'resume_auto': True, 'local_output_delay_us': 0}
        _, result = self.s.prepare(request)
        await until(self.ports.prepare_entered.is_set)
        self.s.stop({'authority': self.auth(2), 'activity': activity(self.owner)})
        self.ports.prepare_gate.set()
        await until(lambda: self.s.ordinary is None)
        self.assertEqual(self.s.lookup(result['operation'])['failure'], 'owner_retired')
        self.assertTrue(self.ports.resources[0].closed)
        self.assertFalse(self.s.prepared)

    async def test_retained_audio_file_is_charged_before_allocation(self):
        from dataclasses import replace
        data = bundle(audio=wav())
        parsed = inspect(data)
        self.s.inspect_bundle = lambda _: replace(parsed, reservation=268435456)
        managed = content(data)
        request = {'authority': self.auth(1), 'content': managed, 'expected_facts': parsed.facts,
                   'resume_auto': True, 'local_output_delay_us': 0}
        _, result = self.s.prepare(request)
        await until(lambda: self.s.ordinary is None)
        self.assertEqual(self.s.lookup(result['operation'])['failure'], 'capacity')
        self.assertFalse(self.ports.resources)
        self.assertFalse(self.ports.prepare_entered.is_set())
