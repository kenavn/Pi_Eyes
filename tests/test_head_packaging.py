import tempfile
import unittest
from pathlib import Path
from nightweaver_head.ownership import OutputLock
from nightweaver_head.wire import validate, Refusal


class PackagingTests(unittest.TestCase):
    def test_exclusive_output_lock(self):
        with tempfile.TemporaryDirectory() as root:
            path = str(Path(root, 'output.lock'))
            first = OutputLock(path)
            try:
                with self.assertRaisesRegex(ValueError, 'already owned'):
                    OutputLock(path)
            finally:
                first.close()
            second = OutputLock(path)
            second.close()

    def test_counter_suffix_newline_and_uuid_normalization(self):
        value = {'device_boot_id': 'AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA',
                 'challenge': 'BBBBBBBB-BBBB-BBBB-BBBB-BBBBBBBBBBBB'}
        validate('status_query', value)
        self.assertEqual(value['device_boot_id'], value['device_boot_id'].lower())
        bad = {'session': {'device_boot_id': value['device_boot_id'], 'session_id': value['challenge']},
               'lease_token': value['challenge'], 'renewal_sequence': '1\n',
               'time_probe': {'epoch': value['challenge'], 'probe_seq': '1', 'host_send_us': '0'}, 'clock_mapping': None}
        with self.assertRaises(Refusal):
            validate('renew', bad)
