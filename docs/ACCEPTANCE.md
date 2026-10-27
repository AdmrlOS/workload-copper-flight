# Demo verification and optional release gates

This repository is being shared with Copper as **demo source**. Its owner grants repository access directly. The stricter checklist below is for qualifying a deployable release and supporting stronger performance claims; it is not a blocker to the agreed source-only handoff. Existing failed measurements remain documented rather than being relabeled as passes.

## Full release gate

Do not qualify a new runtime image as a production release merely because a prior image booted. Tie every hardware result to the exact runtime Git SHA, native binary SHA256 and immutable image digest.

- [ ] Portable Python and browser-module tests pass from a clean checkout, with actual native observations committed only as explicitly attributed parser fixtures.
- [ ] Native CPU/software tests establish real changing depth, policy observations, fixed physics steps and bounded telemetry; these are not GPU acceptance.
- [ ] Published ARM64 image has the intended revision/source hashes and remains private; anonymous pulling is denied.
- [ ] Approved Jetson reports advancing CUDA policy output and positive NVIDIA Vulkan adapter identity on that exact release.
- [ ] Sustained native measurement meets the stated evaluation target: at least 1.0 simulation second/wall second and at least 30 observed native samples/wall second. Browser render/playback speed cannot satisfy this target.
- [ ] Simulated depth is visible, changes, retains original source sequence/CPU sampling times, and is absent or stale when appropriate.
- [ ] Live/Recorded controls, source provenance, timeline and camera controls work in the deployed browser without uncaught errors; inspect narrow and desktop viewports.
- [ ] A complete mission is preserved within the configured retention budget; downloaded telemetry is usable and explicitly not native replay.
- [ ] Customer has approved private GitHub/GHCR/Admiral access and scene/model/vendor redistribution permissions.

## Reproduce hardware and sustained checks

Set `RELEASE_REVISION` to the exact 40-character runtime source revision from the delivered image/evidence, not a newer acceptance-tooling/documentation checkout commit. Connect the authenticated named `web` service as described in [the customer guide](CUSTOMER_GUIDE.md), then:

```sh
python3 tests/check_image.py --url http://127.0.0.1:18083 --backend cuda \
  --expected-revision "$RELEASE_REVISION" --observe-seconds 5 --timeout 180 \
  --report artifacts/customer-hardware.json
python3 scripts/check_customer_readiness.py --url http://127.0.0.1:18083 \
  --expected-revision "$RELEASE_REVISION" --seconds 90 --startup-timeout 10 \
  --report artifacts/customer-readiness.json
```

The sustained check uses actual native wall timestamps and distinct source frames; episode clocks are never joined. It requires changing observed depth, policy progress, error-free observation and sufficient measurement coverage. Default thresholds are explicit acceptance targets, not product guarantees. Lowering a threshold must be disclosed and does not establish the original target.

The readiness tool now uses a configurable **10-wall-second** startup/arming budget (`--startup-timeout`, finite 1..60). This intentionally changes the earlier six-second policy, which rejected observed normal arming around 6.069 seconds; it does not retroactively pass that six-second check or improve native throughput. Startup adds no healthy coverage, post-AUTO manual/frozen/stale states still fail, and a missed deadline remains a failed gate even if later progress resumes. The 1.0× native-time and 30 Hz source targets are unchanged.

For the agreed **hosted Copper walkthrough plus private source**, follow [the partner brief](COPPER_PARTNER_DEMO.md). This is an evaluation preview with the failed realtime result disclosed, not a waiver of these release gates. A screen-shared walkthrough does not require customer registry credentials or transfer of model/vendor files; direct customer access and any populated-image delivery remain separately gated.

## Evidence and known limits

The earlier native-performance canary measured 52.24 native publications/s and 0.816 simulation-time/wall-time during a 65-second off-network read-only check on October 27, 2026. The later frozen candidate `candidate-native-542d0b163e9f` measured **58.84 source samples/s and 0.9193×** over a 90-second observation with real changing depth, CUDA and NVIDIA Vulkan. It still **failed the 1.0× realtime gate**. [Candidate evidence](../CUSTOMER_RELEASE.md) records its exact image/binary identity and browser/archive checks; these results do not certify a later final image.

Native structural flight replay/recomputation is **not implemented**. `telemetry-only` deliberately omits binary CopperLists/keyframes. Per-iteration timings are not model-forward or per-task timings; policy publication sequence is not inference-call count, which stays unavailable. Simulated depth is not physical camera evidence. Fleet-wide throughput, concurrent rollout capacity, physical-robot safety and deployment-time savings have not been measured.

Sanitized final results, revision and immutable image identity belong in `CUSTOMER_RELEASE.md`; raw operator artifacts/credentials remain excluded from GitHub. Any failed or unexecuted gate must remain explicit.
