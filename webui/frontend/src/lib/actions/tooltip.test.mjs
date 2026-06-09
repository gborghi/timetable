/**
 * Tests for the pure placement math of the `tooltip` action.
 * Run via the package `test` script (node --experimental-strip-types).
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';

import { computeTooltipPosition } from './tooltip.ts';

const VIEW = { width: 1000, height: 800 };
const TIP = { width: 200, height: 60 };
const GAP = 8;

test('places above the anchor when there is room', () => {
  const anchor = { left: 400, right: 480, top: 300, bottom: 320, width: 80 };
  const p = computeTooltipPosition(anchor, TIP, VIEW, GAP);
  assert.equal(p.placement, 'above');
  assert.equal(p.top, 300 - 60 - 8);           // anchor.top - tip.h - gap
  assert.equal(p.left, 440 - 100);             // centered: anchorCx - tip.w/2
});

test('flips below when the anchor is near the top edge', () => {
  const anchor = { left: 400, right: 480, top: 10, bottom: 34, width: 80 };
  const p = computeTooltipPosition(anchor, TIP, VIEW, GAP);
  assert.equal(p.placement, 'below');
  assert.equal(p.top, 34 + 8);                 // anchor.bottom + gap
});

test('clamps to the left viewport edge', () => {
  const anchor = { left: 0, right: 40, top: 300, bottom: 320, width: 40 };
  const p = computeTooltipPosition(anchor, TIP, VIEW, GAP);
  assert.equal(p.left, GAP);                   // not negative
});

test('clamps to the right viewport edge', () => {
  const anchor = { left: 980, right: 1000, top: 300, bottom: 320, width: 20 };
  const p = computeTooltipPosition(anchor, TIP, VIEW, GAP);
  assert.equal(p.left, VIEW.width - TIP.width - GAP);   // 1000-200-8 = 792
});
