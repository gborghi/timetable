/**
 * Tests for $lib/metrics_labels.ts — human rendering of the metrics dict
 * (replaces raw JSON.stringify in Dashboard/Schedule/Runs).
 *
 *   node --experimental-strip-types --test webui/frontend/src/lib/metrics_labels.test.mjs
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';

import { humanMetrics, humanMetricsLine } from './metrics_labels.ts';

test('labels known keys in Italian and formats percentages', () => {
  const out = humanMetrics({ coverage: 1, buchi: 12, assignments: 1134 });
  const byKey = Object.fromEntries(out.map((m) => [m.key, m]));
  assert.equal(byKey.coverage.label, 'Copertura');
  assert.equal(byKey.coverage.value, '100%');
  assert.equal(byKey.buchi.label, 'Ore buche');
  assert.equal(byKey.buchi.value, '12');
});

test('unknown keys get a prettified fallback label (never raw)', () => {
  const [m] = humanMetrics({ some_weird_key: 3 });
  assert.equal(m.label, 'Some weird key');
  assert.equal(m.value, '3');
});

test('skips nested objects, arrays, nulls and long prose', () => {
  const out = humanMetrics({
    coverage: 0.5,
    samples: [1, 2, 3],
    nested: { a: 1 },
    empty: null,
    interpretation: 'x'.repeat(80),
  });
  assert.deepEqual(out.map((m) => m.key), ['coverage']);
});

test('rounds non-integer numbers and formats booleans', () => {
  const out = humanMetrics({ mean: 2800.4567, ok: true });
  const byKey = Object.fromEntries(out.map((m) => [m.key, m.value]));
  assert.equal(byKey.mean, '2800.46');
  assert.equal(byKey.ok, 'sì');
});

test('humanMetricsLine joins with a middot and honours max', () => {
  const line = humanMetricsLine({ coverage: 1, buchi: 12, assignments: 1134 }, { max: 2 });
  assert.equal(line, 'Copertura: 100% · Ore buche: 12');
});
