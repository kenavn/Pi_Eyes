import asyncio
import json
import tempfile
import unittest
from nightweaver_head.http import HTTPServer
from nightweaver_head.service import Service
from head_support import Ports, bundle, content, uid, opened, authority, activity, until
from nightweaver_head.bundle import inspect


class HTTPTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.service = Service(self.tmp.name, Ports())
        self.server = HTTPServer(self.service, 'synthetic-secret', '127.0.0.1', 0, test_config=True)
        self.addr = await self.server.start()
        self.connections = []

    async def asyncTearDown(self):
        for reader, writer in self.connections:
            writer.close()
        await self.server.close()
        self.tmp.cleanup()

    async def connect(self):
        reader, writer = await asyncio.open_connection(*self.addr)
        self.connections.append((reader, writer))
        return reader, writer

    def headers(self, method, path, length=0, extras=b''):
        return (f'{method} {path} HTTP/1.1\r\nHost: localhost\r\nAuthorization: Bearer synthetic-secret\r\nContent-Length: {length}\r\n'.encode()
                + extras + b'\r\n')

    async def reply(self, reader):
        response = await asyncio.wait_for(reader.read(), 5)
        head, body = response.split(b'\r\n\r\n', 1)
        self.assertIn(b'cache-control: no-store', head.lower())
        return int(head.split()[1]), json.loads(body)

    async def request(self, path, value=None, method='POST'):
        reader, writer = await self.connect()
        data = json.dumps(value).encode() if value is not None else b''
        writer.write(self.headers(method, path, len(data), b'Content-Type: application/json\r\n') + data)
        return await self.reply(reader)

    async def test_capability_validation_header_aggregate_duplicate_json(self):
        status, cap = await self.request('/head-control/v1/capabilities', method='GET')
        self.assertEqual(status, 200)
        self.assertEqual(cap['device_boot_id'], self.service.boot)
        for extras, data, expected in [(b'X-Big: ' + b'x'*17000 + b'\r\n', b'{}', 413),
                                       (b'Content-Encoding: gzip\r\n', b'{}', 400),
                                       (b'', b'{"x":1,"x":2}', 400)]:
            reader, writer = await self.connect()
            writer.write(self.headers('POST', '/head-control/v1/status', len(data),
                                      b'Content-Type: application/json\r\n' + extras) + data)
            self.assertEqual((await self.reply(reader))[0], expected)
        self.assertEqual((await self.request('/head-control/v1/start', method='GET'))[0], 405)
        self.assertEqual((await self.request('/absent', {}))[0], 404)

    async def test_real_stream_upload_and_identity_lookup(self):
        data = bundle()
        request = {'device_boot_id': self.service.boot, 'job_id': uid(), 'content': content(data)}
        status, receipt = await self.request('/device-content/v1/transfers/open', request)
        self.assertEqual((status, receipt['phase']), (200, 'receiving'))
        reader, writer = await self.connect()
        extras = f'Content-Type: application/octet-stream\r\nX-Device-Boot-Id: {self.service.boot}\r\n'.encode()
        writer.write(self.headers('PUT', '/device-content/v1/transfers/'+request['job_id']+'/bytes', len(data), extras) + data[:10])
        await writer.drain()
        status, lookup = await self.request('/device-content/v1/transfers/lookup',
                                          {'device_boot_id': self.service.boot, 'job_id': request['job_id']})
        self.assertEqual((status, lookup['phase']), (202, 'receiving'))
        self.assertFalse(self.service.store.inventory()['entries'])
        writer.write(data[10:])
        self.assertEqual((await self.reply(reader))[1]['phase'], 'published')
        status, result = await self.request('/head-control/v1/inspect', {'content': request['content']['identity']})
        self.assertEqual(status, 200)
        self.assertEqual(result['facts'], inspect(data).facts)

    async def test_reserved_stop_and_renew_while_six_bodies_held(self):
        opened_request, lease, owner = opened(self.service)
        data = bundle()
        managed = content(data)
        from pathlib import Path
        Path(self.tmp.name, managed['identity']['sha256']).write_bytes(data)
        prepared_request = {'authority': authority(lease, owner, 1), 'content': managed,
                            'expected_facts': inspect(data).facts, 'resume_auto': True, 'local_output_delay_us': 0}
        self.service.prepare(prepared_request)
        await until(lambda: self.service.ordinary is None)
        for _ in range(6):
            reader, writer = await self.connect()
            writer.write(self.headers('POST', '/head-control/v1/prepare', 20, b'Content-Type: application/json\r\n') + b'{')
            await writer.drain()
        await until(lambda: self.server.ordinary == 6)
        renewal = {'session': lease['session'], 'lease_token': lease['lease_token'], 'renewal_sequence': '1',
                   'time_probe': opened_request['time_probe'], 'clock_mapping': None}
        self.assertEqual((await self.request('/head-control/v1/sessions/renew', renewal))[0], 200)
        stop = {'authority': authority(lease, owner, 2), 'activity': activity(owner)}
        self.assertEqual((await self.request('/head-control/v1/stop', stop))[1]['settlement'], 'settled')

    async def test_partial_upload_disconnect_never_published(self):
        data = bundle()
        request = {'device_boot_id': self.service.boot, 'job_id': uid(), 'content': content(data)}
        await self.request('/device-content/v1/transfers/open', request)
        reader, writer = await self.connect()
        extras = f'Content-Type: application/octet-stream\r\nX-Device-Boot-Id: {self.service.boot}\r\n'.encode()
        writer.write(self.headers('PUT', '/device-content/v1/transfers/'+request['job_id']+'/bytes', len(data), extras) + data[:10])
        await writer.drain()
        writer.close()
        await until(lambda: self.service.store.receipts[request['job_id']]['phase'] == 'failed')
        self.assertFalse(self.service.store.inventory()['entries'])

    async def test_disconnected_admission_query_no_reexecution(self):
        request, lease, owner = opened(self.service)
        data = bundle()
        managed = content(data)
        from pathlib import Path
        Path(self.tmp.name, managed['identity']['sha256']).write_bytes(data)
        prepared = {'authority': authority(lease, owner, 1), 'content': managed, 'expected_facts': inspect(data).facts,
                    'resume_auto': True, 'local_output_delay_us': 0}
        await self.request('/head-control/v1/prepare', prepared)
        await until(lambda: self.service.ordinary is None)
        handle = next(iter(self.service.prepared))
        start = {'authority': authority(lease, owner, 2), 'activity': activity(owner), 'prepared_handle_id': handle,
                 'at': None, 'lateness_allowance_us': '1000000', 'local_output_delay_us': 0}
        reader, writer = await self.connect()
        body = json.dumps(start).encode()
        writer.write(self.headers('POST', '/head-control/v1/start', len(body), b'Content-Type: application/json\r\n') + body)
        await writer.drain()
        writer.close()
        await until(lambda: 2 in self.service.receipts)
        await until(lambda: self.service.worker_future is not None and self.service.worker_future.done())
        self.service.tick()
        identity = {k: start['authority'][k] for k in ('session', 'owner', 'operation_revision')}
        self.assertEqual((await self.request('/head-control/v1/operations/lookup', identity))[1]['terminal_reason'], 'completed')
        await self.request('/head-control/v1/start', start)
        self.assertEqual(sum(e[0] == 'frame' for e in self.service.ports.events), 1)

    async def test_header_idle_and_absolute_deadline(self):
        self.server.idle = .01
        reader, writer = await self.connect()
        writer.write(b'POST /head-control/v1/status HTTP/1.1\r\n')
        self.assertEqual((await self.reply(reader))[0], 408)
        self.server.idle = 1
        self.server.deadline = .01
        reader, writer = await self.connect()
        writer.write(self.headers('POST', '/head-control/v1/status', 10, b'Content-Type: application/json\r\n') + b'{')
        self.assertEqual((await self.reply(reader))[0], 408)

    def test_binding_fail_closed(self):
        for bind in ('0.0.0.0', '::', '10.0.4.121', '127.0.0.1'):
            with self.assertRaises(ValueError):
                HTTPServer(self.service, 'secret', bind)

    async def test_blocked_filesystem_does_not_starve_stop_or_renewal(self):
        import threading
        from pathlib import Path
        opened_request, lease, owner = opened(self.service)
        data = bundle()
        managed = content(data)
        Path(self.tmp.name, managed['identity']['sha256']).write_bytes(data)
        self.service.prepare({'authority': authority(lease, owner, 1), 'content': managed,
                              'expected_facts': inspect(data).facts, 'resume_auto': True, 'local_output_delay_us': 0})
        await until(lambda: self.service.ordinary is None)
        gate, entered = threading.Event(), threading.Event()
        def held_disk():
            entered.set()
            gate.wait()
        pending = asyncio.create_task(self.service.disk_call(held_disk))
        try:
            await until(entered.is_set)
            renewal = {'session': lease['session'], 'lease_token': lease['lease_token'], 'renewal_sequence': '1',
                       'time_probe': opened_request['time_probe'], 'clock_mapping': None}
            self.assertEqual((await self.request('/head-control/v1/sessions/renew', renewal))[0], 200)
            stop = {'authority': authority(lease, owner, 2), 'activity': activity(owner)}
            self.assertEqual((await self.request('/head-control/v1/stop', stop))[1]['settlement'], 'settled')
        finally:
            gate.set()
            await pending
