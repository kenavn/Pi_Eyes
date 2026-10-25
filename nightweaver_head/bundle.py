"""Immutable bounded bundle inspection. No extraction and no pygame global state."""
import csv
import io
import math
import re
import stat
import struct
import zipfile
from dataclasses import dataclass
from decimal import Decimal
from .wire import decode, Refusal

MAX_BUNDLE = 67108864
MAX_EXPANDED = 268435456
MAX_EXTENT = 900000000
COLUMNS = ['time_ms', 'type', 'eye_x', 'eye_y', 'left_eye_closed',
           'right_eye_closed', 'both_eyes_closed', 'mouth_position']


@dataclass(frozen=True)
class Frame:
    at_us: int
    kind: str
    values: tuple


@dataclass(frozen=True)
class Bundle:
    facts: dict
    frames: tuple
    audio: bytes
    reservation: int


def unsupported():
    raise Refusal('unsupported_media', 422)


def wav_facts(data):
    if len(data) < 12 or data[:4] != b'RIFF' or data[8:12] != b'WAVE':
        unsupported()
    if struct.unpack_from('<I', data, 4)[0] + 8 != len(data):
        unsupported()
    offset, chunks, metadata = 12, 0, 0
    fmt = samples = None
    while offset < len(data):
        if offset + 8 > len(data):
            unsupported()
        tag, size = struct.unpack_from('<4sI', data, offset)
        offset += 8
        end = offset + size
        chunks += 1
        if end + (size & 1) > len(data) or chunks > 64:
            unsupported()
        chunk = memoryview(data)[offset:end]
        if tag == b'data':
            if samples is not None:
                unsupported()
            samples = chunk
        else:
            metadata += size + 8 + (size & 1)
            if metadata > 65536:
                unsupported()
            if tag == b'fmt ':
                if fmt is not None or size not in (16, 18):
                    unsupported()
                fmt = struct.unpack_from('<HHIIHH', chunk)
                if size == 18 and struct.unpack_from('<H', chunk, 16)[0] != 0:
                    unsupported()
        offset = end + (size & 1)
    if fmt is None or samples is None:
        unsupported()
    encoding, channels, rate, byte_rate, align, bits = fmt
    if ((encoding, bits) not in ((1, 16), (3, 32)) or channels not in (1, 2)
            or not 8000 <= rate <= 192000 or align != channels * (bits // 8)
            or byte_rate != rate * align or len(samples) == 0 or len(samples) % align):
        unsupported()
    if encoding == 3:
        for (sample,) in struct.iter_unpack('<f', samples):
            if not math.isfinite(sample):
                unsupported()
    frames = len(samples) // align
    extent = (frames * 1000000 + rate - 1) // rate
    if extent > MAX_EXTENT:
        unsupported()
    return {'encoding': 'pcm_s16_le' if encoding == 1 else 'float32_le',
            'frames': str(frames), 'sample_rate': rate, 'channels': channels}, extent, samples


def timestamp(text):
    if len(text) > 64 or not re.fullmatch(r'[0-9]+(?:\.[0-9]{1,18})?', text):
        unsupported()
    exact = Decimal(text)
    us = int(exact * 1000)
    if us >= MAX_EXTENT:
        unsupported()
    return exact, us


def boolean(text):
    if text.lower() not in ('true', 'false'):
        unsupported()
    return text.lower() == 'true'


def unit(text):
    try:
        x = float(text)
    except ValueError:
        unsupported()
    if not math.isfinite(x) or not 0 <= x <= 1:
        unsupported()
    return x


def inspect(data):
    if len(data) > MAX_BUNDLE:
        unsupported()
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            infos = archive.infolist()
            names = [info.filename for info in infos]
            if (len(infos) > 16 or len(set(names)) != len(names)
                    or set(names) - {'manifest.json', 'animation.csv', 'audio.dat'}
                    or not {'manifest.json', 'animation.csv'} <= set(names)):
                unsupported()
            total = 0
            for info in infos:
                mode = info.external_attr >> 16
                total += info.file_size
                if (info.flag_bits & 1 or info.compress_type not in (0, 8)
                        or stat.S_ISLNK(mode) or info.is_dir() or total > MAX_EXPANDED
                        or info.file_size > max(1, info.compress_size) * 1000
                        or info.filename == 'manifest.json' and info.file_size > 65536):
                    unsupported()
            manifest = decode(archive.read('manifest.json'))
            allowed = {'version', 'created', 'audio_file', 'audio_format', 'frame_count', 'duration_ms', 'pre_sorted'}
            if (type(manifest) is not dict or set(manifest) - allowed
                    or not {'version', 'audio_file', 'audio_format'} <= manifest.keys()
                    or manifest['version'] != '1.0'):
                unsupported()
            audio = b''
            audio_facts, audio_extent = None, 0
            if manifest['audio_file'] is None and manifest['audio_format'] is None:
                if 'audio.dat' in names:
                    unsupported()
            else:
                label = manifest['audio_file']
                if (type(label) is not str or not label or '/' in label or '\\' in label
                        or label in ('.', '..') or manifest['audio_format'] != 'wav' or 'audio.dat' not in names):
                    unsupported()
                audio = archive.read('audio.dat')
                audio_facts, audio_extent, _ = wav_facts(audio)
            text = archive.read('animation.csv').decode('utf-8')
            if any(len(line.encode('utf-8')) > 4096 for line in text.splitlines()):
                unsupported()
            reader = csv.reader(io.StringIO(text, newline=''))
            if next(reader, None) != COLUMNS:
                unsupported()
            frames, previous = [], Decimal(0)
            for row in reader:
                if len(row) != 8 or len(frames) >= 100000 or sum(len(v.encode('utf-8')) for v in row) + 7 > 4096:
                    unsupported()
                exact, us = timestamp(row[0])
                if exact < previous:
                    unsupported()
                previous = exact
                if row[1] == 'eye':
                    if row[7] not in ('', 'None'):
                        unsupported()
                    values = (unit(row[2]), unit(row[3]), boolean(row[4]), boolean(row[5]), boolean(row[6]))
                elif row[1] == 'mouth':
                    if any(v not in ('', 'None') for v in row[2:7]) or not re.fullmatch('[0-9]+', row[7]) or not 0 <= int(row[7]) <= 255:
                        unsupported()
                    values = (int(row[7]),)
                else:
                    unsupported()
                frames.append(Frame(us, row[1], values))
            movement = frames[-1].at_us + 1 if frames else 0
            logical = max(audio_extent, movement)
            if not 0 < logical <= MAX_EXTENT:
                unsupported()
            facts = {'audio': audio_facts, 'audio_extent_us': str(audio_extent),
                     'movement_extent_us': str(movement), 'logical_extent_us': str(logical),
                     'has_eye_motion': any(f.kind == 'eye' for f in frames),
                     'has_mouth_motion': any(f.kind == 'mouth' for f in frames)}
            return Bundle(facts, tuple(frames), audio, total)
    except (zipfile.BadZipFile, KeyError, UnicodeError, csv.Error, ValueError, OverflowError, RuntimeError):
        unsupported()
