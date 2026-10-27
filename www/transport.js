import { parseState } from './state.js';
import { parseRecording, recordingID } from './mission.js';
import { parseTelemetry } from './live.js';

async function readJSON(fetchImpl, url, signal) {
  const response = await fetchImpl(url, { method: 'GET', cache: 'no-store', credentials: 'same-origin', redirect: 'error', headers: { Accept: 'application/json' }, signal });
  if (!response.ok) { const error = new Error(`HTTP ${response.status}: telemetry endpoint unavailable`); error.status = response.status; throw error; }
  if (!/^application\/json(?:\s*;|$)/i.test(response.headers.get('Content-Type') ?? '')) throw new TypeError(`Expected JSON from ${url}`);
  try { return await response.json(); } catch (error) { if (error.name === 'AbortError') throw error; throw new TypeError(`Malformed JSON from ${url}`); }
}

export async function fetchRecording(fetchImpl, id, signal) {
  if (!recordingID(id)) throw new TypeError('Invalid recording ID');
  return parseRecording(await readJSON(fetchImpl, `/api/recordings/${id}/telemetry`, signal), id);
}

export async function fetchTelemetry(fetchImpl, { afterSeq = null, episodeID = null, signal } = {}) {
  if (afterSeq !== null && (!Number.isSafeInteger(afterSeq) || afterSeq < 0)) throw new TypeError('Invalid telemetry cursor');
  const query = new URLSearchParams();
  if (afterSeq !== null) query.set('after_seq', String(afterSeq));
  if (episodeID !== null) query.set('episode_id', episodeID);
  return parseTelemetry(await readJSON(fetchImpl, `/api/telemetry${query.size ? `?${query}` : ''}`, signal));
}

export async function fetchState(fetchImpl, signal) {
  const response = await fetchImpl('/api/state', {
    method: 'GET', cache: 'no-store', credentials: 'same-origin', redirect: 'error',
    headers: { Accept: 'application/json' }, signal,
  });
  if (!response.ok) throw new Error(`HTTP ${response.status}: state endpoint unavailable`);
  if (!/^application\/json(?:\s*;|$)/i.test(response.headers.get('Content-Type') ?? '')) {
    throw new TypeError('Expected JSON from /api/state');
  }
  let payload;
  try { payload = await response.json(); }
  catch (error) {
    if (error.name === 'AbortError') throw error;
    throw new TypeError('Malformed JSON from /api/state');
  }
  return parseState(payload);
}
