import test from 'node:test';
import assert from 'node:assert/strict';
const live = await import('./live.js').catch(error => { if (error.code === 'ERR_MODULE_NOT_FOUND') return {}; throw error; });
// Test-only generated frames. No demo/runtime fixture data.
const frame = (seq, time) => ({ schema_version: 1, seq, sim_time_s: time, world: 'forest', position_m: { x: time, y: 4, z: -20 }, rotation: { x: 0, y: 0, z: 0, w: 1 } });
const envelope = frames => ({ schema_version: 1, status: 'live', engine: { native: true }, episode: { id: 'test-episode' }, frames, frame_age_s: 0.1, reset: false, oldest_seq: frames[0]?.seq ?? 1, latest_seq: frames.at(-1)?.seq ?? 1, server_uptime_s: 10 });
test('buffers all distinct received samples with monotonic simulation-time playout and no extrapolation', () => {
  assert.equal(typeof live.createLiveBuffer, 'function');
  const buffer = live.createLiveBuffer();
  buffer.ingest(envelope([frame(1, 0), frame(2, .25)]), 0);
  const first = buffer.sample(0);
  assert.ok(first.pose.position.x >= 0 && first.pose.position.x <= .25);
  buffer.ingest(envelope([frame(3, .5), frame(4, .75)]), 1000);
  const a = buffer.sample(1000); const b = buffer.sample(1016);
  assert.ok(b.pose.position.x > a.pose.position.x, 'Each animation frame moves between real samples');
  assert.ok(b.pose.position.x < .75);
  assert.equal(buffer.metrics().simRate, .5, 'Actual simulation time / arrival wall time, not nominal 1x');
  assert.equal(buffer.metrics().sourceHz, 2, 'Distinct received sequences / observed wall interval');
  assert.equal(buffer.frames.length, 4);
  buffer.ingest(envelope([frame(4, .75)]), 1100);
  assert.equal(buffer.frames.length, 4);
  assert.equal(buffer.sample(12000).live, false, 'Repeated polls do not keep a stale source live');
  assert.ok(buffer.sample(12000).pose.position.x <= .75, 'No extrapolation');
  const reset = envelope([frame(1, 0)]); reset.episode.id = 'next-episode'; reset.reset = true;
  buffer.ingest(reset, 13000); assert.equal(buffer.frames.length, 1);
  assert.equal(buffer.sample(13000).pose.position.x, 0);
  buffer.ingest({ ...reset, engine: { native: false } }, 13001);
  assert.equal(buffer.sample(13001).live, false);
});

test('uses native wall timestamps for sample timing when reported, rather than inventing per-frame receipt times', () => {
  const buffer = live.createLiveBuffer();
  const first = { ...frame(1, 0), wall_time_s: 10 }; const last = { ...frame(2, .5), wall_time_s: 12 };
  buffer.ingest(envelope([first, last]), 5000);
  assert.equal(buffer.metrics().simRate, .25);
  assert.equal(buffer.metrics().sourceHz, .5);
  assert.equal(buffer.metrics().clock, 'native');
});

test('live batches preserve real startup frames and equal sim timestamps without fabricating poses', () => {
  const frames = [{ ...frame(0, 0), position_m: null, rotation: null }, frame(1, 0), frame(2, .25)];
  assert.equal(live.parseTelemetry(envelope(frames)).frames.length, 3);
});

test('incremental equal-time rows retain the later advancing row and advance the sequence cursor', () => {
  const buffer = live.createLiveBuffer();
  buffer.ingest(live.parseTelemetry(envelope([frame(0, 0)])), 0);
  buffer.ingest(live.parseTelemetry(envelope([frame(1, 0), frame(2, .1)])), 100);
  assert.deepEqual(buffer.frames.map(row => row.seq), [0, 1, 2]);
  assert.equal(buffer.sample(100).live, true);
});

test('separate equal-only batches advance sequence but never refresh simulation progress', () => {
  const buffer = live.createLiveBuffer();
  buffer.ingest(envelope([frame(0, 0)]), 0);
  buffer.ingest(envelope([frame(1, 0)]), 100);
  assert.equal(buffer.frames.at(-1).seq, 1);
  assert.equal(buffer.sample(100).live, false);
  buffer.ingest(envelope([frame(2, .1)]), 200);
  assert.equal(buffer.sample(200).live, true);
  for (let seq = 3; seq < 30; seq += 1) buffer.ingest(envelope([frame(seq, .1)]), seq * 100);
  assert.equal(buffer.frames.at(-1).seq, 29);
  assert.equal(buffer.sample(2900).live, false);
});

test('validates genuine frame batches without inventing missing pose or source freshness', () => {
  assert.equal(typeof live.parseTelemetry, 'function');
  const parsed = live.parseTelemetry(envelope([frame(1, 1), frame(2, 2)]));
  assert.equal(parsed.frames.length, 2);
  assert.equal(parsed.frames[0].velocity_m_s, null);
  assert.throws(() => live.parseTelemetry({ schema_version: 9 }), /telemetry/i);
  assert.throws(() => live.parseTelemetry(envelope([frame(2, 2), frame(1, 1)])), /order/i);
});
