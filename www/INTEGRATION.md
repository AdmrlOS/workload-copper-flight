# Admiral × Copper flight lab — UI integration

## Surface and ownership

Full-height flight/data demonstration: dominant forest scene, narrow Copper inspector, explicit Live / Recorded source switch, and a simulation-time timeline. Desktop stays within the viewport; only the inspector scrolls. Small screens stack flight first, then inspector. Supplied Admiral Archivo / IBM Plex Mono, actual marks, paper/ink/blue square ruled components remain offline. Copper attribution is retained.

Changes are scoped to `www/` and the requested coordination note `artifacts/partner-ui-plan.md`. Backend, native patches, builds and deployment are owned elsewhere. This UI has not been deployed by its author.

## Browser dependencies and API paths

`static-routes.json` is the strict backend dependency inventory. It includes the new `mission.js`, `live.js`, and `presentation.js`. Test files, documentation and verification evidence are not browser dependencies. No CDN, inline script, import map, dynamic package resolution or unsafe-inline CSP exception.

- `GET /api/state`: unchanged conservative parser, recording/configuration index and backward-compatible live fallback. Polls do not overlap; 3.5 s timeout.
- `GET /api/telemetry`: batched genuine native frames. Initial request omits cursor; subsequent requests use `after_seq` and `episode_id` together. Expected envelope: `{schema_version:1,status,engine,episode,frames,oldest_seq,latest_seq,reset,server_uptime_s,frame_age_s}`. Unknown/malformed JSON does not become live evidence. HTTP 404/405/501 enables `/api/state` fallback for 15 s before retrying batched transport.
- `GET /api/recordings/{id}/telemetry`: `{schema_version:1,recording:{id,completed,started_at,ended_at},provenance:null|object,frames:[native schema_version:1 frames],native_replay_verified:false}`. Same-origin GET, uncached JSON, strict existing recording ID syntax and exact requested ID match. Completed records only. Recording load timeout 30 s; superseded requests abort.
- `GET /api/scene/forest.glb` and `/api/scene/quadcopter.glb`: actual pinned source geometry, no transform repair or remote dependencies.
- Downloads retain exact validated `/api/recordings/{id}/download` paths, completed metadata required.

`provenance.engine` describes the recording's original engine. A legacy `null` provenance remains unavailable; it never falls back to the currently live runtime's revision, Copper version or configuration.

## Timing and interpretation

### Live

Live is always the default. A bounded buffer keeps at most 600 distinct received native frames. It uses simulation-time spacing plus observed arrival spacing; when `wall_time_s` is genuinely reported and monotonic, it instead measures native timestamp cadence. The inspector labels the timing basis explicitly. Receipt cadence is not claimed to be native source sampling frequency.

Presentation advances on requestAnimationFrame within already received endpoints. The source-rate estimate is actual simulation seconds per wall second, not assumed 1×. A delayed cursor and bounded rate correction absorb ordinary arrival jitter without extrapolation. Repeated sequences do not add samples or keep progress fresh. Missing age, nonnative engine, bad world/pose, runtime lifecycle changes, request failure or 2 s stale progress stop the live claim; the last displayed pose freezes.

Batched transport cannot make a slow native runtime realtime. Browser smoothness and measured source throughput are separate facts.

### Recorded

Recorded is an explicit user-selected mode. Opening a completed mission loads real telemetry, paused at its actual start. Play/Pause, restart, seek and 0.25× / 0.5× / 1× / 2× controls operate in simulation time. Switching away pauses the recorded clock; loading data never changes mode or creates a live claim.

Native frame sequence must strictly increase; simulation timestamps may stay equal or increase, matching the real backend. Binary search chooses the latest actual frame at an equal timestamp. Genuine startup frames can lack pose/attitude and remain in the data, with no aircraft placement until usable source data exists. Pose interpolation uses actual positions and unit-quaternion slerp. Inspector numbers remain the actual preceding observed source frame, not invented intermediate telemetry. Rendering can produce one distinct interpolated pose per display frame without claiming new native computation.

Every recorded surface is labelled **Recorded native mission visualization**, **not verified Copper native replay or live computation**. This implementation does not run a Copper binary replay engine.

## Copper inspector / truth boundary

- Observed simulated physics position, velocity, and quaternion are preserved in Bevy world axes, Y-up.
- Existing arm/AUTO/mode flags are labelled input **requests**, not proof of selected controls or actuation, following the native source audit.
- Observed velocity and reported policy vector charts contain only finite source values, preserve gaps, and do not infer tracking error or a predicted trajectory. Their coordinate conventions are not assumed equivalent.
- Policy publication sequence remains a publication sequence, never an exact inference count. An absent exact count is hidden. Live policy-advancing copy requires actual latest source publication progress, reported backend, usable prediction, and live source evidence. Recorded policy observations never say live/confirmed execution.
- Optional actual candidate `frame.copper` scalars are parsed: `recording_mode` (`full` / `telemetry-only`), `full_recording`, `mcu_iteration_wall_us`, `compute_iteration_wall_us`, `export_wall_s`. Whole-iteration durations render as reported wall milliseconds, explicitly not individual task/GPU/inference timings. Telemetry-only produces a prominent **FULL CAPTURE OFF · Telemetry only · no full native archive** banner over the flight canvas. `wall_time_s` is native-process elapsed time, re-anchored by episode buffer resets. These candidate fields have RED→GREEN coverage; the actual new native candidate still requires parent device/deployment verification. Additional reader capabilities are `control_loop_ms`, `tasks:[{name,duration_ms}]`, `depth:{min_m,max_m,valid_pixels,width,height}`, `sensor:{name,sequence,timestamp_s}`; none are manufactured when absent. Native measurement panes remain hidden when unsupported; an honest unavailable note remains. No task topology is presented as executing tasks; no synthetic sensor imagery, frame counts, timings, or GPU metrics.

## Scene fidelity

Forest root is identity: no added translation/scale/rotation. True source bounds are approximately `[-115,-2.5065,-545]` to `[115,28.9794,90]`. The quadcopter source model remains about 0.1185 m wide. It is never enlarged or repositioned relative to the observed pose. A clearly labelled screen-space **vehicle position** cue makes the small aircraft legible. Trace points are actual source positions. The observation camera clears the 29 m canopy (minimum 37 m) and follows only displayed pose; camera controls never affect native simulation.

## Verification for this revision

- Historical UI verification run: `node --test www/*.test.js` passed 42 tests with zero failures/skips; this is not the current suite count. RED→GREEN tests cover recording transport/parsing, real startup absence, equal sim timestamps, playback clock/clamping/seeking, mode isolation, batched live buffering, native/receipt clock distinction, no extrapolation, truthful policy labels, missing-value chart gaps, and explicit offline import allowlist.
- Browser tested at the parent's genuine-data development server `http://127.0.0.1:18082/`: current UI, actual pinned GLBs, read-only Jetson live proxy, and the actual completed mission `20261027T065422Z-0479a668`. This localhost server does not run local native Copper/CUDA.
- Genuine completed mission: 183 native frames; null startup pose preserved; `provenance:null` remains unavailable. Sampling 18.5–19.5 sim seconds at 60 evenly spaced presentation timestamps yielded 60 distinct interpolated positions from those actual frames. This verifies interpolation, not achieved browser FPS or native realtime performance.
- Browser controls exercised: Live default, Recorded auto-open, seek, Play/Pause, switching back to Live disables recorded controls and pauses recorded time, Overview / Follow camera controls. No observed JS errors during exercised controls; no failed resources at the tested mirror. The older deployed service's missing batched endpoint was separately observed to fall back to `/api/state` without fake data.
- Desktop 1440×900 and mobile 390×844 had no horizontal overflow in browser measurements. Mobile permits vertical reading below the full flight composition.
- `verification/partner-recorded.png` is a browser screenshot of the real recorded mission visualization, not live compute proof or native replay verification.

Design self-audit: no gradient/glass/feature-card grid/monument counters/default Inter. Command / Inspect composition, supplied typography, flat square rules, real source geometry, and no filler metrics.
