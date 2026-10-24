import tempfile
import unittest
from pathlib import Path
from nightweaver_head.content import ContentStore
from nightweaver_head.wire import Refusal, validate
from head_support import uid, FakeClock, content


class ContentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.clock = FakeClock()
        self.store = ContentStore(self.tmp.name, uid(), self.clock)
        self.data = b'hello content'
        self.request = {'device_boot_id': self.store.boot, 'job_id': uid(), 'content': content(self.data)}

    def tearDown(self):
        if self.store.active:
            self.store.fail(self.store.active[0], 'cancelled')
        self.tmp.cleanup()

    def test_publish_and_lost_ack_duplicate(self):
        receipt = self.store.open(self.request)
        self.assertEqual(receipt['phase'], 'receiving')
        self.assertFalse(self.store.inventory()['entries'])
        upload = self.store.begin(self.request['job_id'], self.store.boot, len(self.data))
        upload.write(self.data[:3])
        self.assertFalse(self.store.inventory()['entries'])
        upload.write(self.data[3:])
        receipt = upload.finish()
        validate('receipt', receipt, 'device-content')
        self.assertEqual(self.store.read(self.request['content']['identity']), self.data)
        self.assertEqual(self.store.open(self.request), receipt)
        duplicate = self.store.begin(self.request['job_id'], self.store.boot, len(self.data))
        duplicate.write(self.data)
        self.assertEqual(duplicate.finish(), receipt)
        self.assertEqual(self.store.fail(self.request['job_id'], 'cancelled')['phase'], 'published')

    def test_bad_hash_partial_expiry_and_symlink(self):
        self.store.open(self.request)
        upload = self.store.begin(self.request['job_id'], self.store.boot, len(self.data))
        upload.write(b'x' * len(self.data))
        with self.assertRaisesRegex(Refusal, 'content_mismatch'):
            upload.finish()
        self.store.fail(self.request['job_id'], 'content_mismatch')
        self.assertFalse(list(Path(self.tmp.name).iterdir()))
        with self.assertRaisesRegex(Refusal, 'cancelled'):
            self.store.begin(self.request['job_id'], self.store.boot, len(self.data))
        self.request['job_id'] = uid()
        self.store.open(self.request)
        self.clock.value += 120000001
        self.store.expire()
        self.assertEqual(self.store.receipts[self.request['job_id']]['failure'], 'transfer_expired')
        identity = self.request['content']['identity']
        Path(self.tmp.name, identity['sha256']).symlink_to('/etc/passwd')
        with self.assertRaisesRegex(Refusal, 'content_missing'):
            self.store.read(identity)

    def test_job_identity_tombstone_and_quota(self):
        self.store.open(self.request)
        self.store.fail(self.request['job_id'], 'cancelled')
        self.store.receipts.clear()
        with self.assertRaisesRegex(Refusal, 'outcome_unavailable'):
            self.store.open(self.request)
        changed = dict(self.request, content=content(b'other'))
        with self.assertRaisesRegex(Refusal, 'identity_conflict'):
            self.store.open(changed)

    def test_duplicate_published_disconnect_releases_bulk_slot(self):
        self.store.open(self.request)
        upload = self.store.begin(self.request['job_id'], self.store.boot, len(self.data))
        upload.write(self.data)
        upload.finish()
        duplicate = self.store.begin(self.request['job_id'], self.store.boot, len(self.data))
        duplicate.write(self.data[:1])
        self.store.fail(self.request['job_id'], 'cancelled')
        self.assertIsNone(self.store.upload)
        self.assertEqual(self.store.receipts[self.request['job_id']]['phase'], 'published')
        self.assertEqual(self.store.read(self.request['content']['identity']), self.data)

    def test_readonly_local_inventory_never_managed_fallback(self):
        with tempfile.TemporaryDirectory() as local:
            source = Path(local, 'original.skelanim')
            source.write_bytes(self.data)
            Path(local, 'link.skelanim').symlink_to(source)
            self.store.index_local(local)
            entries = self.store.inventory()['entries']
            self.assertEqual(len(entries), 1)
            self.assertEqual(entries[0]['origin'], 'local_library')
            self.assertFalse(self.store.exists(entries[0]['identity']))
            receipt = self.store.open(self.request)
            self.assertEqual(receipt['phase'], 'receiving')
            self.assertEqual(source.read_bytes(), self.data)
