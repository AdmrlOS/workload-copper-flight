import test from 'node:test';
import assert from 'node:assert/strict';
import * as depth from './depth.js';
import { parseFrame } from './state.js';

// Synthetic identity-raster inputs, not native run evidence.
const runID = '20261027T000000Z-1234abcd';
const otherID = '20261027T000001Z-1234abcd';
function full(seq = 7) {
  return { source: 'SimZedFrameStore.depth/Copper.ZedSource', source_width: 320, source_height: 240,
    width: 320, height: 240, encoding: 'u8-hex', sampling: 'identity', source_units: 'millimetres',
    invalid_u8: 0, invalid_rule: 'source_mm == 0 or source_mm > 20000',
    decode_m: '(1 + (q - 1) * 19999 / 254) / 1000; q=0 invalid', range_m: [.001, 20],
    source_seq: seq, sample_wall_time_s: 2, sample_sim_time_s: 1,
    data: Array.from({ length: 256 }, (_, i) => i.toString(16).padStart(2, '0')).join('').repeat(300) };
}
const meta = (value = full()) => { const { data, ...descriptor } = value; return descriptor; };
const frame = (seq = 7) => ({ schema_version: 1, seq: seq + 20, sim_time_s: 2, wall_time_s: 3, depth_raster: meta(full(seq)) });
const selection = (seq = 7, mode = 'live', epoch = 'a', id = runID) => ({ mode, epoch, runID: id, frame: frame(seq) });
const response = (value) => new Response(JSON.stringify(value), { headers: { 'Content-Type': 'application/json' } });

test('slow live fetch is not starved: one in flight, honest old sample, queued newest and 2Hz wall cap', async () => {
  assert.equal(typeof depth.createDepthLoader, 'function');
  let now = 0; const requests = [];
  const loader = depth.createDepthLoader((url, options) => new Promise(resolve => requests.push({ url, options, resolve })), { now: () => now });
  loader.select(selection());
  const first = loader.poll();
  assert.equal(requests.length, 1);
  now = 600; loader.select(selection(8)); await loader.poll();
  now = 1200; loader.select(selection(9)); await loader.poll();
  assert.equal(requests.length, 1); assert.equal(requests[0].options.signal.aborted, false);
  requests[0].resolve(response(full(7))); await first;
  assert.equal(loader.snapshot().raster.source_seq, 7);
  assert.equal(loader.snapshot().frame.seq, 27);
  const next = loader.poll();
  assert.equal(requests.length, 2); assert.match(requests[1].url, /\/depth\/9$/);
  assert.equal(loader.snapshot().raster.source_seq, 7, 'hold full source sample, not a thumbnail or new seq');
  requests[1].resolve(response(full(9))); await next;
  assert.equal(loader.snapshot().raster.source_seq, 9);
  loader.select(selection(10)); now = 1699; await loader.poll(); assert.equal(requests.length, 2);
  now = 1700; const final = loader.poll(); assert.equal(requests.length, 3);
  requests[2].resolve(response(full(10))); await final;
  now = 5000; await loader.poll(); assert.equal(requests.length, 3, 'only fetch new descriptors');
  loader.dispose();
});

test('mode, epoch, run and recorded seek reject aborted responses even if fetch ignores abort', async () => {
  for (const next of [selection(8, 'recorded'), selection(7, 'live', 'b'), selection(7, 'live', 'a', otherID)]) {
    let now = 0; const requests = [];
    const loader = depth.createDepthLoader((url, options) => new Promise(resolve => requests.push({ options, resolve })), { now: () => now });
    loader.select(selection()); const old = loader.poll();
    loader.select(next); assert.equal(requests[0].options.signal.aborted, true);
    requests[0].resolve(response(full())); await old; assert.equal(loader.snapshot().raster, null);
    now = 500; const current = loader.poll(); requests[1].resolve(response(full(next.frame.depth_raster.source_seq))); await current;
    assert.equal(loader.snapshot().raster.source_seq, next.frame.depth_raster.source_seq);
    loader.dispose();
  }
  let resolve; let now = 0;
  const loader = depth.createDepthLoader(() => new Promise(done => { resolve = done; }), { now: () => now });
  loader.select(selection(9, 'recorded')); const future = loader.poll();
  loader.select(selection(7, 'recorded')); resolve(response(full(9))); await future;
  assert.equal(loader.snapshot().raster, null, 'seek must not display a future source frame');
  now = 500; const requested = loader.poll(); resolve(response(full(8))); await requested;
  assert.equal(loader.snapshot().raster, null); assert.match(loader.snapshot().error, /rejected/);
  loader.dispose();
});

test('unchanged paused recording deadline leaves an error instead of loading forever', { timeout: 7000 }, async t => {
  let now = 0; const requests = [];
  const loader = depth.createDepthLoader((url, options) => new Promise((_resolve, reject) => {
    requests.push({ url, options });
    options.signal.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')), { once: true });
  }), { now: () => now });
  t.after(() => loader.dispose());
  const paused = selection(7, 'recorded');
  const view = { mode: paused.mode, frame: paused.frame };
  loader.select(paused); const request = loader.poll();
  assert.equal(loader.snapshot().pending, true);
  assert.equal(depth.depthPresentation(view, loader.snapshot()).kind, 'loading');
  for (now of [100, 499, 500, 1500, 3499]) {
    loader.select(paused); await loader.poll();
  }
  await request; // Exercise the real 3500ms deadline, without replacing timers.
  assert.equal(requests[0].options.signal.aborted, true);
  assert.equal(loader.snapshot().pending, false);
  assert.ok(loader.snapshot().error, 'deadline must publish an error for the unchanged paused selection');
  assert.equal(loader.snapshot().raster, null);
  assert.equal(depth.depthPresentation(view, loader.snapshot()).kind, 'invalid');
  for (now of [3500, 3501, 4000, 10000]) {
    loader.select(paused); await loader.poll();
    assert.equal(loader.snapshot().pending, false);
    assert.ok(loader.snapshot().error);
    assert.equal(depth.depthPresentation(view, loader.snapshot()).kind, 'invalid');
  }
  assert.equal(requests.length, 1, 'polling an unchanged timed-out selection must not restart requests or exceed the rate cap');
});

test('selection cancellation and disposal do not publish a deadline or fetch error', async () => {
  for (const next of [selection(7, 'live'), selection(7, 'recorded', 'b'),
    selection(7, 'recorded', 'a', otherID), selection(8, 'recorded'), null]) {
    const loader = depth.createDepthLoader((_url, options) => new Promise((_resolve, reject) => {
      options.signal.addEventListener('abort', () => reject(new DOMException('Cancelled', 'AbortError')), { once: true });
    }));
    loader.select(selection(7, 'recorded')); const request = loader.poll();
    if (next) loader.select(next); else loader.dispose();
    await request;
    assert.equal(loader.snapshot().pending, false);
    assert.equal(loader.snapshot().error, null);
    assert.equal(loader.snapshot().raster, null);
    loader.dispose();
  }
});

test('raster network reader rejects oversize, wrong content type, malformed JSON and metadata mismatch', async () => {
  for (const input of [response({ ...full(), data: 'ff'.repeat(1000000) }), new Response('<html>'),
    new Response('{', { headers: { 'Content-Type': 'application/json' } }), response(full(8)),
    new Response('{}', { status: 404, headers: { 'Content-Type': 'application/json' } })]) {
    const loader = depth.createDepthLoader(async () => input);
    loader.select(selection()); await loader.poll();
    assert.equal(loader.snapshot().raster, null); assert.ok(loader.snapshot().error);
    loader.dispose();
  }
});

test('full-sample presentation uses actual held seq/time and current live age; old recordings are labelled', () => {
  const observation = { raster: full(), frame: frame() };
  const live = depth.depthPresentation({ frame: frame(9), latestFrame: { wall_time_s: 5 }, mode: 'live', live: true, frameAgeS: .25 }, observation);
  assert.equal(live.preview.width, 320); assert.equal(live.preview.source_seq, 7);
  assert.equal(live.ageS, 3.25); assert.equal(live.kind, 'stale'); assert.equal(live.legacy, false);
  assert.equal(depth.depthPresentation({ frame: frame(), mode: 'recorded' }, observation).kind, 'recorded');
  assert.equal(depth.depthPresentation({ frame: frame(9), mode: 'recorded' }, observation).preview, null, 'recorded presentation must reject a different descriptor');
  assert.equal(depth.depthPresentation({ frame: frame(), mode: 'recorded' }).kind, 'loading');
  const old = { ...full(), width: 32, height: 24, sampling: 'nearest-cell-center', data: '000eff'.repeat(256) };

  // A genuinely old recording omits the descriptor, rather than reporting a malformed one.
  const oldFrame = { ...frame(), depth_preview: old }; delete oldFrame.depth_raster;
  assert.equal(depth.depthPresentation({ frame: oldFrame, mode: 'recorded' }).legacy, true);
});


test('identity metadata stays small and exact 320x240 pixels reach a bounded canvas', () => {
  assert.equal(typeof depth.parseDepthDescriptor, 'function');
  assert.deepEqual(parseFrame(frame()).depth_raster, meta());
  const source = full();
  assert.deepEqual(depth.parseDepthRaster(source, meta(), frame()), source);
  const pixels = depth.depthPixels(source, frame());
  assert.equal(pixels.length, 320 * 240 * 4);
  assert.deepEqual([...pixels.slice(0, 4)], [18, 20, 32, 255]);
  assert.notDeepEqual([...pixels.slice(4, 8)], [...pixels.slice(8, 12)]);
  assert.notDeepEqual([...pixels.slice(8, 12)], [...pixels.slice(12, 16)]);
  let image;
  const canvas = { width: 32, height: 24, getContext: () => ({
    createImageData: (width, height) => ({ width, height, data: new Uint8ClampedArray(width * height * 4) }),
    putImageData: value => { image = value; },
  }) };
  assert.equal(depth.paintDepth(canvas, source, frame()), true);
  assert.equal(canvas.width, 320); assert.equal(canvas.height, 240);
  assert.equal(image.width, 320); assert.equal(image.height, 240);
  assert.deepEqual(image.data, pixels);
  const old = { ...source, width: 32, height: 24, sampling: 'nearest-cell-center', data: '000eff'.repeat(256) };
  assert.equal(depth.paintDepth(canvas, old, frame()), true);
  assert.equal(canvas.width, 32); assert.equal(canvas.height, 24);
});

test('all raster response metadata is bound to captured descriptor and source frame', () => {
  assert.equal(typeof depth.parseDepthRaster, 'function');
  for (const [key, value] of Object.entries(meta())) {
    const mutated = { ...full(), [key]: Array.isArray(value) ? [0, 100] : typeof value === 'string' ? 'wrong' : value + 1 };
    assert.equal(depth.parseDepthRaster(mutated, meta(), frame()), null, key);
  }
  for (const changes of [{ width: true }, { source_seq: 2 ** 53 }, { data: 'FF'.repeat(76800) },
    { data: 'ff'.repeat(76799) }, { sample_wall_time_s: Infinity }, { sample_sim_time_s: 3 }, { data: 'ff'.repeat(1000000) }]) {
    assert.equal(depth.parseDepthRaster({ ...full(), ...changes }, meta(), frame()), null);
  }
  assert.equal(depth.parseDepthDescriptor({ ...meta(), data: full().data }, frame()), null);
  assert.equal(parseFrame({ ...frame(), depth_raster: { ...meta(), width: true } }).depth_raster, null);
  assert.equal(parseFrame({ schema_version: 1, seq: 0 }).depth_raster, undefined);
  assert.equal(Object.hasOwn(depth.parseDepthRaster({ ...full(), ignored: '<script>' }, meta(), frame()), 'ignored'), false);
});
