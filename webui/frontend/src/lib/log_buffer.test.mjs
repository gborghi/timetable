/**
 * Tests for $lib/log_buffer.ts — the bounded ring buffer behind
 * RunLogPanel's batched SSE flush.
 *
 *   node --experimental-strip-types --test webui/frontend/src/lib/log_buffer.test.mjs
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';

import { appendCapped, MAX_LOG_LINES } from './log_buffer.ts';

test('appends without exceeding the cap', () => {
  const out = appendCapped(['a', 'b'], ['c', 'd'], 10);
  assert.deepEqual(out, ['a', 'b', 'c', 'd']);
});

test('drops the oldest lines past the cap', () => {
  const out = appendCapped(['a', 'b', 'c'], ['d', 'e'], 3);
  assert.deepEqual(out, ['c', 'd', 'e']);
});

test('a single batch larger than the cap keeps only the last window', () => {
  const incoming = Array.from({ length: 5000 }, (_, i) => `L${i}`);
  const out = appendCapped(['old'], incoming, 2000);
  assert.equal(out.length, 2000);
  assert.equal(out[0], 'L3000');
  assert.equal(out[out.length - 1], 'L4999');
});

test('empty incoming returns a copy, never the same reference', () => {
  const existing = ['a', 'b'];
  const out = appendCapped(existing, [], 10);
  assert.deepEqual(out, existing);
  assert.notEqual(out, existing);
});

test('never mutates its inputs', () => {
  const existing = ['a', 'b', 'c'];
  const incoming = ['d'];
  appendCapped(existing, incoming, 3);
  assert.deepEqual(existing, ['a', 'b', 'c']);
  assert.deepEqual(incoming, ['d']);
});

test('default cap is MAX_LOG_LINES', () => {
  const incoming = Array.from({ length: MAX_LOG_LINES + 500 }, (_, i) => `${i}`);
  const out = appendCapped([], incoming);
  assert.equal(out.length, MAX_LOG_LINES);
});
