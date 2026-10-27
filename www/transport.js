import { parseState } from './state.js';

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
