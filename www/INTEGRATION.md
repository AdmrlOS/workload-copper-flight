# Admiral / Copper flight monitor — UI integration

## Scope and runtime boundary

All deliverable changes are under `www/`. The UI is dependency-free HTML/CSS/ES modules apart from locally vendored Three.js. It renders received native poses; it contains no physics, policy implementation, native/WASM substitute, remote video feed, or simulation controls. The three buttons affect the observation camera only.

Hardware is not inferred from deployment intent. Copy says **native compute**, not Jetson, unless an actual identity is available. Native graphics backend/adapter and requested vs reported inference are separate observations. The inspected integration was **local CPU CuVitFly with software Vulkan / llvmpipe**, not Jetson/CUDA.

## Production files and static routes

`static-routes.json` is the exact dependency inventory: **21 static paths**, plus two scene endpoints. Map `/` to `/index.html`. Serve only the packaged paths, using the backend's descriptor/no-follow safety. Tests, documentation, verification evidence, the manifest itself, and vendor provenance are not browser dependencies.

- Surface: `index.html`, `styles.css`, `app.js`.
- Data/runtime: `state.js`, `transport.js`, `monitor.js`, `format.js`.
- Scene: `pose.js`, `viewer.js`.
- Brand: `assets/Archivo.woff2`, `assets/IBMPlexMono-Regular.woff2`, `assets/IBMPlexMono-Medium.woff2`, `assets/admiral-logo-light.svg`, `assets/admiral-icon.svg`, `assets/paper-tile.png`, `assets/dark-texture-tile.png`.
- Three.js: `vendor/three-r182/build/three.module.js`, `vendor/three-r182/build/three.core.js`, `vendor/three-r182/examples/jsm/loaders/GLTFLoader.js`, `vendor/three-r182/examples/jsm/controls/OrbitControls.js`, `vendor/three-r182/examples/jsm/utils/BufferGeometryUtils.js`.

Three.js is pinned to **r182 / 0.182.0**. MIT `LICENSE`, `PROVENANCE.md`, and `SHA256SUMS` are preserved under `vendor/three-r182/`. Only the three add-ons' bare `three` imports were rewritten to local relative paths. No inline import map or CSP relaxation is needed. The supplied brand bundle's WebP textures were losslessly represented as local PNGs to work with the backend's allowed image suffixes; paper grain is restrained with CSS opacity.

Required APIs:

- `GET /api/state` — poll every 200 ms, never overlap requests, 3.5 s request timeout.
- `GET /api/scene/forest.glb`.
- `GET /api/scene/quadcopter.glb`.
- Completed recording URLs exactly as supplied, with IDs matching `[0-9]{8}T[0-9]{6}Z-[0-9a-f]{8}` and the exact local `/api/recordings/ID/download` path.

The tested GLBs contain no external images or decoder dependencies. Both loaded under the actual service's `default-src 'self'; script-src 'self'; style-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'` CSP. No `unsafe-inline`, blob-image allowance, CDN, fonts API, or network package resolver was used.

## Evidence rules

- Valid HTTP alone never makes telemetry live. A later native frame sequence must advance; runtime frame age must be known and below 2 s. Repeated successful frozen responses become stale after 2 s. Errors preserve last received values but mark them unavailable/currently unconfirmed.
- Missing vectors, booleans, counters, graphics identity and quaternions stay unknown. A vehicle is hidden until a fresh native position **and actual quaternion** are available. No identity orientation is invented for missing rotation.
- A `policy_observation_seq` is a publication sequence, **not an exact inference count**. Policy confirmation requires fresh advancing native frame sequence, recently advancing policy publication sequence, an actual reported CPU/CUDA backend, and a finite prediction. A null `inference_count` remains `—` even when policy evidence is confirmed.
- Requested CUDA is never converted to observed CUDA. Requested vs observed mismatch is explicit. Native graphics and browser WebGL are not conflated.
- Recording metadata has unknown, empty, incomplete, complete, invalid-path and partial-index states. Download links are only emitted for completed files and exact validated local paths. Recordings do not create a verified-replay claim.

## Pinned world/pose alignment

Checked `upstream` at exact source revision `d46ef87a65c7ba93bcad3c236da99e52cd77f319`, file `examples/cu_flight_controller/src/sim.rs`, using `git show` rather than assuming a world transform:

- Forest `SIM_WORLD.scale = 1.0`.
- World root `world_translation = Vec3::ZERO`, `world_scale = Vec3::splat(SIM_WORLD.scale)`, default/identity rotation.
- Native quad root receives its actual translation/quaternion; the GLB's internal node transforms remain intact.

The browser therefore applies **no extra forest translation, scaling, rotation or axis conversion**. Both paths use Y-up. Urban frames explicitly refuse a forest pose visualization rather than placing them in the wrong scene.

The default stabilized chase camera follows only the displayed observed/interpolated vehicle position. It uses a shallow viewing angle to retain nearby forest context. Dragging switches to orbit; reset and frame-vehicle are view-only. The vehicle transform is never changed by camera controls.

Pose history holds 24 samples and a maximum 256 actual trace points, resets across episodes/restarts/regression or long gaps, and interpolates only within observed endpoints with a 200 ms presentation delay. It never extrapolates. Stale/unreachable/between-episode states freeze the displayed pose and show an overlay. Restoring a disposed page from bfcache reloads fresh observations.

## Verification performed

Command: `node --test www/*.test.js` — **25 tests passed**, zero failed/skipped. Pure parsing, transport, progress/freshness, policy evidence, literal recording IDs, unknown/partial metadata, quaternion interpolation, absence, source connection, trace bounds, no extrapolation and chase framing were exercised RED before GREEN. Test files:

- `assets.test.js`
- `format.test.js`
- `monitor.test.js`
- `pose.test.js`
- `state.test.js`
- `transport.test.js`

All **18 JavaScript files**, including test files and vendored modules, passed `node --check`.

Actual browser verification used the real `service.make_server` CSP/static path, then the newest local UI through a temporary same-origin inspection proxy to the parent's **real native CPU service at `http://127.0.0.1:18081`**. The proxy forwarded actual state and immutable GLBs, not fixtures. It was not a release/deployment.

Observed in that real integration:

- WebGL2 context, forest + native black quad, full native quaternion, advancing native sequence, and a bounded real sampled path.
- `CPU policy observed` with advancing `policy_observation_seq`; exact inference count remained `—`.
- Actual Vulkan adapter `llvmpipe (LLVM 21.1.8, 128 bits)`; no hardware/CUDA verification claim.
- Genuine grounded AUTO-wait phase: `Disarmed`, AUTO `Disabled`, sim time `0.53`, frame `3`, position `[-10.00, 0.07, 20.00]`. The vehicle did not fly before native activation.
- Real between-episode transition: source `paused`, `Last displayed pose · frozen`, policy badge `Unconfirmed`.
- Camera reset/orbit and chase controls worked without changing native execution.
- No JS/CSP errors in inspected live states; zero non-local browser resources and zero failed asset requests.
- No horizontal page overflow at 320, 390, 768, 960 or 1440 pixel viewports; controls have 44 px minimum height.

Earlier isolated browser fixtures (not shipped) verified successful-but-frozen responses, transport failure, absent orientation, unsafe recording URLs, and HTML-injection resistance. A mobile overflow caused by an absolutely positioned screen-reader label escaping its table scroller was reproduced and fixed. The bfcache lifecycle regression was reproduced and fixed. Hidden-tab rAF suspension was distinguished from a scene failure by a foreground recheck.

`verification/native-cpu-chase.png` is a screenshot of the newest UI against the actual CPU integration, not generated telemetry or Jetson proof. The backend currently reports `engine.revision = "unknown"`; the UI preserves that honestly. Jetson/CUDA hardware execution and native replay verification remain outside this UI task.

Design self-audit: **0/10 slop tells**. Monitor composition, supplied Admiral typography/marks, one brand blue, square ruled surfaces, and a real scene observation rather than a marketing hero.
