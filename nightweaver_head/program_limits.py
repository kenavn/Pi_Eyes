"""Generated program bounds, separate from imported authoring bundle bounds."""
import sys
from .wire import Refusal

PREPARED_BYTES = 256 * 1024 * 1024
# A retained native selection owns both decoded WAV bytes and RAM-backed input.
# The detailed peak check below additionally charges metadata and parsing.
PROGRAM_BYTES = PREPARED_BYTES // 2
EXPANDED_PROGRAM_BYTES = PREPARED_BYTES
MANIFEST_PARSE_BYTES = 16 * 1024 * 1024


def object_bytes(value):
    """Measure the bounded, already validated manifest graph on this interpreter."""
    total, seen, pending = 0, set(), [value]
    while pending:
        item = pending.pop()
        identity = id(item)
        if identity in seen:
            continue
        seen.add(identity)
        total += sys.getsizeof(item)
        if isinstance(item, dict):
            pending.extend(item.keys())
            pending.extend(item.values())
        elif isinstance(item, (list, tuple)):
            pending.extend(item)
    return total


def program_reservation(manifest, archive_bytes, audio_bytes, event_bytes,
                        available_bytes=PREPARED_BYTES):
    # Each event has a closed schema, at most three small dictionaries, scalar
    # fields and one Fraction/index tuple. This conservatively includes their
    # Python object/storage overhead on the supported 32/64-bit runtimes.
    count = int(manifest['event_count'])
    objects = 2 * object_bytes(manifest) + count * 3072 + 65536
    # Constant-space preflight and one <=4096-byte line copy replace splitlines.
    # Retain conservative raw/decode scratch and per-event bookkeeping coverage.
    parsing = archive_bytes + audio_bytes + 2 * event_bytes + count * 64 + objects
    retained = 2 * audio_bytes + objects
    if max(archive_bytes + MANIFEST_PARSE_BYTES, parsing, retained) > available_bytes:
        raise Refusal('capacity', 429)
    # Service separately adds the RAM-backed native WAV input once it exists.
    return audio_bytes + objects
