# Current software session — 2026-10-26

NIGHT-451 continuation from8d72370d875aeb6a00487e90b74a27427ec5e199.
Replaced unbounded splitlines with constant-space physical-record preflight and
one-line decoding. Enforced actual count/4096-byte bounds before event decoding,
including LF/CR/CRLF and terminal delimiter semantics. Begin at time zero now
precedes native Play; a leading silence preserves idle until timed Begin. The
continuous selection is retained across uses, repeats and stops.

Updated the one HTTP program contract with required original source_content and
source_audio, and native_audio_frames replacing source_audio_frames. Parser checks
exact original duration separately from generated48k PCM16 ceil spans, channel
policy, complete file count, span collisions and silent gaps. Shared generated schema
SHA256 b700e35afd8e5e2ce191f319af95aac175c049f6d33b77cac32a04796fe920cf.
Local authoring remains internal Program construction without fabricated catalogue
identity; it does not produce valid managed HTTP manifests.

Author checks: full head suite67 tests on Python3.9.25 and3.14.6, compileall both,
shared schema equality and diff whitespace. The unmodified external
NIGHT-456 OrderingTests.test_initial_begin_precedes_first_play passes when imported
directly against this lane on3.9.25 (only this normative test; exact-clean-source
wrapper and full cross-language rehearsal await its owner’s pin/manifest update). No native/house devices or deployment.
Actual tracemalloc inspection peak (archive allocated before tracing):

| Runtime | Newline payload | Archive bytes | New peak bytes | Archive + peak | Budget |
| --- | ---: | ---: | ---: | ---: | ---: |
|3.9.25|8388608|8390229|8447482|16837711|33554432|
|3.9.25|33554432|33556053|33567891|67123944|268435456|
|3.14.6|8388608|8390229|8427630|16817859|33554432|
|3.14.6|33554432|33556053|33561631|67117684|268435456|

All cases refused unsupported_media. Regression checks charge archive+measured
peak, enforce a small fixed margin above raw payload, validate line semantics and
deflate ratio refusal, and prove malformed input never selects native audio or
publishes Prepared. Historical pass3 remains recorded; user's explicit removal of
caps permits continuation, with next independent review pass4, not a reset.

Next: coordinator assigns independent review of this coherent change and updates
external Rust/Python rehearsal to this exact clean source and provenance contract.
Then verify normative origin Begin ordering and actual Rust normalized archives.
The one pygame music selection does not demonstrate general simultaneous BG/main
head contributions; canonical show background currently has no head use. Native
armhf Python3.9.2/pygame1.9.6/SDL1.2, physical timing/output, CI/main landing and
separately authorized deployment remain unclaimed.
