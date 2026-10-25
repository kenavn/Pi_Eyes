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
dependent service/native implementation is still in progress and is not qualified.
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
control job,8 immutable prepared handles,64 ordinary receipts plus an independent Stop
receipt,4096 complete activity tombstones and256MiB prepared expansion reservation.
Exact retained mutations return observations without executing again. Query the exact
operation after connection loss. Expiry retires output and cannot be resurrected.
Stop targets the latest admitted activity or a captured owner before first Start. It
retires that owner before cancellation. Stale StopA after B admission refuses with no
side effects. Natural occurrence completion does not retire an owner.

Preparation validates bounded ZIP/CSV and PCM16/IEEEfloat32 RIFF facts, then verifies
required audio loading in a separate bounded pygame subprocess. It does not replace the
active music slot. Only the sole output worker selects audio and sends local UDP. The
worker owns motion, decoder observations, cancellation, final delayed motion tail,
autonomous-eye restoration and temporary audio disposal. No required-audio failure is
treated as audio-less playback. Stop/expiry prevent future loop or authored-frame output.
Unknown cleanup retains ownership; settled means software output/worker disposal, not
physical motor stillness or drained downstream speakers.

Scheduled starts use captured Host clock mapping when Ready/Degraded. Unknown mapping
acts on receipt and reports `no_clock`. Lateness is checked again after audio selection,
immediately before output. Positive local delay withholds all authored motion before
its due decoder position. A terminal−1 decoder position continues a bounded tail from
the last real observation; ending before any real position fails. Long-play rate
following, pause, seek, nonzero rehearsal origins and MP3 are unsupported.

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
CLI using this same engine, with required `--sink-name`, optional `--loop`,
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
ActivityIdentity requires the actual occurrence `role_id`, which must belong to
that Owner. The participant Owner remains immutable across natural A-to-B role
changes; compatible preparation is role-neutral and shares its prepared handle.
The scalar Owner.role_id contract is removed without a compatibility alias.
