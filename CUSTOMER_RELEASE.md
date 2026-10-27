# Customer evaluation evidence — October 27, 2026

## Tested demo source and measured limits

This is a **demo-source handoff to the Copper team**, not a production-release qualification. The owner will grant private repository access directly. The performance checks below preserve what was actually measured; failing the 1.0× target does not block sharing this demo source or turn a source handoff into a realtime claim.

- **Runtime source:** `add80e2634fb7f92b1827b9be9ca8c1d50f5d82a` (later acceptance-tooling/documentation commits do not change the deployed image).
- **Private ARM64 image:** `ghcr.io/admrlos/workload-copper-flight@sha256:b2c688e35ffb06e7cbd0c1af3374eed8b0b0a30061f64f4786ae7bf6f23f5c5e`.
- **Passed on that exact image:** positive CUDA policy/native physics progress, NVIDIA Vulkan identity, actual changing depth, desktop/mobile Live and Recorded UI, camera controls, no captured console errors/overflow, and a downloadable completed 45.141-simulated-second mission (2,889 native rows, 89 distinct preview rasters).
- **Failed release gate:** 90.113 seconds of observation produced **0.92345× native real time / 59.10 genuine source samples per native wall second**, with zero source gaps/invalid frames. The unchanged strict 1.0× target was not met.
- **Additional readiness failure:** the checker's six-second arming budget rejected normal episode startup; a downloaded mission first observed armed AUTO at 6.069 wall seconds after its first native sample. The checker retained those failures for the episode, producing 203 validation errors and failed terminal/healthy-coverage gates. This is not a reported CUDA crash or transport error. Align and re-verify the checker/lifecycle policy before relying on a release pass; do not suppress the failures or lower the realtime target.
- **Source checks:** independently reviewed fixes; 125 Python tests (13 opt-in skips) and 50 browser tests successful. Fresh source export: 120 portable Python tests (10 skips), 50 browser tests successful. GitHub-hosted jobs did not start because of account billing/spending-limit annotations.

[Machine-readable latest hardware evidence](docs/evidence/customer-reviewed-2026-10-27.json) records the failed gates. The earlier candidate evidence below is retained as history, not substituted for this image's results. Model/scene/vendor approvals remain a prerequisite for transferring a populated image or asset bundle, not for this source-only demo handoff. No fleet-scale speedup or native flight replay is established.

## Follow-up tooling and agreed Copper sharing scope

- The readiness tool now exposes `--startup-timeout` (default **10 wall seconds**, finite 1..60) and records the required budget. This deliberately changes the six-second policy; mock-clock regressions pass realistic 6.2/6.5-second startup at 10 and fail it at an explicit six. Startup earns no healthy credit, post-AUTO/manual/stale/frozen checks remain fail-closed, and expired transitions retain their failure while allowing later genuine progress to be measured. **This is a checker-policy correction, not a native performance improvement or a pass of the old policy.**
- Parent source verification after that change: **131 Python tests run, 13 opt-in skips, no failures; 50 browser-module tests passed**. A fresh source export passed **126 portable Python tests (10 skips) and 50 browser tests**; secret findings were unchanged, previously reviewed resource-ID/dependency-name false positives, with none left untriaged. The earlier exact-image hardware results above are unchanged; these tooling edits do not identify a newly deployed runtime.
- The attempted 90-second hardware recheck received **zero source samples** because the old forwarding session returned connection resets. The CLI then explicitly reported expired operator login; failed retries were stopped and browser sign-in was requested. No new native rate, startup pass or current live availability is established by this attempt. Restore authentication and verify both HTTP endpoints before a live customer call.
- The proposed offscreen 16 ms pacing fix was rejected after an actual cached-Bevy scheduling probe disproved a hard 64 Hz fixed-step cap. **No native patch, model change, replacement binary, image publication or deployment was made in this follow-up.** The remaining native throughput shortfall is unresolved.
- The agreed delivery is **private demo source, with an optional hosted Copper-team walkthrough**. The owner will grant Copper access directly; no automated invitations were sent. The [partner brief](docs/COPPER_PARTNER_DEMO.md) includes the walkthrough and an unsent invitation draft with the measured limits disclosed. Populated images and model/scene/vendor transfers remain on hold pending distribution approval. Production qualification is not required for this source handoff.

## Earlier development candidate — not a passed realtime release

The approved development Jetson previously ran the private, immutable candidate below. It demonstrated native Copper flight graphs, CUDA policy execution, native NVIDIA Vulkan simulated depth, browser observability, completed telemetry visualization and authenticated off-network access. **The strict ≥1.0× realtime release target is not met.** Do not present this preview as a production qualification, physical-drone test, native flight replay or fleet-scale benchmark.

## Tested candidate identity

| Item | Exact observed identity |
|---|---|
| Candidate revision | `candidate-native-542d0b163e9f` |
| Linux ARM64 image | `ghcr.io/admrlos/workload-copper-flight@sha256:ce5747f451f235583bb7edfbd0e65c52f49c03cd9e3d0fa4d2c55c79382a3684` |
| Native CUDA binary SHA256 | `542d0b163e9fe127af26ce5ecdb89e91d3102db7c634fc1c12f21e543f9f4624` |
| Upstream Copper source | `d46ef87a65c7ba93bcad3c236da99e52cd77f319` |
| Graphics actually observed | Vulkan / NVIDIA Tegra Orin (nvgpu) / NVIDIA vendor 4318 / IntegratedGpu |
| Inference actually observed | `cuda`, with advancing reported policy output |
| Recording policy | `telemetry-only`: full CopperList/keyframe capture OFF |

This candidate was built from an explicitly frozen working tree, not mislabeled as a committed Git SHA. Forty-nine packaged files, including the native binary, were checked against their source manifest before publication. Publishing these source changes does not retroactively change the image's candidate identity. Any later image needs its own revision and acceptance evidence.

Registry metadata was read back as private; anonymous manifest access returned HTTP 401. Device deployment preserved the previous selected configuration for rollback, persistent storage, named `web` service, developer-session policy and unrelated fleet fields. This was one development device, not a customer fleet rollout.

## Sustained hardware observation

A 90.194-second off-network observation covered three episodes. Native simulation/wall clocks were evaluated within each episode; pre-existing history was excluded.

| Measurement | Observed |
|---|---:|
| Distinct actual native samples | 4,890 |
| Covered native wall time | 83.061 s |
| Covered simulation time | 76.359 s |
| Simulation / native wall time | **0.9193× — FAIL against 1.0× target** |
| Actual observed source publication cadence | **58.84 samples/native wall second — PASS against 30** |
| Source sequence gaps / invalid frames | 0 / 0 |
| Observed depth source sequences / distinct preview rasters | 153 / 141 |
| Positive CUDA/NVIDIA live observations | 183 |
| HTTP/observation errors | 0 |

The sample cadence is not the depth-preview refresh rate, exact model inference-call count, browser FPS, per-task latency or hard-real-time certification. The preview samples real completed depth buffers at at most 2 Hz; the native sensor and policy retain their own execution path. Whole-iteration timings are not model-forward timings. Restart/startup gaps are not included in the within-episode native rate; the 90-second observation duration is reported separately.

The hardware acceptance check passed advancing native position and CUDA policy output with positive NVIDIA Vulkan adapter identity. The realtime gate stayed failed; no threshold was relaxed to obtain a pass.

## UI and recording checks on the device

- Live view showed advancing actual source sequences, CUDA policy evidence, NVIDIA adapter identity, and a changing source-depth preview through the authenticated off-network tunnel.
- Frame, Overview and Follow camera controls changed the actual rendered camera state; the velocity chart axis control worked.
- Recorded view loaded a completed mission from this candidate, scrubbed to 5.5 simulated seconds and displayed its original depth source sample and candidate provenance.
- Desktop 1440×900 and narrow 390×844 browser checks had no captured console errors or horizontal overflow. The forest/quadcopter GLBs loaded locally at source scale.
- Downloaded and inspected a completed 45.156-second mission archive: 2,890 native rows, 89 distinct depth previews, valid candidate provenance and confined regular archive entries. The gzip download was 355,075 bytes; the original telemetry values were not changed.
- Recorded visualization is **not native Copper replay**. Browser interpolation creates no new source samples and establishes no GPU execution by itself.

## Portable and packaging checks

- Python: 114 tests ran successfully, with 13 explicitly opt-in checks skipped.
- Browser modules/assets: 47 passed, zero failed.
- Clean index export with a fresh pinned upstream clone: 109 portable Python tests succeeded (10 opt-in skips), and all 47 browser tests passed. No ignored local binaries/artifacts were copied into that source export.
- Source review found and fixed terminal-readiness/report replacement, equal-time incremental cursor, playback-rate and episode-lifecycle defects. The corrected source passed 125 Python tests (13 opt-in skips) and 50 browser tests in the parent verification run; a fresh final source export also passed 120 portable Python tests (10 opt-in skips) and all 50 browser tests. Independent re-review approved the scoped fixes. These later UI/tooling changes do not retroactively change the earlier candidate image identity or its 47-test browser run.
- Candidate-image packaging: 3 passed, including the native binary checksum and NVIDIA graphics closure.
- Native CPU/software run: changing real depth, learned-policy observations and vehicle physics passed; this is separate from the hardware evidence above.

These local checks are not a claim that a fresh customer source build or GitHub-hosted GPU test completed. The rover GitHub Actions jobs could not start because GitHub reported failed account payments or a spending limit; repository administrators must resolve billing and rerun CI. The same account limitation may affect flight CI. No billing or account settings were changed.

## Five-minute guided demonstration

1. For a hosted walkthrough, the presenter uses authenticated Admiral access and the named EdgeWire `web` service in [the customer guide](docs/CUSTOMER_GUIDE.md), then shares their screen. Direct device viewers need their own approved access and authenticated forward; this operator's loopback URL is not a public share link.
2. Open **Live**. Show observed state, policy publication, explicit CUDA backend and source evidence. Explain that physics, sensor rendering and Copper graphs run natively on the Jetson, while the browser visualizes received observations.
3. Scroll the inspector to **Simulated sensor depth**. Show changing source sequence, CPU sampling age, 320×240 source → 32×24 quantized preview, invalid pixels and units. This is not a physical camera/RGB feed.
4. Open **Recorded**, choose a completed mission and scrub its timeline. Show preserved source provenance and clearly state that no native flight recomputation is implemented.
5. Explain Admiral's immutable-image, canary, configuration promotion and rollback workflow. Describe repeatability as the deployment benefit; do not invent a deployment-time saving or concurrent fleet capacity number.

## Before expanded delivery or a live walkthrough

- Resolve the failed realtime target before claiming realtime qualification. This demo-source handoff retains the measured **0.92×** limit; production qualification is outside its scope.
- Independent source review and clean-export portable verification are complete. Verify the exact remote source commit before granting customer access; this does not override the failed realtime gate or certify a later image.
- The repository owner handles Copper's private-source access directly. Registry and scoped Admiral access are needed only for separately approved image/device access, not for reading the source or watching a presenter screen share. No customer membership or credentials have been invented or provisioned here.
- Obtain the scene/model/vendor distribution approvals described in [third-party notices](THIRD_PARTY_NOTICES.md) before transferring a populated image or asset bundle. Private hosting does not establish redistribution rights.
- Restore GitHub Actions billing availability and verify rerun results. Do not call unavailable CI green.
- Use [the acceptance checklist](docs/ACCEPTANCE.md) for any new final image. Fleet throughput, physical safety, hard-real-time deadlines and native flight replay remain outside this preview's proven scope.
