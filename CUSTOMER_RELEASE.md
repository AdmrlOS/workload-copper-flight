# Customer evaluation evidence — October 27, 2026

## Latest tested committed preview — NOT release-approved

- **Runtime source:** `add80e2634fb7f92b1827b9be9ca8c1d50f5d82a` (subsequent documentation-only commits do not change the deployed runtime).
- **Private ARM64 image:** `ghcr.io/admrlos/workload-copper-flight@sha256:b2c688e35ffb06e7cbd0c1af3374eed8b0b0a30061f64f4786ae7bf6f23f5c5e`.
- **Passed on that exact image:** positive CUDA policy/native physics progress, NVIDIA Vulkan identity, actual changing depth, desktop/mobile Live and Recorded UI, camera controls, no captured console errors/overflow, and a downloadable completed 45.141-simulated-second mission (2,889 native rows, 89 distinct preview rasters).
- **Failed release gate:** 90.113 seconds of observation produced **0.92345× native real time / 59.10 genuine source samples per native wall second**, with zero source gaps/invalid frames. The unchanged strict 1.0× target was not met.
- **Additional readiness failure:** the checker's six-second arming budget rejected normal episode startup; a downloaded mission first observed armed AUTO at 6.069 wall seconds after its first native sample. The checker retained those failures for the episode, producing 203 validation errors and failed terminal/healthy-coverage gates. This is not a reported CUDA crash or transport error. Align and re-verify the checker/lifecycle policy before relying on a release pass; do not suppress the failures or lower the realtime target.
- **Source checks:** independently reviewed fixes; 125 Python tests (13 opt-in skips) and 50 browser tests successful. Fresh source export: 120 portable Python tests (10 skips), 50 browser tests successful. GitHub-hosted jobs did not start because of account billing/spending-limit annotations.

[Machine-readable latest evidence](docs/evidence/customer-reviewed-2026-10-27.json) records the failed gates. The earlier candidate evidence below is retained as history, not substituted for this image's results. **External delivery still requires approved customer access and model/scene/vendor distribution rights.** No fleet-scale speedup or native flight replay is established.

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

1. Use customer-scoped Admiral authorization and the named EdgeWire `web` service in [the customer guide](docs/CUSTOMER_GUIDE.md). Each viewer needs their own authenticated forward; this operator's loopback URL is not a public share link.
2. Open **Live**. Show observed state, policy publication, explicit CUDA backend and source evidence. Explain that physics, sensor rendering and Copper graphs run natively on the Jetson, while the browser visualizes received observations.
3. Scroll the inspector to **Simulated sensor depth**. Show changing source sequence, CPU sampling age, 320×240 source → 32×24 quantized preview, invalid pixels and units. This is not a physical camera/RGB feed.
4. Open **Recorded**, choose a completed mission and scrub its timeline. Show preserved source provenance and clearly state that no native flight recomputation is implemented.
5. Explain Admiral's immutable-image, canary, configuration promotion and rollback workflow. Describe repeatability as the deployment benefit; do not invent a deployment-time saving or concurrent fleet capacity number.

## Before external customer delivery

- Resolve the failed realtime target or explicitly agree to a guided **0.92× evaluation preview**, retaining the failed gate in the evidence.
- Independent source review and clean-export portable verification are complete. Verify the exact remote source commit before granting customer access; this does not override the failed realtime gate or certify a later image.
- Have an authorized owner grant the intended customer GitHub, registry and scoped Admiral access. No customer membership or credentials have been invented or provisioned here.
- Obtain the scene/model/vendor distribution approvals described in [third-party notices](THIRD_PARTY_NOTICES.md) before transferring a populated image or asset bundle. Private hosting does not establish redistribution rights.
- Restore GitHub Actions billing availability and verify rerun results. Do not call unavailable CI green.
- Use [the acceptance checklist](docs/ACCEPTANCE.md) for any new final image. Fleet throughput, physical safety, hard-real-time deadlines and native flight replay remain outside this preview's proven scope.
