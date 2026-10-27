import test from 'node:test';
import assert from 'node:assert/strict';
const presentation = await import('./presentation.js').catch(error => { if (error.code === 'ERR_MODULE_NOT_FOUND') return {}; throw error; });

test('source switching never presents a recording as live and pauses recorded time outside its mode', async () => {
  assert.equal(typeof presentation.createSession, 'function');
  const { createLiveBuffer } = await import('./live.js');
  const live = createLiveBuffer(); const session = presentation.createSession(live);
  assert.equal(session.mode, 'live');
  const f = t => ({ schema_version: 1, seq: t + 1, sim_time_s: t, world: 'forest', position_m: { x: t, y: 2, z: 0 }, rotation: { x: 0, y: 0, z: 0, w: 1 } });
  session.load({ recording: { id: 'test' }, provenance: null, frames: [f(0), f(1)] });
  assert.equal(session.view(1000).mode, 'live'); assert.equal(session.view(1000).frame, null);
  session.setMode('recorded', 1000); session.clock.play(1000);
  assert.equal(session.view(1200).timeS, .2);
  session.setMode('live', 1200); assert.equal(session.clock.playing, false);
  session.setMode('recorded', 9000); assert.equal(session.view(9000).timeS, .2);
  assert.equal(session.view(9000).mode, 'recorded');
});

test('makes telemetry-only full capture OFF explicit without manufacturing replay evidence', () => {
  assert.equal(typeof presentation.captureEvidence, 'function');
  assert.equal(presentation.captureEvidence(null), null);
  assert.match(presentation.captureEvidence({ recording_mode: 'telemetry-only', full_recording: false }).text, /FULL CAPTURE OFF/);
  assert.equal(presentation.captureEvidence({ recording_mode: 'telemetry-only', full_recording: false }).full, false);
  assert.match(presentation.captureEvidence({ recording_mode: 'full', full_recording: true }).detail, /unverified/);
  assert.equal(presentation.captureEvidence({ recording_mode: 'full', full_recording: false }).full, false);
});

test('keeps recorded evidence distinct from live computation and labels unknown policy fields', () => {
  assert.equal(typeof presentation.evidenceLabel, 'function');
  const frame = { seq: 9, inference_backend: 'cuda', policy_observation_seq: 300, policy_prediction_m_s: { x: 1, y: 2, z: 3 }, inference_count: null };
  assert.match(presentation.evidenceLabel('recorded', frame, true), /recorded/i);
  assert.doesNotMatch(presentation.evidenceLabel('recorded', frame, true), /live|confirmed/i);
  assert.match(presentation.evidenceLabel('live', frame, false), /reported/i);
  assert.match(presentation.evidenceLabel('live', frame, true), /advancing/i);
  assert.match(presentation.evidenceLabel('live', {}, true), /unavailable/i);
});

test('chart paths use only finite observed values and break over unknowns without filling zero', () => {
  assert.equal(typeof presentation.chartPath, 'function');
  const frames = [{ sim_time_s: 0, velocity_m_s: { x: 0 } }, { sim_time_s: 1, velocity_m_s: { x: 2 } }, { sim_time_s: 2 }, { sim_time_s: 3, velocity_m_s: { x: -2 } }];
  const path = presentation.chartPath(frames, f => f.velocity_m_s?.x, { start: 0, end: 3, min: -2, max: 2, width: 300, height: 100 });
  assert.equal(path, 'M0,50L100,0M300,100');
  assert.equal(presentation.chartPath([], f => f.x, {}), '');
});

test('partner surface exposes source modes and no status-card dashboard or inline script', async () => {
  const { readFileSync } = await import('node:fs');
  const html = readFileSync(new URL('./index.html', import.meta.url), 'utf8');
  for (const id of ['mode-live', 'mode-recorded', 'mission-select', 'play-pause', 'timeline', 'copper-inspector', 'vehicle-cue']) assert.ok(html.includes(`id="${id}"`), `Missing interaction ${id}`);
  assert.match(html, /Recorded native mission visualization/);
  assert.match(html, /not.*native replay/i);
  assert.equal(html.includes('class="sidebar"'), false);
});
