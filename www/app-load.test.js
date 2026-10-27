import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createSession } from './presentation.js';
import { recordingID } from './mission.js';

test('actual loadMission preserves selected playback rate when reopening a mission', async () => {
  const source = readFileSync(new URL('./app.js', import.meta.url), 'utf8');
  // Execute the actual controller function with DOM/network seams and a real session/clock.
  const controller = source.slice(source.indexOf('async function loadMission()'), source.indexOf('\nfunction updateMeasurements'));
  const session = createSession(null);
  const elements = new Map();
  const node = id => { if (!elements.has(id)) elements.set(id, { value: '', textContent: '' }); return elements.get(id); };
  node('mission-select').value = '20261027T065422Z-0479a668';
  node('playback-rate').value = '1';
  const mission = { recording: { id: node('mission-select').value }, frames: [{ sim_time_s: 0 }, { sim_time_s: 10 }] };
  const load = new Function('session', 'node', 'recordingID', 'fetchRecording', `
    let recordingGeneration = 0, recordingController, recordingError, disposed = false;
    let dataKey = '', chartKey = '', measurementKey = '';
    const fetchImpl = () => {}; const put = (id, text) => { node(id).textContent = text; };
    const showError = () => {};
    ${controller}
    return loadMission;
  `)(session, node, recordingID, async () => mission);
  await load();
  node('playback-rate').value = '2';
  session.clock.setRate(2, 0);
  await load();
  assert.equal(session.clock.rate, Number(node('playback-rate').value));
  assert.equal(session.clock.rate, 2);
  session.clock.play(1000);
  assert.equal(session.clock.time(1500), 1, 'real simulation-time clock advances at selected 2x');
});
