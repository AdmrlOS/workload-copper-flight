import test from 'node:test';
import assert from 'node:assert/strict';
const mission = await import('./mission.js').catch(error => { if (error.code === 'ERR_MODULE_NOT_FOUND') return {}; throw error; });
// Unit-only synthetic frames; never loaded or served by the viewer.
const id = '20261027T063423Z-aef6e125';
const frame = (seq, time, x = seq) => ({ schema_version: 1, seq, sim_time_s: time, world: 'forest', position_m: { x, y: 4, z: -20 }, rotation: { x: 0, y: 0, z: 0, w: 1 } });
const payload = () => ({ schema_version: 1, recording: { id, completed: true, started_at: '2026-10-27T06:34:23Z', ended_at: '2026-10-27T06:37:11Z' }, provenance: null, frames: [frame(1, 1), frame(2, 2)] });

test('playback clock advances in simulation seconds, clamps, seeks and pauses without resuming across modes', () => {
  assert.equal(typeof mission.createPlayback, 'function');
  const clock = mission.createPlayback(mission.parseRecording(payload(), id));
  assert.equal(clock.time(1000), 1);
  clock.play(1000); assert.equal(clock.time(1250), 1.25);
  clock.pause(1500); assert.equal(clock.time(9000), 1.5);
  clock.setRate(2, 9000); clock.play(9000); assert.equal(clock.time(9100), 1.7);
  clock.seek(1.2, 9100); assert.equal(clock.time(9200), 1.4);
  assert.equal(clock.time(99000), 2); assert.equal(clock.playing, false);
  clock.seek(-30, 0); assert.equal(clock.time(0), 1);
  assert.throws(() => clock.setRate(0, 0), /rate/i);
});

test('samples recording in simulation time while inspector remains actual observed source data', () => {
  assert.equal(typeof mission.sampleMission, 'function');
  const recording = mission.parseRecording(payload(), id);
  const sampled = mission.sampleMission(recording, 1.5);
  assert.equal(sampled.pose.position.x, 1.5);
  assert.equal(sampled.frame.seq, 1, 'Inspector does not invent an intermediate source frame');
  assert.equal(sampled.interpolated, true);
  assert.deepEqual(sampled.bracket, [1, 2]);
  assert.equal(mission.sampleMission(recording, -8).pose.position.x, 1);
  assert.equal(mission.sampleMission(recording, 99).pose.position.x, 2);
  assert.equal(mission.sampleMission(recording, 2).frame.seq, 2);
  assert.equal(mission.sampleMission(null, 0), null);
});

test('retains genuine startup frames without a pose and accepts nondecreasing simulation timestamps', () => {
  const input = payload();
  input.frames = [{ ...frame(0, 0), position_m: null, rotation: null }, frame(1, 0), frame(2, 1)];
  const parsed = mission.parseRecording(input, id);
  assert.equal(parsed.frames.length, 3);
  assert.equal(parsed.frames[0].position_m, null);
  assert.equal(mission.sampleMission(parsed, 0).frame.seq, 1, 'At equal timestamps use the last actual observation');
  const invalidPose = payload(); invalidPose.frames[0].rotation.w = 4;
  assert.equal(mission.parseRecording(invalidPose, id).frames[0].rotation, null, 'Unavailable attitude remains absent, never identity');
});

test('accepts only completed, ordered native telemetry and retains unavailable fields as null', () => {
  assert.equal(typeof mission.parseRecording, 'function');
  const parsed = mission.parseRecording(payload(), id);
  assert.equal(parsed.recording.id, id);
  assert.equal(parsed.frames.length, 2);
  assert.equal(parsed.frames[0].velocity_m_s, null);
  assert.equal(parsed.provenance, null);
  for (const change of [p => p.schema_version = 2, p => p.recording.completed = false, p => p.recording.id = '../bad', p => p.frames.reverse(), p => p.frames[1].sim_time_s = .5, p => p.frames[1].seq = 1, p => p.frames[1].world = 'urban', p => p.frames = []]) {
    const invalid = payload(); change(invalid);
    assert.throws(() => mission.parseRecording(invalid, id), /record|telemetry|frame/i);
  }
  assert.throws(() => mission.parseRecording(payload(), '20261027T063423Z-00000000'), /record/i);
});
