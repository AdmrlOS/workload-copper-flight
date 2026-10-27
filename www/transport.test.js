import test from 'node:test';
import assert from 'node:assert/strict';
const transport = await import('./transport.js').catch((error) => {
  if (error.code === 'ERR_MODULE_NOT_FOUND') return {};
  throw error;
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
