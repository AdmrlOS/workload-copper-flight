import test from 'node:test';
import assert from 'node:assert/strict';
const transport = await import('./transport.js').catch((error) => {
  if (error.code === 'ERR_MODULE_NOT_FOUND') return {};
  throw error;
});

test('reads completed telemetry with strict IDs and batched live frames with exact cursors', async () => {
  assert.equal(typeof transport.fetchRecording, 'function');
  assert.equal(typeof transport.fetchTelemetry, 'function');
  const id = '20261027T010000Z-deadbeef';
  const frame = { schema_version: 1, seq: 1, sim_time_s: 0, world: 'forest', position_m: { x: 0, y: 1, z: 0 }, rotation: { x: 0, y: 0, z: 0, w: 1 } };
  let request;
  const fetchImpl = async (url, options) => { request = { url, options }; return Response.json({ schema_version: 1, recording: { id, completed: true }, frames: [frame] }); };
  await transport.fetchRecording(fetchImpl, id);
  assert.equal(request.url, `/api/recordings/${id}/telemetry`);
  assert.equal(request.options.cache, 'no-store');
  await assert.rejects(() => transport.fetchRecording(fetchImpl, '../bad'), /record/i);
  await transport.fetchTelemetry(async (url, options) => { request = { url, options }; return Response.json({ schema_version: 1, status: 'live', frames: [frame] }); }, { afterSeq: 0, episodeID: id });
  assert.equal(request.url, `/api/telemetry?after_seq=0&episode_id=${id}`);
  await assert.rejects(() => transport.fetchTelemetry(fetchImpl, { afterSeq: -1 }), /cursor/i);
  await assert.rejects(() => transport.fetchTelemetry(async () => new Response('<html>', { headers: { 'Content-Type': 'text/html' } })), /Expected JSON/);
});

test('rejects HTTP errors, HTML fallbacks and malformed JSON rather than publishing telemetry', async () => {
  await assert.rejects(transport.fetchState(async () => Response.json({ status: 'live' }, { status: 503 })), /HTTP 503/);
  await assert.rejects(transport.fetchState(async () => new Response('<html>fallback</html>', { headers: { 'Content-Type': 'text/html' } })), /Expected JSON/);
  await assert.rejects(transport.fetchState(async () => new Response('{bad', { headers: { 'Content-Type': 'application/json' } })), /Malformed JSON/);
  await assert.rejects(transport.fetchState(async () => Response.json({ ok: true })), /Invalid runtime state/);
  await assert.rejects(transport.fetchState(async () => { throw new TypeError('Network unavailable'); }), /Network unavailable/);
});

test('reads state only with a same-origin, uncached, read-only JSON request', async () => {
  assert.equal(typeof transport.fetchState, 'function');
  const controller = new AbortController();
  let request;
  const result = await transport.fetchState(async (url, options) => {
    request = { url, options };
    return Response.json({ status: 'starting' });
  }, controller.signal);
  assert.equal(result.status, 'starting');
  assert.deepEqual(request, { url: '/api/state', options: {
    method: 'GET', cache: 'no-store', credentials: 'same-origin', redirect: 'error',
    headers: { Accept: 'application/json' }, signal: controller.signal,
  } });
});
