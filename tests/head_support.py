import asyncio
import hashlib
import io
import json
import struct
import threading
import uuid
import zipfile
from nightweaver_head.bundle import COLUMNS


def uid():
    return str(uuid.uuid4())


def wav(frames=80, rate=8000, channels=1, encoding=1, samples=None, metadata=False):
    bits = 16 if encoding == 1 else 32
    samples = samples if samples is not None else b'\0' * frames * channels * (bits // 8)
    def chunk(tag, data):
        return tag + struct.pack('<I', len(data)) + data + (b'\0' if len(data) & 1 else b'')
    fmt = struct.pack('<HHIIHH', encoding, channels, rate, rate * channels * (bits // 8), channels * (bits // 8), bits)
    payload = b'WAVE' + chunk(b'fmt ', fmt) + chunk(b'data', samples)
    if metadata:
        payload += chunk(b'LIST', b'abc') + chunk(b'iXML', b'x')
    return b'RIFF' + struct.pack('<I', len(payload)) + payload


def bundle(rows=None, audio=None, manifest=None):
    rows = rows if rows is not None else ['0,mouth,None,None,None,None,None,100']
    meta = {'version': '1.0', 'audio_file': 'test.wav' if audio else None,
            'audio_format': 'wav' if audio else None}
    if manifest:
        meta.update(manifest)
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w', zipfile.ZIP_STORED) as archive:
        archive.writestr('manifest.json', json.dumps(meta))
        archive.writestr('animation.csv', ','.join(COLUMNS) + '\n' + ('\n'.join(rows) + '\n' if rows else ''))
        if audio:
            archive.writestr('audio.dat', audio)
    return stream.getvalue()


class FakeClock:
    def __init__(self):
        self.value = 1000000
        self.hook = None

    def now(self):
        return self.value

    def wait(self, event, us):
        self.value += us
        if self.hook:
            self.hook()


class Audio:
    def __init__(self, payload):
        self.payload = payload
        self.closed = False
        self.close_count = 0

    def close(self):
        if not self.closed:
            self.close_count += 1
            self.closed = True


class Ports:
    ready = True
    sink_name = 'synthetic'
    def __init__(self):
        self.events = []
        self.positions = []
        self.is_busy = False
        self.cleanup_gate = None
        self.entered = threading.Event()
        self.failed_verify = False
        self.resources = []
        self.prepare_gate = self.load_gate = None
        self.prepare_entered = threading.Event()
        self.load_entered = threading.Event()

    def prepare_audio(self, audio):
        self.prepare_entered.set()
        if self.prepare_gate:
            self.prepare_gate.wait()
        if self.failed_verify:
            raise RuntimeError('synthetic unavailable')
        self.events.append(('prepare_audio', len(audio)))
        resource = Audio(audio)
        self.resources.append(resource)
        return resource

    def load(self, audio):
        assert not audio.closed
        self.events.append(('load', audio))
        self.load_entered.set()
        if self.load_gate:
            self.load_gate.wait()

    def play(self):
        self.events.append(('play',))

    def position(self):
        return self.positions.pop(0) if self.positions else -1

    def busy(self):
        return self.is_busy

    def stop(self):
        self.events.append(('stop',))

    def auto(self, enabled):
        self.events.append(('auto', enabled))
        if enabled and self.cleanup_gate:
            self.entered.set()
            self.cleanup_gate.wait()

    def frame(self, frame):
        self.events.append(('frame', frame.at_us, frame.values))

    def dispose(self):
        self.events.append(('dispose',))

    def close(self):
        self.events.append(('close',))


def owner(epoch):
    return {'command': {'process_epoch': epoch, 'command': {'nonce': uid(), 'window_sequence': '1'}},
            'coordinator_epoch': epoch, 'loaded': {'project': {'project_id': uid(), 'revision': '1'}, 'context_generation': '1'},
            'stage_id': uid(), 'play_id': uid(), 'run_id': uid(), 'device_id': uid(), 'role_ids': [uid()],
            'participant_generation': '1'}


def opened(service, mapping=None):
    epoch = uid()
    request = {'protocol_version': 1, 'device_boot_id': service.boot, 'coordinator_epoch': epoch,
               'handshake_nonce': uid(), 'time_probe': {'epoch': epoch, 'probe_seq': '1', 'host_send_us': '0'},
               'clock_mapping': mapping}
    lease = service.open(request)
    return request, lease, owner(epoch)


def authority(lease, owner, rev):
    return {k: lease[k] for k in ('session', 'lease_token')} | {'owner': owner, 'operation_revision': str(rev)}


def activity(owner):
    return {'owner': owner, 'role_id': owner['role_ids'][0], 'occurrence': {'use_id': uid(), 'path': [], 'root_repeat_index': '0'},
            'cancellation_generation': '0'}


def content(data):
    return {'asset_id': uid(), 'version_id': uid(), 'identity': {'sha256': hashlib.sha256(data).hexdigest(), 'length': str(len(data))}}


async def until(predicate):
    for _ in range(10000):
        if predicate():
            return
        await asyncio.sleep(0)
    raise AssertionError('condition did not settle')
