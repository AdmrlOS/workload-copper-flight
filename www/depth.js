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

export function depthPresentation(view) {
  const frame = view.frame;
  if (!frame || !Object.hasOwn(frame, 'depth_preview')) return { kind: 'absent', preview: null, ageS: null };
  const preview = parseDepthPreview(frame.depth_preview, frame);
  if (!preview) return { kind: 'invalid', preview: null, ageS: null };
  const recorded = view.mode === 'recorded';
  const wall = !recorded && Number.isFinite(view.latestFrame?.wall_time_s) ? view.latestFrame.wall_time_s : frame.wall_time_s;
  const receiptAge = !recorded && Number.isFinite(view.frameAgeS) ? view.frameAgeS : 0;
  const ageS = Math.max(0, wall - preview.sample_wall_time_s) + receiptAge;
  return { kind: recorded ? 'recorded' : !view.live || ageS >= 2 ? 'stale' : 'live', preview, ageS };
}

export function depthPixels(value, frame) {
  const preview = parseDepthPreview(value, frame);
  if (!preview) return null;
  const pixels = new Uint8ClampedArray(32 * 24 * 4);
  for (let i = 0; i < 768; i++) {
    const q = Number.parseInt(preview.data.slice(i * 2, i * 2 + 2), 16);
    // Valid near = Admiral blue; far = paper. Invalid = ink, not zero metres.
    const t = (q - 1) / 254;
    const rgb = q === 0 ? [18, 20, 32] : [33 + 209 * t, 82 + 157 * t, 238 - 7 * t];
    pixels.set([...rgb, 255], i * 4);
  }
  return pixels;
}
