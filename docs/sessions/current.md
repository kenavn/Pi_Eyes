# Current software session — 2026-10-25

NIGHT-421, source baseline338627b8b5c01adc258556cce238cb78afcb0112.
Implemented prepared HTTP/control/content service and one interruptible playback engine.
Removed superseded MQTT owner/callers/deployment references. Kept the editor format and
all eye/mouth/boot/display/pigpio/backlight/calibration implementations unchanged.
Runtime/install handoff: [head-http.md](../head-http.md). Frozen schemas retain exact
Nightweaver2c20956a1f9790d904a3ec5ea68fa12e90574650 provenance.

Author validation:40 synthetic/fake-port/owned-loopback unittest cases passed on
Python3.9.25 and3.14.4 with hash-pinned h11 0.16.0; compileall and git diff whitespace
checks passed. Independent source review pass1/3 found two blockers: unclassified header ingress could
occupy reserved capacity, and a published duplicate upload could clear another job
reservation. Both are corrected with finite-burst loopback and exact A/B/C replay
regressions. Pass2/3 cleared both product fixes and required timer-controlled admission
coverage. The regression now injects header timer callbacks and a fake service clock,
proves dispatch before explicitly delivered expiry, then drives timeout/cleanup directly.
Pass3/3 and remote CI/landing remain coordinator gates; the count does not reset.
A one-off read-only inspection of privately captured hode1/hode2 archives matched
independent Rust facts: audio81251834/79668105us, movement81245001/79639506us,
8133/7934 movement rows. Those archives are not committed or required by tests.

No deployment, target SSH, real pygame/audio initialization or playback was performed.
Actual Python3.9.2/pygame1.9.6 target audio loading, Show network/firewall/sink readiness,
physical sound/movement and operator acceptance remain unqualified. The service never
claims physical quiet or speaker drain. No automatic process-failure restart, media
fallback, long-play rate following, MP3, pause or seek is supplied.

Next: independent bounded source review of this coherent branch; coordinator publishes
only after blockers clear, then verifies exact-head CI before merging. Final deployment
unit/config/credential rendering belongs to the separately scoped infrastructure work.
