"""Bounded one-request HTTP/1.1 server using h11's framing parser."""
import asyncio
import hmac
import json
import re
import socket
import time
import uuid
import h11
from .wire import Refusal, decode


class HTTPServer:
    def __init__(self, service, secret, bind, port=8082, test_config=False):
        if bind not in ('192.168.2.119', '192.168.2.53'):
            if not test_config or bind != '127.0.0.1':
                raise ValueError('exact configured Show Ethernet IPv4 required')
        if not secret or len(secret) > 4096 or any(not 33 <= ord(c) <= 126 for c in secret):
            raise ValueError('invalid credential file')
        self.service, self.secret, self.bind, self.port = service, secret, bind, port
        self.connections = set()
        self.ordinary = 0
        self.observers = 0
        self.reserved = set()
        self.server = None
        self.tasks = set()
        self.background = set()
        self.deadline = 5.0
        self.idle = 1.0
        self.bulk_deadline = 120.0
        self.bulk_idle = 5.0

    async def start(self):
        # No StreamReader callback coroutine: reject excess sockets before task allocation.
        self.server = await asyncio.start_server(self.accept, self.bind, self.port,
                                                 family=socket.AF_INET, limit=16384)
        self.service.begin()
        return self.server.sockets[0].getsockname()

    def accept(self, reader, writer):
        if len(self.connections) >= 8:
            writer.close()
            return
        self.connections.add(writer)
        task = asyncio.create_task(self.handle(reader, writer))
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    async def read(self, reader, until, idle):
        remaining = until - time.monotonic()
        if remaining <= 0:
            raise Refusal('malformed', 408)
        try:
            data = await asyncio.wait_for(reader.read(16384), min(idle, remaining))
        except asyncio.TimeoutError:
            raise Refusal('malformed', 408) from None
        if not data:
            raise Refusal('malformed', 400)
        return data

    def background_task(self, coroutine):
        task = asyncio.create_task(coroutine)
        self.background.add(task)
        def done(future):
            self.background.discard(future)
            if not future.cancelled():
                future.exception()
        task.add_done_callback(done)
        return task

    async def disk_until(self, deadline, function, *args):
        task = self.background_task(self.service.disk_call(function, *args))
        try:
            return await asyncio.wait_for(asyncio.shield(task), max(0, deadline - time.monotonic()))
        except asyncio.TimeoutError:
            raise Refusal('transfer_expired', 408) from None

    async def handle(self, reader, writer):
        codec = h11.Connection(h11.SERVER, max_incomplete_event_size=16384)
        upload = None
        classification = None
        head_bytes = b''
        started = time.monotonic()
        deadline = started + self.deadline
        try:
            # Count actual complete aggregate headers, including a complete giant header.
            while b'\r\n\r\n' not in head_bytes:
                data = await self.read(reader, deadline, self.idle)
                head_bytes += data
                header_end = head_bytes.find(b'\r\n\r\n')
                if (len(head_bytes) if header_end < 0 else header_end + 4) > 16384:
                    raise Refusal('malformed', 413)
            codec.receive_data(head_bytes)
            event = codec.next_event()
            if not isinstance(event, h11.Request):
                raise Refusal('malformed')
            headers = {}
            for key, value in event.headers:
                name = key.decode('ascii').lower()
                if name in headers:
                    raise Refusal('malformed')
                headers[name] = value.decode('ascii')
            method = event.method.decode('ascii')
            path = event.target.decode('ascii')
            if '?' in path or '#' in path or not path.startswith('/'):
                raise Refusal('malformed')
            if not hmac.compare_digest(headers.get('authorization', ''), 'Bearer ' + self.secret):
                raise Refusal('unauthenticated', 401)
            if ('transfer-encoding' in headers or 'content-encoding' in headers
                    or 'upgrade' in headers or 'expect' in headers
                    or headers.get('connection', '').lower() == 'upgrade'):
                raise Refusal('malformed')
            reserved = path in ('/head-control/v1/stop', '/head-control/v1/sessions/renew')
            observation = path in ('/head-control/v1/status', '/head-control/v1/capabilities',
                                   '/head-control/v1/operations/lookup', '/device-content/v1/transfers/lookup')
            if reserved:
                if path in self.reserved:
                    raise Refusal('capacity', 429)
                self.reserved.add(path)
                classification = ('reserved', path)
            else:
                if self.ordinary >= 6 or observation and self.observers >= 2:
                    raise Refusal('capacity', 429)
                self.ordinary += 1
                if observation:
                    self.observers += 1
                classification = ('ordinary', observation)
            text_length = headers.get('content-length', '0')
            if not re.fullmatch('0|[1-9][0-9]*', text_length) or len(text_length) > 20:
                raise Refusal('malformed')
            length = int(text_length)
            bulk = re.fullmatch(r'/device-content/v1/transfers/([0-9a-fA-F-]{36})/bytes', path)
            if bulk:
                if method != 'PUT':
                    raise Refusal('malformed', 405)
                if headers.get('content-type') != 'application/octet-stream':
                    raise Refusal('malformed', 415)
                if 'content-length' not in headers or 'x-device-boot-id' not in headers:
                    raise Refusal('malformed')
                deadline, idle = started + self.bulk_deadline, self.bulk_idle
                try:
                    job = uuid.UUID(bulk[1])
                    boot = uuid.UUID(headers['x-device-boot-id'])
                    if not job.int or not boot.int:
                        raise ValueError()
                except ValueError:
                    raise Refusal('malformed') from None
                upload = await self.disk_until(deadline, self.service.store.begin, str(job), str(boot), length)
            else:
                idle = self.idle
                if length > 131072:
                    raise Refusal('malformed', 413)
                if method != 'GET' and headers.get('content-type') != 'application/json':
                    raise Refusal('malformed', 415)
                if method == 'GET' and length:
                    raise Refusal('malformed')
            body = bytearray()
            count = 0
            while True:
                event = codec.next_event()
                if event is h11.NEED_DATA:
                    codec.receive_data(await self.read(reader, deadline, idle))
                    continue
                if isinstance(event, h11.Data):
                    count += len(event.data)
                    if count > length:
                        raise Refusal('malformed', 413)
                    if upload:
                        await self.disk_until(deadline, upload.write, event.data)
                    else:
                        body.extend(event.data)
                elif isinstance(event, h11.EndOfMessage):
                    # Bytes after first message are never admitted as another operation.
                    if codec.trailing_data[0]:
                        raise Refusal('malformed')
                    break
                else:
                    raise Refusal('malformed')
            if upload:
                result = await self.disk_until(deadline, upload.finish)
                status = 200
                upload = None
            else:
                request = decode(bytes(body)) if method != 'GET' else None
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise Refusal('malformed', 408)
                # Shield an admitted inspect; disconnect/deadline must not release ownership.
                task = asyncio.create_task(self.service.dispatch(method, path, request))
                try:
                    status, result = await asyncio.wait_for(asyncio.shield(task), remaining)
                except asyncio.TimeoutError:
                    task.add_done_callback(lambda future: future.exception() if not future.cancelled() else None)
                    raise Refusal('unknown_outcome', 503) from None
            await self.respond(writer, codec, status, result)
        except Refusal as error:
            if upload and error.status == 408:
                error = Refusal('transfer_expired', 408)
            if upload:
                self.background_task(self.service.disk_call(self.service.store.fail, upload.job,
                         'transfer_expired' if error.status == 408 else error.reason if error.reason in
                         ('cancelled', 'content_mismatch', 'length_exceeded') else 'cancelled'))
                # A stuck disk retains the transfer until disposal actually returns.

            await self.respond(writer, codec, error.status, {'reason': error.reason})
        except (h11.ProtocolError, UnicodeError, ValueError, ConnectionError, OSError) as error:
            if upload:
                self.background_task(self.service.disk_call(self.service.store.fail, upload.job,
                                     'disk_full' if isinstance(error, OSError) and error.errno == 28 else 'cancelled'))
            await self.respond(writer, codec, 507 if isinstance(error, OSError) and error.errno == 28 else 400,
                               {'reason': 'disk_full' if isinstance(error, OSError) and error.errno == 28 else 'malformed'})
        finally:
            if classification:
                kind, value = classification
                if kind == 'reserved':
                    self.reserved.discard(value)
                else:
                    self.ordinary -= 1
                    self.observers -= int(value)
            writer.close()
            try:
                await asyncio.wait_for(writer.wait_closed(), .5)
            except (ConnectionError, asyncio.TimeoutError):
                pass
            self.connections.discard(writer)

    async def respond(self, writer, codec, status, value):
        try:
            data = json.dumps(value, separators=(',', ':'), allow_nan=False).encode('utf-8')
            if len(data) > 262144:
                status, data = 503, b'{"reason":"capacity"}'
            headers = [(b'content-type', b'application/json'), (b'cache-control', b'no-store'),
                       (b'connection', b'close'), (b'content-length', str(len(data)).encode('ascii'))]
            try:
                output = codec.send(h11.Response(status_code=status, headers=headers))
                output += codec.send(h11.Data(data=data)) + codec.send(h11.EndOfMessage())
            except h11.ProtocolError:
                output = ('HTTP/1.1 %d Error\r\nContent-Type: application/json\r\nCache-Control: no-store\r\nConnection: close\r\nContent-Length: %d\r\n\r\n' % (status, len(data))).encode() + data
            writer.write(output)
            await asyncio.wait_for(writer.drain(), 1)
        except (ConnectionError, OSError, asyncio.TimeoutError):
            pass

    async def close(self):
        self.server.close()
        await self.server.wait_closed()
        for writer in self.connections.copy():
            writer.close()
        if self.tasks:
            await asyncio.gather(*self.tasks, return_exceptions=True)
        if self.background:
            try:
                await asyncio.wait_for(asyncio.gather(*self.background), 5)
            except asyncio.TimeoutError:
                return False
        return await self.service.shutdown()
