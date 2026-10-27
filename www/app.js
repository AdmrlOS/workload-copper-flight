import { createMonitor } from './monitor.js';
import { fetchTelemetry, fetchRecording } from './transport.js';
import { safeDownloadURL } from './state.js';
import { recordingID } from './mission.js';
import { createLiveBuffer } from './live.js';
import { createSession, evidenceLabel, chartPath, captureEvidence } from './presentation.js';
import { depthPresentation, depthPixels } from './depth.js';
import { number } from './format.js';

const node = id => document.getElementById(id);
const put = (id, value) => { const target = node(id); const text = String(value ?? 'Unavailable'); if (target.textContent !== text) target.textContent = text; };
const monitor = createMonitor();
const buffer = createLiveBuffer();
const session = createSession(buffer);
const fetchImpl = globalThis.fetch.bind(globalThis);
let sourceRoute = '/api/telemetry';
let legacyUntil = 0;
let feedPending = false;
let disposed = false;
let feedController;
let recordingController;
let recordingGeneration = 0;
let recordingError = null;
let feedError = null;
let recordingIndexKey = '';
let dataKey = '';
let chartKey = '';
let measurementKey = '';
let axis = 'z';
let viewer;
let frameRequest;
let lastRenderAt = -Infinity;

function showError(text) {
  node('error-detail').hidden = !text;
  put('error-detail', text ?? '');
}

function updateIndex(state) {
  const recordings = (state?.recordings ?? []).filter(r => r.completed === true && recordingID(r.id));
  const key = JSON.stringify(recordings.map(r => r.id));
  if (key === recordingIndexKey) return;
  recordingIndexKey = key;
  const select = node('mission-select');
  const selected = select.value;
  select.replaceChildren();
  if (!recordings.length) {
    const option = document.createElement('option'); option.value = ''; option.textContent = 'No completed missions reported'; select.append(option);
  }
  for (const recording of recordings) {
    const option = document.createElement('option'); option.value = recording.id; option.textContent = `${recording.id} · completed`; select.append(option);
  }
  if (recordings.some(r => r.id === selected)) select.value = selected;
  node('load-mission').disabled = !select.value;
}

async function pollState() {
  const snapshot = await monitor.poll();
  if (disposed) return;
  updateIndex(snapshot.state);
  if (performance.now() < legacyUntil) {
    sourceRoute = '/api/state';
    if (snapshot.error || !snapshot.state) { buffer.fail(); feedError = snapshot.error; return; }
    const state = snapshot.state;
    buffer.ingest({ ...state, frames: state.frame ? [state.frame] : [], reset: false }, snapshot.observation?.receivedAt ?? performance.now());
    feedError = null;
  }
}

async function pollFeed() {
  if (feedPending || disposed || performance.now() < legacyUntil) return;
  feedPending = true;
  feedController = new AbortController();
  const timeout = setTimeout(() => feedController.abort(), 3500);
  try {
    const latest = buffer.frames.at(-1);
    const envelope = await fetchTelemetry(fetchImpl, { afterSeq: sourceRoute === '/api/telemetry' ? latest?.seq ?? null : null, episodeID: sourceRoute === '/api/telemetry' ? buffer.source?.episode?.id ?? null : null, signal: feedController.signal });
    if (disposed) return;
    sourceRoute = '/api/telemetry';
    buffer.ingest(envelope, performance.now()); feedError = null;
  } catch (failure) {
    if (disposed) return;
    if ([404, 405, 501].includes(failure.status)) { legacyUntil = performance.now() + 15000; void pollState(); }
    else { buffer.fail(); feedError = failure.name === 'AbortError' ? 'Native telemetry request timed out' : failure.message; }
  } finally { clearTimeout(timeout); feedPending = false; }
}

function setMode(mode) {
  session.setMode(mode, performance.now());
  dataKey = ''; chartKey = ''; measurementKey = '';
  node('mode-live').setAttribute('aria-pressed', String(mode === 'live'));
  node('mode-recorded').setAttribute('aria-pressed', String(mode === 'recorded'));
  node('mission-picker').hidden = mode !== 'recorded';
  node('recorded-disclaimer').hidden = mode !== 'recorded';
  node('live-disclaimer').hidden = mode !== 'live';
  node('transport-source').hidden = mode !== 'live';
  put('mode-title', mode === 'live' ? 'Live native telemetry' : 'Recorded native mission visualization');
  put('presentation-note', mode === 'live' ? 'Buffered observed poses. No extrapolation. Scene motion is not proof of realtime native computation.' : 'Simulation-time interpolation of recorded native telemetry. Not verified Copper native replay or live computation.');
  showError(mode === 'recorded' ? recordingError : feedError);
  render(performance.now());
  if (mode === 'recorded' && !session.mission && node('mission-select').value) void loadMission();
}

async function loadMission() {
  const id = node('mission-select').value;
  if (!recordingID(id)) return;
  const generation = ++recordingGeneration;
  recordingController?.abort(); recordingController = new AbortController();
  const timeout = setTimeout(() => recordingController.abort(), 30000);
  node('load-mission').disabled = true; put('load-mission', 'Loading…'); recordingError = null;
  put('source-subtitle', 'Reading completed native telemetry · no generated frames');
  try {
    const mission = await fetchRecording(fetchImpl, id, recordingController.signal);
    if (disposed || generation !== recordingGeneration) return;
    session.load(mission); session.clock.setRate(Number(node('playback-rate').value), performance.now()); dataKey = ''; chartKey = ''; measurementKey = '';
    // Loading a mission never changes the selected source or claims live compute.
    if (session.mode === 'recorded') showError(null);
  } catch (failure) {
    if (disposed || generation !== recordingGeneration) return;
    recordingError = failure.name === 'AbortError' ? 'Recorded telemetry request timed out' : `Recorded telemetry unavailable: ${failure.message}`;
    if (session.mode === 'recorded') showError(recordingError);
  } finally {
    clearTimeout(timeout);
    if (generation === recordingGeneration && !disposed) { node('load-mission').disabled = !node('mission-select').value; put('load-mission', 'Open mission ↗'); }
  }
}

function updateMeasurements(copper) {
  const key = JSON.stringify(copper ?? null);
  if (key === measurementKey) return; measurementKey = key;
  const rows = [];
  for (const [field, label] of [['mcu_iteration_wall_us', 'MCU whole iteration'], ['compute_iteration_wall_us', 'Compute whole iteration']]) {
    if (Number.isFinite(copper?.[field])) rows.push([label, `${number(copper[field] / 1000, 3)} ms`]);
  }
  if (copper?.control_loop_ms !== null && copper?.control_loop_ms !== undefined) rows.push(['Control loop', `${number(copper.control_loop_ms, 3)} ms`]);
  for (const task of copper?.tasks ?? []) rows.push([`Task / ${task.name}`, `${number(task.duration_ms, 3)} ms`]);
  if (copper?.depth) { const d = copper.depth; rows.push(['Depth range', `${number(d.min_m)}–${number(d.max_m)} m`], ['Depth valid pixels', `${d.valid_pixels} / ${d.width * d.height}`]); }
  if (copper?.sensor) { const s = copper.sensor; rows.push([`Sensor / ${s.name}`, `seq ${s.sequence} · ${number(s.timestamp_s, 3)} s`]); }
  node('native-measurements').hidden = !rows.length;
  node('unsupported-note').hidden = Boolean(copper?.depth && copper?.sensor && (copper?.tasks?.length || copper?.control_loop_ms !== null && copper?.control_loop_ms !== undefined));
  const absent = [];
  if (!copper?.depth && !copper?.sensor) absent.push('Sensor/depth');
  if (!copper?.tasks?.length && (copper?.control_loop_ms === null || copper?.control_loop_ms === undefined)) absent.push('Task/control-loop timing');
  put('unsupported-note', absent.length ? `${absent.join(' and ')} not reported by this source.` : 'Additional native measurements are shown only when reported.');
  const list = node('copper-measurements'); list.replaceChildren();
  for (const [label, value] of rows) { const row = document.createElement('div'); const dt = document.createElement('dt'); const dd = document.createElement('dd'); dt.textContent = label; dd.textContent = value; row.append(dt, dd); list.append(row); }
}

function renderCharts(view) {
  const frames = view.frames;
  const key = JSON.stringify([view.mode, view.key, frames[0]?.seq, frames.at(-1)?.seq, axis]);
  if (key === chartKey) return; chartKey = key;
  const start = frames[0]?.sim_time_s ?? 0; const end = frames.at(-1)?.sim_time_s ?? 1;
  const chartFrames = view.mode === 'live' ? frames.filter(f => f.sim_time_s >= end - 12) : frames;
  const chartStart = chartFrames[0]?.sim_time_s ?? start;
  const values = chartFrames.flatMap(f => [f.velocity_m_s?.[axis], f.policy_prediction_m_s?.[axis]]).filter(Number.isFinite);
  const max = Math.max(1, ...values.map(Math.abs));
  const bounds = { start: chartStart, end, min: -max, max, width: 320, height: 94 };
  node('velocity-path').setAttribute('d', chartPath(chartFrames, f => f.velocity_m_s?.[axis], bounds));
  node('prediction-path').setAttribute('d', chartPath(chartFrames, f => f.policy_prediction_m_s?.[axis], bounds));
  put('chart-max', number(max, 1)); put('chart-min', number(-max, 1));
  put('chart-note', values.length ? `${number(chartStart, 1)}–${number(end, 1)} s · source samples · ${axis.toUpperCase()} axis` : 'Velocity / policy samples unavailable; no values synthesized.');
  const ys = frames.map(f => f.position_m?.y).filter(Number.isFinite);
  node('altitude-path').setAttribute('d', chartPath(frames, f => f.position_m?.y, { start, end, min: ys.length ? Math.min(...ys) - .5 : 0, max: ys.length ? Math.max(...ys) + .5 : 1, width: 1000, height: 36 }));
  put('timeline-start', frames.length ? number(start, 2) : '—'); put('timeline-end', frames.length ? number(end, 2) : '—');
  node('timeline').min = String(start); node('timeline').max = String(end > start ? end : start + .001);
}

let depthImageKey = null;
function renderDepth(view, latestFrame) {
  const state = depthPresentation({ ...view, latestFrame });
  node('depth-section').dataset.state = state.kind;
  const preview = state.preview;
  node('depth-content').hidden = !preview;
  node('depth-absence').hidden = Boolean(preview);
  put('depth-status', { absent: 'Not reported', invalid: 'Rejected / invalid', recorded: 'Recorded / source sample', stale: 'Live / stale sample', live: 'Live / source sample' }[state.kind]);
  if (!preview) {
    put('depth-absence', state.kind === 'invalid' ? 'Malformed depth preview rejected. No pixels displayed.' : 'No completed source depth observation reported.');
    if (depthImageKey !== null) node('depth-canvas').getContext('2d')?.clearRect(0, 0, 32, 24);
    depthImageKey = null;
    return;
  }
  // The image follows the actual left-hand source frame, never the interpolated pose.
  const key = JSON.stringify([view.mode, view.key, preview.source_seq, preview.data]);
  if (key !== depthImageKey) {
    const context = node('depth-canvas').getContext('2d');
    const pixels = depthPixels(preview, view.frame);
    if (context && pixels) { const image = context.createImageData(32, 24); image.data.set(pixels); context.putImageData(image, 0, 0); }
    depthImageKey = key;
  }
  put('depth-seq', `seq ${preview.source_seq} · frame ${view.frame.seq}`);
  put('depth-age', `${number(state.ageS, 2)} s${view.mode === 'recorded' ? ' at source row' : ' · native wall + receipt age'}`);
  put('depth-sim-time', `${number(preview.sample_sim_time_s, 3)} s`);
  put('depth-source-note', `${view.mode === 'recorded' ? 'Recorded' : 'Live'} actual source pixels, never interpolated. ${preview.source}. CPU sampling time is not acquisition time; acquisition timestamp unavailable.`);
}

function render(now) {
  const view = session.view(now); const frame = view.frame;
  const frameCapture = captureEvidence(frame?.copper);
  node('capture-mode').hidden = !frameCapture;
  if (frameCapture) { node('capture-mode').dataset.full = String(frameCapture.full); put('capture-mode', `${frameCapture.text} · ${frameCapture.detail}`); }
  const recorded = view.mode === 'recorded';
  const state = monitor.snapshot().state;
  const latest = buffer.frames.at(-1); const previous = buffer.frames.at(-2);
  const advancingPolicy = view.live && latest?.policy_observation_seq !== null && previous?.policy_observation_seq !== null && latest?.policy_observation_seq > previous?.policy_observation_seq;
  const connection = node('connection'); connection.dataset.health = recorded ? 'recorded' : view.live ? 'live' : buffer.frames.length ? 'stale' : 'waiting';
  put('connection-label', recorded ? session.mission ? session.clock?.playing ? 'Recorded / visualization playing' : 'Recorded / paused' : 'Choose mission' : view.live ? 'Native source advancing' : 'Source not live');
  put('source-subtitle', recorded ? session.mission ? `${session.mission.recording.id} · completed native telemetry` : 'Select a completed mission · simulation-time visualization' : `${sourceRoute} · ${view.reason}`);
  put('transport-source', view.live ? 'LIVE / jitter-buffered source' : 'LIVE / waiting for progress');
  put('clock-time', number(view.timeS, 2));
  put('clock-end', recorded && session.clock ? `/ ${number(session.clock.end, 2)} s` : 's');
  for (const id of ['play-pause', 'restart', 'timeline', 'playback-rate']) node(id).disabled = !recorded || !session.clock;
  put('play-pause', session.clock?.playing ? 'Pause' : 'Play');
  if (Number.isFinite(view.timeS)) node('timeline').value = String(view.timeS);
  put('frame-age', recorded ? 'Recorded source' : view.frameAgeS === null || view.frameAgeS === undefined ? 'Unavailable' : `${number(view.frameAgeS, 2)} s`);
  const metrics = buffer.metrics();
  put('cadence-label', recorded ? 'Recorded sample interval' : metrics.clock === 'native' ? 'Native timestamp cadence' : 'Received source cadence');
  put('sim-rate-label', recorded ? 'Visualization speed' : 'Sim time / wall time');
  const recordedInterval = recorded && view.frames.length > 1 ? (view.frames.at(-1).sim_time_s - view.frames[0].sim_time_s) / (view.frames.length - 1) : null;
  put('source-cadence', recorded ? recordedInterval === null ? 'Unavailable' : `${number(recordedInterval * 1000, 1)} ms · mean` : metrics.sourceHz === null ? 'Measuring' : `${number(metrics.sourceHz, 1)} frames/s`);
  put('sim-rate', recorded ? `${session.clock?.rate ?? 1}× sim time` : metrics.simRate === null ? 'Measuring' : `${number(metrics.simRate, 2)}× observed`);
  put('evidence-note', recorded ? 'Recorded samples, rendered on the browser animation clock. Visualization speed says nothing about native execution speed.' : `${metrics.clock === 'native' ? 'Measured using reported native wall timestamps' : 'Measured from distinct received frames and browser receipt intervals'}, not rendering or control-loop execution. Presentation buffer ${number(metrics.delayS, 2)} sim s.`);
  put('inference-badge', evidenceLabel(view.mode, frame, advancingPolicy));
  const key = JSON.stringify([view.mode, view.key, frame?.seq, view.live]);
  if (key !== dataKey) {
    dataKey = key;
    put('frame-seq', frame ? `SEQ ${frame.seq}` : 'SEQ —');
    put('telemetry-validity', frame ? recorded ? 'Recorded source frame' : view.live ? 'Observed source frame' : 'Last source frame' : 'No source frame');
    put('flight-mode', frame?.mode ? `${frame.mode} request` : 'Mode request unavailable');
    put('armed', frame?.armed === true ? 'Arm requested' : frame?.armed === false ? 'Disarm requested' : 'Arm request unavailable');
    put('auto-enabled', frame?.auto_enabled === true ? 'Auto requested' : frame?.auto_enabled === false ? 'Manual requested' : 'Auto request unavailable');
    for (const a of ['x', 'y', 'z']) { put(`position-${a}`, number(frame?.position_m?.[a])); put(`velocity-${a}`, number(frame?.velocity_m_s?.[a])); put(`policy-${a}`, number(frame?.policy_prediction_m_s?.[a])); }
    put('rotation', frame?.rotation ? ['x', 'y', 'z', 'w'].map(a => number(frame.rotation[a], 3)).join(' / ') : 'Unavailable');
    put('policy-seq', frame?.policy_observation_seq === null || frame?.policy_observation_seq === undefined ? 'Unavailable' : `seq ${frame.policy_observation_seq}`);
    node('inference-count-row').hidden = frame?.inference_count === null || frame?.inference_count === undefined;
    put('inference-count', number(frame?.inference_count, 0));
    put('runtime-source', recorded ? `/api/recordings/${session.mission?.recording.id ?? '…'}/telemetry` : sourceRoute);
    put('mission-id', recorded ? session.mission?.recording.id : buffer.source?.episode?.id);
    put('copper-version', recorded ? session.mission?.provenance?.engine?.copper_version ?? 'Not reported in recording' : buffer.source?.engine?.copper_version ?? state?.engine.copper_version);
    put('runtime-revision', recorded ? session.mission?.provenance?.engine?.revision ?? 'Not reported in recording' : buffer.source?.engine?.revision ?? state?.engine.revision);
    put('graphics-adapter', frame?.graphics?.adapter_name);
    put('provenance', recorded ? session.mission?.provenance ? JSON.stringify(session.mission.provenance, null, 2) : 'No provenance reported for this recording.' : JSON.stringify(buffer.source?.engine ?? state?.engine ?? null, null, 2));
    const recording = recorded ? state?.recordings.find(r => r.id === session.mission?.recording.id) : null;
    const download = safeDownloadURL(recording); node('download-recording').hidden = !download; if (download) node('download-recording').href = download; else node('download-recording').removeAttribute('href');
    updateMeasurements(frame?.copper);
  }
  renderDepth(view, latest);
  renderCharts(view);
  showError(recorded ? recordingError : feedError);
  return view;
}

node('mode-live').addEventListener('click', () => setMode('live'));
node('mode-recorded').addEventListener('click', () => setMode('recorded'));
node('mission-select').addEventListener('change', () => { node('load-mission').disabled = !node('mission-select').value; void loadMission(); });
node('load-mission').addEventListener('click', loadMission);
node('play-pause').addEventListener('click', () => { const clock = session.clock; if (!clock || session.mode !== 'recorded') return; if (clock.playing) clock.pause(performance.now()); else clock.play(performance.now()); render(performance.now()); });
node('restart').addEventListener('click', () => { session.clock?.seek(session.clock.start, performance.now()); render(performance.now()); });
node('timeline').addEventListener('input', event => { if (session.mode === 'recorded') { session.clock?.seek(Number(event.target.value), performance.now()); render(performance.now()); } });
node('playback-rate').addEventListener('change', event => { session.clock?.setRate(Number(event.target.value), performance.now()); render(performance.now()); });
node('chart-axis').addEventListener('change', event => { axis = event.target.value; chartKey = ''; });
node('toggle-source').addEventListener('click', () => { const expanded = node('toggle-source').getAttribute('aria-expanded') === 'true'; node('toggle-source').setAttribute('aria-expanded', String(!expanded)); node('source-detail').hidden = expanded; });

function animate(now) { if (disposed) return; if (now - lastRenderAt >= 80) { render(now); lastRenderAt = now; } frameRequest = requestAnimationFrame(animate); }
render(performance.now());
void pollState(); void pollFeed();
const stateInterval = setInterval(pollState, 200);
const feedInterval = setInterval(pollFeed, 200);
frameRequest = requestAnimationFrame(animate);
import('./viewer.js').then(({ createViewer }) => createViewer(now => session.view(now))).then(instance => { viewer = instance; }).catch(failure => { put('scene-overlay-title', 'Browser scene unavailable'); put('scene-overlay-detail', 'The local WebGL module could not load. Source telemetry remains available in the Copper inspector.'); console.error('Copper viewer unavailable:', failure); });
window.addEventListener('pagehide', () => { disposed = true; clearInterval(stateInterval); clearInterval(feedInterval); cancelAnimationFrame(frameRequest); recordingController?.abort(); feedController?.abort(); monitor.dispose(); viewer?.dispose(); }, { once: true });
window.addEventListener('pageshow', event => { if (event.persisted) window.location.reload(); });
