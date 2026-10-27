# Native integration evidence and handoff

## Completed

Pinned Copper `d46ef87a65c7ba93bcad3c236da99e52cd77f319` builds on Linux ARM64 with the original MCU + compute task graph and real `cu-vitfly`. Registry dependencies are preserved in `Cargo.lock`; six public CDN inputs are size/SHA-256 locked. Runtime assets/model are immutable, explicit paths bypass download caches, binary logs and telemetry use active-run environment paths.

The minimal native patch adds real Bevy-side telemetry and a **true surface-free mode**: `FLIGHT_DISPLAY_MODE=headless` or `software` disables Winit and windows, keeps the original camera/depth readback path, renders the scene to an image, and drives Bevy with ScheduleRunner. No Weston, Xvfb, display socket, DRM connector or swapchain is required in this mode. `drm`/`existing`/unset retain the Winit path.

## Exact artifacts

| Image | Local image ID | Size |
|---|---|---:|
| `workload-copper-flight:native-cpu-offscreen` | `sha256:689ddbe3caff4ae9e45a569d1e2a7f409cc202455f0869d6ddac0dada862f3c5` | 1,545,790,245 B |
| `workload-copper-flight:native-cuda-offscreen` | `sha256:d118b0ec498ed36b03704ee242f67eadf5a82fe7488d0c0910f53d7641d2b397` | 2,165,764,625 B |
| `workload-copper-flight:development-offscreen` | `sha256:7d135a1c715d6df5d2c575f21a8c1df1da9c6f29e7c50ec0c3bb17be07fc0323` | 2,169,356,854 B |

All are ARM64 and remain local/unpublished. `development-offscreen` packages the parent-owned supervisor/runtime/UI snapshot; only importability, packaging and native binary identity were verified here, not its full service integration.

- CPU binary: `vendor-assets/offscreen/quad-sim`, SHA-256 `0ded03ed06a195daa57bd2258275d0884438e88fa18d8fea0a3114897af2e3d3`.
- CUDA binary: `vendor-assets/offscreen/quad-sim-cuda`, SHA-256 `347a434163cf1681b97b28b59c0fc997a46999b580939ba303e4154ca3b623e5`.
- Full machine-readable handles, source hashes, commands, timings and checks: `native-evidence.json`.

## Actual execution

`copper-flight-native-offscreen-proof` (`0d5e23aa762b1b05c00b2e3a7293d2763e51131845d6b2bf5fd119a0de00e8c9`) ran the native executable directly, **network none**, no DISPLAY/WAYLAND_DISPLAY and no Xvfb/Weston. Exit 0 after **39.235328 wall seconds**. Real telemetry: **51 rows**, sim time **0 → 12.1875 s**, policy preview sequence **0 → 568**, actual loaded backend `cpu`, actual renderer `Vulkan` / `llvmpipe (LLVM 21.1.8, 128 bits)`, armed+AUTO+Angle, changing position/quaternion/velocity, finite learned policy output. Final position: `(-11.184832, 7.2351475, -43.098755)` m. Raw proof: `artifacts/native/cpu-offscreen-surfacefree/`.

The earlier independently checked Xvfb proof remains untouched: container `copper-flight-native-cpu-final` (`b41231e4777d91a09d3e5b87b3b88a5950f7c4cdd755d5b9389fdf81b419465e`), `artifacts/native/cpu-final/`, exit 0, 51 rows, 12.125 simulated seconds, policy preview sequence 571.

CUDA compilation is verified: NVCC 12.6.85, Candle 0.11.0, **11 generated PTX files all targeting sm_87**, recorded in `artifacts/native/cuda-ptx.json`. Final offscreen CPU+CUDA compilation took 54.284959 wall seconds with warm dependencies (cold CPU compilation was 8m34s; initial CUDA increment 1m56s). No CUDA inference or NVIDIA rendering was executed locally. CUDA executables dynamically require `libcuda.so.1` even with `FLIGHT_INFERENCE=cpu`; use the CPU-only image on hosts without injected NVIDIA driver libraries.

## Commands

Reconstruct sources/assets:

```sh
python3 scripts/native_sources.py prepare --source upstream
python3 scripts/native_sources.py assets --destination acquired
RUN_NATIVE_RUST_TESTS=1 python3 -m unittest discover -s tests -p test_sources.py -v
```

Package the actual completed native artifacts (no recompile):

```sh
docker build --target native-local --build-context native-binary=vendor-assets/offscreen -t workload-copper-flight:native-cpu-offscreen .
docker build --target native-local-cuda --build-context native-binary=vendor-assets/offscreen -t workload-copper-flight:native-cuda-offscreen .
docker build --target flight --build-arg NATIVE_RUNTIME=native-local-cuda --build-context native-binary=vendor-assets/offscreen -t workload-copper-flight:development-offscreen .
```

The default `flight` target also supports source compilation through `native-build` rather than the named binary context. The exercised compilation commands and container mounts are in `native-evidence.json`; builds bound jobs to 3 and disable incremental/debug information.

Repeat surface-free CPU execution into a **new** output directory:

```sh
mkdir -p artifacts/native/new-offscreen-proof
docker run --init --network none --shm-size 1g \
  -v "$PWD/artifacts/native/new-offscreen-proof:/data" \
  -e FLIGHT_DISPLAY_MODE=headless -e FLIGHT_INFERENCE=cpu \
  -e COPPER_FLIGHT_LOG_DIR=/data -e COPPER_FLIGHT_TELEMETRY=/data/telemetry.jsonl \
  -e FLIGHT_EPISODE_SECONDS=12 -e WGPU_BACKEND=vulkan -e WGPU_SETTINGS_PRIO=webgpu \
  workload-copper-flight:native-cpu-offscreen /opt/copper-flight/bin/quad-sim
```

## Tests and limitations

- Eight acquisition/helper tests passed, including real checksum rejection, cache repair, contained paths, immutable revision verification, patch idempotency, full source reconstruction, finite duration validation, offscreen-mode selection and JSON/null/quaternion serialization. New helper behavior was observed red before implementation.
- Upstream `vitfly_is_rate_limited_and_infers_between_context_packets` passed on Linux ARM64 with the real offline model.
- Changed Rust files were formatted with the pinned toolchain's rustfmt. Full `just fmt`/workspace checks were unavailable (`just` absent); this was not represented as a full upstream gate.
- Telemetry is documented in `native-contract.md`: actual transforms including quaternion, RC armed/auto/mode, loaded inference device, policy preview publication sequence, renderer adapter/backend. Exact `inference_count` deliberately remains null; preview publications are **not** inference-call counts. Sampling is capped at 10 Hz outside the Copper loop; software rendering delivered fewer rows per wall second.
- Binary logs were generated, but deterministic replay computation was **not** verified from them.
- **Parent integration remaining:** bypass Weston for the new native headless/software modes. Existing parent `runtime/display.py` still constructs Weston plans. Integrate the separate matched NVIDIA graphics payload from `graphics/`; these images do not yet contain it. CUDA runtime forces `VK_DRIVER_FILES=/etc/vulkan/icd.d/nvidia_icd.json` and Vulkan, preventing Mesa from silently satisfying GPU acceptance. Real Jetson CUDA + native Vulkan/depth acceptance remains pending.
- Initial failures were preserved honestly: login shell reset Cargo PATH (127), Xvfb PID1 readiness stall, missing xkbcommon-X11 library (101), and llvmpipe default maximum-feature initialization (101). Recovery used non-login shell, `--init`, the missing runtime library, and explicit `WGPU_SETTINGS_PRIO=webgpu` respectively.
- Each 12-second proof produced **nine 128-MiB slabs = 1.125 GiB logical log size**, excluding base symlinks. A simple linear 45-second projection is **4.21875 GiB**, not proof that a 45-second run fits 4 GiB. No large 45-second run was performed. Do not drop replay inputs to meet the budget; parent must size retention/episodes using device measurements.
- Build cache volumes: `copper-flight-native-target` about **5.3 GiB**, registry about **772 MiB**. Native evidence occupied about **2.73 GiB allocated** at measurement. Host free space was about **11.25 GiB** after builds; no unrelated Docker resources were pruned. Stop large builds/runs until disk budgeting is resolved.
- Upstream source is Apache-2.0; `cu-vitfly` declares MIT OR Apache-2.0. CDN model/scene redistribution rights were not independently established. The unused city asset embeds Sketchfab Standard terms and is excluded from runtime. Preserve notices and keep evaluation private pending rights review.

No service/boot/runtime/UI/other tests, deployment/configuration, credentials, git staging, commits or publication were modified by this native workstream; parent-owned files were only read and copied into the packaging layer.
