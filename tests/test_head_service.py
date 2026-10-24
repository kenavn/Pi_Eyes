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
