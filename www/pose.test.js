import test from 'node:test';
import assert from 'node:assert/strict';
const poses = await import('./pose.js').catch((error) => {
  if (error.code === 'ERR_MODULE_NOT_FOUND') return {};
  throw error;
});
const pose = (x = 0, rotation = { x: 0, y: 0, z: 0, w: 1 }) => ({ position: { x, y: 2, z: 3 }, rotation });

const snapshot = (overrides = {}) => ({
  health: { kind: 'live', frameAgeS: 0.1 }, error: null,
  observation: { firstSeenAt: 0, receivedAt: 100 },
  state: { status: 'live', engine: { native: true, revision: 'runtime-1' }, episode: { id: 'episode-1' },
    frame: { seq: 1, world: 'forest', position_m: pose().position, rotation: pose().rotation } },
  ...overrides,
});

test('connects the scene only to fresh confirmed native pose including actual orientation', () => {
  assert.equal(typeof poses.sourceConnection, 'function');
  assert.equal(typeof poses.poseFromFrame, 'function');
  assert.equal(poses.sourceConnection(snapshot()).live, true);
  for (const kind of ['connecting', 'starting', 'waiting', 'unknown', 'stale', 'error', 'failed', 'between_episodes', 'stopped']) {
    assert.equal(poses.sourceConnection(snapshot({ health: { kind } })).live, false);
  }
  for (const frame of [null, { position_m: pose().position }, { rotation: pose().rotation }, { position_m: { x: 0, y: NaN, z: 0 }, rotation: pose().rotation }]) {
    assert.equal(poses.poseFromFrame(frame), null);
  }
  assert.deepEqual(poses.poseFromFrame(snapshot().state.frame), pose());
  const noOrientation = snapshot();
  noOrientation.state.frame.rotation = null;
  assert.equal(poses.sourceConnection(noOrientation).live, false);
  assert.match(poses.sourceConnection(noOrientation).reason, /orientation/i);
  const urban = snapshot(); urban.state.frame.world = 'urban';
  assert.equal(poses.sourceConnection(urban).live, false);
  assert.match(poses.sourceConnection(urban).reason, /forest/i);
  const unconfirmed = snapshot(); unconfirmed.state.engine.native = null;
  assert.equal(poses.sourceConnection(unconfirmed).live, false);
});

test('buffers only observed pose samples, bounds traces, and never extrapolates', () => {
  assert.equal(typeof poses.ingestSample, 'function');
  assert.equal(typeof poses.samplePose, 'function');
  let history = poses.ingestSample(null, snapshot());
  assert.equal(history.samples.length, 1);
  assert.equal(poses.ingestSample(history, snapshot()), history, 'Repeated sequence is not a new sample');
  const next = snapshot(); next.state.frame.seq = 2; next.state.frame.position_m = pose(10).position; next.observation.receivedAt = 300;
  history = poses.ingestSample(history, next);
  assert.equal(poses.samplePose(history, 200).pose.position.x, 5);
  assert.equal(poses.samplePose(history, 200).interpolated, true);
  assert.equal(poses.samplePose(history, 9000).pose.position.x, 10);
  assert.equal(poses.samplePose(history, -100).pose.position.x, 0);
  assert.equal(poses.samplePose(history, 9000).interpolated, false);
  assert.equal(poses.samplePose(null, 0), null);
  const stale = snapshot({ health: { kind: 'stale', frameAgeS: 9 } });
  assert.equal(poses.ingestSample(history, stale), history);
  for (let seq = 3; seq < 400; seq += 1) {
    const sample = snapshot(); sample.state.frame.seq = seq; sample.observation.receivedAt = seq * 200;
    history = poses.ingestSample(history, sample);
  }
  assert.equal(history.samples.length, 24);
  assert.equal(history.trace.length, 256);
  const newEpisode = snapshot(); newEpisode.state.episode.id = 'episode-2';
  const reset = poses.ingestSample(history, newEpisode);
  assert.equal(reset.samples.length, 1);
  assert.equal(reset.trace.length, 1);
  const afterGap = snapshot(); afterGap.state.frame.seq = 400; afterGap.observation.receivedAt = 90000;
  assert.equal(poses.ingestSample(history, afterGap).samples.length, 1);
});

test('chase framing follows an observed position without changing the vehicle pose', () => {
  assert.equal(typeof poses.chaseView, 'function');
  const actual = pose(10);
  const before = structuredClone(actual);
  const view = poses.chaseView(actual);
  assert.ok(view.position.y >= 37, 'Camera clears the pinned forest canopy (maximum height below 29 m)');
  assert.ok(view.position.x > actual.position.x + 5);
  assert.ok(view.position.z > actual.position.z + 10);
  assert.deepEqual(view.target, actual.position, 'Frame the measured vehicle, not a point ahead of it');
  const high = pose(20); high.position.y = 80;
  assert.ok(poses.chaseView(high).position.y > high.position.y);
  assert.deepEqual(actual, before);
  assert.equal(poses.chaseView(null), null);
});

test('interpolates actual positions and unit quaternions, clamped to observed endpoints', () => {
  assert.equal(typeof poses.interpolatePose, 'function');
  const start = pose(0);
  const end = pose(10, { x: 0, y: 1, z: 0, w: 0 });
  const middle = poses.interpolatePose(start, end, 0.5);
  assert.deepEqual(middle.position, { x: 5, y: 2, z: 3 });
  assert.ok(Math.abs(middle.rotation.y - Math.SQRT1_2) < 1e-9);
  assert.ok(Math.abs(middle.rotation.w - Math.SQRT1_2) < 1e-9);
  assert.deepEqual(poses.interpolatePose(start, end, -20), start);
  assert.deepEqual(poses.interpolatePose(start, end, 20), end);
  assert.equal(poses.interpolatePose(null, end, 0.5), null);
  assert.equal(poses.interpolatePose(start, null, 0.5), null);
  assert.equal(poses.interpolatePose(start, end, NaN), null);
  const antipodal = poses.interpolatePose(start, pose(0, { x: 0, y: 0, z: 0, w: -1 }), 0.5);
  assert.ok(Math.abs(antipodal.rotation.w), 1);
});
