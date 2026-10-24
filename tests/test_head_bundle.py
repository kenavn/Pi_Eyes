import io
import math
import struct
import unittest
import zipfile
from nightweaver_head.bundle import inspect, timestamp, wav_facts
from nightweaver_head.wire import Refusal, decode, validate
from head_support import bundle, wav, opened, Ports


class BundleTests(unittest.TestCase):
    def test_cross_language_facts(self):
        cases = [(3900088, 48000, 2, 3, 81251834), (3824069, 48000, 2, 3, 79668105),
                 (1886277, 44100, 1, 1, 42772722)]
        for frames, rate, channels, encoding, extent in cases:
            facts, got = wav_facts(wav(frames, rate, channels, encoding, metadata=True))
            self.assertEqual(got, extent)
            self.assertEqual(facts['frames'], str(frames))
        self.assertEqual(timestamp('81245.00048828125')[1], 81245000)
        facts = inspect(bundle()).facts
        self.assertEqual(facts['movement_extent_us'], '1')
        self.assertEqual(facts['logical_extent_us'], '1')
        self.assertIsNone(facts['audio'])
        validate('inspect_result', {'content': {'sha256': 'a'*64, 'length': '1'}, 'facts': facts})

    def test_float_finite_not_clipped(self):
        data = wav(1, encoding=3, samples=struct.pack('<f', 123.0))
        self.assertEqual(wav_facts(data)[0]['encoding'], 'float32_le')
        for x in (float('nan'), float('inf'), -float('inf')):
            with self.assertRaises(Refusal):
                wav_facts(wav(1, encoding=3, samples=struct.pack('<f', x)))

    def test_bad_riff(self):
        data = wav(metadata=True)
        for bad in (data[:-1], data + b'x', data[:20], data.replace(b'fmt ', b'xxxx')):
            with self.assertRaises(Refusal):
                wav_facts(bad)
        pcm8 = bytearray(wav())
        struct.pack_into('<H', pcm8, 34, 8)
        with self.assertRaises(Refusal):
            wav_facts(bytes(pcm8))

    def test_strict_csv(self):
        for row in ['-1,mouth,None,None,None,None,None,1', 'NaN,mouth,None,None,None,None,None,1',
                    '0,mouth,None,None,None,None,None,1.1', '0,eye,NaN,0,True,False,False,None',
                    '0,eye,0,0,maybe,False,False,None', '0,mouth,0,None,None,None,None,2']:
            with self.subTest(row=row), self.assertRaises(Refusal):
                inspect(bundle([row]))
        for rows in [['1,mouth,None,None,None,None,None,1', '0,mouth,None,None,None,None,None,2'],
                     ['0.0009,mouth,None,None,None,None,None,1', '0.0008,mouth,None,None,None,None,None,2']]:
            with self.assertRaises(Refusal):
                inspect(bundle(rows))
        b = inspect(bundle(['000.0009,mouth,None,None,None,None,None,1',
                            '000.00099,mouth,None,None,None,None,None,2']))
        self.assertEqual([f.values for f in b.frames], [(1,), (2,)])

    def test_archive_and_manifest(self):
        for name in ('../animation.csv', '/audio.dat', 'unknown', 'folder/'):
            data = io.BytesIO(bundle())
            with zipfile.ZipFile(data, 'a') as archive:
                archive.writestr(name, b'x')
            with self.assertRaises(Refusal):
                inspect(data.getvalue())
        with self.assertRaises(Refusal):
            inspect(bundle(manifest={'audio_file': 'missing.wav', 'audio_format': 'wav'}))
        with self.assertRaises(Refusal):
            decode(b'{"a":1,"a":2}')
        for value in (b'{"a":NaN}', b'\xff'):
            with self.assertRaises(Refusal):
                decode(value)

    def test_shared_semantic_fixture(self):
        import json
        from pathlib import Path
        cases = json.loads((Path(__file__).parent / 'fixtures/bundle-facts.json').read_text())
        for case in cases:
            with self.subTest(name=case['name']):
                audio = None if case['encoding'] is None else wav(case['frames'], case['sample_rate'],
                        case['channels'], 3 if case['encoding'] == 'float32_le' else 1)
                rows = [] if case['last_time_ms'] is None else [case['last_time_ms'] + ',mouth,None,None,None,None,None,123']
                facts = inspect(bundle(rows, audio)).facts
                for key in ('audio_extent_us', 'movement_extent_us', 'logical_extent_us'):
                    self.assertEqual(int(facts[key]), case[key])

    def test_fmt16_or_fmt18_zero_extension_only(self):
        source = wav()
        def extended(extension):
            value = source[:16] + struct.pack('<I', 16 + len(extension)) + source[20:36] + extension + source[36:]
            return value[:4] + struct.pack('<I', len(value)-8) + value[8:]
        self.assertEqual(wav_facts(extended(b'\0\0'))[0]['encoding'], 'pcm_s16_le')
        for extension in (b'\x02\0xx', b'\x01\0', b'\0\0xx'):
            with self.assertRaises(Refusal):
                wav_facts(extended(extension))
