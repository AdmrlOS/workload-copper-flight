# Copper × Admiral — demo source and walkthrough

## Agreed sharing scope

- **Audience:** the Copper team.
- **Delivery:** private demo-source access, with an optional presenter-led walkthrough. This is not a production-release qualification.
- **Hold back:** populated workload images, model/scene bundles and vendor-runtime transfers until the relevant distribution approvals are confirmed.
- **Access:** the repository owner will grant Copper access directly. Both Admiral repositories remain private; no automated invitations were sent. Copper does not need to create its own repositories.

This demonstration is simulated flight, not a physical-drone or camera test. Its purpose is to show Copper running natively under Admiral and make its observations inspectable—not to claim an unmeasured fleet-capacity or deployment-time saving.

## What to demonstrate

| Layer | Runs where | Evidence to show |
|---|---|---|
| Vehicle simulation and simulated depth | Native Jetson process | Advancing source pose, native simulation/wall clocks, NVIDIA Vulkan adapter |
| Copper control and learned-policy graphs | Native Jetson process | Explicit CUDA backend, changing policy publication and predicted vector |
| Workload operations | Admiral | Immutable image identity, configuration history, saved rollback selection and persistent completed missions |
| Presentation | Presenter's browser | Observed path, buffered pose visualization, actual quantized source depth and completed telemetry timeline |

The browser never becomes the source of physics, policy or sensor observations. Native flight replay is not implemented; the Recorded tab visualizes saved native telemetry. The separate rover workload demonstrates its own verified deterministic replay and must be described separately.

## Suggested walkthrough

1. **Architecture and identity.** Open Source evidence. Show the exact runtime revision, immutable image, native/CUDA backend and NVIDIA adapter. Use the tested identity in `CUSTOMER_RELEASE.md`; a newer source checkout is not automatically the deployed runtime revision.
2. **Live flight.** Show changing native poses and policy observations. Try Frame, Overview and Follow. Explain that smooth browser interpolation is presentation, not a native-throughput measurement.
3. **Inside Copper.** Scroll to simulated depth. Show original source sequence, sampling age, source units and invalid pixels. The 32×24 preview samples a real completed 320×240 native buffer; it is not a physical camera or RGB feed.
4. **A completed mission.** Select Recorded, scrub, change playback rate and reopen the mission. Inspect provenance and download available telemetry. State plainly that this is not flight-graph recomputation.
5. **Deployment workflow.** Walk through the tested image/configuration history and saved rollback. Explain how the same pinned artifact and acceptance checks support repeatability. Do not trigger a live rollout during the customer call without separate agreement.
6. **Collaboration discussion.** Agree with Copper on the native measurements, recording/replay requirements, target hardware, and a properly scoped multi-device evaluation.

## Repositories

- Rover: `https://github.com/AdmrlOS/workload-copper`
- Flight: `https://github.com/AdmrlOS/workload-copper-flight`

Each includes a customer guide. Flight's `CUSTOMER_RELEASE.md` and `docs/evidence/` contain exact tested identities and all passing/failed gates. Before the call, use those current results rather than quoting an older screenshot or an earlier image's benchmark.

## Presenter access and fallback

The presenter runs an authenticated Admiral EdgeWire forward to the named `web` service and opens the loopback viewer. This does not create a public customer URL. A screen-share walkthrough needs no unauthenticated exposure or transfer of model/vendor files. For direct customer interaction, arrange separately approved Admiral/device access and a customer-owned authenticated forward.

If the live source is unavailable, do not conceal it. Use a completed native mission explicitly in Recorded mode, retaining its provenance and original timing. Recorded playback is a fallback for visualization, not evidence that the disconnected device is computing live.

## Pre-call check

- Read the latest exact-image hardware, source-freshness, performance and startup results.
- Confirm the live viewer and a completed mission are accessible through the authenticated tunnel.
- Keep failed or unexecuted gates visible. No physical-robot safety, hard-real-time, fleet-capacity or quantified deployment-acceleration claim is approved by this single-device demo.
- Do not distribute credentials, raw operator snapshots, model assets or a populated image.
- Repository access is handled directly by the owner; no new customer identity or invitation is invented by this demo.

## Draft invitation — not sent

**Subject:** Copper on Admiral — native Jetson demo and source walkthrough

Copper team,

We have a native Copper flight demonstration running on a development Jetson under Admiral, with CUDA policy execution, NVIDIA-rendered simulated depth and a browser view of the actual native observations.

We would like to walk you through the flight, inspect the Copper data together, and show the immutable-image deployment, configuration and recording workflow. The latest completed single-device measurement was approximately **0.92× simulation/wall time and 59 genuine native publications/second**: an evaluation preview, not a passed realtime or fleet-scale qualification. The separate rover workload also provides a deterministic-replay example. We will share the exact measured results and remaining limits.

The two demo-source repositories are private, and Admiral's repository owner will grant you access directly. We can also arrange a hosted walkthrough. Source sharing is separate from any model/vendor image bundle, which will not be transferred without the relevant approvals.

We can then agree on the target hardware, native observability/replay requirements and acceptance criteria for a broader deployment evaluation.
