# Native simulator integration contract

Pinned upstream: `d46ef87a65c7ba93bcad3c236da99e52cd77f319` (Copper 1.4.0-dev).
Native executable: `/opt/copper-flight/bin/quad-sim` (real `sim,forest-world,autonomous-demo` graph; never `bevymon`).

Environment:
- `COPPER_FLIGHT_ASSET_DIR=/opt/copper-flight/assets`: immutable Bevy scene/UI asset directory. A supplied directory is strictly offline; missing assets fail.
- `COPPER_FLIGHT_MODEL=/opt/copper-flight/models/vitfly-vitlstm-f32.safetensors`: immutable model file; explicit path bypasses download/cache and fails if missing/invalid.
- `COPPER_FLIGHT_LOG_DIR`: active run's writable logs directory, e.g. `/data/runs/<run>/logs`. Native names `flight_controller_sim.copper`, `flight_compute_sim.copper` plus complete numbered slab families. These are actual binary Copper logs, not a replay claim.
- `COPPER_FLIGHT_TELEMETRY`: writable JSONL file for this process. Truncated on startup, flushed per sample. Parent should supply a unique run path.
- `FLIGHT_EPISODE_SECONDS`: positive finite simulation-time exit deadline; default 45 seconds. Autonomous starts at 4 simulation seconds. Deadline is simulation time, not wall time.
- `FLIGHT_WORLD=forest`: this image compiles the forest world only (urban is not packaged).
- `FLIGHT_INFERENCE`: optional `cpu`/`cuda` override; CPU default for CPU image, CUDA default for CUDA image. Unknown/unsupported devices fail rather than silently falling back.

Telemetry schema v1 (up to ~10 Hz wall-clock Bevy Update system, outside Copper's hot control loop):
`schema_version:1`, `seq` (starts at 0), `sim_time_s` (physics time), `position_m:{x,y,z}|null`, `rotation:{x,y,z,w}|null` (actual vehicle quaternion), `velocity_m_s:{x,y,z}|null` (Bevy world, Y up), `armed` (actual RC armed input), `auto_enabled` (actual RC auto input), `mode` (`Acro`/`Angle`/`PositionHold`), `world` (`forest`), `policy_prediction_m_s:{x,y,z}|null` (upstream preview command frame: north, west, up), `inference_backend:null|cpu|cuda` (actual loaded task device observed through reflection, not compile flags), `inference_count:null` (exact task count deliberately not instrumented), `policy_observation_seq` (existing upstream policy-preview publication sequence; raw and conditioned predictions can each publish, so NOT an inference count), `graphics_backend:string|null`, `graphics_adapter:string|null`, `graphics_vendor_id:uint32|null`, `graphics_device_type:null|IntegratedGpu|DiscreteGpu|Cpu|VirtualGpu|Other` (actual Bevy `RenderAdapterInfo`: `backend`, `name`, `vendor`, and debug-formatted `device_type`; all nullable before the adapter resource is available).

`sim_time_s` advancing proves simulator progress; native model output and backend must be observed separately. Before vehicle spawn, position/velocity are null. Policy preview sequence is not an exact inference count and is not reported as one. No synthetic fallback.

The service validates both raw adapter fields and their nested equivalents: `graphics.vendor_id` is an integer in `0..4294967295` (never a boolean, string, or float); `graphics.device_type` is one of the exact enum strings above or null. State normalizes actual values into `frame.graphics.{backend,adapter_name,vendor_id,device_type}`, keeping unavailable metadata null and preserving the original raw fields, policy sequence, and null exact inference count. There is no inferred/default NVIDIA identity.

Adapter metadata is an evidence boundary, not a hardware acceptance result. Noop/Unknown backends, missing metadata, and Cpu/VirtualGpu/Other adapters do not establish native Jetson graphics. Positive NVIDIA graphics evidence requires the actually observed Vulkan backend, vendor `0x10de` (4318), and IntegratedGpu/DiscreteGpu device type on the target, alongside independently verified CUDA inference and target identity. A CPU llvmpipe Vulkan adapter (observed vendor 65541, device type Cpu) is explicit software proof only; a name containing NVIDIA or a CUDA-compiled binary alone is insufficient.

CPU software-rendering acceptance command (image handle/evidence added after real build):
`docker run --init --network none --shm-size 1g -v <run-dir>:/data -e COPPER_FLIGHT_LOG_DIR=/data/logs -e COPPER_FLIGHT_TELEMETRY=/data/telemetry.jsonl -e FLIGHT_EPISODE_SECONDS=12 <image> xvfb-run -a -s '-screen 0 800x600x24' /opt/copper-flight/bin/quad-sim`

## Headless integration status

True surface-free mode is implemented and exercised. `FLIGHT_DISPLAY_MODE=headless` (or explicit `software`) disables Winit/window/swapchain, runs Bevy via ScheduleRunner, uses an offscreen 800x600 scene target, and retains the original offscreen stereo/depth cameras/readback and Copper/ViTFly graph. This mode must bypass Weston in the supervisor. `drm`/`existing`/unset retain the original Winit display path. Local container `copper-flight-native-offscreen-proof` ran `/opt/copper-flight/bin/quad-sim` directly with no DISPLAY/WAYLAND_DISPLAY and no Xvfb/Weston, `--network none`, exit 0: 51 telemetry rows, sim_time_s 0→12.1875, policy_observation_seq 0→568, actual CPU inference and Vulkan llvmpipe adapter, armed+AUTO true, changing real position and quaternion. Raw files: `artifacts/native/cpu-offscreen-surfacefree/`. CUDA counterpart compiled successfully but remains device-only pending. Final candidate images: `workload-copper-flight:native-cpu-offscreen`, `workload-copper-flight:native-cuda-offscreen`, `workload-copper-flight:development-offscreen`. The final flight target now copies the checksum-locked matching image-owned graphics payload and bounded depth probe; all 25 live injected-library basenames remain excluded. CUDA runtime defaults force `WGPU_BACKEND=vulkan` and `VK_DRIVER_FILES=/etc/vulkan/icd.d/nvidia_icd.json`, so a missing GPU ICD fails rather than proving software graphics. NVIDIA execution remains unverified.

## Positive adapter metadata follow-up proof

Both Linux AArch64 simulator variants were rebuilt offline/locked against the pinned workspace using the existing cached builder (`rustc 1.99.1`, the actual cached version). New artifacts and full binary/source SHA-256 hashes, exact builder/runtime image IDs, commands, and raw evidence are isolated in `vendor-assets/adapter-proof/`; earlier offscreen binaries and proof were not overwritten. This is a binary follow-up, not a rebuilt final release image.

The new CPU binary was bind-mounted read-only into the existing CPU runtime image and executed directly for a 6-second simulation deadline with `--network none`, no DISPLAY/Wayland/Xvfb/Weston, explicit Mesa `lvp_icd.json`, and `WGPU_SETTINGS_PRIO=webgpu`. It exited 0 after 22.7 wall seconds: 26 native rows, simulation time 0→6.09375 seconds, policy publication sequence 0→213, 8 armed+AUTO rows, finite policy outputs and changing vehicle position/quaternion. Every row reported actual Vulkan llvmpipe, vendor 65541, device type Cpu; exact inference count stayed null. All rows passed backend validation and normalized without changing metadata or policy sequence; the recorded software sample was correctly rejected by hardware acceptance. The log footprint was 671,106,155 bytes (~640 MiB), below 1 GiB. CUDA compiled but was not executed; neither these builds nor this software run establish NVIDIA/Jetson acceptance. See `vendor-assets/adapter-proof/evidence.json` and `cpu-6s/`.

## Measured local proof / operational cautions

- Real CPU task + native Vulkan llvmpipe execution completed offline: container `copper-flight-native-cpu-proof`, image `workload-copper-flight:native-cpu`; raw files `artifacts/native/cpu-webgpu/`.
- Requires `--init` for `xvfb-run`; as PID 1 its Xvfb readiness wait did not complete on this host. Runtime image includes tini.
- llvmpipe needs `WGPU_SETTINGS_PRIO=webgpu` on Mesa 26.0.8 / wgpu 29; default maximum-feature initialization failed with `ERROR_FEATURE_NOT_PRESENT`. This is an explicit local software-renderer setting, not a claim about Jetson GPU compatibility.
- 12.15625 simulated seconds finished in about 42 wall seconds; 50 real telemetry rows; policy preview publication sequence reached 570; position reached approximately (-10.99, 7.02, -44.68) meters. Exact inference count stays null.
- Raw compute+MCU logs occupied about 1 GiB at 12 simulation seconds. A 45-second run can exceed a 4-GiB aggregate retention budget by itself. Parent should bound episode duration/retention based on hardware measurements; do not silently suppress raw sources or alter the graph.
- Only the CPU/software-Vulkan path is executed locally. CUDA binary has compiled sm_87 PTX; real CUDA + native NVIDIA graphics requires matched target device userspace and remains device-only pending.
