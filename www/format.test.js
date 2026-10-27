import test from 'node:test';
import assert from 'node:assert/strict';
const display = await import('./format.js').catch((error) => {
  if (error.code === 'ERR_MODULE_NOT_FOUND') return {};
  throw error;
});

test('formats recording byte counts without treating missing size as empty', () => {
  assert.equal(typeof display.bytes, 'function');
  for (const value of [null, undefined, -1, '1', Infinity]) assert.equal(display.bytes(value), '—');
  assert.equal(display.bytes(0), '0 B');
  assert.equal(display.bytes(1023), '1023 B');
  assert.equal(display.bytes(1024), '1.0 KiB');
  assert.equal(display.bytes(1572864), '1.5 MiB');
  assert.equal(display.bytes(1073741824), '1.0 GiB');
});

test('formats only finite observed numbers and preserves true zero', () => {
  assert.equal(typeof display.number, 'function');
  assert.equal(display.number(null), '—');
  assert.equal(display.number(undefined), '—');
  assert.equal(display.number('4'), '—');
  assert.equal(display.number(Infinity), '—');
  assert.equal(display.number(NaN), '—');
  assert.equal(display.number(0), '0.00');
  assert.equal(display.number(-1.25), '-1.25');
  assert.equal(display.number(12, 0), '12');
});
