# Full-resolution source depth

The depth canvas displays **320×240 actual quantized source pixels**, not a blurred or enlarged 32×24 thumbnail. The native implementation remains responsible for obtaining the completed CPU source buffer and the 500 ms wall-clock sampling cache. This backend/browser change does not alter Copper control, physics, inference, GPU readback, branding, or native replay claims.

## Native file interface

Native writes to the existing `COPPER_FLIGHT_TELEMETRY` JSONL file, not stdout:

```json
{"schema_version":1,"kind":"depth-raster","depth_raster":{"...":"full metadata plus data"}}
```

A standalone event precedes the first pose referencing it. It has no pose `seq` and never increments pose history, receipt freshness, health, policy evidence, or simulation progress. Ordinary poses may add `depth_raster` containing only the metadata below. Existing `depth_preview` (32×24 nearest-cell-center data) is unchanged for compatibility.

Both descriptor and raster use:

- `source`: `SimZedFrameStore.depth/Copper.ZedSource`
- `source_width`, `width`: `320`; `source_height`, `height`: `240`
- `sampling`: `identity`; `encoding`: `u8-hex`; `source_units`: `millimetres`
- `invalid_u8`: `0`; `invalid_rule`: `source_mm == 0 or source_mm > 20000`
- `decode_m`: `(1 + (q - 1) * 19999 / 254) / 1000; q=0 invalid`
- `range_m`: `[0.001,20]`
- actual `source_seq` (nonnegative JavaScript-safe integer), `sample_wall_time_s`, `sample_sim_time_s` (finite nonnegative native CPU sample times, no acquisition timestamp claim)

A full raster additionally has `data`: **153600 lowercase hexadecimal characters**, two per source pixel, row-major. Invalid source pixels are encoded as zero. Native omits an observation if the entire source buffer is invalid, matching the legacy preview behavior; it does not invent distances. Pose descriptors must not contain data. Descriptor sample times cannot be later than their containing pose times (existing 1 µs tolerance).

The existing 64 KiB manifest/pose JSON limit and 32 MiB playback artifact limit are unchanged. Standalone native events have a separate 192 KiB bounded JSON/line limit with duplicate-key, nesting and finite-number checks. Events are validated but omitted from completed pose playback responses and live pose history. Original JSONL, including raster events, is already included in recording archives.

## Read-only exact endpoint

`GET /api/recordings/RUN_ID/depth/SOURCE_SEQ` returns the full raster object, **not** an envelope, for that exact run and source sequence. IDs retain the existing `YYYYMMDDTHHMMSSZ-xxxxxxxx` grammar. Source sequences are canonical decimal safe integers: no signs, leading zeroes, encoded path components, extra segments, or query parameters.

- Current episode: an eight-entry bounded in-memory cache, cleared on episode start; no depth filesystem writes or new recording subdirectories.
- Cache miss/completed recording: pin the existing regular single-link `telemetry.jsonl` and validated run manifest using no-follow directory/file descriptors under the retention lock. Release the lock before scanning. Read no more than the pinned initial size, at most 32 MiB, with 192 KiB bounded lines and the existing pose count/order checks. A partial final row is permitted only for an active writer. A pinned file remains readable if retention unlinks its path.
- Reuse the existing two-reader playback semaphore. HTTP 429 means readers are busy. Missing run/sequence is 404; malformed/unsafe content or path is 400; inactive incomplete recording is 409; oversized artifact is 413. No nearest-sequence or cross-run fallback.
- Only this full-raster endpoint may use stdlib gzip level 1. Exact parsed `gzip` tokens with valid positive quality values permit compression; `q=0`, malformed quality values and ambiguous duplicates fail closed. Wildcards do not opt in. `Vary: Accept-Encoding` is set. Ordinary state/telemetry transport is unchanged; Chrome decompresses full-raster JSON automatically.

## Browser behavior

`state.js` allowlists small descriptors. `depth.js` validates fixed dimensions/constants, exact hex length, finite sample times, safe sequence, and **every response metadata field against the captured requested descriptor and source frame** before rendering. The network reader caps decompressed JSON at 192 KiB. Pixels use a precomputed palette and numeric nibble decoding, without per-pixel arrays or substrings. The real canvas backing store is 320×240 and each source pixel maps to one canvas pixel. CSS applies no blur or invented detail.

Requests start only from the independent 200 ms wall timer, never requestAnimationFrame, and a monotonic 500 ms gate limits starts to two per second. There is at most one current full-raster request in flight. A newer descriptor in the same live episode does **not** abort a slow request: its validated response may display its actual older source sequence/times while the newest descriptor waits for the next request. The prior full raster is held rather than replaced by thumbnails. Age uses the current live native wall clock plus receipt age, not the old response's receipt time.

Mode, episode/epoch, recording-load and disposal changes abort/invalidate outstanding responses even when a transport ignores abort. Recorded seeks additionally require the returned descriptor to match the currently selected source frame; no future-row raster is displayed. Depth remains non-interpolated source evidence, separate from pose animation. Old recordings that omit full-raster descriptors use their real 32×24 canvas and are explicitly labelled **Legacy 32×24 thumbnail**, never full resolution.

## Verification

- `python3 -m unittest discover -s tests -v`
- `npm test --prefix www`
- `tests/test_depth_fullres.py`: real HTTP 200, exact run/sequence matching, malformed metadata/events, size boundaries, encoded traversal, symlinks/hardlinks, reader exhaustion, retention pinning, cache bounds, and a real child process whose depth-only output cannot satisfy the startup watchdog.
- `www/depth-fullres.test.js`: varied adjacent pixels, exact canvas dimensions, every metadata field, bounded network input, slow-live/latest-queue behavior, wall-rate gating, stale async mode/epoch/run/seek responses, truthful age and legacy fallback.
- Optional actual Chromium integration: run `python3 tests/depth_browser_fixture.py`, then `DEPTH_BROWSER_URL=http://127.0.0.1:PORT/ DEPTH_CHROME_BIN=/path/to/chrome node --test www/depth-canvas.test.js`. It launches a separate headless profile, exercises the real app/HTTP endpoint, reads actual 320×240 Canvas2D pixels, verifies automatic gzip decoding, and opens an old recording to verify explicit 32×24 fallback. The fixture is synthetic test input, **not native execution or deployment evidence**.

RED/GREEN logs, complete Python/Node suite outputs and actual Chromium canvas output are saved under ignored `artifacts/depth-fullres/`.
