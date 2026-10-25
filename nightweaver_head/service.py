"""Serialized control authority plus bounded background inspection/output owners."""
import asyncio
import copy
import hashlib
import json
import threading
import uuid
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from .bundle import inspect
from .content import ContentStore
from .engine import BundlePlayer, Clock
from .wire import Refusal, validate


def uid():
    return str(uuid.uuid4())


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'))


def validate_facts(facts):
    audio, extent = facts['audio'], int(facts['audio_extent_us'])
    if audio is None:
        if extent:
            raise Refusal('malformed')
    elif extent != (int(audio['frames']) * 1000000 + audio['sample_rate'] - 1) // audio['sample_rate']:
        raise Refusal('malformed')
    movement, logical = int(facts['movement_extent_us']), int(facts['logical_extent_us'])
    if (max(extent, movement) != logical or logical > 900000000
            or bool(movement) != (facts['has_eye_motion'] or facts['has_mouth_motion'])):
        raise Refusal('malformed')


class Service:
    def __init__(self, root, ports, clock=None, source_revision='development', build_sha256=None):
        self.clock, self.ports = clock or Clock(), ports
        self.boot = uid()
        self.store = ContentStore(root, self.boot, self.clock)
        self.source_revision = source_revision
        self.build_sha256 = build_sha256 or hashlib.sha256(b'development').hexdigest()
        self.session = self.owner = self.open_request = self.open_lease = None
        self.lease_token = None
        self.lease_until = 0
        self.expired = self.retired = False
        self.high = self.observation = self.renewal_high = 0
        self.renewal_request = self.renewal_lease = None
        self.mapping = None
        self.receipts = OrderedDict()
        self.stop_receipt = None
        self.prepared = {}
        self.tombstones = set()
        self.latest_activity = None
        self.latest_result = None
        self.ordinary = self.control_task = None
        self.worker = self.worker_future = self.cancelled = None
        self.worker_deadline = None
        self.worker_timed_out = False
        self.engine = BundlePlayer(ports, self.clock)
        self.inspector = ThreadPoolExecutor(max_workers=1, thread_name_prefix='head-inspect')
        self.output = ThreadPoolExecutor(max_workers=1, thread_name_prefix='head-output')
        self.disk = ThreadPoolExecutor(max_workers=1, thread_name_prefix='head-content')
        self.disk_pending = 0
        self.closed = False
        self.ticker = None

    def now(self):
        return self.clock.now()

    def begin(self):
        self.ticker = asyncio.create_task(self.tick_loop())

    async def tick_loop(self):
        while not self.closed:
            self.tick()
            await asyncio.sleep(.01)

    def tick(self):
        if self.session and not self.expired and self.now() >= self.lease_until:
            self.expired = self.retired = True
            if self.cancelled:
                self.cancelled.set()
                self.worker_deadline = min(self.worker_deadline or self.now() + 5000000, self.now() + 5000000)
        if self.worker_future and not self.worker_future.done() and self.worker_deadline is not None and self.now() >= self.worker_deadline:
            self.worker_timed_out = True
            self.cancelled.set()
            self.worker.update(phase='unknown', settlement='unknown', failure='unknown_outcome')
        if self.worker is not None and self.engine.audio_position_us is not None:
            self.worker['audio_position_us'] = str(self.engine.audio_position_us)
        # Output future completion means the thread has returned after restoration/disposal.
        if self.worker_future and self.worker_future.done():
            failure = self.worker_future.result()
            if failure is None and self.worker_timed_out:
                failure = 'worker_failure'
            result = self.worker
            result.update(phase='unknown' if failure == 'unknown_outcome' else 'settled',
                          settlement='unknown' if failure == 'unknown_outcome' else 'settled',
                          failure=failure, terminal_reason='failed' if failure else
                          'lease_expired' if self.expired else 'stopped' if self.cancelled.is_set() else 'completed',
                          observed_local_us=str(self.now()), audio_position_us=None if self.engine.audio_position_us is None
                          else str(self.engine.audio_position_us))
            if failure != 'unknown_outcome':
                self.worker_future = self.worker = self.cancelled = self.worker_deadline = None
                self.worker_timed_out = False
            # Unknown cleanup deliberately retains this worker and claim forever.

    def quiet(self):
        self.tick()
        return self.worker_future is None and self.ordinary is None

    def check_boot(self, boot):
        if boot != self.boot:
            raise Refusal('stale_owner', 409)

    def check_session(self, request):
        self.tick()
        if request['session'] != self.session or request['lease_token'] != self.lease_token:
            raise Refusal('stale_owner', 409)
        if self.expired or self.session is None:
            raise Refusal('expired_session', 409)

    def check_owner(self, owner):
        epoch = self.open_request['coordinator_epoch']
        if owner['coordinator_epoch'] != epoch or owner['command']['process_epoch'] != epoch:
            raise Refusal('stale_owner', 409)
        if self.owner is not None and owner != self.owner:
            raise Refusal('stale_owner', 409)

    def check_mapping(self, probe, mapping, epoch):
        if probe['epoch'] != epoch or mapping is not None and mapping['epoch'] != epoch:
            raise Refusal('timebase_epoch_mismatch', 409)

    def apply_mapping(self, mapping):
        if mapping is not None and (self.mapping is None or int(mapping['mapping_seq']) > int(self.mapping['mapping_seq'])):
            self.mapping = copy.deepcopy(mapping)

    def lease(self, probe, recv):
        return {'session': self.session, 'lease_token': self.lease_token,
                'handshake_nonce': self.open_request['handshake_nonce'],
                'remaining_lease_us': str(max(0, self.lease_until - self.now())), 'renew_after_us': '1000000',
                'time_reply': dict(probe, client_boot_id=self.boot, client_recv_us=str(recv), client_send_us=str(self.now()))}

    def open(self, request):
        self.tick()
        self.check_boot(request['device_boot_id'])
        self.check_mapping(request['time_probe'], request['clock_mapping'], request['coordinator_epoch'])
        if self.session:
            if not self.expired and request == self.open_request:
                return copy.deepcopy(self.open_lease)
            raise Refusal('output_owned', 409)
        self.open_request = copy.deepcopy(request)
        self.session = {'device_boot_id': self.boot, 'session_id': uid()}
        self.lease_token = uid()
        self.lease_until = self.now() + 3000000
        self.apply_mapping(request['clock_mapping'])
        self.open_lease = self.lease(request['time_probe'], self.now())
        return copy.deepcopy(self.open_lease)

    def renew(self, request):
        self.check_session(request)
        self.check_mapping(request['time_probe'], request['clock_mapping'], self.open_request['coordinator_epoch'])
        sequence = int(request['renewal_sequence'])
        if sequence <= self.renewal_high:
            if request == self.renewal_request:
                return copy.deepcopy(self.renewal_lease)
            raise Refusal('revision_conflict', 409)
        self.renewal_high = sequence
        self.renewal_request = copy.deepcopy(request)
        self.lease_until = self.now() + 3000000
        self.apply_mapping(request['clock_mapping'])
        self.renewal_lease = self.lease(request['time_probe'], self.now())
        return copy.deepcopy(self.renewal_lease)

    def close(self, request):
        # Expired authority may release only its own proven-quiet resources.
        if request['session'] != self.session or request['lease_token'] != self.lease_token:
            raise Refusal('stale_owner', 409)
        if not self.quiet():
            raise Refusal('prior_worker_unsettled', 409)
        response = {'session': self.session}
        self.prepared.clear()
        self.store.pins.clear()
        self.session = self.owner = self.open_request = self.open_lease = self.lease_token = None
        self.expired = self.retired = False
        self.high = self.renewal_high = 0
        self.mapping = self.latest_activity = self.latest_result = self.stop_receipt = None
        self.receipts.clear()
        self.tombstones.clear()
        return response

    def receipt(self, authority, request, kind):
        self.check_session(authority)
        self.check_owner(authority['owner'])
        rev = int(authority['operation_revision'])
        retained = self.stop_receipt if self.stop_receipt and self.stop_receipt[0] == rev else self.receipts.get(rev)
        if retained:
            payload, result = retained[1:] if len(retained) == 3 else retained
            if payload != (kind, request):
                raise Refusal('revision_conflict', 409)
            return result
        if rev <= self.high:
            raise Refusal('stale_revision', 409)
        return None

    def admit(self, authority, request, kind, activity=None):
        rev = int(authority['operation_revision'])
        self.high = rev
        self.owner = copy.deepcopy(authority['owner'])
        identity = {k: copy.deepcopy(authority[k]) for k in ('session', 'owner', 'operation_revision')}
        result = {'operation': identity, 'phase': 'starting', 'settlement': 'pending',
                  'activity': copy.deepcopy(activity), 'prepared': None, 'terminal_reason': None,
                  'failure': None, 'clock_use': 'no_clock', 'observed_local_us': str(self.now()),
                  'audio_position_us': None}
        payload = (kind, copy.deepcopy(request))
        if kind == 'stop':
            self.stop_receipt = (rev, payload, result)
        else:
            self.receipts[rev] = (payload, result)
            while len(self.receipts) > 64:
                self.receipts.popitem(last=False)
        self.latest_result = result
        return result

    def result_status(self, result):
        return (202 if result['settlement'] == 'pending' else 200), copy.deepcopy(result)

    def ordinary_available(self):
        if self.ordinary is not None:
            raise Refusal('capacity', 429)

    def prepare(self, request):
        authority = request['authority']
        old = self.receipt(authority, request, 'prepare')
        if old:
            return self.result_status(old)
        if self.retired:
            raise Refusal('owner_retired', 409)
        self.ordinary_available()
        config = {k: request[k] for k in ('content', 'expected_facts', 'resume_auto', 'local_output_delay_us')}
        if len(self.prepared) >= 8 and not any(item[2] == config for item in self.prepared.values()):
            raise Refusal('capacity', 429)
        result = self.admit(authority, request, 'prepare')
        self.ordinary = result
        self.control_task = asyncio.create_task(self.do_prepare(request, result))
        return self.result_status(result)

    def inspect_bundle(self, identity):
        return inspect(self.store.read(identity))

    async def do_prepare(self, request, result):
        loop = asyncio.get_running_loop()
        try:
            bundle = await loop.run_in_executor(self.inspector, self.inspect_bundle, request['content']['identity'])
            if bundle.facts != request['expected_facts']:
                raise Refusal('extent_mismatch', 422)
            if bundle.audio:
                await loop.run_in_executor(self.inspector, self.ports.verify, bundle.audio)
            self.check_session(request['authority'])
            if self.retired:
                raise Refusal('owner_retired', 409)
            config = {k: request[k] for k in ('content', 'expected_facts', 'resume_auto', 'local_output_delay_us')}
            existing = next((item for item in self.prepared.values() if item[2] == config), None)
            if existing:
                prepared = existing[0]
            else:
                if sum(b.reservation for _, b, _ in self.prepared.values()) + bundle.reservation > 268435456:
                    raise Refusal('capacity', 429)
                delay = max(0, request['local_output_delay_us'])
                physical = max(int(bundle.facts['audio_extent_us']),
                               int(bundle.facts['movement_extent_us']) + delay if bundle.frames else 0)
                prepared = {'handle_id': uid(), 'session': self.session, 'owner': self.owner,
                            'content': request['content'], 'facts': bundle.facts,
                            'resume_auto': request['resume_auto'], 'local_output_delay_us': request['local_output_delay_us'],
                            'physical_occupancy_us': str(physical)}
                self.prepared[prepared['handle_id']] = (prepared, bundle, config)
                self.store.pins.add(request['content']['identity']['sha256'])
            result.update(phase='prepared', settlement='settled', prepared=prepared)
        except asyncio.CancelledError:
            # executor work cannot be cancelled: retain ordinary obligation until it returns.
            result.update(phase='unknown', settlement='unknown', failure='unknown_outcome', terminal_reason='failed')
            return
        except Exception as error:
            result.update(phase='settled', settlement='settled', terminal_reason='failed',
                          failure=error.reason if isinstance(error, Refusal) else 'worker_failure')
        finally:
            if result['settlement'] != 'unknown':
                self.ordinary = self.control_task = None
            result['observed_local_us'] = str(self.now())

    def start(self, request):
        authority, activity = request['authority'], request['activity']
        old = self.receipt(authority, request, 'start')
        if old:
            return self.result_status(old)
        if self.retired:
            raise Refusal('owner_retired', 409)
        if activity['owner'] != authority['owner'] or activity['role_id'] not in activity['owner']['role_ids']:
            raise Refusal('identity_conflict', 409)
        item = self.prepared.get(request['prepared_handle_id'])
        if item is None or item[0]['owner'] != authority['owner'] or item[0]['session'] != self.session:
            raise Refusal('stale_owner', 409)
        if item[0]['local_output_delay_us'] != request['local_output_delay_us']:
            raise Refusal('identity_conflict', 409)
        at = request['at']
        if at and at['epoch'] != self.open_request['coordinator_epoch']:
            raise Refusal('timebase_epoch_mismatch', 409)
        key = canonical(activity)
        if key in self.tombstones:
            raise Refusal('identity_conflict', 409)
        if len(self.tombstones) >= 4096:
            raise Refusal('capacity', 429)
        self.ordinary_available()
        result = self.admit(authority, request, 'start', activity)
        self.tombstones.add(key)
        self.latest_activity = copy.deepcopy(activity)
        self.ordinary = result
        target = self.now()
        if at and self.mapping and self.mapping['state'] in ('ready', 'degraded'):
            m = self.mapping
            mapped = int(m['ref_local_us']) + ((int(at['host_us']) - int(m['ref_host_us'])) * (1000000000 + m['rate_ppb'])) // 1000000000
            if 0 <= mapped <= 9223372036854775807:
                target = mapped
                result['clock_use'] = 'mapped'
        self.control_task = asyncio.create_task(self.do_start(request, result, item, target))
        return self.result_status(result)

    async def do_start(self, request, result, item, target):
        try:
            while True:
                if self.retired:
                    result.update(phase='settled', settlement='settled', terminal_reason='lease_expired' if self.expired else 'stopped')
                    return
                self.check_session(request['authority'])
                if self.retired:
                    raise Refusal('owner_retired', 409)
                self.tick()
                if self.now() - target > int(request['lateness_allowance_us']):
                    raise Refusal('prior_worker_unsettled' if self.worker_future else 'late', 422)
                if self.now() >= target and self.worker_future is None:
                    break
                await asyncio.sleep(.001)
            self.cancelled = threading.Event()
            self.engine.audio_position_us = None
            self.worker = result
            self.worker_deadline = self.now() + 5000000
            self.worker_timed_out = False
            loop = asyncio.get_running_loop()
            def started():
                loop.call_soon_threadsafe(self.mark_running, result, int(item[0]['physical_occupancy_us']))
            def fence():
                if self.cancelled.is_set() or self.now() >= self.lease_until or self.retired:
                    raise Refusal('cancelled', 409)
                if self.now() - target > int(request['lateness_allowance_us']):
                    raise Refusal('late', 422)
            self.worker_future = loop.run_in_executor(
                self.output, self.engine.run, item[1], self.cancelled,
                request['local_output_delay_us'], item[0]['resume_auto'], False, started, fence)
        except asyncio.CancelledError:
            result.update(phase='settled', settlement='settled', terminal_reason='lease_expired' if self.expired else 'stopped')
        except Refusal as error:
            result.update(phase='settled', settlement='settled', terminal_reason='failed', failure=error.reason)
        finally:
            self.ordinary = self.control_task = None

    def mark_running(self, result, physical):
        if self.worker is result and not self.worker_timed_out:
            self.worker_deadline = self.now() + physical + 5000000
        if result['settlement'] == 'pending':
            result.update(phase='running', observed_local_us=str(self.now()))

    def stop(self, request):
        authority, activity = request['authority'], request['activity']
        old = self.receipt(authority, request, 'stop')
        if old:
            self.update_stop(old)
            return self.result_status(old)
        if activity['owner'] != authority['owner'] or activity['role_id'] not in activity['owner']['role_ids']:
            raise Refusal('identity_conflict', 409)
        if self.latest_activity is not None and activity != self.latest_activity:
            raise Refusal('wrong_activity', 409)
        # No prepared owner has ever been captured: no authority to retire output.
        if self.owner is None:
            raise Refusal('stale_owner', 409)
        result = self.admit(authority, request, 'stop', activity)
        self.retired = True
        result['phase'] = 'stopping'
        if self.cancelled:
            self.cancelled.set()
        self.update_stop(result)
        return self.result_status(result)

    def update_stop(self, result):
        if self.quiet():
            result.update(phase='settled', settlement='settled', terminal_reason='stopped', failure=None, observed_local_us=str(self.now()))
        elif self.now() - int(result['observed_local_us']) >= 5000000:
            result.update(phase='unknown', settlement='unknown', failure='unknown_outcome')

    def lookup(self, request):
        self.tick()
        if request['session'] != self.session or request['owner'] != self.owner:
            raise Refusal('stale_owner', 409)
        rev = int(request['operation_revision'])
        retained = self.stop_receipt if self.stop_receipt and self.stop_receipt[0] == rev else self.receipts.get(rev)
        if retained is None:
            raise Refusal('outcome_unavailable', 404)
        result = retained[-1]
        if request != result['operation']:
            raise Refusal('identity_conflict', 409)
        if self.stop_receipt and result is self.stop_receipt[-1]:
            self.update_stop(result)
        return copy.deepcopy(result)

    def capabilities(self):
        return {'protocol_version': 1, 'device_boot_id': self.boot, 'source_revision': self.source_revision,
                'build_sha256': self.build_sha256, 'eyes': True, 'mouth': True, 'resume_auto': True,
                'pcm_wav': True, 'float_wav': True, 'audio_less': True, 'scheduled_start': True,
                'long_play_rate_following': False, 'audio_ready': self.ports.ready,
                'audio_path': {'sink_name': self.ports.sink_name, 'sample_rate': '48000', 'channels': '2'},
                'capacities': {'sessions': '1', 'workers': '1', 'ordinary_jobs': '1', 'prepared_handles': '8',
                               'receipts': '64', 'start_tombstones': '4096', 'bundle_bytes': '67108864',
                               'store_bytes': '1073741824', 'prepared_bytes': '268435456'},
                'start_action_time_us': None, 'restoration_action_time_us': None}

    async def dispatch(self, method, path, request):
        self.tick()
        head = '/head-control/v1'
        content = '/device-content/v1'
        routes = {
            head + '/capabilities': ('GET', None, lambda _: self.capabilities()),
            head + '/sessions/open': ('POST', 'open', self.open),
            head + '/sessions/renew': ('POST', 'renew', self.renew),
            head + '/sessions/close': ('POST', 'close', self.close),
            head + '/prepare': ('POST', 'prepare', self.prepare),
            head + '/start': ('POST', 'start', self.start),
            head + '/stop': ('POST', 'stop', self.stop),
            head + '/operations/lookup': ('POST', 'query', self.lookup),
        }
        if path == head + '/status':
            if method != 'POST':
                raise Refusal('malformed', 405)
            validate('status_query', request)
            self.check_boot(request['device_boot_id'])
            if self.observation >= 9223372036854775807:
                raise Refusal('capacity', 429)
            self.observation += 1
            if self.stop_receipt:
                self.update_stop(self.stop_receipt[-1])
            return 200, {'device_boot_id': self.boot, 'challenge': request['challenge'],
                         'observation_sequence': str(self.observation), 'session': self.session,
                         'owner': self.owner, 'operation': copy.deepcopy(self.latest_result),
                         'audio_ready': self.ports.ready, 'clock_mapping': self.mapping}
        if path == head + '/inspect':
            if method != 'POST':
                raise Refusal('malformed', 405)
            validate('inspect', request)
            self.ordinary_available()
            self.ordinary = 'inspect'
            try:
                bundle = await asyncio.get_running_loop().run_in_executor(self.inspector, self.inspect_bundle, request['content'])
                return 200, {'content': request['content'], 'facts': bundle.facts}
            finally:
                self.ordinary = None
        if path.startswith(content):
            return await self.disk_call(self.dispatch_content, method, path[len(content):], request)
        if path not in routes:
            raise Refusal('outcome_unavailable', 404)
        expected, schema, handler = routes[path]
        if method != expected:
            raise Refusal('malformed', 405)
        if schema:
            if schema == 'open' and type(request) is dict and type(request.get('protocol_version')) is int and request['protocol_version'] != 1:
                raise Refusal('unsupported_protocol', 422)
            validate(schema, request)
            if schema == 'prepare':
                validate_facts(request['expected_facts'])
        result = handler(request)
        return result if isinstance(result, tuple) else (200, result)

    async def disk_call(self, function, *args):
        # A stalled filesystem cannot occupy the control loop or grow an executor queue.
        if self.disk_pending >= 8:
            raise Refusal('capacity', 429)
        self.disk_pending += 1
        future = asyncio.get_running_loop().run_in_executor(self.disk, function, *args)
        def completed(done):
            self.disk_pending -= 1
            if not done.cancelled():
                done.exception()
        future.add_done_callback(completed)
        return await asyncio.shield(future)

    def dispatch_content(self, method, path, request):
        if path == '/inventory':
            if method != 'GET':
                raise Refusal('malformed', 405)
            return 200, self.store.inventory()
        schemas = {'/inspect': 'query', '/transfers/open': 'transfer',
                   '/transfers/lookup': 'transfer_query', '/transfers/cancel': 'transfer_query'}
        if path not in schemas:
            raise Refusal('outcome_unavailable', 404)
        if method != 'POST':
            raise Refusal('malformed', 405)
        validate(schemas[path], request, 'device-content')
        if path == '/inspect':
            self.store.boot_check(request['device_boot_id'])
            return 200, self.store.entry(request['identity'])
        if path == '/transfers/open':
            return 200, self.store.open(request)
        receipt = self.store.lookup(request)
        if path == '/transfers/cancel':
            receipt = self.store.fail(request['job_id'], 'cancelled')
        return (202 if receipt['phase'] == 'receiving' else 200), receipt

    async def shutdown(self):
        self.closed = True
        if self.ticker:
            self.ticker.cancel()
        self.retired = True
        if self.cancelled:
            self.cancelled.set()
        if self.control_task:
            try:
                await asyncio.wait_for(asyncio.shield(self.control_task), 5)
            except asyncio.TimeoutError:
                return False
        if self.worker_future:
            try:
                outcome = await asyncio.wait_for(asyncio.shield(self.worker_future), 5)
                if outcome == 'unknown_outcome':
                    return False
            except asyncio.TimeoutError:
                return False
        if self.disk_pending or self.ordinary is not None:
            return False
        if self.store.active:
            await self.disk_call(self.store.fail, self.store.active[0], 'cancelled')
        self.disk.shutdown(wait=True)
        self.inspector.shutdown(wait=True)
        self.output.shutdown(wait=True)
        try:
            self.ports.close()
        except Exception:
            return False
        return True
