import test from 'node:test';
import assert from 'node:assert/strict';
import { existsSync, readFileSync, statSync } from 'node:fs';

const root = new URL('./', import.meta.url);
const read = (name) => readFileSync(new URL(name, root), 'utf8');

test('ships an explicit offline browser dependency inventory for the backend allowlist', () => {
  assert.ok(existsSync(new URL('static-routes.json', root)), 'Create the explicit static route manifest');
  const manifest = JSON.parse(read('static-routes.json'));
  assert.equal(manifest.library, 'three@0.182.0');
  assert.deepEqual(manifest.scene_routes, ['/api/scene/forest.glb', '/api/scene/quadcopter.glb']);
  assert.equal(new Set(manifest.static_routes).size, manifest.static_routes.length);
  for (const route of manifest.static_routes) {
    assert.match(route, /^\/[A-Za-z0-9_./-]+$/);
    assert.equal(route.includes('..'), false);
    assert.ok(statSync(new URL(route.slice(1), root)).isFile(), `${route} must be a real file`);
    assert.equal(route.endsWith('.test.js'), false, 'Test fixtures are not production browser assets');
  }
  for (const required of ['index.html', 'styles.css', 'app.js', 'monitor.js', 'state.js', 'transport.js', 'format.js', 'pose.js', 'viewer.js']) {
    assert.ok(manifest.static_routes.includes(`/${required}`), `Manifest missing ${required}`);
  }
  for (const addon of ['loaders/GLTFLoader.js', 'controls/OrbitControls.js', 'utils/BufferGeometryUtils.js']) {
    const source = read(`vendor/three-r182/examples/jsm/${addon}`);
    assert.ok(source.includes("from '../../../build/three.module.js'"));
    assert.equal(/^\s*}\s+from ['"]three['"]/m.test(source), false);
  }
  assert.ok(read('vendor/three-r182/build/three.core.js').includes("const REVISION = '182'"));
  assert.ok(read('vendor/three-r182/LICENSE').includes('MIT License'));
  for (const file of ['app.js', 'transport.js', 'live.js', 'mission.js', 'presentation.js', 'viewer.js']) {
    assert.ok(manifest.static_routes.includes(`/${file}`), `Missing entry module ${file}`);
    for (const match of read(file).matchAll(/from ['"]\.\/([^'"]+)['"]/g)) assert.ok(manifest.static_routes.includes(`/${match[1]}`), `Allowlist missing imported ${match[1]}`);
  }
  const html = read('index.html');
  assert.ok(manifest.static_routes.includes('/depth.js'), 'Ship the bounded depth module');
  assert.match(html, /id="depth-canvas"[^>]*width="320"[^>]*height="240"/, 'Full source canvas is 320x240, not a CSS-upscaled thumbnail');
  assert.match(read('app.js'), /renderDepth\(view,\s*latest\)/, 'Render depth on every inspector refresh');
  assert.match(read('app.js'), /depthPresentation\(/, 'Wire source age and modes into inspector');
  assert.match(read('app.js'), /createDepthLoader\(/);
  assert.match(read('app.js'), /setInterval\(pollDepth,\s*200\)/, 'Depth network uses wall timer, not requestAnimationFrame');
  assert.match(read('app.js'), /paintDepth\(/);
  assert.match(read('app.js'), /Legacy 32×24/);
  assert.equal(/filter\s*:\s*blur/i.test(read('styles.css')), false);
  assert.match(html, /Simulated sensor depth/);
  assert.equal(/<script(?![^>]*\bsrc\s*=)/i.test(html), false, 'No inline scripts or import maps');
  assert.equal(/\son\w+\s*=/i.test(html), false, 'No inline handlers');
  assert.equal(/\sstyle\s*=/i.test(html), false, 'No inline CSS');
  const ids = [...html.matchAll(/\bid="([^"]+)"/g)].map((match) => match[1]);
  assert.equal(new Set(ids).size, ids.length, 'No duplicate element IDs');
  for (const match of read('app.js').matchAll(/(?:node|put)\('([^']+)'/g)) assert.ok(ids.includes(match[1]), `Missing DOM target ${match[1]}`);
});
