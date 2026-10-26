"""Closed, bounded immutable whole-program archive; never extracts archive paths."""
import io
import stat
import struct
import wave
import zipfile
from dataclasses import dataclass
from fractions import Fraction
from .bundle import MAX_EXTENT, wav_facts, unsupported
from .program_limits import (PROGRAM_BYTES, EXPANDED_PROGRAM_BYTES, PREPARED_BYTES,
                             MANIFEST_PARSE_BYTES, program_reservation)
from .wire import decode, validate, Refusal


def event_lines(raw, expected):
    """Preflight physical records in constant space before yielding any copies.

    Match bytes.splitlines LF/CR/CRLF and terminal-delimiter semantics. The
    declared count never controls an allocation until actual shape is checked.
    """
    count, start, index = 0, 0, 0
    while index < len(raw):
        value = raw[index]
        if value in (10, 13):
            count += 1
            if count > expected or index - start > 4096:
                unsupported()
            index += 1
            if value == 13 and index < len(raw) and raw[index] == 10:
                index += 1
            start = index
        else:
            index += 1
            if index - start > 4096:
                unsupported()
    if start < len(raw):
        count += 1
    if not count or count != expected:
        unsupported()
    start, index = 0, 0
    while index < len(raw):
        value = raw[index]
        if value in (10, 13):
            yield raw[start:index]
            index += 1
            if value == 13 and index < len(raw) and raw[index] == 10:
                index += 1
            start = index
        else:
            index += 1
    if start < len(raw):
        yield raw[start:]


def coordinate(value):
    whole, numerator, denominator = (int(value[k]) for k in ('whole_us', 'numerator', 'denominator'))
    if numerator >= denominator or whole > MAX_EXTENT:
        unsupported()
    return Fraction(whole) + Fraction(numerator, denominator)


@dataclass(frozen=True)
class Program:
    facts: dict
    manifest: dict
    events: tuple
    audio: bytes
    reservation: int


def inspect_program(data, local_output_delay_us=None, available_bytes=PREPARED_BYTES):
    if len(data) > PROGRAM_BYTES:
        unsupported()
    if len(data) + MANIFEST_PARSE_BYTES > available_bytes:
        raise Refusal('capacity', 429)
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            infos = archive.infolist()
            names = [i.filename for i in infos]
            if len(names) != len(set(names)) or set(names) not in ({'manifest.json', 'events.jsonl'}, {'manifest.json', 'events.jsonl', 'audio.dat'}):
                unsupported()
            total = 0
            for info in infos:
                total += info.file_size
                if (info.flag_bits & 1 or info.compress_type not in (0, 8) or info.is_dir()
                        or stat.S_ISLNK(info.external_attr >> 16) or total > EXPANDED_PROGRAM_BYTES
                        or info.file_size > max(1, info.compress_size) * 1000
                        or info.filename == 'manifest.json' and info.file_size > 1048576):
                    unsupported()
            manifest = validate('manifest', decode(archive.read('manifest.json')), 'head-program')
            duration, uses = int(manifest['duration_us']), manifest['uses']
            if duration > MAX_EXTENT or int(manifest['event_count']) > 100000:
                unsupported()
            sizes = {info.filename: info.file_size for info in infos}
            reservation = program_reservation(manifest, len(data), sizes.get('audio.dat', 0),
                                              sizes['events.jsonl'], available_bytes)
            previous, identities = Fraction(0), set()
            for index, use in enumerate(uses):
                start, end = coordinate(use['start']), coordinate(use['end'])
                occurrence = use['occurrence']
                identity = (use['role_id'], occurrence['use_id'],
                            tuple((step['clip_id'], step['repeat_index']) for step in occurrence['path']))
                if (int(use['id']) != index or start < previous or end <= start or end > duration
                        or identity in identities or len(use['occurrence']['path']) > 32
                        or int(use['source_movement_extent_us']) > end - start):
                    unsupported()
                identities.add(identity)
                previous = end
            voiced = [u['source_audio'] for u in uses if u['source_audio'] is not None]
            for use in uses:
                source = use['source_audio']
                if source is None:
                    if int(use['native_audio_frames']):
                        unsupported()
                elif (not int(source['frames']) or Fraction(int(source['frames']) * 1000000, source['sample_rate'])
                      > coordinate(use['end']) - coordinate(use['start'])):
                    unsupported()
            audio = archive.read('audio.dat') if 'audio.dat' in names else b''
            if manifest['audio'] is None:
                if audio or voiced or any(int(u['native_audio_frames']) or int(u['audio_start_frame']) for u in uses):
                    unsupported()
            else:
                facts, extent, samples = wav_facts(audio)
                mono = all(source['encoding'] == 'pcm_s16_le' and source['channels'] == 1
                           and source['sample_rate'] == 48000 for source in voiced)
                if (not voiced or facts['encoding'] != 'pcm_s16_le' or facts['sample_rate'] != 48000
                        or facts['channels'] != (1 if mono else 2)):
                    unsupported()
                if facts != manifest['audio']:
                    unsupported()
                expected_frames = (duration * facts['sample_rate'] + 999999) // 1000000
                for use in uses:
                    source = use['source_audio']
                    native_count = ((int(source['frames']) * 48000 + source['sample_rate'] - 1)
                                    // source['sample_rate']) if source is not None else 0
                    expected_start = coordinate(use['start']) * facts['sample_rate'] / 1000000
                    ceiled_start = -(-expected_start.numerator // expected_start.denominator)
                    if (int(use['audio_start_frame']) != ceiled_start
                            or int(use['native_audio_frames']) != native_count
                            or int(use['audio_start_frame']) + int(use['native_audio_frames']) > int(facts['frames'])):
                        unsupported()
                    expected_frames = max(expected_frames, int(use['audio_start_frame']) + int(use['native_audio_frames']))
                if int(facts['frames']) != expected_frames:
                    unsupported()
                # The retained decoder continuously plays the full WAV. Every sample
                # outside complete declared source spans must therefore be silence.
                width = facts['channels'] * 2
                cursor = 0
                def silence(first, last):
                    if any(memoryview(samples)[first * width:last * width]):
                        unsupported()
                for use in uses:
                    start, count = int(use['audio_start_frame']), int(use['native_audio_frames'])
                    if not count:
                        continue
                    if start < cursor:
                        unsupported()
                    silence(cursor, start)
                    cursor = start + count
                silence(cursor, int(facts['frames']))
            raw = archive.read('events.jsonl')
            lines = event_lines(raw, int(manifest['event_count']))
            events, previous_key, counts, source_indices, motion_times = [], None, {}, {}, {}
            eyes = mouths = False
            for line in lines:
                event = validate('event', decode(line), 'head-program')
                use_id = int(event['use_id'])
                if use_id >= len(uses):
                    unsupported()
                use, at, kind = uses[use_id], coordinate(event['at']), event['event']['kind']
                start, end = coordinate(use['start']), coordinate(use['end'])
                # Manifest use order resolves shared boundaries: all of old use first.
                rank = 0 if kind == 'begin' else 2 if kind == 'end' else 1
                key = (at, use_id, rank)
                if previous_key is not None and key < previous_key:
                    unsupported()
                previous_key = key
                if not start <= at <= end:
                    unsupported()
                if kind in ('begin', 'end'):
                    if at != (start if kind == 'begin' else end) or (use_id, kind) in counts:
                        unsupported()
                    counts[use_id, kind] = 1
                else:
                    source = int(event['event']['source_index'])
                    if source != source_indices.get(use_id, -1) + 1:
                        unsupported()
                    source_indices[use_id] = source
                    motion_times.setdefault(use_id, []).append(at)
                    eyes |= kind == 'eye'
                    mouths |= kind == 'mouth'
                events.append((at, event))
            if len(counts) != 2 * len(uses) or not (audio or eyes or mouths):
                unsupported()
            delays = set()
            for index, use in enumerate(uses):
                motion = motion_times.get(index, [])
                movement_extent = int(use['source_movement_extent_us'])
                if bool(motion) != bool(movement_extent):
                    unsupported()
                if motion:
                    delay = motion[-1] - coordinate(use['start']) - (movement_extent - 1)
                    if delay < 0 or delay.denominator != 1:
                        unsupported()
                    delays.add(delay)
                    if any(at - coordinate(use['start']) - delay < 0
                           or (at - coordinate(use['start']) - delay).denominator != 1 for at in motion):
                        unsupported()
            if len(delays) > 1 or (local_output_delay_us is not None
                    and delays and delays != {max(local_output_delay_us, 0)}):
                unsupported()
            facts = {'duration_us': manifest['duration_us'], 'audio': manifest['audio'],
                     'has_eye_motion': eyes, 'has_mouth_motion': mouths,
                     'uses': str(len(uses)), 'event_count': str(len(events))}
            return Program(facts, manifest, tuple(events), audio, reservation)
    except (zipfile.BadZipFile, KeyError, UnicodeError, ValueError, OverflowError, RuntimeError):
        unsupported()


def compile_source(bundle, delay_us=0, resume_auto=True):
    """Explicit local authoring maintenance input, compiled before native setup.

    This is source ingestion, not a second playback engine or HTTP content model.
    Its internal metadata is not a serializable managed HTTP manifest: it owns no
    managed asset/version identity and must never fabricate one.
    The invocation owns its generated local role/use identities and retains all source
    samples; the common player handles a movement tail after decoder completion.
    """
    import uuid
    def time(us):
        return {'whole_us': str(us), 'numerator': '0', 'denominator': '1'}
    delay = max(0, delay_us)
    audio, audio_facts = bundle.audio, bundle.facts['audio']
    if audio and audio_facts['encoding'] == 'float32_le':
        # Local authoring uses the same native PCM16 output contract as the
        # device mixer. Keep source facts immutable and preserve channel order.
        _, _, samples = wav_facts(audio)
        pcm = bytearray(len(samples) // 2)
        for index, (sample,) in enumerate(struct.iter_unpack('<f', samples)):
            value = max(-32768, min(32767, round(sample * 32768)))
            struct.pack_into('<h', pcm, index * 2, value)
        stream = io.BytesIO()
        with wave.open(stream, 'wb') as output:
            output.setnchannels(audio_facts['channels'])
            output.setsampwidth(2)
            output.setframerate(audio_facts['sample_rate'])
            output.writeframes(pcm)
        audio = stream.getvalue()
        audio_facts, _, _ = wav_facts(audio)
    extent = max(int(bundle.facts['audio_extent_us']),
                 int(bundle.facts['movement_extent_us']) + delay if bundle.frames else 0)
    use = {'id': '0', 'role_id': str(uuid.uuid4()),
           'occurrence': {'use_id': str(uuid.uuid4()), 'path': []},
           'start': time(0), 'end': time(extent), 'resume_auto': resume_auto,
           'audio_start_frame': '0',
           'source_audio': bundle.facts['audio'],
           'native_audio_frames': bundle.facts['audio']['frames'] if bundle.audio else '0',
           'source_movement_extent_us': bundle.facts['movement_extent_us']}
    events = [(Fraction(0), {'at': time(0), 'use_id': '0', 'event': {'kind': 'begin'}})]
    for index, frame in enumerate(bundle.frames):
        payload = {'kind': frame.kind, 'source_index': str(index)}
        if frame.kind == 'mouth':
            payload['position'] = frame.values[0]
        else:
            payload.update(zip(('x', 'y', 'left_closed', 'right_closed', 'both_closed'), frame.values))
        at = frame.at_us + delay
        events.append((Fraction(at), {'at': time(at), 'use_id': '0', 'event': payload}))
    events.append((Fraction(extent), {'at': time(extent), 'use_id': '0', 'event': {'kind': 'end'}}))
    manifest = {'format': 'nightweaver_head_program_1', 'duration_us': str(extent),
                'audio': audio_facts, 'uses': [use], 'event_count': str(len(events))}
    facts = {'duration_us': str(extent), 'audio': audio_facts,
             'has_eye_motion': bundle.facts['has_eye_motion'], 'has_mouth_motion': bundle.facts['has_mouth_motion'],
             'uses': '1', 'event_count': str(len(events))}
    return Program(facts, manifest, tuple(events), audio, bundle.reservation + len(audio))
