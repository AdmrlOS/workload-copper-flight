// Fixed native contract only. Never allocate from untrusted raster dimensions.
const constants = Object.freeze({
  source: 'SimZedFrameStore.depth/Copper.ZedSource', source_width: 320, source_height: 240,
  width: 32, height: 24, encoding: 'u8-hex', sampling: 'nearest-cell-center',
  source_units: 'millimetres', invalid_u8: 0,
  invalid_rule: 'source_mm == 0 or source_mm > 20000',
  decode_m: '(1 + (q - 1) * 19999 / 254) / 1000; q=0 invalid',
});

export function parseDepthPreview(value, frame) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null;
  if (!Object.entries(constants).every(([key, expected]) => value[key] === expected)) return null;
  if (!Number.isSafeInteger(value.source_seq) || value.source_seq < 0) return null;
  for (const [sample, row] of [['sample_wall_time_s', 'wall_time_s'], ['sample_sim_time_s', 'sim_time_s']]) {
    if (!Number.isFinite(value[sample]) || value[sample] < 0 || !Number.isFinite(frame?.[row]) || value[sample] > frame[row] + 1e-6) return null;
  }
  if (!Array.isArray(value.range_m) || value.range_m.length !== 2 || value.range_m[0] !== .001 || value.range_m[1] !== 20) return null;
  if (typeof value.data !== 'string' || value.data.length !== 1536 || !/^[0-9a-f]+$/.test(value.data) || !/[1-9a-f]/.test(value.data)) return null;
  // Allowlist fields, not a native object spread (including hostile extra fields).
  return { ...constants, source_seq: value.source_seq, sample_wall_time_s: value.sample_wall_time_s,
    sample_sim_time_s: value.sample_sim_time_s, range_m: [.001, 20], data: value.data };
}

export function depthPresentation(view, observation = null) {
  const frame = view.frame;
  if (!frame) return { kind: 'absent', preview: null, ageS: null };
  const full = Object.hasOwn(frame, 'depth_raster');
  if (full && !parseDepthDescriptor(frame.depth_raster, frame)) return { kind: 'invalid', preview: null, ageS: null };
  if (full && !observation?.raster) return { kind: observation?.error ? 'invalid' : 'loading', preview: null, ageS: null };
  if (!full && !Object.hasOwn(frame, 'depth_preview')) return { kind: 'absent', preview: null, ageS: null };
  const sourceFrame = full ? observation.frame : frame;
  const preview = full ? parseDepthRaster(observation.raster,
    view.mode === 'recorded' ? frame.depth_raster : rasterMetadata(observation.raster, sourceFrame), sourceFrame) : parseDepthPreview(frame.depth_preview, frame);
  if (!preview) return { kind: 'invalid', preview: null, ageS: null };
  const recorded = view.mode === 'recorded';
  const wall = !recorded && Number.isFinite(view.latestFrame?.wall_time_s) ? view.latestFrame.wall_time_s : frame.wall_time_s;
  const receiptAge = !recorded && Number.isFinite(view.frameAgeS) ? view.frameAgeS : 0;
  const ageS = Math.max(0, wall - preview.sample_wall_time_s) + receiptAge;
  return { kind: recorded ? 'recorded' : !view.live || ageS >= 2 ? 'stale' : 'live', preview, ageS, legacy: !full, sourceFrame };
}

const rasterConstants = Object.freeze({ ...constants, width: 320, height: 240, sampling: 'identity' });

function rasterMetadata(value, frame) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null;
  if (!Object.entries(rasterConstants).every(([key, expected]) => value[key] === expected)) return null;
  if (!Number.isSafeInteger(value.source_seq) || value.source_seq < 0) return null;
  for (const [sample, row] of [['sample_wall_time_s', 'wall_time_s'], ['sample_sim_time_s', 'sim_time_s']]) {
    if (!Number.isFinite(value[sample]) || value[sample] < 0 || !Number.isFinite(frame?.[row]) || value[sample] > frame[row] + 1e-6) return null;
  }
  if (!Array.isArray(value.range_m) || value.range_m.length !== 2 || value.range_m[0] !== .001 || value.range_m[1] !== 20) return null;
  return { ...rasterConstants, source_seq: value.source_seq, sample_wall_time_s: value.sample_wall_time_s,
    sample_sim_time_s: value.sample_sim_time_s, range_m: [.001, 20] };
}

export function parseDepthDescriptor(value, frame) {
  if (value && Object.hasOwn(value, 'data')) return null;
  return rasterMetadata(value, frame);
}

export function parseDepthRaster(value, descriptor, frame) {
  const expected = parseDepthDescriptor(descriptor, frame);
  const actual = rasterMetadata(value, frame);
  if (!expected || !actual || !Object.keys(expected).every(key => key === 'range_m'
    ? actual[key].every((v, i) => v === expected[key][i]) : actual[key] === expected[key])) return null;
  if (typeof value.data !== 'string' || value.data.length !== 153600 || !/^[0-9a-f]+$/.test(value.data)) return null;
  return { ...actual, data: value.data };
}

// Precompute the palette once. Decode two hex nibbles without per-pixel arrays/strings.
const palette = new Uint8ClampedArray(256 * 4);
for (let q = 0; q < 256; q++) {
  const t = (q - 1) / 254; const offset = q * 4;
  palette[offset] = q === 0 ? 18 : 33 + 209 * t;
  palette[offset + 1] = q === 0 ? 20 : 82 + 157 * t;
  palette[offset + 2] = q === 0 ? 32 : 238 - 7 * t;
  palette[offset + 3] = 255;
}
const nibble = code => code <= 57 ? code - 48 : code - 87;

export function depthPixels(value, frame) {
  const preview = value?.width === 320 ? parseDepthRaster(value, rasterMetadata(value, frame), frame) : parseDepthPreview(value, frame);
  if (!preview) return null;
  const count = preview.width * preview.height;
  const pixels = new Uint8ClampedArray(count * 4);
  for (let i = 0; i < count; i++) {
    const q = nibble(preview.data.charCodeAt(i * 2)) * 16 + nibble(preview.data.charCodeAt(i * 2 + 1));
    const source = q * 4; const target = i * 4;
    pixels[target] = palette[source]; pixels[target + 1] = palette[source + 1];
    pixels[target + 2] = palette[source + 2]; pixels[target + 3] = 255;
  }
  return pixels;
}

export function paintDepth(canvas, value, frame) {
  const pixels = depthPixels(value, frame);
  if (!pixels) return false;
  const context = canvas.getContext('2d');
  if (!context) return false;
  canvas.width = value.width; canvas.height = value.height;
  const image = context.createImageData(value.width, value.height);
  image.data.set(pixels); context.putImageData(image, 0, 0);
  return true;
}

async function readRasterJSON(response) {
  if (!response.ok) throw new Error(`Depth HTTP ${response.status}`);
  if (!/^application\/json(?:\s*;|$)/i.test(response.headers.get('Content-Type') ?? '')) throw new TypeError('Expected depth JSON');
  const reader = response.body.getReader(); const chunks = []; let size = 0;
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      size += value.byteLength;
      if (size > 192 * 1024) { await reader.cancel(); throw new TypeError('Depth response too large'); }
      chunks.push(value);
    }
  } finally { reader.releaseLock(); }
  const bytes = new Uint8Array(size); let offset = 0;
  for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.byteLength; }
  return JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(bytes));
}

// Selection/paint run on the inspector clock; only poll() may start network IO.
export function createDepthLoader(fetchImpl, { now = () => performance.now() } = {}) {
  let target = null; let contextKey = null; let selectedKey = null; let attemptedKey = null;
  let result = null; let error = null; let pending = null; let lastStarted = -Infinity; let disposed = false;
  function cancel() { pending?.controller.abort(); pending = null; }
  return {
    select({ mode, runID, epoch, frame }) {
      const descriptor = parseDepthDescriptor(frame?.depth_raster, frame);
      const valid = ['live', 'recorded'].includes(mode) && typeof runID === 'string' && /^[0-9]{8}T[0-9]{6}Z-[0-9a-f]{8}$/.test(runID);
      const nextContext = JSON.stringify([mode, runID, epoch]);
      const nextKey = descriptor && valid ? JSON.stringify([nextContext, descriptor]) : null;
      if (nextContext !== contextKey || mode === 'recorded' && nextKey !== selectedKey) {
        cancel(); result = null; error = null; attemptedKey = null;
      }
      contextKey = nextContext; selectedKey = nextKey;
      target = nextKey ? { mode, runID, descriptor, key: nextKey, context: contextKey,
        frame: { seq: frame.seq, wall_time_s: frame.wall_time_s, sim_time_s: frame.sim_time_s } } : null;
    },
    async poll() {
      if (disposed || pending || !target || target.key === attemptedKey || now() - lastStarted < 500) return;
      const request = { ...target, controller: new AbortController() };
      pending = request; attemptedKey = request.key; lastStarted = now(); error = null;
      const timeout = setTimeout(() => {
        if (disposed || pending !== request) return;
        error = 'Depth request timed out'; pending = null;
        request.controller.abort();
      }, 3500);
      try {
        const response = await fetchImpl(`/api/recordings/${request.runID}/depth/${request.descriptor.source_seq}`, {
          method: 'GET', cache: 'no-store', credentials: 'same-origin', redirect: 'error',
          headers: { Accept: 'application/json' }, signal: request.controller.signal,
        });
        const raster = parseDepthRaster(await readRasterJSON(response), request.descriptor, request.frame);
        if (!raster) throw new TypeError('Depth response metadata/pixels rejected');
        if (disposed || request.controller.signal.aborted || pending !== request || request.context !== contextKey ||
          request.mode === 'recorded' && request.key !== selectedKey) return;
        result = { raster, frame: request.frame, key: request.key };
      } catch (failure) {
        if (!disposed && pending === request && !request.controller.signal.aborted) error = failure.message;
      } finally {
        clearTimeout(timeout);
        if (pending === request) pending = null;
      }
    },
    snapshot() { return { raster: result?.raster ?? null, frame: result?.frame ?? null,
      key: result?.key ?? null, error, pending: pending !== null }; },
    dispose() { disposed = true; cancel(); result = null; },
  };
}
