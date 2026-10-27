import { createMonitor, POLL_INTERVAL_MS } from './monitor.js';
import { inferenceEvidence, safeDownloadURL } from './state.js';
import { number, bytes } from './format.js';

const monitor = createMonitor();
const node = (id) => document.getElementById(id);
const put = (id, value) => { const target = node(id); const text = String(value ?? 'Unknown'); if (target.textContent !== text) target.textContent = text; };
const upper = (value) => value === null || value === undefined ? 'Unknown' : value.toUpperCase();
const booleanLabel = (value, yes, no) => value === true ? yes : value === false ? no : 'Unknown';
const statusCopy = {
  connecting: ['Connecting to monitor', 'Waiting for a valid response from the local runtime.'],
  starting: ['Native runtime starting', 'The runtime reports startup. Live requires fresh, advancing native frame evidence.'],
  waiting: ['Awaiting native progress', 'Waiting for a usable native frame and a later advancing sequence.'],
  unknown: ['Frame freshness unknown', 'Runtime frame age is unavailable. Sequence progress alone is not a freshness guarantee.'],
  live: ['Telemetry advancing', 'The native frame sequence is advancing within the freshness window.'],
  stale: ['Telemetry stale', 'Frame age or time without sequence progress reached 2 s. Values below are last reported.'],
  error: ['Monitor disconnected', 'The state endpoint is unavailable or invalid. Last received values are not current.'],
  failed: ['Native runtime failed', 'The runtime reported a failure. No running simulation is being claimed.'],
  stopped: ['Native runtime stopped', 'No running simulation is being claimed. Any values below are last reported.'],
  between_episodes: ['Between episodes', 'The runtime is between simulation episodes. Waiting for the next frame sequence.'],
};
let recordingsKey = null;

function renderRecordings(state, health) {
  const recordings = state?.recordings ?? [];
  const known = state?.recordings_known === true;
  const partial = state?.recordings_partial === true;
  put('recording-count', known ? `${recordings.length} ${partial ? 'usable · partial index' : 'listed'}${health.kind === 'error' ? ' · last index' : ''}` : 'Index unknown');
  const key = JSON.stringify([known, partial, recordings]);
  if (key === recordingsKey) return;
  recordingsKey = key;
  const body = node('recording-rows');
  body.replaceChildren();
  if (!recordings.length) {
    const row = document.createElement('tr');
    const cell = document.createElement('td');
    cell.colSpan = 5;
    cell.className = 'empty-state';
    cell.textContent = partial ? 'No usable recording metadata. The runtime index contains invalid entries.' : known ? 'No native recording files reported yet.' : 'The recording index has not been received.';
    row.append(cell);
    body.append(row);
    return;
  }
  for (const recording of recordings) {
    const row = document.createElement('tr');
    const values = [recording.id, booleanLabel(recording.completed, 'Completed', 'Incomplete'), recording.started_at ?? 'Unknown', bytes(recording.size_bytes)];
    for (const value of values) {
      const cell = document.createElement('td');
      cell.textContent = value;
      row.append(cell);
    }
    const cell = document.createElement('td');
    const url = safeDownloadURL(recording);
    if (url) {
      const link = document.createElement('a');
      link.className = 'download-link';
      link.href = url;
      link.textContent = 'Download ↓';
      link.setAttribute('aria-label', `Download completed recording ${recording.id}`);
      cell.append(link);
    } else {
      const unavailable = document.createElement('span');
      unavailable.className = 'download-unavailable';
      unavailable.textContent = recording.completed === true ? 'Path unavailable' : 'Not downloadable';
      cell.append(unavailable);
    }
    row.append(cell);
    body.append(row);
  }
}

function render(snapshot) {
  const { state, health, observation, error, receivedAt } = snapshot;
  const frame = state?.frame;
  const evidence = inferenceEvidence(state, health);
  const [label, detail] = statusCopy[health.kind];
  node('status-band').dataset.health = health.kind;
  put('status-label', label);
  put('status-detail', detail);
  put('runtime-status', state?.status ?? 'unknown');
  put('frame-seq', number(frame?.seq, 0));
  put('frame-age', number(health.frameAgeS, 2));
  put('uptime', number(state?.uptime_s, 0));
  put('progress-note', observation?.lastProgressAt !== null && observation ? `Sequence last advanced ${number(health.progressAgeS, 1)} s ago` : 'No sequence progress observed');
  const errorText = error ?? state?.error ?? (health.kind === 'failed' ? 'Runtime reported failure without an error message.' : null);
  node('error-detail').hidden = !errorText;
  put('error-detail', errorText ?? '');
  put('telemetry-validity', !frame ? 'Awaiting usable frame' : health.kind === 'live' ? 'Current native frame' : 'Last reported frame');
  put('armed', booleanLabel(frame?.armed, 'Armed', 'Disarmed'));
  put('auto-enabled', booleanLabel(frame?.auto_enabled, 'Enabled', 'Disabled'));
  node('armed').dataset.value = frame?.armed === true ? 'true' : frame?.armed === false ? 'false' : 'unknown';
  node('auto-enabled').dataset.value = frame?.auto_enabled === true ? 'true' : frame?.auto_enabled === false ? 'false' : 'unknown';
  put('flight-mode', frame?.mode ?? '—');
  for (const axis of ['x', 'y', 'z']) {
    put(`position-${axis}`, number(frame?.position_m?.[axis]));
    put(`velocity-${axis}`, number(frame?.velocity_m_s?.[axis]));
    put(`policy-${axis}`, number(frame?.policy_prediction_m_s?.[axis]));
  }
  for (const axis of ['x', 'y', 'z', 'w']) put(`rotation-${axis}`, number(frame?.rotation?.[axis], 3));
  put('sim-time', number(frame?.sim_time_s, 2));
  put('observed-world', frame?.world ?? 'Unknown');
  put('frame-schema', number(frame?.schema_version, 0));
  put('native-engine', booleanLabel(state?.engine.native, 'Reported native', 'Not native'));
  put('graphics-backend', frame?.graphics.backend ?? 'Unknown');
  put('graphics-adapter', frame?.graphics.adapter_name ?? 'Unknown');
  put('requested-world', state?.configuration.world ?? 'Unknown');
  put('requested-inference', upper(evidence.requested));
  put('requested-autonomy', booleanLabel(state?.configuration.autonomy, 'Enabled', 'Disabled'));
  put('episode-duration', number(state?.configuration.episode_seconds, 0));
  put('observed-inference', upper(evidence.backend));
  put('inference-count', number(evidence.count, 0));
  put('policy-seq', number(frame?.policy_observation_seq, 0));
  put('inference-badge', evidence.confirmed ? `${upper(evidence.backend)} policy observed` : 'Unconfirmed');
  node('inference-badge').dataset.confirmed = String(evidence.confirmed);
  let inferenceNote = 'No policy evidence yet. Requested configuration is not proof of execution.';
  if (evidence.backend !== null && !evidence.confirmed) inferenceNote = 'Backend is last reported, not currently confirmed. Fresh native frames, advancing policy publications and a finite prediction are required.';
  if (evidence.confirmed) inferenceNote = 'Native frame and policy publication sequences are advancing with a reported backend and finite prediction. Publication sequence is not an exact inference count.';
  if (evidence.mismatch) inferenceNote = `Requested ${upper(evidence.requested)}; the last native frame reports ${upper(evidence.backend)}. Configuration and execution differ. ${evidence.confirmed ? 'Current policy publication evidence is present.' : 'Current inference is unconfirmed.'}`;
  put('inference-note', inferenceNote);
  put('episode-title', state?.episode?.id ?? 'No current episode reported');
  put('episode-start', state?.episode?.started_at ?? 'Unknown');
  put('last-response', receivedAt ?? 'Not received');
  put('copper-version', state?.engine.copper_version ?? 'Unknown');
  put('source-revision', state?.engine.source_revision ?? 'Unknown');
  put('runtime-revision', state?.engine.revision ?? 'Unknown');
  renderRecordings(state, health);
}

render(monitor.snapshot());
const poll = async () => render(await monitor.poll());
void poll();
const interval = setInterval(poll, POLL_INTERVAL_MS);
let viewer;
import('./viewer.js').then(({ createViewer }) => createViewer(() => monitor.snapshot())).then((instance) => { viewer = instance; }).catch((failure) => {
  put('scene-overlay-title', 'Browser scene unavailable');
  put('scene-overlay-detail', 'The local WebGL module could not load. Native status remains available below.');
  put('scene-source', 'Browser module unavailable');
  console.error('Copper viewer unavailable:', failure);
});
window.addEventListener('pagehide', () => { clearInterval(interval); monitor.dispose(); viewer?.dispose(); }, { once: true });
// A bfcache restore must not keep a disposed monitor displaying old live claims.
window.addEventListener('pageshow', (event) => { if (event.persisted) window.location.reload(); });
