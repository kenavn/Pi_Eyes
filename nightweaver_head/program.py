"""Closed, bounded immutable whole-program archive; never extracts archive paths."""
import io
import stat
import zipfile
from dataclasses import dataclass
from fractions import Fraction
from .bundle import MAX_BUNDLE, MAX_EXPANDED, MAX_EXTENT, wav_facts, unsupported
from .wire import decode, validate, Refusal


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


def inspect_program(data, local_output_delay_us=None):
    if len(data) > MAX_BUNDLE:
        unsupported()
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
                        or stat.S_ISLNK(info.external_attr >> 16) or total > MAX_EXPANDED
                        or info.file_size > max(1, info.compress_size) * 1000
                        or info.filename == 'manifest.json' and info.file_size > 1048576):
                    unsupported()
            manifest = validate('manifest', decode(archive.read('manifest.json')), 'head-program')
            duration, uses = int(manifest['duration_us']), manifest['uses']
            if duration > MAX_EXTENT or int(manifest['event_count']) > 100000:
                unsupported()
            previous, identities = Fraction(0), set()
            for index, use in enumerate(uses):
                start, end = coordinate(use['start']), coordinate(use['end'])
                identity = (use['role_id'], str(use['occurrence']))
                if (int(use['id']) != index or start < previous or end <= start or end > duration
                        or identity in identities or len(use['occurrence']['path']) > 32
                        or int(use['source_movement_extent_us']) > end - start):
                    unsupported()
                identities.add(identity)
                previous = end
            audio = archive.read('audio.dat') if 'audio.dat' in names else b''
            if manifest['audio'] is None:
                if audio or any(int(u['source_audio_frames']) or int(u['audio_start_frame']) for u in uses):
                    unsupported()
            else:
                facts, extent = wav_facts(audio)
                if facts != manifest['audio']:
                    unsupported()
                expected_frames = (duration * facts['sample_rate'] + 999999) // 1000000
                for use in uses:
                    expected_start = coordinate(use['start']) * facts['sample_rate'] / 1000000
                    ceiled_start = -(-expected_start.numerator // expected_start.denominator)
                    if (int(use['audio_start_frame']) != ceiled_start
                            or int(use['source_audio_frames']) * 1000000 > (coordinate(use['end']) - coordinate(use['start'])) * facts['sample_rate']
                            or int(use['audio_start_frame']) + int(use['source_audio_frames']) > int(facts['frames'])):
                        unsupported()
                    expected_frames = max(expected_frames, int(use['audio_start_frame']) + int(use['source_audio_frames']))
                if int(facts['frames']) != expected_frames:
                    unsupported()
            raw = archive.read('events.jsonl')
            lines = raw.splitlines()
            if not lines or len(lines) != int(manifest['event_count']) or len(lines) > 100000:
                unsupported()
            events, previous_key, counts, source_indices, motion_times = [], None, {}, {}, {}
            eyes = mouths = False
            for line in lines:
                if len(line) > 4096:
                    unsupported()
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
            return Program(facts, manifest, tuple(events), audio, total)
    except (zipfile.BadZipFile, KeyError, UnicodeError, ValueError, OverflowError, RuntimeError):
        unsupported()


def compile_source(bundle, delay_us=0, resume_auto=True):
    """Explicit local authoring maintenance input, compiled before native setup.

    This is source ingestion, not a second playback engine or HTTP content model.
    The invocation owns its generated local role/use identities and retains all source
    samples; the common player handles a movement tail after decoder completion.
    """
    import uuid
    def time(us):
        return {'whole_us': str(us), 'numerator': '0', 'denominator': '1'}
    delay = max(0, delay_us)
    extent = max(int(bundle.facts['audio_extent_us']),
                 int(bundle.facts['movement_extent_us']) + delay if bundle.frames else 0)
    use = {'id': '0', 'role_id': str(uuid.uuid4()),
           'occurrence': {'use_id': str(uuid.uuid4()), 'path': []},
           'start': time(0), 'end': time(extent), 'resume_auto': resume_auto,
           'audio_start_frame': '0',
           'source_audio_frames': bundle.facts['audio']['frames'] if bundle.audio else '0',
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
                'audio': bundle.facts['audio'], 'uses': [use], 'event_count': str(len(events))}
    facts = {'duration_us': str(extent), 'audio': bundle.facts['audio'],
             'has_eye_motion': bundle.facts['has_eye_motion'], 'has_mouth_motion': bundle.facts['has_mouth_motion'],
             'uses': '1', 'event_count': str(len(events))}
    return Program(facts, manifest, tuple(events), bundle.audio, bundle.reservation)
