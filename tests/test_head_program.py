import copy
import io
import json
import struct
import tempfile
import threading
import tracemalloc
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from nightweaver_head.program import inspect_program, compile_source
from nightweaver_head.engine import ProgramPlayer, PygamePorts
from nightweaver_head.service import Service
from nightweaver_head.wire import Refusal, validate
from head_support import (program, archive_program, wav, FakeClock, Ports, opened,
                          authority, activity, program_content, time_at, until, bundle, uid)


class ProgramTests(unittest.TestCase):
    def mutate(self, change):
        data = program()
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            manifest = json.loads(archive.read('manifest.json'))
            events = [json.loads(line) for line in archive.read('events.jsonl').splitlines()]
        change(manifest, events)
        return archive_program(manifest, events)

    def test_event_line_preflight_bounds_and_delimiters(self):
        from nightweaver_head.program import event_lines
        for raw in (b'a', b'a\n', b'a\r', b'a\r\n', b'a\rb\nc\r\nd',
                    b'\n', b'\r\n', b'x' * 4096):
            expected = raw.splitlines()
            self.assertEqual(list(event_lines(raw, len(expected))), expected)
        for raw, count in ((b'', 0), (b'a\nb', 1), (b'a', 2), (b'x' * 4097, 1),
                           (b'x' * 4097 + b'\n', 1)):
            with self.subTest(raw=raw[:10], count=count), self.assertRaises(Refusal):
                next(event_lines(raw, count))
        # No first line is exposed for decoding before the complete shape passes.
        with self.assertRaises(Refusal):
            next(event_lines(b'valid\n' + b'\n' * 100001, 2))

    def test_malicious_physical_lines_have_bounded_actual_peak(self):
        with zipfile.ZipFile(io.BytesIO(program())) as original:
            manifest = original.read('manifest.json')
        for size, budget in ((8 * 1024 * 1024, 32 * 1024 * 1024),
                             (32 * 1024 * 1024, 256 * 1024 * 1024)):
            stream = io.BytesIO()
            with zipfile.ZipFile(stream, 'w', compression=zipfile.ZIP_STORED) as archive:
                archive.writestr('manifest.json', manifest)
                archive.writestr('events.jsonl', b'\n' * size)
            data = stream.getvalue()
            tracemalloc.start()
            try:
                with self.assertRaisesRegex(Refusal, 'unsupported_media'):
                    inspect_program(data, available_bytes=budget)
                _, peak = tracemalloc.get_traced_memory()
            finally:
                tracemalloc.stop()
            # Archive exists before tracing. Charge it too, matching reservation.
            self.assertLess(len(data) + peak, budget)
            self.assertLess(peak, size + 2 * 1024 * 1024)

    def test_deflate_ratio_and_valid_line_boundaries(self):
        with zipfile.ZipFile(io.BytesIO(program())) as archive:
            manifest = archive.read('manifest.json')
            lines = archive.read('events.jsonl').splitlines()
        for delimiter in (b'\n', b'\r', b'\r\n'):
            for trailing in (False, True):
                for width in (4096, 4097):
                    payload = delimiter.join(line + b' ' * (width - len(line)) for line in lines)
                    if trailing:
                        payload += delimiter
                    stream = io.BytesIO()
                    with zipfile.ZipFile(stream, 'w', zipfile.ZIP_DEFLATED) as archive:
                        archive.writestr('manifest.json', manifest)
                        archive.writestr('events.jsonl', payload)
                    if width == 4096:
                        self.assertEqual(len(inspect_program(stream.getvalue()).events), len(lines))
                    else:
                        with self.assertRaises(Refusal):
                            inspect_program(stream.getvalue())
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, 'w', zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('manifest.json', manifest)
            archive.writestr('events.jsonl', b'\n' * (8 * 1024 * 1024))
        observed = []
        original = zipfile.ZipFile.read
        def read(archive, name, *args, **kwargs):
            observed.append(name)
            return original(archive, name, *args, **kwargs)
        with patch.object(zipfile.ZipFile, 'read', read), self.assertRaises(Refusal):
            inspect_program(stream.getvalue())
        self.assertEqual(observed, [])

    def test_origin_begin_precedes_native_play_without_reselection(self):
        ports, clock = Ports(), FakeClock()
        parsed = inspect_program(program(audio=wav(frames=288, rate=48000)))
        ports.positions = [0, 1000, 6000]
        self.assertIsNone(ProgramPlayer(ports, clock).run(parsed, object(), threading.Event()))
        self.assertLess(ports.events.index(('auto', False)), ports.events.index(('play',)))
        self.assertFalse(any(event[0] == 'load' for event in ports.events))

    def test_leading_silence_keeps_idle_until_authored_begin(self):
        with zipfile.ZipFile(io.BytesIO(program(audio=wav(frames=288, rate=48000)))) as archive:
            manifest = json.loads(archive.read('manifest.json'))
            events = [json.loads(line) for line in archive.read('events.jsonl').splitlines()]
            audio = archive.read('audio.dat')
        manifest['uses'][0].update(start=time_at(500), audio_start_frame='24', end=time_at(2500))
        for event, at in zip(events[:3], (500, 1500, 2500)):
            event['at'] = time_at(at)
        parsed = inspect_program(archive_program(manifest, events, audio))
        ports, clock = Ports(), FakeClock()
        ports.positions = [0, 500, 1500, 6000]
        self.assertIsNone(ProgramPlayer(ports, clock).run(parsed, object(), threading.Event()))
        self.assertLess(ports.events.index(('play',)), ports.events.index(('auto', False)))
        self.assertEqual(sum(event[0] == 'play' for event in ports.events), 1)

    def test_declared_peak_budget_refuses_before_expanding_events_or_audio(self):
        data = self.mutate(lambda manifest, _: manifest.update(event_count='100000'))
        observed = []
        original = zipfile.ZipFile.read
        def read(archive, name, *args, **kwargs):
            observed.append(name)
            return original(archive, name, *args, **kwargs)
        with patch.object(zipfile.ZipFile, 'read', read):
            with self.assertRaisesRegex(Refusal, 'capacity'):
                inspect_program(data, available_bytes=32 * 1024 * 1024)
        self.assertEqual(observed, ['manifest.json'])

    def test_derived_program_budget_is_distinct_from_raw_bundle_limit(self):
        from nightweaver_head.program_limits import program_reservation, PROGRAM_BYTES, PREPARED_BYTES
        data = program()
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            manifest = json.loads(archive.read('manifest.json'))
        # A generated 80MiB mono program can fit its WAV + retained native input.
        # This proves admission arithmetic without allocating a large test payload.
        audio_bytes = 80 * 1024 * 1024
        retained = program_reservation(manifest, audio_bytes + 4096, audio_bytes, 1024)
        self.assertLess(retained + audio_bytes, PREPARED_BYTES)
        self.assertLess(audio_bytes + 4096, PROGRAM_BYTES)
        with self.assertRaisesRegex(Refusal, 'capacity'):
            program_reservation(manifest, audio_bytes + 4096, audio_bytes, 1024,
                                available_bytes=150 * 1024 * 1024)

    def test_peak_event_object_allowance_covers_largest_closed_event_shape(self):
        from fractions import Fraction
        from nightweaver_head.program_limits import object_bytes
        event = json.loads(json.dumps({'at': time_at(899999999, 9223372036854775806,
                                                    9223372036854775807),
            'use_id': '1023', 'event': {'kind': 'eye', 'source_index': '99999',
                'x': 1.0, 'y': 1.0, 'left_closed': True, 'right_closed': True, 'both_closed': True}}))
        validate('event', event, 'head-program')
        at = Fraction(899999999) + Fraction(9223372036854775806, 9223372036854775807)
        self.assertLessEqual(object_bytes((at, event)), 3072)

    def test_local_float_authoring_input_is_normalized_before_native_selection(self):
        from nightweaver_head.bundle import inspect, wav_facts
        payload = struct.pack('<ffff', -0.5, 0.5, 2.0, -2.0)
        source = inspect(bundle(audio=wav(frames=2, rate=44100, channels=2,
                                          encoding=3, samples=payload)))
        compiled = compile_source(source)
        facts, _, samples = wav_facts(compiled.audio)
        self.assertEqual(facts['encoding'], 'pcm_s16_le')
        self.assertEqual((facts['channels'], facts['sample_rate'], facts['frames']), (2, 44100, '2'))
        self.assertEqual(struct.unpack('<hhhh', samples), (-16384, 16384, 32767, -32768))
        self.assertEqual(source.facts['audio']['encoding'], 'float32_le')
        self.assertEqual(source.audio[-len(payload):], payload)

    def test_closed_manifest_events_order_extents_and_source_identity(self):
        changes = [lambda m, e: m.update(extra=1), lambda m, e: m.update(duration_us='1'),
                   lambda m, e: m['uses'][1].update(id='0'),
                   lambda m, e: m['uses'][1].update(occurrence=m['uses'][0]['occurrence']),
                   lambda m, e: e[1]['event'].update(position=256),
                   lambda m, e: e[1]['event'].update(position=float('nan')),
                   lambda m, e: e[1].update(use_id='9'),
                   lambda m, e: e[1].update(at=time_at(0, 1, 1)),
                   lambda m, e: e.reverse(), lambda m, e: e.pop(),
                   lambda m, e: e[0]['event'].update(kind='other'),
                   lambda m, e: e[1]['event'].update(source_index='01'),
                   lambda m, e: e[1]['event'].update(source_index='2'),
                   lambda m, e: m['uses'][0].update(source_movement_extent_us='1002'),
                   lambda m, e: e[1].update(at=time_at(999, 1, 3))]
        for change in changes:
            with self.subTest(change=change), self.assertRaises(Refusal):
                inspect_program(self.mutate(change))

    def test_captured_delay_and_role_occurrence_identity(self):
        data = program(delay=250)
        parsed = inspect_program(data, local_output_delay_us=250)
        self.assertEqual(parsed.events[1][1]['use_id'], '0')
        self.assertEqual(parsed.events[1][1]['event']['source_index'], '0')
        self.assertNotEqual(parsed.manifest['uses'][0]['occurrence'], parsed.manifest['uses'][1]['occurrence'])
        with self.assertRaises(Refusal):
            inspect_program(data, local_output_delay_us=0)

    def test_occurrence_identity_ignores_all_object_key_order(self):
        def duplicate(m, e):
            first = m['uses'][0]['occurrence']
            first['path'] = [{'clip_id': first['use_id'], 'repeat_index': '0'}]
            m['uses'][1]['occurrence'] = {
                'path': [{'repeat_index': '0', 'clip_id': first['use_id']}],
                'use_id': first['use_id']}
            self.assertEqual(first, m['uses'][1]['occurrence'])
        with self.assertRaises(Refusal):
            inspect_program(self.mutate(duplicate))

    def test_native_pcm_gap_and_tail_silence(self):
        for channels in (1, 2):
            silent = bytearray(288 * channels * 2)
            silent[:2] = struct.pack('<h', 1)
            data = program(audio=wav(frames=288, rate=48000, channels=channels,
                                     samples=bytes(silent)))
            inspect_program(data)
            for frame in (48, 80, 143, 192, 287):
                with self.subTest(channels=channels, frame=frame):
                    samples = bytearray(silent)
                    samples[frame * channels * 2:frame * channels * 2 + 2] = struct.pack('<h', 1)
                    with self.assertRaises(Refusal):
                        inspect_program(program(audio=wav(frames=288, rate=48000,
                            channels=channels, samples=bytes(samples))))

    def normalized_program(self, rate=44100, frames=1, start=0, end=23,
                           native_frames=None, channels=2):
        with zipfile.ZipFile(io.BytesIO(program())) as archive:
            manifest = json.loads(archive.read('manifest.json'))
        use = manifest['uses'][0]
        count = (frames * 48000 + rate - 1) // rate
        use.update(start=time_at(start), end=time_at(end), source_movement_extent_us='0',
                   source_audio={'encoding': 'float32_le', 'frames': str(frames),
                                 'sample_rate': rate, 'channels': 1},
                   native_audio_frames=str(count if native_frames is None else native_frames),
                   audio_start_frame=str((start * 48000 + 999999) // 1000000))
        total = max((end * 48000 + 999999) // 1000000, int(use['audio_start_frame']) + count)
        audio = wav(frames=total, rate=48000, channels=channels)
        from nightweaver_head.bundle import wav_facts
        manifest.update(uses=[use], duration_us=str(end), event_count='2', audio=wav_facts(audio)[0])
        events = [{'at': time_at(at), 'use_id': '0', 'event': {'kind': kind}}
                  for at, kind in ((start, 'begin'), (end, 'end'))]
        return manifest, events, audio

    def test_normalized_source_exact_extent_and_native_ceil_tail(self):
        for rate, frames, end in ((44100, 1, 23), (192000, 1, 6), (8000, 1, 125)):
            manifest, events, audio = self.normalized_program(rate, frames, end=end)
            parsed = inspect_program(archive_program(manifest, events, audio))
            self.assertEqual(parsed.manifest['uses'][0]['source_audio']['sample_rate'], rate)
            self.assertEqual(parsed.manifest['uses'][0]['native_audio_frames'],
                             str((frames * 48000 + rate - 1) // rate))
        for change in (lambda m: m['uses'][0].update(native_audio_frames='1'),
                       lambda m: m['uses'][0]['source_audio'].update(frames='2'),
                       lambda m: m['uses'][0].update(audio_start_frame='1'),
                       lambda m: m['uses'][0].pop('source_content')):
            manifest, events, audio = self.normalized_program()
            change(manifest)
            with self.assertRaises(Refusal):
                inspect_program(archive_program(manifest, events, audio))
        manifest, events, audio = self.normalized_program(channels=1)
        with self.assertRaises(Refusal):
            inspect_program(archive_program(manifest, events, audio))

    def test_quantized_native_spans_cannot_collide(self):
        manifest, events, _ = self.normalized_program(start=1, end=24)
        later = copy.deepcopy(manifest['uses'][0])
        later.update(id='1', occurrence={'use_id': uid(), 'path': []},
                     start=time_at(24), end=time_at(47), audio_start_frame='2')
        manifest.update(uses=[manifest['uses'][0], later], duration_us='47', event_count='4')
        events.extend({'at': time_at(at), 'use_id': '1', 'event': {'kind': kind}}
                      for at, kind in ((24, 'begin'), (47, 'end')))
        audio = wav(frames=4, rate=48000, channels=2)
        from nightweaver_head.bundle import wav_facts
        manifest['audio'] = wav_facts(audio)[0]
        with self.assertRaises(Refusal):
            inspect_program(archive_program(manifest, events, audio))

    def test_archive_paths_duplicates_and_missing_audio(self):
        for name in ('../escape', '/tmp/escape', 'animation.csv', 'manifest.json'):
            data = io.BytesIO(program())
            with zipfile.ZipFile(data, 'a') as archive:
                archive.writestr(name, '{}')
            with self.assertRaises(Refusal):
                inspect_program(data.getvalue())
        with self.assertRaises(Refusal):
            inspect_program(self.mutate(lambda m, e: m.update(audio={
                'encoding': 'pcm_s16_le', 'frames': '8', 'sample_rate': 8000, 'channels': 1})))

    def test_generated_audio_is_native_pcm48k_and_sources_keep_original_facts(self):
        parsed = inspect_program(program(audio=wav(frames=288, rate=48000)))
        self.assertEqual(parsed.facts['audio']['frames'], '288')
        self.assertIsNone(inspect_program(program()).facts['audio'])
        for rate, encoding in ((8000, 1), (48000, 3)):
            with self.assertRaises(Refusal):
                inspect_program(program(audio=wav(frames=288, rate=rate, encoding=encoding)))

    def test_gaps_and_abutting_order_with_fractional_cursor(self):
        for gap in (0, 1000):
            ports, clock = Ports(), FakeClock()
            parsed = inspect_program(program(gap=gap))
            result = ProgramPlayer(ports, clock).run(parsed, None, threading.Event())
            self.assertIsNone(result)
            self.assertEqual([event for event in ports.events if event[0] == 'auto'],
                             [('auto', False), ('auto', True), ('auto', False), ('auto', True)])
            self.assertEqual([e[2] for e in ports.events if e[0] == 'frame'], [(100,), (101,)])
            self.assertFalse(any(e[0] in ('load', 'dispose', 'play') for e in ports.events))
        parsed = inspect_program(self.mutate(lambda m, e: (m['uses'][0].update(start=time_at(0, 1, 3)), e[0].update(at=time_at(0, 1, 3)), e[1].update(at=time_at(1000, 1, 3)))))
        ports, clock = Ports(), FakeClock()
        ProgramPlayer(ports, clock).run(parsed, None, threading.Event())
        self.assertEqual(next(e[1] for e in ports.events if e[0] == 'frame'), 2000)

    def test_decoder_cursor_and_sentinel_final_events_once(self):
        ports, clock = Ports(), FakeClock()
        ports.positions = [0, 1000, -1]
        parsed = inspect_program(program(audio=wav(frames=288, rate=48000)))
        self.assertIsNone(ProgramPlayer(ports, clock).run(parsed, object(), threading.Event()))
        self.assertEqual(len([e for e in ports.events if e[0] == 'play']), 1)
        self.assertEqual(len([e for e in ports.events if e[0] == 'frame']), 2)
        self.assertEqual(len([e for e in ports.events if e == ('auto', True)]), 2)
        ports.positions = [-1]
        self.assertEqual(ProgramPlayer(ports, FakeClock()).run(parsed, object(), threading.Event()), 'worker_failure')

    def test_faithful_old_pygame_prepare_selects_parent_without_play_or_udp(self):
        music = Mock(spec=['load', 'play', 'stop', 'get_pos', 'get_busy'])
        mixer = SimpleNamespace(music=music, get_init=lambda: (48000, -16, 2), quit=Mock())
        route = Mock()
        ports = PygamePorts('synthetic', route_check=route)
        ports.pg, ports.ready, ports.sock = SimpleNamespace(mixer=mixer), True, Mock()
        resource = ports.prepare_audio(wav(frames=288, rate=48000))
        try:
            self.assertEqual(music.load.call_count, 1)
            route.assert_called_once()
            music.play.assert_not_called()
            music.get_pos.assert_not_called()
            ports.sock.sendto.assert_not_called()
            music.get_pos.side_effect = [0, 1, 6, 0, 1, 6]
            music.get_busy.return_value = False
            parsed = inspect_program(program(audio=wav(frames=288, rate=48000)))
            for _ in range(2):
                self.assertIsNone(ProgramPlayer(ports, FakeClock()).run(parsed, resource, threading.Event()))
            self.assertEqual(music.load.call_count, 1)
            ports.dispose()
            self.assertEqual(music.load.call_count, 2)
        finally:
            ports.close()
            resource.close()

    def test_local_authoring_source_compiles_once_with_preserved_delay_policy(self):
        from nightweaver_head.bundle import inspect
        source = inspect(bundle(['0,mouth,None,None,None,None,None,100'], audio=wav()))
        compiled = compile_source(source, delay_us=15000, resume_auto=False)
        self.assertEqual(compiled.audio, source.audio)
        self.assertEqual(compiled.manifest['uses'][0]['resume_auto'], False)
        self.assertEqual(compiled.events[1][0], 15000)
        self.assertEqual(compiled.facts['duration_us'], '15001')
        ports, clock = Ports(), FakeClock()
        ports.positions = [0, 10000, -1]
        self.assertIsNone(ProgramPlayer(ports, clock).run(compiled, object(), threading.Event()))
        self.assertEqual([event for event in ports.events if event[0] == 'auto'], [('auto', False)])
        self.assertEqual(sum(e[0] == 'frame' for e in ports.events), 1)

    def test_every_authored_native_packet_checks_cancellation(self):
        from nightweaver_head.bundle import Frame
        ports = PygamePorts('synthetic')
        cancel = threading.Event()
        ports.bind_cancellation(cancel)
        ports.sock = Mock()
        ports.sock.sendto.side_effect = lambda *_: cancel.set()
        ports.frame(Frame(0, 'eye', (0.5, 0.5, True, True, False)))
        self.assertEqual(ports.sock.sendto.call_count, 1)
        ports.auto(True)  # Explicit authored idle restoration remains permitted.
        self.assertEqual(ports.sock.sendto.call_count, 6)


class ServiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ports, self.clock = Ports(), FakeClock()
        self.service = Service(self.tmp.name, self.ports, self.clock)
        _, self.lease, self.owner = opened(self.service)
        self.data = program(self.owner['role_ids'][0], delay=250)
        self.content = program_content(self.data, self.owner)
        Path(self.tmp.name, self.content['identity']['sha256']).write_bytes(self.data)
        self.rev = 0

    async def asyncTearDown(self):
        self.assertTrue(await self.service.shutdown())
        self.tmp.cleanup()

    def auth(self):
        self.rev += 1
        return authority(self.lease, self.owner, self.rev)

    async def prepare(self):
        request = {'authority': self.auth(), 'content': self.content,
                   'expected_facts': inspect_program(self.data).facts, 'local_output_delay_us': 250}
        status, result = await self.service.dispatch('POST', '/head-control/v1/prepare', request)
        self.assertEqual(status, 202)
        await until(lambda: self.service.ordinary is None)
        result = self.service.lookup(result['operation'])
        validate('result', result)
        self.assertEqual(result['phase'], 'prepared')
        return result['prepared'], request

    async def start(self, prepared, run=None):
        run = run or activity(self.owner)
        request = {'authority': self.auth(), 'activity': run, 'prepared_handle_id': prepared['handle_id'],
                   'at': None, 'lateness_allowance_us': '100000', 'local_output_delay_us': 250}
        _, result = await self.service.dispatch('POST', '/head-control/v1/start', request)
        await until(lambda: self.service.ordinary is None)
        while self.service.worker_future and not self.service.worker_future.done():
            await until(lambda: self.service.worker_future.done())
        self.service.tick()
        return run, result

    async def test_prepare_repeat_stop_new_run_stale_stop_and_disarm(self):
        prepared, request = await self.prepare()
        self.assertEqual(prepared['physical_occupancy_us'], '6000')  # Compiler already captured delay.
        self.assertEqual((await self.service.dispatch('POST', '/head-control/v1/prepare', request))[0], 200)
        run_a, result_a = await self.start(prepared)
        repeat = copy.deepcopy(run_a)
        repeat['root_repeat_index'] = '1'
        _, result_repeat = await self.start(prepared, repeat)
        stop = {'authority': self.auth(), 'activity': repeat}
        self.assertEqual(self.service.stop(stop)[1]['settlement'], 'settled')
        self.assertFalse(self.service.retired)
        with self.assertRaisesRegex(Refusal, 'wrong_activity'):
            await self.start(prepared, dict(repeat, root_repeat_index='2'))
        run_b, _ = await self.start(prepared)
        with self.assertRaisesRegex(Refusal, 'wrong_activity'):
            self.service.stop({'authority': self.auth(), 'activity': repeat})
        _, result = await self.service.dispatch('POST', '/head-control/v1/disarm', {'authority': self.auth()})
        await until(lambda: self.service.cleanup_task is None)
        self.assertEqual(result['settlement'], 'pending')  # Dispatch returns an immutable observation.
        self.assertFalse(self.service.prepared)
        with self.assertRaisesRegex(Refusal, 'owner_retired'):
            await self.start(prepared)
        self.assertFalse(any(e[0] == 'load' for e in self.ports.events))  # Audio-less no native contribution.

    async def test_content_owner_facts_refusals_and_receipt_conflict(self):
        prepared, request = await self.prepare()
        wrong = copy.deepcopy(request)
        wrong['local_output_delay_us'] = 2
        with self.assertRaisesRegex(Refusal, 'revision_conflict'):
            self.service.prepare(wrong)
        foreign = copy.deepcopy(request)
        foreign['authority'] = self.auth()
        foreign['content']['device_id'] = self.owner['stage_id']
        with self.assertRaises(Refusal):
            self.service.prepare(foreign)
        self.service.receipts.clear()
        with self.assertRaisesRegex(Refusal, 'stale_revision'):
            self.service.prepare(request)

    async def test_prepared_program_is_bound_to_its_play_before_output(self):
        prepared, _ = await self.prepare()
        wrong = activity(self.owner)
        wrong['play_id'] = uid()
        before = list(self.ports.events)
        with self.assertRaisesRegex(Refusal, 'identity_conflict'):
            await self.start(prepared, wrong)
        self.assertEqual(self.ports.events, before)
        self.assertIsNone(self.service.latest_activity)

    async def test_one_run_lease_covers_repeats_and_old_repeat_stop_retires_all(self):
        prepared, _ = await self.prepare()
        first, _ = await self.start(prepared)
        repeated = dict(first, root_repeat_index='1', cancellation_generation='3')
        await self.start(prepared, repeated)
        self.assertEqual(self.service.completed_repeat, 1)
        before = list(self.ports.events)
        with self.assertRaisesRegex(Refusal, 'identity_conflict'):
            await self.start(prepared, first)
        self.assertEqual(self.ports.events, before)
        self.assertEqual(self.service.stop({'authority': self.auth(), 'activity': first})[1]['settlement'], 'settled')
        with self.assertRaisesRegex(Refusal, 'wrong_activity'):
            await self.start(prepared, dict(repeated, root_repeat_index='2'))

    async def test_prestart_retirement_rolls_without_uuid_history_or_replay(self):
        prepared, _ = await self.prepare()
        first = None
        # These are pure, pre-start cancellations: no native playback or wall-clock wait.
        # Crossing the old UUID-set ceiling must not require a service restart.
        for _ in range(4097):
            run = activity(self.owner)
            first = first or run
            result = self.service.stop({'authority': self.auth(), 'activity': run})[1]
            self.assertEqual(result['settlement'], 'settled')
        self.assertEqual(self.service.retired_activation_high, 4097)
        self.assertLessEqual(len(self.service.receipts), 64)
        self.assertFalse(self.ports.events)
        with self.assertRaisesRegex(Refusal, 'wrong_activity'):
            await self.start(prepared, first)
        latest, _ = await self.start(prepared)
        self.assertEqual(latest['activation_generation'], '4098')
        with self.assertRaisesRegex(Refusal, 'wrong_activity'):
            self.service.stop({'authority': self.auth(), 'activity': first})

    async def test_a_lease_cannot_be_rebound_to_another_actual_cue(self):
        prepared, _ = await self.prepare()
        run, _ = await self.start(prepared)
        forged = dict(run, run_id=uid(), root_repeat_index='1')
        before = list(self.ports.events)
        with self.assertRaisesRegex(Refusal, 'identity_conflict'):
            await self.start(prepared, forged)
        self.assertEqual(self.ports.events, before)

    async def test_malicious_event_count_refuses_before_native_setup_or_ready(self):
        facts = inspect_program(self.data).facts
        with zipfile.ZipFile(io.BytesIO(self.data)) as original:
            manifest = original.read('manifest.json')
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, 'w', zipfile.ZIP_STORED) as archive:
            archive.writestr('manifest.json', manifest)
            archive.writestr('events.jsonl', b'\n' * (8 * 1024 * 1024))
        self.data = stream.getvalue()
        self.content = program_content(self.data, self.owner)
        Path(self.tmp.name, self.content['identity']['sha256']).write_bytes(self.data)
        _, result = self.service.prepare({'authority': self.auth(), 'content': self.content,
            'expected_facts': facts, 'local_output_delay_us': 250})
        await until(lambda: self.service.ordinary is None)
        self.assertEqual(self.service.lookup(result['operation'])['failure'], 'unsupported_media')
        self.assertFalse(self.service.prepared)
        self.assertFalse(self.ports.events)
        self.assertFalse(self.ports.resources)

    async def test_wrong_facts_fail_before_native_selection(self):
        facts = inspect_program(self.data).facts
        facts['duration_us'] = '7'
        _, result = self.service.prepare({'authority': self.auth(), 'content': self.content,
            'expected_facts': facts, 'local_output_delay_us': 250})
        await until(lambda: self.service.ordinary is None)
        observed = self.service.lookup(result['operation'])
        self.assertEqual(observed['failure'], 'extent_mismatch')
        self.assertFalse(self.service.prepared)
        self.assertFalse(self.ports.resources)
        await self.prepare()

    async def test_unqualified_native_float_refuses_before_load(self):
        self.assertFalse(self.service.capabilities()['float_wav'])
        self.data = program(self.owner['role_ids'][0], audio=wav(frames=288, rate=48000, encoding=3), delay=250)
        self.content = program_content(self.data, self.owner)
        Path(self.tmp.name, self.content['identity']['sha256']).write_bytes(self.data)
        _, result = self.service.prepare({'authority': self.auth(), 'content': self.content,
            'expected_facts': {'duration_us': '6000', 'audio': {'encoding': 'float32_le',
                'frames': '288', 'sample_rate': 48000, 'channels': 1}, 'uses': '2',
                'event_count': '6', 'has_eye_motion': False, 'has_mouth_motion': True},
            'local_output_delay_us': 250})
        await until(lambda: self.service.ordinary is None)
        self.assertEqual(self.service.lookup(result['operation'])['failure'], 'unsupported_media')
        self.assertFalse(self.ports.events)
        self.assertFalse(self.service.prepared)

    async def test_generated_content_upload_uses_its_separate_budget(self):
        from head_support import content
        length = 80 * 1024 * 1024
        managed = content(b'')
        managed['identity']['length'] = str(length)
        with self.assertRaisesRegex(Refusal, 'length_exceeded'):
            self.service.store.open({'device_boot_id': self.service.boot, 'job_id': uid(), 'content': managed})
        derived = dict(program_content(b'', self.owner), kind='prepared_program')
        derived['identity']['length'] = str(length)
        result = self.service.store.open({'device_boot_id': self.service.boot, 'job_id': uid(), 'content': derived})
        self.assertEqual(result['phase'], 'receiving')
        self.assertFalse(self.ports.events)

    async def test_expiry_disposes_preparation_and_never_resurrects(self):
        await self.prepare()
        self.clock.value = self.service.lease_until
        self.service.tick()
        await until(lambda: self.service.cleanup_task is None)
        self.assertFalse(self.service.prepared)
        self.assertTrue(self.service.retired)
        request = {'authority': self.auth()}
        status, disarmed = self.service.disarm(request)
        self.assertEqual(status, 200)
        self.assertEqual(disarmed['settlement'], 'settled')
        self.assertEqual(disarmed['terminal_reason'], 'stopped')
        self.assertIsNone(disarmed['failure'])
        self.assertEqual(self.service.disarm(request), (status, disarmed))
        self.assertEqual(self.service.lookup(disarmed['operation']), disarmed)
        closed = await self.service.close({k: self.lease[k] for k in ('session', 'lease_token')})
        self.assertEqual(closed['session'], self.lease['session'])

    async def test_expired_disarm_preserves_authority_and_revision_fences(self):
        prepared, prepare = await self.prepare()
        self.clock.value = self.service.lease_until
        self.service.tick()
        await until(lambda: self.service.cleanup_task is None)
        request = {'authority': self.auth()}
        for field, value in (('lease_token', uid()), ('session', dict(self.lease['session'], session_id=uid())),
                             ('owner', dict(self.owner, preparation_id=uid())),
                             ('owner', dict(self.owner, command=dict(self.owner['command'],
                                                                   command={'nonce': uid(), 'window_sequence': '1'})))):
            wrong = copy.deepcopy(request)
            wrong['authority'][field] = value
            with self.assertRaisesRegex(Refusal, 'stale_owner'):
                self.service.disarm(wrong)
        with self.assertRaisesRegex(Refusal, 'revision_conflict'):
            self.service.disarm({'authority': prepare['authority']})
        # Cleanup admission does not restore playback or renewal authority.
        with self.assertRaisesRegex(Refusal, 'expired_session'):
            self.service.prepare(prepare)
        with self.assertRaisesRegex(Refusal, 'expired_session'):
            self.service.start({'authority': request['authority'], 'activity': activity(self.owner),
                                'prepared_handle_id': prepared['handle_id']})
        with self.assertRaisesRegex(Refusal, 'expired_session'):
            self.service.renew(request['authority'])
        _, disarmed = self.service.disarm(request)
        with self.assertRaisesRegex(Refusal, 'stale_revision'):
            self.service.disarm({'authority': authority(self.lease, self.owner, 0)})
        self.assertEqual(self.service.disarm(request)[1], disarmed)
        await self.service.close({k: self.lease[k] for k in ('session', 'lease_token')})
        opened(self.service)
        with self.assertRaisesRegex(Refusal, 'stale_owner'):
            self.service.disarm(request)

    async def test_expired_unclaimed_session_cannot_admit_new_cleanup_owner(self):
        self.clock.value = self.service.lease_until
        with self.assertRaisesRegex(Refusal, 'expired_session'):
            self.service.disarm({'authority': self.auth()})
        self.assertIsNone(self.service.owner)

    async def test_expired_disarm_joins_running_output_before_releasing_owner(self):
        prepared, _ = await self.prepare()
        gate = threading.Event()
        self.ports.cleanup_gate = gate
        run = activity(self.owner)
        self.service.start({'authority': self.auth(), 'activity': run,
                            'prepared_handle_id': prepared['handle_id'], 'at': None,
                            'lateness_allowance_us': '100000', 'local_output_delay_us': 250})
        await until(self.ports.entered.is_set)
        try:
            self.clock.value = self.service.lease_until
            request = {'authority': self.auth()}
            _, disarmed = self.service.disarm(request)
            self.assertEqual(disarmed['settlement'], 'pending')
            self.clock.value += 5000001
            self.assertEqual(self.service.lookup(disarmed['operation'])['settlement'], 'unknown')
            self.assertIn(prepared['handle_id'], self.service.prepared)
            with self.assertRaisesRegex(Refusal, 'prior_worker_unsettled'):
                await self.service.close({k: self.lease[k] for k in ('session', 'lease_token')})
        finally:
            gate.set()
        await until(lambda: self.service.worker_future.done())
        self.service.tick()
        self.service.tick()  # Output must join before the retained preparation disposal is scheduled.
        await until(lambda: self.service.cleanup_task is None)
        settled = self.service.lookup(disarmed['operation'])
        self.assertEqual(settled['settlement'], 'settled')
        self.assertIsNone(settled['failure'])
        self.assertFalse(self.service.prepared)
        self.assertEqual(self.service.disarm(request)[1], settled)

    async def test_expired_disarm_joins_late_prepare_and_native_disposal(self):
        self.data = program(self.owner['role_ids'][0], audio=wav(frames=288, rate=48000), delay=250)
        self.content = program_content(self.data, self.owner)
        Path(self.tmp.name, self.content['identity']['sha256']).write_bytes(self.data)
        prepare_gate, dispose_gate, dispose_entered = threading.Event(), threading.Event(), threading.Event()
        self.ports.prepare_gate = prepare_gate
        original = self.ports.dispose
        def dispose():
            dispose_entered.set()
            dispose_gate.wait()
            original()
        self.ports.dispose = dispose
        prepare = {'authority': self.auth(), 'content': self.content,
                   'expected_facts': inspect_program(self.data).facts, 'local_output_delay_us': 250}
        _, preparing = self.service.prepare(prepare)
        await until(self.ports.prepare_entered.is_set)
        try:
            self.clock.value = self.service.lease_until
            request = {'authority': self.auth()}
            _, disarmed = self.service.disarm(request)
            self.assertEqual(disarmed['settlement'], 'pending')
            prepare_gate.set()
            await until(dispose_entered.is_set)
            # No handle was published, but the provisional native owner still exists.
            self.assertFalse(self.service.prepared)
            self.assertFalse(self.ports.resources[0].closed)
            self.clock.value += 5000001
            self.assertEqual(self.service.lookup(disarmed['operation'])['settlement'], 'unknown')
            self.assertEqual(self.service.disarm(request)[1]['settlement'], 'unknown')
            with self.assertRaisesRegex(Refusal, 'prior_worker_unsettled'):
                await self.service.close({k: self.lease[k] for k in ('session', 'lease_token')})
        finally:
            prepare_gate.set()
            dispose_gate.set()
        await until(lambda: self.service.ordinary is None)
        settled = self.service.lookup(disarmed['operation'])
        self.assertEqual(settled['settlement'], 'settled')
        self.assertIsNone(settled['failure'])
        failed = self.service.lookup(preparing['operation'])
        self.assertEqual(failed['failure'], 'expired_session')
        self.assertIsNone(failed['prepared'])
        self.assertTrue(self.ports.resources[0].closed)
        self.assertEqual(self.ports.resources[0].close_count, 1)
        self.assertFalse(any(event[0] == 'play' for event in self.ports.events))

    async def test_stop_during_active_use_joins_before_settlement_and_retains(self):
        prepared, _ = await self.prepare()
        gate = threading.Event()
        self.ports.cleanup_gate = gate
        cancelled = threading.Event()
        original_frame = self.ports.frame
        def frame(value):
            original_frame(value)
            cancelled.set()
        self.ports.frame = frame
        # Stop arrives while the worker's restoration is deliberately held.
        run = activity(self.owner)
        request = {'authority': self.auth(), 'activity': run, 'prepared_handle_id': prepared['handle_id'],
                   'at': None, 'lateness_allowance_us': '100000', 'local_output_delay_us': 250}
        _, result = await self.service.dispatch('POST', '/head-control/v1/start', request)
        await until(self.ports.entered.is_set)
        stop = {'authority': self.auth(), 'activity': run}
        try:
            self.assertEqual(self.service.stop(stop)[1]['settlement'], 'pending')
            self.assertFalse(self.service.quiet())
            self.service.lease_until += 10000000
            self.clock.value += 5000001
            self.service.tick()
            self.assertEqual(self.service.stop(stop)[1]['settlement'], 'unknown')
            self.assertIn(prepared['handle_id'], self.service.prepared)
            self.assertFalse(any(e[0] == 'dispose' for e in self.ports.events))
        finally:
            gate.set()
        await until(lambda: self.service.worker_future.done())
        self.service.tick()
        self.assertEqual(self.service.stop(stop)[1]['settlement'], 'settled')
        self.assertIn(prepared['handle_id'], self.service.prepared)
        self.assertEqual(sum(e[0] == 'frame' for e in self.ports.events), 1)

    async def test_old_repeat_stop_cancels_queued_repeat_and_joins_active_worker(self):
        prepared, _ = await self.prepare()
        gate = threading.Event()
        self.ports.cleanup_gate = gate
        first = activity(self.owner)
        def request(run):
            return {'authority': self.auth(), 'activity': run,
                    'prepared_handle_id': prepared['handle_id'], 'at': None,
                    'lateness_allowance_us': '100000', 'local_output_delay_us': 250}
        await self.service.dispatch('POST', '/head-control/v1/start', request(first))
        await until(self.ports.entered.is_set)
        await until(lambda: self.service.ordinary is None)
        repeated = dict(first, root_repeat_index='1', cancellation_generation='3')
        await self.service.dispatch('POST', '/head-control/v1/start', request(repeated))
        try:
            self.assertIsNotNone(self.service.ordinary)
            self.assertEqual(self.service.stop({'authority': self.auth(), 'activity': first})[1]['settlement'], 'pending')
            self.assertFalse(self.service.quiet())
            await until(lambda: self.service.ordinary is None)
        finally:
            gate.set()
        await until(lambda: self.service.worker_future.done())
        self.service.tick()
        self.assertEqual(self.service.stop({'authority': self.auth(), 'activity': first})[1]['settlement'], 'settled')
        self.assertEqual(sum(e[0] == 'frame' for e in self.ports.events), 1)
        with self.assertRaisesRegex(Refusal, 'wrong_activity'):
            await self.start(prepared, dict(repeated, root_repeat_index='2'))

    async def test_voice_prepare_loads_once_repeats_reuse_and_disarm_disposes(self):
        self.data = program(self.owner['role_ids'][0], audio=wav(frames=288, rate=48000), delay=250)
        self.content = program_content(self.data, self.owner)
        Path(self.tmp.name, self.content['identity']['sha256']).write_bytes(self.data)
        prepared, _ = await self.prepare()
        self.assertEqual(sum(e[0] == 'load' for e in self.ports.events), 1)
        _, duplicate = self.service.prepare({'authority': self.auth(), 'content': self.content,
            'expected_facts': inspect_program(self.data).facts, 'local_output_delay_us': 250})
        await until(lambda: self.service.ordinary is None)
        self.assertEqual(self.service.lookup(duplicate['operation'])['prepared']['handle_id'], prepared['handle_id'])
        self.assertEqual(sum(e[0] == 'load' for e in self.ports.events), 1)
        self.assertFalse(any(e[0] in ('play', 'auto', 'frame') for e in self.ports.events))
        self.ports.positions = [0, 1000, 6000]
        run, _ = await self.start(prepared)
        self.service.stop({'authority': self.auth(), 'activity': run})
        self.ports.positions = [0, 1000, 6000]
        await self.start(prepared)
        self.assertEqual(sum(e[0] == 'load' for e in self.ports.events), 1)
        self.assertFalse(any(e[0] == 'dispose' for e in self.ports.events))
        _, result = self.service.disarm({'authority': self.auth()})
        await until(lambda: self.service.cleanup_task is None)
        self.assertTrue(self.ports.resources[0].closed)
        self.assertEqual(sum(e[0] == 'dispose' for e in self.ports.events), 1)

    async def test_disarm_waits_for_native_disposal_join(self):
        prepared, _ = await self.prepare()
        gate, entered = threading.Event(), threading.Event()
        original = self.ports.dispose
        def dispose():
            entered.set()
            gate.wait()
            original()
        self.ports.dispose = dispose
        request = {'authority': self.auth()}
        _, result = self.service.disarm(request)
        await until(entered.is_set)
        try:
            self.clock.value += 5000001
            self.service.tick()
            self.assertEqual(self.service.disarm(request)[1]['settlement'], 'unknown')
            self.assertIn(prepared['handle_id'], self.service.prepared)
            with self.assertRaisesRegex(Refusal, 'prior_worker_unsettled'):
                await self.service.close({k: self.lease[k] for k in ('session', 'lease_token')})
        finally:
            gate.set()
        await until(lambda: self.service.cleanup_task is None)
        self.assertFalse(self.service.prepared)

    async def test_disarm_pending_native_prepare_does_not_publish_ready(self):
        self.data = program(self.owner['role_ids'][0], audio=wav(frames=288, rate=48000), delay=250)
        self.content = program_content(self.data, self.owner)
        Path(self.tmp.name, self.content['identity']['sha256']).write_bytes(self.data)
        gate = threading.Event()
        self.ports.prepare_gate = gate
        request = {'authority': self.auth(), 'content': self.content,
                   'expected_facts': inspect_program(self.data).facts, 'local_output_delay_us': 250}
        _, result = self.service.prepare(request)
        await until(self.ports.prepare_entered.is_set)
        _, disarmed = self.service.disarm({'authority': self.auth()})
        try:
            self.assertEqual(disarmed['settlement'], 'pending')
            self.assertEqual(result['settlement'], 'pending')
            self.assertFalse(self.service.prepared)
            self.assertFalse(self.service.quiet())
        finally:
            gate.set()
        await until(lambda: self.service.ordinary is None)
        self.service.tick()
        self.assertEqual(self.service.lookup(disarmed['operation'])['settlement'], 'settled')
        self.assertFalse(self.service.prepared)
        self.assertTrue(self.ports.resources[0].closed)


class UnknownCleanupTests(unittest.IsolatedAsyncioTestCase):
    async def test_failed_close_disposal_retains_preparation_and_session(self):
        with tempfile.TemporaryDirectory() as root:
            ports, clock = Ports(), FakeClock()
            service = Service(root, ports, clock)
            _, lease, owner = opened(service)
            data = program(owner['role_ids'][0])
            ref = program_content(data, owner)
            Path(root, ref['identity']['sha256']).write_bytes(data)
            service.prepare({'authority': authority(lease, owner, 1), 'content': ref,
                'expected_facts': inspect_program(data).facts, 'local_output_delay_us': 0})
            await until(lambda: service.ordinary is None)
            def fail_disposal():
                raise RuntimeError('synthetic uncertain decoder release')
            ports.dispose = fail_disposal
            with self.assertRaisesRegex(Refusal, 'unknown_outcome'):
                await service.close({k: lease[k] for k in ('session', 'lease_token')})
            self.assertTrue(service.prepared)
            self.assertEqual(service.session, lease['session'])
            self.assertTrue(service.retired)
            self.assertFalse(service.quiet())
            clock.value = service.lease_until
            request = {'authority': authority(lease, owner, 2)}
            _, disarmed = service.disarm(request)
            self.assertEqual(disarmed['settlement'], 'pending')
            clock.value += 5000001
            retained = service.lookup(disarmed['operation'])
            self.assertEqual(retained['settlement'], 'unknown')
            self.assertEqual(retained['failure'], 'unknown_outcome')
            self.assertEqual(service.disarm(request)[1], retained)
            with self.assertRaisesRegex(Refusal, 'prior_worker_unsettled'):
                await service.close({k: lease[k] for k in ('session', 'lease_token')})
            self.assertFalse(await service.shutdown())
            service.output.shutdown(wait=True)
            service.inspector.shutdown(wait=True)
            service.disk.shutdown(wait=True)

    async def test_failed_restoration_keeps_worker_claim_after_actual_return(self):
        with tempfile.TemporaryDirectory() as root:
            ports, clock = Ports(), FakeClock()
            service = Service(root, ports, clock)
            _, lease, owner = opened(service)
            data = program(owner['role_ids'][0])
            ref = program_content(data, owner)
            Path(root, ref['identity']['sha256']).write_bytes(data)
            _, prepared_result = service.prepare({'authority': authority(lease, owner, 1), 'content': ref,
                'expected_facts': inspect_program(data).facts, 'local_output_delay_us': 0})
            await until(lambda: service.ordinary is None)
            prepared_result = service.lookup(prepared_result['operation'])
            original_auto = ports.auto
            def fail_restore(enabled):
                if enabled:
                    raise RuntimeError('synthetic uncertain restoration')
                original_auto(enabled)
            ports.auto = fail_restore
            service.start({'authority': authority(lease, owner, 2), 'activity': activity(owner),
                'prepared_handle_id': prepared_result['prepared']['handle_id'], 'at': None,
                'lateness_allowance_us': '100000', 'local_output_delay_us': 0})
            await until(lambda: service.worker_future is not None and service.worker_future.done())
            service.tick()
            self.assertEqual(service.worker['settlement'], 'unknown')
            self.assertFalse(service.quiet())
            self.assertTrue(service.prepared)
            self.assertFalse(await service.shutdown())
            # All fake calls have returned. Test-only executor reclamation is not settlement.
            service.output.shutdown(wait=True)
            service.inspector.shutdown(wait=True)
            service.disk.shutdown(wait=True)
