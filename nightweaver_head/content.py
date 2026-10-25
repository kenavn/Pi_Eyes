"""Atomic bounded delivered content. No deletion policy or arbitrary path input."""
import hashlib
import os
import stat
import tempfile
from collections import OrderedDict
from pathlib import Path
from .bundle import MAX_BUNDLE
from .program_limits import PROGRAM_BYTES
from .wire import Refusal


class ContentStore:
    def __init__(self, root, boot, clock, local_root=None):
        self.root = Path(root)
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        if self.root.is_symlink():
            raise ValueError('content root cannot be symlink')
        self.boot, self.clock, self.local_root = boot, clock, local_root
        self.receipts, self.tombstones = OrderedDict(), {}
        self.active = None
        self.pins = set()
        self.upload = None
        self.local_entries = []

    def index_local(self, root):
        """Startup-only read-only bounded observations; never a managed fallback."""
        entries = []
        path = Path(root)
        if not path.exists():
            self.local_entries = []
            return
        with os.scandir(path) as files:
            for index, entry in enumerate(files):
                if index >= 1024:
                    break
                if not entry.name.endswith('.skelanim') or not entry.is_file(follow_symlinks=False):
                    continue
                fd = os.open(entry.path, os.O_RDONLY | os.O_NOFOLLOW)
                with os.fdopen(fd, 'rb') as stream:
                    info = os.fstat(stream.fileno())
                    if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= MAX_BUNDLE:
                        continue
                    digest = hashlib.sha256()
                    remaining = info.st_size
                    while remaining:
                        block = stream.read(min(65536, remaining))
                        if not block:
                            raise ValueError('local library changed during observation')
                        digest.update(block)
                        remaining -= len(block)
                    if stream.read(1):
                        raise ValueError('local library changed during observation')
                    entries.append({'identity': {'sha256': digest.hexdigest(), 'length': str(info.st_size)},
                                    'origin': 'local_library', 'pinned': False})
        self.local_entries = entries

    def boot_check(self, boot):
        if boot != self.boot:
            raise Refusal('stale_boot', 409)

    def open_file(self, identity):
        try:
            fd = os.open(str(self.root / identity['sha256']), os.O_RDONLY | os.O_NOFOLLOW)
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_size != int(identity['length']):
                os.close(fd)
                raise Refusal('content_missing', 404)
            return os.fdopen(fd, 'rb')
        except OSError:
            raise Refusal('content_missing', 404) from None

    def read(self, identity, limit=MAX_BUNDLE):
        if int(identity['length']) > limit:
            raise Refusal('unsupported_media', 422)
        with self.open_file(identity) as stream:
            data = stream.read(limit + 1)
        if len(data) != int(identity['length']) or hashlib.sha256(data).hexdigest() != identity['sha256']:
            raise Refusal('content_mismatch', 422)
        return data

    def exists(self, identity):
        try:
            if int(identity['length']) > PROGRAM_BYTES:
                return False
            with self.open_file(identity) as stream:
                digest = hashlib.sha256()
                remaining = int(identity['length'])
                while remaining:
                    block = stream.read(min(65536, remaining))
                    if not block:
                        return False
                    digest.update(block)
                    remaining -= len(block)
                return not stream.read(1) and digest.hexdigest() == identity['sha256']
        except Refusal:
            return False

    def entry(self, identity):
        if not self.exists(identity):
            raise Refusal('content_missing', 404)
        return {'identity': identity, 'origin': 'delivered', 'pinned': identity['sha256'] in self.pins}

    def inventory(self):
        entries, scanned, truncated = [], 0, False
        with os.scandir(self.root) as files:
            for path in files:
                scanned += 1
                if scanned > 2048:
                    truncated = True
                    break
                if len(path.name) != 64 or any(c not in '0123456789abcdef' for c in path.name):
                    continue
                info = path.stat(follow_symlinks=False)
                if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= PROGRAM_BYTES:
                    continue
                if len(entries) == 1024:
                    truncated = True
                    break
                entries.append(self.entry({'sha256': path.name, 'length': str(info.st_size)}))
        combined = entries + self.local_entries
        return {'device_boot_id': self.boot, 'entries': combined[:1024],
                'truncated': truncated or len(combined) > 1024}

    def expire(self):
        if self.active and self.clock.now() >= self.active[1]:
            self.fail(self.active[0], 'transfer_expired')

    def open(self, request):
        self.boot_check(request['device_boot_id'])
        self.expire()
        job = request['job_id']
        if job in self.tombstones:
            if self.tombstones[job] != request:
                raise Refusal('identity_conflict', 409)
            if job not in self.receipts:
                raise Refusal('outcome_unavailable', 404)
            return self.receipts[job]
        if self.active or self.upload or len(self.tombstones) >= 4096:
            raise Refusal('capacity', 429)
        identity = request['content']['identity']
        length = int(identity['length'])
        if length > (PROGRAM_BYTES if request['content']['kind'] == 'prepared_program' else MAX_BUNDLE):
            raise Refusal('length_exceeded', 413)
        used, count = 0, 0
        with os.scandir(self.root) as files:
            for entry in files:
                count += 1
                if count > 2048:
                    raise Refusal('capacity', 429)
                info = entry.stat(follow_symlinks=False)
                if stat.S_ISREG(info.st_mode):
                    used += info.st_size
        published = self.exists(identity)
        if not published and identity['sha256'] in self.pins:
            raise Refusal('content_mismatch', 422)
        if not published and used + length > 1073741824:
            raise Refusal('capacity', 429)
        receipt = {'request': request, 'phase': 'published' if published else 'receiving',
                   'received_bytes': identity['length'] if published else '0', 'failure': None}
        self.tombstones[job] = request
        self.receipts[job] = receipt
        if not published:
            self.active = (job, self.clock.now() + 120000000)
        while len(self.receipts) > 64:
            self.receipts.popitem(last=False)
        return receipt

    def lookup(self, query):
        self.boot_check(query['device_boot_id'])
        self.expire()
        if query['job_id'] not in self.receipts:
            raise Refusal('outcome_unavailable', 404)
        return self.receipts[query['job_id']]

    def fail(self, job, reason):
        receipt = self.receipts[job]
        if receipt['phase'] != 'receiving':
            if self.upload and self.upload.job == job:
                self.upload.abort()
            return receipt
        if self.upload and self.upload.job == job:
            self.upload.abort()
        receipt.update(phase='failed', failure=reason)
        if self.active and self.active[0] == job:
            self.active = None
        return receipt

    def begin(self, job, boot, length):
        self.boot_check(boot)
        self.expire()
        if job not in self.receipts:
            raise Refusal('outcome_unavailable', 404)
        receipt = self.receipts[job]
        if int(receipt['request']['content']['identity']['length']) != length:
            raise Refusal('content_mismatch', 422)
        if receipt['phase'] == 'failed':
            raise Refusal('cancelled', 409)
        if self.upload:
            raise Refusal('capacity', 429)
        try:
            upload = Upload(self, job, receipt)
        except OSError as error:
            self.fail(job, 'disk_full')
            raise Refusal('disk_full', 507) from None
        self.upload = upload
        return upload


class Upload:
    def __init__(self, store, job, receipt):
        self.store, self.job, self.receipt = store, job, receipt
        self.digest, self.count = hashlib.sha256(), 0
        self.identity = receipt['request']['content']['identity']
        self.path = self.stream = None
        if receipt['phase'] == 'receiving':
            fd, self.path = tempfile.mkstemp(prefix='.upload-', dir=str(store.root))
            self.stream = os.fdopen(fd, 'wb')

    def write(self, data):
        if self.receipt['phase'] == 'failed':
            raise Refusal('cancelled', 409)
        if self.count + len(data) > int(self.identity['length']):
            raise Refusal('length_exceeded', 413)
        self.digest.update(data)
        self.count += len(data)
        if self.stream:
            self.stream.write(data)
            self.receipt['received_bytes'] = str(self.count)

    def finish(self):
        if self.receipt['phase'] == 'failed':
            raise Refusal('cancelled', 409)
        if self.count != int(self.identity['length']) or self.digest.hexdigest() != self.identity['sha256']:
            raise Refusal('content_mismatch', 422)
        if self.stream:
            self.stream.flush()
            os.fsync(self.stream.fileno())
            self.stream.close()
            self.stream = None
            os.replace(self.path, self.store.root / self.identity['sha256'])
            self.path = None
            fd = os.open(str(self.store.root), os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
        self.receipt.update(phase='published', received_bytes=str(self.count), failure=None)
        if self.store.active and self.store.active[0] == self.job:
            self.store.active = None
        if self.store.upload is self:
            self.store.upload = None
        return self.receipt

    def abort(self):
        if self.stream:
            self.stream.close()
            self.stream = None
        if self.path:
            os.unlink(self.path)
            self.path = None
        if self.store.upload is self:
            self.store.upload = None
