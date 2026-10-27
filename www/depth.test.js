import test from 'node:test';
import assert from 'node:assert/strict';
import { parseFrame } from './state.js';
import * as depth from './depth.js';
import { readFileSync } from 'node:fs';
import { parseRecording, sampleMission } from './mission.js';
import { parseTelemetry } from './live.js';

// Synthetic unit inputs only; real native execution is checked separately.
export const previewFixture = () => ({
  source: 'SimZedFrameStore.depth/Copper.ZedSource', source_seq: 7,
  source_width: 320, source_height: 240, sample_wall_time_s: 2, sample_sim_time_s: 1,
  width: 32, height: 24, encoding: 'u8-hex', sampling: 'nearest-cell-center',
  source_units: 'millimetres', range_m: [0.001, 20], invalid_u8: 0,
  invalid_rule: 'source_mm == 0 or source_mm > 20000',
  decode_m: '(1 + (q - 1) * 19999 / 254) / 1000; q=0 invalid',
  data: '000eff'.repeat(256),
});

test('preserves a measured depth preview and its original sampling metadata', () => {
  const preview = previewFixture();
  const frame = parseFrame({ schema_version: 1, seq: 20, sim_time_s: 2, wall_time_s: 3, depth_preview: preview });
  assert.deepEqual(frame.depth_preview, preview);
  assert.equal(parseFrame({ schema_version: 1, seq: 0 }).depth_preview, undefined);
});

test('depth presentation distinguishes absence, rejection, stale live and recorded sample age', () => {
  assert.equal(typeof depth.depthPresentation, 'function', 'Depth presentation has not been implemented');
  const frame = { schema_version: 1, seq: 20, sim_time_s: 2, wall_time_s: 3, depth_preview: previewFixture() };
  assert.equal(depth.depthPresentation({ frame: {}, mode: 'live', live: false }).kind, 'absent');
  assert.equal(depth.depthPresentation({ frame: { depth_preview: null }, mode: 'live' }).kind, 'invalid');
  const recorded = depth.depthPresentation({ frame, mode: 'recorded' });
  assert.equal(recorded.kind, 'recorded'); assert.equal(recorded.ageS, 1);
  assert.equal(depth.depthPresentation({ frame, mode: 'live', live: true, frameAgeS: .2 }).kind, 'live');
  const stale = depth.depthPresentation({ frame, mode: 'live', live: false, frameAgeS: 3 });
  assert.equal(stale.kind, 'stale'); assert.equal(stale.ageS, 4);
  assert.equal(depth.depthPresentation({ frame, mode: 'live', live: true, frameAgeS: 0, latestFrame: { wall_time_s: 8 } }).ageS, 6);
});

test('bounded image decoding uses exact source pixels, invalid ink and physical range', () => {
  assert.equal(typeof depth.depthPixels, 'function', 'Safe pixel decoder has not been implemented');
  const pixels = depth.depthPixels(previewFixture(), { wall_time_s: 3, sim_time_s: 2 });
  assert.equal(pixels.length, 32 * 24 * 4);
  assert.deepEqual([...pixels.slice(0, 4)], [18, 20, 32, 255]);
  assert.notDeepEqual([...pixels.slice(4, 8)], [...pixels.slice(8, 12)]);
  assert.equal(depth.depthPixels({ ...previewFixture(), width: 1000000 }, { wall_time_s: 3, sim_time_s: 2 }), null);
});

test('rejects malformed, oversize and malicious native previews without trusting extra fields', () => {
  const base = { schema_version: 1, seq: 20, sim_time_s: 2, wall_time_s: 3 };
  for (const changes of [{ width: 1e9 }, { height: true }, { source_seq: 2 ** 53 }, { data: 'aa'.repeat(100000) },
    { data: '<script>'.repeat(192) }, { data: '00'.repeat(768) }, { data: 'FF'.repeat(768) },
    { sample_wall_time_s: Infinity }, { sample_sim_time_s: 3 }, { range_m: [0, 100] }, { invalid_rule: '<img>' }]) {
    assert.equal(parseFrame({ ...base, depth_preview: { ...previewFixture(), ...changes } }).depth_preview, null);
  }
  const parsed = parseFrame({ ...base, depth_preview: { ...previewFixture(), acquisition_timestamp: '<script>' } });
  assert.equal(Object.hasOwn(parsed.depth_preview, 'acquisition_timestamp'), false);
});

test('saved native/software trace survives live and recorded normalization without interpolating depth', () => {
  const frames = readFileSync(new URL('../tests/fixtures/native-depth-observations.jsonl', import.meta.url), 'utf8').trim().split('\n').map(JSON.parse);
  const id = '20261027T000000Z-1234abcd';
  const mission = parseRecording({ schema_version: 1, recording: { id, completed: true }, frames }, id);
  const live = parseTelemetry({ schema_version: 1, status: 'stopped', frames });
  assert.deepEqual(live.frames.map(f => f.depth_preview), mission.frames.map(f => f.depth_preview));
  assert.equal(mission.frames[0].depth_preview, undefined);
  const index = frames.findIndex(f => f.depth_preview && f.rotation);
  const t = (frames[index].sim_time_s + frames[index + 1].sim_time_s) / 2;
  const view = sampleMission(mission, t);
  assert.deepEqual(view.frame.depth_preview, frames[index].depth_preview);
  assert.equal(view.frame.inference_count, null);
  for (let i = 0; i < 10000; i++) {
    const frame = mission.frames[i % mission.frames.length];
    if (frame.depth_preview) assert.equal(depth.depthPixels(frame.depth_preview, frame).length, 3072);
  }
});
