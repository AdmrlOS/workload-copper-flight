import test from 'node:test';
import assert from 'node:assert/strict';
const monitoring = await import('./monitor.js').catch((error) => {
  if (error.code === 'ERR_MODULE_NOT_FOUND') return {};
  throw error;
});

test('does not overlap requests and aborts requests which exceed the deadline', async () => {
  let calls = 0;
  let release;
  const monitor = monitoring.createMonitor({ fetchImpl: () => {
    calls += 1;
    return new Promise((resolve) => { release = resolve; });
  } });
  const pending = monitor.poll();
  const overlapping = monitor.poll();
  assert.equal(calls, 1);
  release(Response.json({ status: 'starting' }));
  await Promise.all([pending, overlapping]);
  const deadline = monitoring.createMonitor({ timeoutMs: 5, fetchImpl: (url, options) => new Promise((resolve, reject) => {
    options.signal.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')));
  }) });
  await deadline.poll();
  assert.equal(deadline.snapshot().health.kind, 'error');
  assert.match(deadline.snapshot().error, /timed out/);
  deadline.dispose();
  monitor.dispose();
});

test('polling retains the last valid state but marks network and malformed responses unavailable', async () => {
  assert.equal(typeof monitoring.createMonitor, 'function');
  let clock = 0;
  let response = Response.json({ status: 'starting', engine: { source_revision: 'exact-source' } });
  const monitor = monitoring.createMonitor({ fetchImpl: async () => response, now: () => clock });
  assert.equal(monitor.snapshot().health.kind, 'connecting');
  await monitor.poll();
  assert.equal(monitor.snapshot().health.kind, 'starting');
  assert.equal(monitor.snapshot().state.engine.source_revision, 'exact-source');
  response = new Response('bad response', { status: 503 });
  clock = 3000;
  await monitor.poll();
  assert.equal(monitor.snapshot().health.kind, 'error');
  assert.match(monitor.snapshot().error, /HTTP 503/);
  assert.equal(monitor.snapshot().state.engine.source_revision, 'exact-source');
  response = Response.json({ ok: true });
  await monitor.poll();
  assert.equal(monitor.snapshot().health.kind, 'error');
  response = Response.json({ status: 'stopped' });
  await monitor.poll();
  assert.equal(monitor.snapshot().health.kind, 'stopped');
  assert.equal(monitor.snapshot().error, null);
  assert.equal(monitoring.POLL_INTERVAL_MS, 200);
});
