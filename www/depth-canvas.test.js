// Optional real-Chromium check. Fixture is explicitly synthetic, not native evidence.
import test from 'node:test';
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { mkdtempSync, readFileSync, existsSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { setTimeout as delay } from 'node:timers/promises';

const base = process.env.DEPTH_BROWSER_URL;
const chrome = process.env.DEPTH_CHROME_BIN;

test('actual Chromium app paints distinct adjacent 320x240 source pixels and labels old recordings', { skip: !base || !chrome }, async () => {
  const profile = mkdtempSync(join(tmpdir(), 'depth-chromium-'));
  const browser = spawn(chrome, ['--headless=new', '--no-first-run', '--no-default-browser-check',
    '--remote-debugging-port=0', `--user-data-dir=${profile}`, 'about:blank'], { stdio: 'ignore' });
  let socket;
  try {
    const active = join(profile, 'DevToolsActivePort');
    for (let i = 0; !existsSync(active) && i < 200; i++) await delay(50);
    assert.ok(existsSync(active), 'isolated Chrome must expose CDP');
    const port = readFileSync(active, 'utf8').split('\n')[0];
    const target = await (await fetch(`http://127.0.0.1:${port}/json/new?about:blank`, { method: 'PUT' })).json();
    socket = new WebSocket(target.webSocketDebuggerUrl);
    await new Promise((resolve, reject) => { socket.onopen = resolve; socket.onerror = reject; });
    let seq = 0; const waiting = new Map(); const errors = [];
    socket.onmessage = event => { const message = JSON.parse(event.data); if (message.method === 'Runtime.exceptionThrown' || message.method === 'Log.entryAdded') errors.push(message.params); if (waiting.has(message.id)) { waiting.get(message.id)(message); waiting.delete(message.id); } };
    const cdp = (method, params = {}) => new Promise((resolve, reject) => {
      const id = ++seq; waiting.set(id, result => result.error ? reject(new Error(JSON.stringify(result.error))) : resolve(result.result));
      socket.send(JSON.stringify({ id, method, params }));
    });
    const evaluate = async expression => {
      const result = await cdp('Runtime.evaluate', { expression, awaitPromise: true, returnByValue: true });
      assert.equal(result.exceptionDetails, undefined, JSON.stringify(result.exceptionDetails));
      return result.result.value;
    };
    const until = async expression => {
      for (let i = 0; i < 160; i++) { const result = await evaluate(expression); if (result) return result; await delay(50); }
      throw new Error(`Timed out: ${expression}; ${JSON.stringify({ page: await evaluate("({url:location.href,text:document.body?.innerText?.slice(0,1500)})"), errors })}`);
    };
    await cdp('Runtime.enable'); await cdp('Log.enable');
    await cdp('Page.navigate', { url: base });
    await until("document.querySelector('#mission-select')?.options.length === 2");
    await evaluate("document.querySelector('#mode-recorded').click(); document.querySelector('#mission-select').value='20261027T000000Z-1234abcd'; document.querySelector('#mission-select').dispatchEvent(new Event('change')); true");
    await until("document.querySelector('#depth-resolution')?.textContent === '320×240 · full source raster' && !document.querySelector('#depth-content').hidden");
    const full = await evaluate("(() => {const canvas=document.querySelector('#depth-canvas'); const data=canvas.getContext('2d').getImageData(0,0,320,240).data;return {width:canvas.width,height:canvas.height,bytes:data.length,adjacent:Array.from(data.slice(0,24)),seq:document.querySelector('#depth-seq').textContent,status:document.querySelector('#depth-status').textContent,note:document.querySelector('#depth-source-note').textContent};})()");
    assert.equal(full.width, 320); assert.equal(full.height, 240); assert.equal(full.bytes, 307200);
    assert.deepEqual(full.adjacent.slice(0, 4), [18, 20, 32, 255]);
    assert.notDeepEqual(full.adjacent.slice(4, 8), full.adjacent.slice(8, 12));
    assert.notDeepEqual(full.adjacent.slice(8, 12), full.adjacent.slice(12, 16));
    assert.match(full.seq, /seq 7/); assert.match(full.status, /Recorded/); assert.match(full.note, /identity/);
    assert.equal(await evaluate("document.querySelector('#depth-sim-time').textContent"), 'wall 2.000 s · sim 1.000 s');
    const http = await evaluate("fetch('/api/recordings/20261027T000000Z-1234abcd/depth/7').then(async r => ({status:r.status,encoding:r.headers.get('Content-Encoding'),length:(await r.json()).data.length}))");
    assert.deepEqual(http, { status: 200, encoding: 'gzip', length: 153600 });
    await evaluate("document.querySelector('#mission-select').value='20261027T000001Z-1234abcd'; document.querySelector('#mission-select').dispatchEvent(new Event('change')); true");
    await until("document.querySelector('#depth-status')?.textContent.includes('Legacy 32×24')");
    const legacy = await evaluate("({width:document.querySelector('#depth-canvas').width,height:document.querySelector('#depth-canvas').height,label:document.querySelector('#depth-resolution').textContent})");
    assert.deepEqual(legacy, { width: 32, height: 24, label: 'Legacy 32×24 thumbnail (320×240 source)' });
    console.log(JSON.stringify({ synthetic: true, full, http, legacy }));
  } finally {
    socket?.close();
    const exited = new Promise(resolve => browser.once('exit', resolve));
    browser.kill('SIGTERM');
    await Promise.race([exited, delay(3000)]);
    if (browser.exitCode === null) browser.kill('SIGKILL');
    rmSync(profile, { recursive: true, force: true });
  }
});
