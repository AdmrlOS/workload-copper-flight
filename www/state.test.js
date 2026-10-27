import test from 'node:test';
import assert from 'node:assert/strict';

// Importing a not-yet-implemented module keeps the first RED an assertion.
const model = await import('./state.js').catch((error) => {
  if (error.code === 'ERR_MODULE_NOT_FOUND') return {};
  throw error;
});

const envelope = (overrides = {}) => ({
  status: 'live', error: null,
  engine: { native: true, copper_version: '1.4.0-dev', source_revision: 'source-abc', revision: 'runtime-def' },
  configuration: { world: 'forest', inference: 'cuda', autonomy: true, episode_seconds: 45 },
  episode: { id: 'episode-1', started_at: '2026-10-27T01:00:00Z' },
  frame_age_s: 0.1, frame: null, recordings: [], uptime_s: 23,
  ...overrides,
});

test('rejects malformed envelopes instead of treating successful HTTP as valid state', () => {
  for (const input of [null, [], 'live', {}, { status: 'running' }, { status: 1 }]) {
    assert.throws(() => model.parseState(input), /Invalid runtime state/);
  }
  for (const status of ['starting', 'live', 'between_episodes', 'failed', 'stopped']) {
    assert.equal(model.parseState({ status }).status, status);
  }
});

const nativeFrame = (overrides = {}) => ({
  schema_version: 1, seq: 10, sim_time_s: 4.2,
  position_m: { x: 1, y: -2, z: 3 }, velocity_m_s: { x: 0.5, y: 0, z: -0.1 },
  rotation: { x: 0, y: 0, z: 0, w: 1 },
  armed: false, auto_enabled: true, mode: 'AUTO', world: 'forest',
  policy_prediction_m_s: { x: 1.2, y: -0.4, z: 0 }, policy_observation_seq: null, inference_backend: 'cpu', inference_count: 17,
  graphics: { backend: 'Vulkan', adapter_name: 'Observed adapter' }, ...overrides,
});

test('preserves a reported native wall timestamp without assigning receipt times to source frames', () => {
  assert.equal(model.parseFrame(nativeFrame({ wall_time_s: 5.25 })).wall_time_s, 5.25);
  assert.equal(Object.hasOwn(model.parseFrame(nativeFrame()), 'wall_time_s'), false);
  assert.equal(model.parseFrame(nativeFrame({ wall_time_s: -1 })).wall_time_s, null);
});

test('reads actual Copper whole-iteration timing and distinguishes telemetry-only from full capture', () => {
  const copper = { recording_mode: 'telemetry-only', full_recording: false, mcu_iteration_wall_us: 1634, compute_iteration_wall_us: 4200, export_wall_s: 8.4 };
  const parsed = model.parseFrame(nativeFrame({ copper })).copper;
  for (const key of Object.keys(copper)) assert.equal(parsed[key], copper[key]);
  const invalid = model.parseFrame(nativeFrame({ copper: { recording_mode: 'replay', full_recording: 'true', mcu_iteration_wall_us: -1, compute_iteration_wall_us: 1.5, export_wall_s: -1 } })).copper;
  assert.equal(invalid.recording_mode, null); assert.equal(invalid.full_recording, null);
  assert.equal(invalid.mcu_iteration_wall_us, null); assert.equal(invalid.compute_iteration_wall_us, null); assert.equal(invalid.export_wall_s, null);
});

test('optional Copper measurements preserve only genuine finite fields; absence adds no fake task metrics', () => {
  const copper = { control_loop_ms: .54, tasks: [{ name: 'policy', duration_ms: .23 }, { name: 'invalid', duration_ms: -3 }], depth: { min_m: .3, max_m: 14, valid_pixels: 300, width: 32, height: 24 }, sensor: { name: 'depth', sequence: 17, timestamp_s: 4.2 } };
  const parsed = model.parseFrame(nativeFrame({ copper })).copper;
  assert.equal(parsed?.control_loop_ms, .54);
  assert.deepEqual(parsed.tasks, [{ name: 'policy', duration_ms: .23 }]);
  assert.deepEqual(parsed.depth, copper.depth);
  assert.deepEqual(parsed.sensor, copper.sensor);
  assert.equal(Object.hasOwn(model.parseFrame(nativeFrame()), 'copper'), false);
  const invalid = model.parseFrame(nativeFrame({ copper: { control_loop_ms: NaN, tasks: [{ name: 'policy', duration_ms: '12' }], depth: { min_m: -1 } } })).copper;
  assert.equal(invalid.control_loop_ms, null);
  assert.deepEqual(invalid.tasks, []);
  assert.equal(invalid.depth, null);
});

test('normalizes versioned native frames without coercing or fabricating values', () => {
  const read = (frame) => model.parseState(envelope({ frame })).frame;
  assert.deepEqual(read(nativeFrame()), nativeFrame());
  for (const frame of [null, {}, nativeFrame({ schema_version: 2 }), nativeFrame({ seq: -1 }), nativeFrame({ seq: 1.5 })]) {
    assert.equal(read(frame), null);
  }
  const frame = read(nativeFrame({
    sim_time_s: NaN, armed: 'false', auto_enabled: 1,
    position_m: { x: 0, y: 1, z: Infinity }, velocity_m_s: { x: '0', y: 1, z: 2 },
    policy_prediction_m_s: null, inference_backend: 'CUDA', inference_count: '17', graphics: null,
  }));
  assert.equal(frame.sim_time_s, null);
  assert.equal(frame.armed, null);
  assert.equal(frame.auto_enabled, null);
  assert.equal(frame.position_m, null);
  assert.equal(frame.velocity_m_s, null);
  assert.equal(frame.policy_prediction_m_s, null);
  assert.equal(frame.inference_backend, null);
  assert.equal(frame.inference_count, null);
  assert.deepEqual(frame.graphics, { backend: null, adapter_name: null });
  const state = model.parseState(envelope({ frame_age_s: -1, uptime_s: '3', configuration: { autonomy: 'true' } }));
  assert.equal(state.frame_age_s, null);
  assert.equal(state.uptime_s, null);
  assert.equal(state.configuration.autonomy, null);
});

test('allows completed recording downloads only for exact safe same-origin ID paths', () => {
  assert.equal(typeof model.safeDownloadURL, 'function');
  const recording = { id: '20261027T010000Z-deadbeef', completed: true, download_url: '/api/recordings/20261027T010000Z-deadbeef/download' };
  assert.equal(model.safeDownloadURL(recording), recording.download_url);
  for (const change of [
    { completed: false }, { completed: 'true' }, { id: '../escape' }, { id: 'abc%2fdef' },
    { id: 'id.with.dot' }, { id: '<script>' }, { id: ' trailing ' },
    { download_url: 'https://example.com/api/recordings/20261027T010000Z-deadbeef/download' },
    { download_url: '//example.com/a' }, { download_url: 'javascript:alert(1)' },
    { download_url: '/api/recordings/other/download' },
    { download_url: '/api/recordings/20261027T010000Z-deadbeef/download?redirect=elsewhere' },
  ]) assert.equal(model.safeDownloadURL({ ...recording, ...change }), null);
  assert.equal(model.safeDownloadURL(null), null);
  const state = model.parseState(envelope({ recordings: [{ ...recording, size_bytes: 0, started_at: 'start', ended_at: null }, null] }));
  assert.equal(state.recordings.length, 1);
  assert.deepEqual(state.recordings[0], { ...recording, size_bytes: 0, started_at: 'start', ended_at: null });
});

test('requires observed sequence progress and ages frozen successful responses into stale', () => {
  assert.equal(typeof model.observeProgress, 'function');
  assert.equal(typeof model.resolveHealth, 'function');
  const state = model.parseState(envelope({ frame: nativeFrame() }));
  let observation = model.observeProgress(null, state, 0);
  assert.equal(model.resolveHealth(state, observation, 0).kind, 'waiting');
  observation = model.observeProgress(observation, state, 500);
  assert.equal(model.resolveHealth(state, observation, 500).kind, 'waiting');
  const advancing = model.parseState(envelope({ frame: nativeFrame({ seq: 11, sim_time_s: 4.7 }) }));
  observation = model.observeProgress(observation, advancing, 1000);
  assert.equal(model.resolveHealth(advancing, observation, 1000).kind, 'live');
  observation = model.observeProgress(observation, advancing, 3000);
  assert.equal(model.resolveHealth(advancing, observation, 3000).kind, 'stale');
  assert.equal(model.resolveHealth(advancing, observation, 3000).progressAgeS, 2);
});

test('resets progress evidence across episode changes, native restarts and sequence regressions', () => {
  const initial = model.parseState(envelope({ frame: nativeFrame() }));
  let observation = model.observeProgress(null, initial, 0);
  const advancing = model.parseState(envelope({ frame: nativeFrame({ seq: 11, sim_time_s: 5 }) }));
  observation = model.observeProgress(observation, advancing, 500);
  for (const change of [
    { episode: { id: 'episode-2', started_at: 'new-start' } },
    { episode: { id: 'episode-1', started_at: 'new-start' } },
    { engine: { ...advancing.engine, revision: 'new-runtime' } },
    { frame: nativeFrame({ seq: 1 }) },
    { frame: nativeFrame({ seq: 12, sim_time_s: 0 }) },
    { uptime_s: 0 },
  ]) {
    const resetState = model.parseState(envelope({ ...advancing, ...change }));
    const reset = model.observeProgress(observation, resetState, 1000);
    assert.equal(model.resolveHealth(resetState, reset, 1000).kind, 'waiting');
    assert.equal(reset.lastProgressAt, null);
  }
  assert.equal(model.observeProgress(observation, model.parseState(envelope()), 1000), null);
});

test('honors lifecycle, transport errors and backend frame age before any live claim', () => {
  assert.equal(model.resolveHealth(null, null, 0).kind, 'connecting');
  assert.equal(model.resolveHealth(null, null, 0, 'HTTP 503').kind, 'error');
  for (const status of ['starting', 'between_episodes', 'failed', 'stopped']) {
    const state = model.parseState(envelope({ status, frame: nativeFrame() }));
    const observation = model.observeProgress(null, state, 0);
    assert.equal(model.resolveHealth(state, observation, 3000).kind, status);
  }
  const state = model.parseState(envelope({ frame: nativeFrame() }));
  const first = model.observeProgress(null, state, 0);
  const next = model.parseState(envelope({ frame: nativeFrame({ seq: 11 }), frame_age_s: 1.9 }));
  const observation = model.observeProgress(first, next, 500);
  assert.equal(model.resolveHealth(next, observation, 500, 'Network unavailable').kind, 'error');
  assert.equal(model.resolveHealth(next, observation, 700).kind, 'stale');
  assert.ok(Math.abs(model.resolveHealth(next, observation, 700).frameAgeS - 2.1) < 0.00001);
  const unknownAge = model.parseState(envelope({ frame: nativeFrame({ seq: 11 }), frame_age_s: null }));
  assert.equal(model.resolveHealth(unknownAge, observation, 700).kind, 'unknown');
  assert.equal(model.resolveHealth(model.parseState(envelope()), null, 700).kind, 'waiting');
  assert.equal(model.resolveHealth(model.parseState(envelope({ error: 'Native failure' })), null, 700).kind, 'failed');
});

test('never promotes requested CUDA into observed policy evidence or invents an exact count', () => {
  const read = (frame, kind = 'live', policyAgeS = 0) => model.inferenceEvidence(model.parseState(envelope({ frame })), { kind, policyAgeS });
  assert.deepEqual(read(null), { requested: 'cuda', backend: null, count: null, confirmed: false, mismatch: false });
  assert.equal(read(nativeFrame()).confirmed, false, 'Exact count alone does not prove advancing policy publication');
  const cpu = nativeFrame({ policy_observation_seq: 42 });
  assert.deepEqual(read(cpu), { requested: 'cuda', backend: 'cpu', count: 17, confirmed: true, mismatch: true });
  const cuda = nativeFrame({ inference_backend: 'cuda', policy_observation_seq: 42 });
  assert.equal(read(cuda).confirmed, true);
  assert.equal(read(cuda).mismatch, false);
  for (const count of [null, 0, -1, '17']) assert.equal(read({ ...cuda, inference_count: count }).confirmed, true, 'Policy publication progress is separate from exact inference count');
  for (const kind of ['stale', 'waiting', 'unknown', 'error', 'failed']) assert.equal(read(cuda, kind).confirmed, false);
  for (const age of [null, 2, 20, undefined]) assert.equal(read(cuda, 'live', age === undefined ? null : age).confirmed, false);
  assert.equal(read({ ...cuda, inference_backend: null }).confirmed, false);
  assert.equal(read({ ...cuda, policy_prediction_m_s: null }).confirmed, false);
  assert.equal(read({ ...cuda, policy_observation_seq: null }).confirmed, false);
  assert.equal(model.inferenceEvidence(null, { kind: 'connecting' }).requested, null);
});

test('confirms observed policy only while native frames and policy publication sequence both advance', () => {
  const initial = model.parseState(envelope({ frame: nativeFrame({ policy_observation_seq: 575, inference_count: null }) }));
  let observation = model.observeProgress(null, initial, 0);
  const next = model.parseState(envelope({ frame: nativeFrame({ seq: 11, sim_time_s: 4.7, policy_observation_seq: 580, inference_count: null }) }));
  observation = model.observeProgress(observation, next, 500);
  let health = model.resolveHealth(next, observation, 500);
  assert.equal(health.kind, 'live');
  assert.equal(model.inferenceEvidence(next, health).confirmed, true);
  assert.equal(model.inferenceEvidence(next, health).count, null);
  const frozenPolicy = model.parseState(envelope({ frame: nativeFrame({ seq: 12, sim_time_s: 7, policy_observation_seq: 580, inference_count: null }) }));
  observation = model.observeProgress(observation, frozenPolicy, 3000);
  health = model.resolveHealth(frozenPolicy, observation, 3000);
  assert.equal(health.kind, 'live');
  assert.equal(model.inferenceEvidence(frozenPolicy, health).confirmed, false);
  const resetPolicy = model.parseState(envelope({ frame: nativeFrame({ seq: 13, sim_time_s: 8, policy_observation_seq: 0, inference_count: null }) }));
  observation = model.observeProgress(observation, resetPolicy, 3200);
  assert.equal(model.inferenceEvidence(resetPolicy, model.resolveHealth(resetPolicy, observation, 3200)).confirmed, false);
});

test('distinguishes an unavailable recording index from a confirmed empty index', () => {
  assert.equal(model.parseState({ status: 'starting' }).recordings_known, false);
  assert.equal(model.parseState(envelope()).recordings_known, true);
  assert.equal(model.parseState(envelope({ recordings: null })).recordings_known, false);
  assert.equal(model.parseState(envelope({ recordings: [] })).recordings.length, 0);
});

test('keeps absent or invalid native rotation unknown instead of inventing an identity quaternion', () => {
  const read = (rotation) => model.parseState(envelope({ frame: nativeFrame({ rotation }) })).frame.rotation;
  for (const rotation of [undefined, null, {}, { x: 0, y: 0, z: 0, w: 0 }, { x: 0, y: '0', z: 0, w: 1 }, { x: Infinity, y: 0, z: 0, w: 1 }]) assert.equal(read(rotation), null);
  assert.deepEqual(read({ x: 0, y: 0, z: 0, w: 1 }), { x: 0, y: 0, z: 0, w: 1 });
});

test('validates the actual runtime recording ID format without repairing source identifiers', () => {
  for (const id of ['flight_123-abc', '20261027T010000Z-DEADBEEF', '2026-10-27T010000Z-deadbeef', '20261027T010000Z-deadbeef ', '20261027T010000Z-deadbee']) {
    assert.equal(model.safeDownloadURL({ id, completed: true, download_url: `/api/recordings/${id}/download` }), null);
    const state = model.parseState(envelope({ recordings: [{ id, completed: true }] }));
    assert.equal(state.recordings[0].id, id, 'Do not trim, lowercase, or repair the source identifier');
  }
});

test('marks malformed recording entries as a partial index rather than a confirmed empty recording set', () => {
  const state = model.parseState(envelope({ recordings: [null, {}, { id: '   ' }] }));
  assert.equal(state.recordings_partial, true);
  assert.equal(state.recordings.length, 0);
  assert.equal(model.parseState(envelope()).recordings_partial, false);
});

test('preserves policy observation sequence without substituting it for inference count', () => {
  const state = model.parseState(envelope({ frame: nativeFrame({ policy_observation_seq: 575, inference_count: null }) }));
  assert.equal(state.frame.policy_observation_seq, 575);
  assert.equal(state.frame.inference_count, null);
  for (const value of [undefined, '575', -1, 1.5]) {
    assert.equal(model.parseState(envelope({ frame: nativeFrame({ policy_observation_seq: value }) })).frame.policy_observation_seq, null);
  }
});

// Synthetic values are confined to tests; the production UI has no fixtures.
test('parses the runtime envelope without inventing missing observations', () => {
  assert.equal(typeof model.parseState, 'function', 'parseState must be implemented');
  const state = model.parseState(envelope());
  assert.equal(state.status, 'live');
  assert.equal(state.engine.source_revision, 'source-abc');
  assert.equal(state.engine.revision, 'runtime-def');
  assert.equal(state.configuration.inference, 'cuda');
  assert.equal(state.frame, null);
  const minimal = model.parseState({ status: 'starting' });
  assert.equal(minimal.engine.native, null);
  assert.equal(minimal.engine.copper_version, null);
  assert.equal(minimal.configuration.inference, null);
  assert.equal(minimal.uptime_s, null);
  assert.equal(minimal.frame_age_s, null);
});
