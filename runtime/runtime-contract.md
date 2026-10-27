# Flight runtime contract

Scope: the Python supervisor, secure boot, display/native launch wrappers and read-only HTTP. No deployment, fleet, Dockerfile, browser-policy or on-device GPU claim is made here.

## Installed layout and entrypoint

Install the repository's `boot.py`, `service.py`, `runtime/`, `scripts/start-flight`, `scripts/run-native-flight`, and packaged `www/` under `/opt/copper-flight`; both scripts must be executable. Launch **`/opt/copper-flight/scripts/start-flight` as root**, including when the runtime starts in `/` and ignores Docker USER/WORKDIR. Working directories are derived from the installed, immutable application location, not inherited process cwd.

Boot creates/opens only `/data/copper-flight` (or a confined child selected by `FLIGHT_DATA_DIR`), its `runs` leaf, and `/run/copper-flight/xdg`. It uses descriptor-relative no-follow operations; no recursive chown and no modification to `/data/runs` or unrelated volume state. Service launch is:

```
setpriv --reuid=10001 --regid=10001 --groups=28 --no-new-privs python3 /opt/copper-flight/service.py
```

The actual interpreter is `sys.executable`. The engine inherits UID/GID 10001, supplementary numeric group 28 and NoNewPrivs. `/run/copper-flight` is root-owned 0711; XDG leaf is 0700. Boot remains a small root process supervisor without an HTTP listener. It supervises the display helper and dropped service; the service supervises native process groups.

## Display selection (explicit; no software fallback)

`FLIGHT_DISPLAY_MODE`:

* `drm` (wrapper default): require a connected `/sys/class/drm/card*-*/status` before launching. Root display helper command is `setpriv --no-new-privs weston --no-config --backend=drm --renderer=gl --shell=kiosk-shell.so --socket=wayland-flight-PID --idle-time=0`. `LIBSEAT_BACKEND` defaults to `builtin`; libseat's root/builtin backend and actual VT/seat/device access must work in the target image. This does **not** assert that CUDA's device/driver injection supplies graphics. After readiness, transfer only the private XDG leaf and its socket to UID/GID 10001. DRM mode is not verified on Jetson.
* **`headless`** (set this explicitly for browser-primary deployments): managed Weston `--backend=headless --renderer=gl`, with compositor itself dropped using `setpriv --reuid=10001 --regid=10001 --groups=28 --no-new-privs`. Requires working hardware EGL/surfaceless userspace for Weston plus hardware Vulkan/Wayland support for Bevy. No connector required, but this is **not** a surface-free native renderer; Weston is still required.
* `software`: explicit **local software acceptance only**, managed Weston headless/pixman, dropped compositor, `LIBGL_ALWAYS_SOFTWARE=1`, and `WGPU_SETTINGS_PRIO=webgpu` by default (explicit administrator overrides are forwarded to native unchanged). Requires explicit absolute `VK_ICD_FILENAMES` path(s) to installed software Vulkan ICD(s). This mode is not evidence of NVIDIA graphics/CUDA.
* `existing`: launch/kill no host display process. Require explicit `WAYLAND_DISPLAY` socket basename + absolute `XDG_RUNTIME_DIR` with a real socket, or explicit `DISPLAY`. Existing display access/authentication is the administrator's responsibility. Software adapter telemetry is still rejected unless the selected mode is `software`.

Managed display exports its private XDG directory and Wayland socket to service/engine. Startup is bounded at 30 seconds. Early exit/timeout is a hard failure; display output is captured in bounded `/data/copper-flight/display.log` (8 MiB) and stderr. Display/service failure tears down owned process groups. No other display sessions are killed.

### Image dependency contract (native engineer owns installation)

Python 3; util-linux `setpriv`; Weston with headless and DRM backends, kiosk shell, GL and pixman renderers; libseat/seatd support for DRM/builtin root seat; Wayland client/server/EGL, EGL/GLES/GL, Vulkan loader, libxkbcommon, libudev, and native binary's remaining dynamically linked libraries (including audio/X11 if compiled). Ubuntu package names typically include `python3 util-linux weston libseat1 seatd libwayland-client0 libwayland-egl1 libegl1 libgles2 libgl1 libvulkan1 libxkbcommon0 libudev1`; resolve the exact library closure against the final image.

On Jetson, **matching NVIDIA EGL/GBM/GLES userspace and a working NVIDIA Vulkan ICD** must be supplied by the matching runtime profile/payload. Compute/PTX injection alone is insufficient. Parent owns the matching R39.2.1 payload research and surface-free probe; do not replace those drivers with incompatible desktop packages. Local `software` acceptance additionally uses Mesa software Vulkan (`mesa-vulkan-drivers`, explicit installed lvp ICD). Weston software process/UID supervision has actually run in a local ARM64 Linux container; no NVIDIA/Jetson EGL/Vulkan/CUDA execution has been tested by this runtime work.

## Native execution and offline inputs

Default native executable: **`/opt/copper-flight/bin/quad-sim`**, matching `native-contract.md`. `COPPER_FLIGHT_NATIVE_BINARY` is an administrator/test-only absolute executable override, not an HTTP control. Default launcher is `/opt/copper-flight/scripts/run-native-flight`; `COPPER_FLIGHT_LAUNCHER` is an absolute administrator/test override.

For each unique run ID, service sets:

```
FLIGHT_WORLD=forest
FLIGHT_INFERENCE=cpu|cuda
FLIGHT_EPISODE_SECONDS=45
COPPER_FLIGHT_LOG_DIR=/data/copper-flight/runs/ID/logs
COPPER_FLIGHT_TELEMETRY=/data/copper-flight/runs/ID/telemetry.jsonl
```

Defaults if not explicitly supplied: `FLIGHT_WORLD=forest`, `FLIGHT_INFERENCE=cpu`. The image/configuration must explicitly choose CUDA when desired; no inferred CUDA claim. `urban` requires a native graph that actually reports urban; a compiled forest graph requested as urban fails rather than pretending to switch worlds.

Wrapper sets explicit offline defaults `COPPER_FLIGHT_ASSET_DIR=/opt/copper-flight/assets`, `COPPER_FLIGHT_MODEL=/opt/copper-flight/models/vitfly-vitlstm-f32.safetensors`; missing files fail without attempting download. Native code must validate actual assets/model contents. Wrapper sets `WGPU_BACKEND=vulkan` and selects Wayland vs explicitly existing X11 via `WINIT_UNIX_BACKEND`. Requested vs actual inference mismatch fails. Actual adapter names containing llvmpipe/lavapipe/softpipe/SwiftShader/software fail outside explicit software mode. Null graphics/backend metrics remain unknown, never synthesized.

## Telemetry, episodes, health

JSONL schema v1 matches `native-contract.md`: strictly contiguous seq starting at 0; nonnegative finite/nonregressing simulation time; nullable actual position/velocity/policy vectors; actual booleans/world/mode; nullable actual inference backend/count; actual flat `graphics_backend`, `graphics_adapter`. Optional actual `rotation:{x,y,z,w}|null` and `policy_observation_seq:int|null` are preserved and validated. API adds `graphics:{backend,adapter_name}` by direct mapping of the flat native values; it does not invent an inference count or convert policy publication sequence into exact inference calls.

Each JSON line is bounded at 64 KiB, nesting at 8, duplicate keys/nonfinite/malformed values are rejected. New bounded schema fields can pass through. Partial lines are buffered; truncation/regression fails. No synthetic live/replay frames exist in runtime code.

* `/healthz` remains 503 until **simulation time actually advances between native observations**; HTTP response/FPS/compiled CUDA flags do not establish health.
* No first telemetry within `FLIGHT_STARTUP_TIMEOUT_SECONDS` (default/max 300; minimum .1) fails. Once telemetry starts, absence of **simulation progress**, including a stream of advancing seq with frozen simulation time, fails within `FLIGHT_INACTIVITY_TIMEOUT_SECONDS` (default/max 30; minimum .1).
* Clean episode completion requires native exit 0, actual simulation progress, a complete final JSON line with `sim_time_s >= requested episode duration`, observed requested backend, observed armed+auto state, and an actual non-null native policy prediction. Native must flush its terminal deadline sample before exiting. A zero exit alone is not completion/replay verification.
* Native owns autoarm at simulation second 4. Service loops clean episodes after `FLIGHT_PAUSE_SECONDS` (default 2; .1..30). Failure is fatal, process groups are terminated/KILL-escalated, API status becomes `failed` with error, and service exits nonzero. Intentional stop becomes `stopped`.

Default episode 45 simulation seconds; accepted runtime bound 4.01..3600. Startup/inactivity test overrides are explicitly bounded. The actual 45-second episode's log footprint fitting the default budget remains a native integration gate; the budget must not be disabled to force a pass.

## Persistence and downloads

Only `/data/copper-flight/runs/ID` is managed. IDs are `YYYYMMDDTHHMMSSZ-8lowerhex`. Files: atomically fsynced `manifest.json`, `telemetry.jsonl`, `native.log`, `logs/flight_compute_sim*.copper`, `logs/flight_controller_sim*.copper` and their actual slab families/relative sibling aliases. Default **2 retained runs / 4 GiB aggregate logical file bytes**, configurable `FLIGHT_KEEP_RUNS=1..16`, `FLIGHT_MAX_BYTES=1MiB..64GiB`. Retention is polled during recording; old managed runs are pruned first. Protected active run overflow fails. Corrupt/unmanaged manifests are not promoted or deleted blindly; they still count toward safety limits where applicable. Restart publishes only robustly validated completed manifests; current active incomplete run may appear as `completed:false`. No `verified` flag/replay badge exists.

Downloads require a completed run. Safe regular single-link files are pinned under the recording lock, then lock is released before compression or network writes. Open is no-follow/nonblocking to reject symlink/FIFO/directory/hardlink substitutions; only two native slab families' safe file-shaped Copper artifacts (and other safe Copper slabs), manifest/telemetry/native logs are eligible. Only validated relative sibling Copper aliases to included regular files are emitted. `logs/` is explicitly confined; no arbitrary recursive asset/filesystem archive. Full numbered slab families are preserved, not just slab zero.

There is one concurrent archive job; others receive 429. An unlinked temporary gzip snapshot is created under the app data directory, and slow network sockets time out after 5 seconds; the retention lock is not held while compressing/uploading. The run-retention budget does not count this one temporary download snapshot or the separate bounded display diagnostic log: provision transient disk headroom (up to another retained-run archive) rather than interpreting 4 GiB as a whole-volume quota.

## Read-only UI HTTP contract

Bind `0.0.0.0:8080` (`PORT` override). Unauthenticated, read-only, **trusted-network only**; no control endpoints. GET `/api/state` returns the requested native engine/configuration/episode/frame/recordings/uptime schema. GET `/healthz` reports simulation progress readiness; GET `/api/recordings/ID/download` returns gzip archive.

Exact scene endpoints only: **`/api/scene/forest.glb`**, **`/api/scene/quadcopter.glb`** from matching regular immutable files under `COPPER_FLIGHT_ASSET_DIR`; MIME `model/gltf-binary`. Encoded aliases, traversal, private/unlisted assets, symlinks, FIFOs, hardlinks are refused. Reads are chunked with socket timeouts; midstream file failure closes rather than injecting JSON into the binary stream.

Browser modules/styles/fonts/logos/vendor modules are served from a finite startup inventory of packaged `www/` files with suffixes `.html .js .css .svg .png .jpg .jpeg .ico .woff .woff2 .ttf`; root `/` maps to `index.html`. Each directory component is opened relative to a no-follow descriptor, and the final file must be regular/single-link. New runtime-added files are not admitted to this inventory. CSP has `default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' blob: data:; connect-src 'self' blob:; object-src 'none'; base-uri 'none'; frame-ancestors 'none'` (blob/data image allowance supports locally decoded GLB textures): **no inline import map/scripts/styles**, no external CDN; vendor modules must use local relative imports. WebGL is presentation of real native pose, not native GPU compute/policy execution.

## Exercised vs blocked

Tests use explicitly labelled protocol/failure-injection subprocesses, not replacement production engines. Local macOS unit/subprocess HTTP/retention/watchdog tests and local Linux ARM64 container tests exercise the wrappers. The opted-in ephemeral Linux root test actually launches boot from `/`, checks UID/GID 10001 + group 28 + NoNewPrivs and fixed cwd for service/engine, starts **real Weston headless/pixman** as UID 10001 in explicit software mode, observes startup-watchdog failure/exit 1, confirms engine teardown, and preserves old `/data/runs` sentinel.

Separately, all 51 rows in the parent's archived `artifacts/native/cpu-final/telemetry.jsonl` passed this runtime's frame validator (last sim time 12.125, actual backend cpu, llvmpipe, real rotation and policy observation sequence). That is **archive-schema compatibility evidence only**, never replayed as live data and not an on-device/GPU test. Native full-duration/budget, exact terminal-flush ordering, matching Jetson EGL/GBM/Vulkan userspace, hardware headless Weston/Bevy, NVIDIA adapter telemetry and actual CUDA policy execution remain integration/device acceptance gates owned by parent/native engineers.
