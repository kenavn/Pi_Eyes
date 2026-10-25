# Prepared head HTTP service

NIGHT-421 replaces the MQTT playback owner with one authenticated HTTP/1.1 owner.
Software only: no deployment or physical hearing/movement qualification is implied.
The lower-level `eyes.py`, `mouth.py`, boot/display/pigpio/backlight and calibration
remain untouched. The editor and `.skelanim` authoring format remain unchanged.

## Contract and runtime

The exact generated schemas in `nightweaver_head/contracts/` are copied byte-for-byte
from Nightweaver commit `a8991e1`,
`contracts/head-control.schema.json`, `contracts/device-content.schema.json` and
`contracts/head-program.schema.json`. This is the N449 frozen contract checkpoint;
the runtime consumes whole-show program archives with retained parent-native selection.
Software checks do not qualify the installed native target.
The normative route/authority/timing contract is that commit's
`docs/contracts/head-control.md`. Schema regeneration belongs to Nightweaver;
update the provenance and conformance fixtures together after an approved contract change.
The root schemas catalogue payload types, rather than one request envelope.

Python 3.9+ and pinned, hash-verified `h11==0.16.0` are the service's runtime requirements.
Production uses the already installed pygame 1.9.6 through an isolated environment
created with `--system-site-packages`; never upgrade global Python, pygame or pip.
Importing the package or compiling it performs no hardware initialization. Automated
tests use synthetic in-memory ZIP/WAV bytes, fake output ports and owned loopback only.

Every route requires an installation-owned bearer credential; no project-supplied URL,
secret argument or credential in observation state. Production binds only its exact
configured Show Ethernet address (`192.168.2.119` or `192.168.2.53`), TCP8082.
Missing address/route fails closed. No wildcard, Wi-Fi fallback, redirects, upgrades,
compression, pipelining or chunked uploads. Plain HTTP is confined to the trusted Show
Ethernet; this does not claim transport encryption.

The server has at most8 connections,6 ordinary connections, two concurrent observations,
one Stop slot and one renewal slot. At most two header-pending peers are evictable;
an arrival replaces the oldest unknown peer immediately when that pool is full.
Header parsing uses callbacks and bounded timers, creating a request task only after
classification. Classified requests, Stop/renewal and admitted uploads are never evicted.
This reserves dispatch through finite bursts of partial headers, not an infinite hostile
connection flood. An unclassified connection has an absolute5s and idle1s header deadline. Control bodies are128KiB, aggregate headers16KiB, responses256KiB;
ordinary request deadline5s, idle1s. Streamed upload deadline120s, idle5s. Uploads hash
incrementally on a separate bounded filesystem owner. At most8 disk requests can remain
pending, even if the filesystem stalls. Stop and lease expiry never wait for that owner.

One session has a3s lease (renew each1s), one playback worker, one ordinary inspection/
control job,1 immutable retained prepared program,64 ordinary receipts plus an independent Stop
receipt,4096 complete activity tombstones and256MiB prepared expansion reservation.
Exact retained mutations return observations without executing again. Query the exact
operation after connection loss. Expiry retires output and cannot be resurrected.
Stop targets the latest complete aggregate activity, fences all future starts of that
actual run, and joins its worker while retaining the prepared decoder. A later actual
run or root repeat uses the same selection. Stale StopA after B admission refuses
without cancellation. Disarm and lease expiry retire preparation, join active work,
and dispose native selection and pins. Disarm shares the reserved Stop admission slot.
Neither a timeout nor unknown cleanup proves quiet.

Preparation accepts only a compiled program ZIP: `manifest.json`, `events.jsonl`,
and optional WAV `audio.dat`. It validates generated wire fields, exact rational
coordinates, ordered role/occurrence/source identities, complete Begin/End pairs,
source extents, native frame placement and finite archive/event/reservation bounds.
No archive paths are extracted. PCM16/IEEEfloat32 WAV retains the explicit native
sample rate and mono/stereo layout; malformed or mismatched audio fails preparation.
The separate `/inspect` route still ingests authored `.skelanim` source ZIP/CSV and
returns import BundleFacts, not ProgramFacts or a runtime handle.

During quiet setup, Prepare checks the production Ethernet route afresh and actually
selects required audio with this process's initialized pygame mixer. It performs no
Play, authored UDP, mode output, subprocess decoder verification, or fabricated
pre-play position observation. One native music selection means one retained program.
Ready is published only after inspection and native selection return. Start/repeat
perform no load, temporary-file creation, process launch or new audio connection.

One continuous real decoder cursor drives every authored use and gap. Event coordinates
already include captured motion delay; the endpoint does not apply it a second time.
At a shared boundary the old final motion precedes old End, new Begin and new motion.
End restores idle only for authored `resume_auto=true`, releasing blink holds with
0x45 before automatic modes; false leaves the modes disabled through the gap.
A terminal −1 cursor continues a bounded tail from the last real observation; ending
before any valid decoder position fails. Audio-less programs contribute no native voice
and use the injected monotonic clock. Final samples/modes run once. Stop joins and
restores the currently active use without replacing its retained selection. Disarm
replaces the stopped decoder with an unplayed tiny buffer compatible with pygame1.9.6;
no unsupported `music.unload` call or package upgrade is used.

Scheduled starts use captured Host clock mapping when Ready/Degraded. Unknown mapping
acts on receipt and reports `no_clock`. Lateness is fenced immediately before output.
Long-play rate following, pause, seek, nonzero rehearsal origins and MP3 are unsupported.
Settled proves software calls/joins, not physical motor stillness or downstream drain.

Managed content is published by SHA256 only after exact length/hash, flush, fsync,
atomic rename and directory fsync. Failed/partial uploads never appear in inventory.
There is one transfer,64 transfer receipts and4096 boot-lifetime job tombstones.
No cache purge is provided. A directory-entry safety bound2048 refuses new publication
before a scan can become unbounded. Existing `/etc/anim` is read-only indexed at startup
(up to1024 entries); those observations never substitute for managed delivery. No ZIP
paths are extracted. Prepared bytes remain pinned until quiet session release.

## Separately authorized stopped rollout

This procedure is a handoff for a later installation owner. Do not run the repository's
bootstrap/deploy script or broad Ansible role against preserved heads to install HTTP.
Do not run unattended playback or send test eye/jaw commands.

1. Confirm no live run, capture source/service/config/private media backups and preserve
   each head's dirty checkout and `/etc/anim`. Record unchanged hashes of lower-layer files,
   boot/display configuration and calibration. Verify port8082 is free.
2. Stage a reviewed exact source revision in a separate service directory. Create an
   isolated Python3.9 environment with `--system-site-packages` and install only
   `requirements-head.txt` with `--require-hashes`. Preserve installed pygame and OS.
3. Supply a root-owned installation JSON file (0640, service-private group) containing
   exactly `bind`, `port`, `interface`, `secret_file`, `content_root`,
   `local_library_root`, `sink_name`, `source_revision`. Set managed root
   `/var/lib/pi-eyes/content`, local library `/etc/anim`, port8082 and the head's exact
   reserved Show IP. The secret file is root-owned0640 or0600, contains only the bearer,
   and is never in Git, argv, a project or logs. Use a distinct head audio sink name.
4. Pin Pulse to `tcp:192.168.2.235:4713`, the configured sink,48000Hz stereo. Verify
   `ip -4 route get 192.168.2.235 from <ShowIP>` uses the configured Ethernet interface.
   The service checks the route before initialization. This is readiness evidence only;
   physical audio and local motion alignment still require Kenneth's qualification.
5. Restrict8082 to controller192.168.2.235 on Show Ethernet. Preserve management SSH.
   Restrict external UDP5005/5006 so only local playback owns them during performances;
   retain explicitly operated local maintenance access. Keep lower UDP controllers running.
6. Disable and stop the old MQTT playback unit before installing the new owner; remove
   its executable service path. Store rollback copies privately outside executable paths.
   No dual owners. Install a dedicated `pi-eyes-head.service` with `Restart=no`,
   `User=kenneth`, `Group=kenneth`, `SupplementaryGroups=audio pulse-access`,
   `RuntimeDirectory=pi-eyes-head`, `RuntimeDirectoryMode=0700`, and
   `ExecStart=<isolated-python> -m nightweaver_head --config <root-owned-config>`.
   Keep required user Pulse/DBus environment consistent with the preserved installation.
7. Start idle only. Verify listener address, credential rejection, fresh capabilities,
   boot identity, route/source and exact installed build hash. Do not call Start or the
   maintenance CLI. Record installed versus software-only state distinctly.
8. At any failed non-actuating readiness check, stop HTTP and restore only the captured
   prior service/config/settings. Restore its playback owner only after HTTP exits;
   never overlap them. No OS, firmware, calibration, media or project rollback by inference.

The service and maintenance CLI acquire the same `/run/pi-eyes-head/output.lock` before
hardware initialization. The lock directory must already exist with service-private
permissions (systemd creates it). `editor/bundlePlayer.py` is an explicit local maintenance
CLI accepting the explicitly preserved `.skelanim` authoring input. Setup compiles
one local ProgramUse and selects native audio once; it uses the same ProgramPlayer
for each retained repeat, with required `--sink-name`, optional `--loop`,
`--no-resume-auto` and motion `--start-delay` milliseconds. Its UDP destination is local
loopback only. Stop the service and obtain operator authorization before using it.

## Software validation

```
python -m pip install --require-hashes -r requirements-head.txt
python -m compileall -q nightweaver_head editor/bundlePlayer.py
python -m unittest discover -s tests -p 'test_head_*.py'
```

CI runs these checks on Python3.9 and3.14 without pygame or hardware. Synthetic fact
fixtures match the independent Nightweaver head-integration probe. Automated success
does not verify installed target pygame decoding, route/firewall, speaker drain,
physical movement, optical timing or full-show acceptance.

### Participant role scope (NIGHT-433)

Owner requires `role_ids`, the complete sorted unique nonempty role UUID set,
maximum 1024. Empty, duplicate, unsorted, invalid or oversized sets refuse.
Preparation Owner captures preparation ID/revision/full Prepare command, without a
future run. ActivityIdentity captures the actual cue command, run/play/root-repeat and
cancellation generation. Actual role, full authored occurrence path and source-row
identity remain in the immutable program manifest/events. Every use role must belong
to Owner.role_ids. Shared content transfer uses Managed or PreparedProgram references;
generated program bytes have no invented managed asset/version identity.

### NIGHT-451 retained-program author checks

The replacement removes the subprocess verifier and per-occurrence BundlePlayer.
Source ingestion remains solely for import inspection and the explicitly required
local authoring maintenance CLI. Generated program archives are bounded to128MiB compressed,
256MiB expanded,1024 uses and100000 events; manifest metadata is at most1MiB and
one event line at most4KiB. Prepared archive/audio reservations remain at most256MiB, including conservative
metadata and parsing peak charges checked before payload expansion. Raw authoring
bundles retain their separate64MiB limit.
Authored audio accepts PCM16 or finite float32, mono/stereo,8000..192000Hz.
The SDL1.2 native endpoint advertises PCM16 only; Host Setup must normalize
float32 before transfer. The local maintenance compiler likewise converts float32
to clipped PCM16 during preparation, preserving rate and channel order.
One common format is explicit in the immutable program; the endpoint does not convert
heterogeneous source formats or invent managed versions for prepared bytes.

Author validation uses the private existing Python3.9.25 and3.14.6 peer environments
with h11 installed; final follow-up validation is recorded separately. Coverage includes closed archive/wire
validation, complete source identities and captured delay, exact fractional boundaries,
gaps and final modes, source import, retained native selection without setup output,
Stop/repeat/Disarm, stale activity rejection, held native preparation/restoration/
disposal joins, expiry, unknown cleanup, reserved HTTP capacity and the real UDP eye
consumer's0x45 release. Compileall and whitespace checks pass. Vendored control/content schemas follow the required play binding, activation
generation and distinct program capacity in Nightweaver `e7c4150`; program schema
remains frozen at `a8991e1`. These are author checks;
independent review, cross-language integrated acceptance and installed native/physical
qualification remain separate coordinator gates. No device output or deployment was
performed for these tests.


NIGHT-451 bounded review pass1/3 identified three blockers, corrected for pass2:
Close now awaits the same tracked off-loop disposal owner as Disarm, with session,
pins and native ownership retained until actual join; failed disposal stays unknown.
Occurrence uniqueness compares role/use/path tuples independently of JSON object order.
The WAV validator exposes its checked sample payload to the program parser, which
verifies every native frame outside declared complete source spans is silence (PCM16
zero bytes or finite float32 zero, including negative zero). Nonzero authored source
samples remain valid. Regression tests hold Close disposal while real loopback HTTP
status, renewal and reserved Stop respond; reordered nested identities and nonzero
mono/stereo PCM/float gaps/tails are refused. The actual N449 Rust encoder's synthetic
250µs/two-use/six-event PCM16 archive passes this stricter Python consumer on both
supported test runtimes. These corrections do not reset the three-pass review ledger
or establish native target qualification.

The final follow-up binds every prepared program to its captured play. A monotonic
activation generation identifies one actual run/cue lease across all root repeats.
Stop retires that entire lease, including a queued repeat while an older repeat is
still joining; stale commands cannot affect the next lease. Bounded generation and
repeat watermarks replace accumulated UUID tombstones. Pre-start cancellation can
cross the former4096-entry ceiling without native output or a service restart.
These source changes require a matching Host deployment; they are not compatibility
paths for the installed older protocol.

Final follow-up author validation:59 head tests pass on both Python3.9.25 and
3.14.6, including queued-repeat cancellation and conservative event-memory sizing.
Compileall passes on both; whitespace checks pass. No live devices were used.
