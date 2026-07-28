/**
 * Tests for $lib/off_grid.ts — surfacing lessons that fall outside the
 * configured Tab Ore grid so they don't silently vanish from the view.
 *
 *   node --experimental-strip-types --test webui/frontend/src/lib/off_grid.test.mjs
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';

import { offGridLessons, slotKey } from './off_grid.ts';

const configured = new Set(['0-8', '0-9', '1-8']);

test('lessons on configured slots are not flagged', () => {
  const lessons = [
    { day: 0, hour: 8, subject: 'Mat' },
    { day: 1, hour: 8, subject: 'Ita' },
  ];
  assert.deepEqual(offGridLessons(lessons, configured), []);
});

test('lessons on an unconfigured (day, hour) are flagged', () => {
  const lessons = [
    { day: 0, hour: 8, subject: 'Mat' },   // ok
    { day: 0, hour: 13, subject: 'Fis' },  // off-grid: hour 13 not configured
    { day: 5, hour: 8, subject: 'Sto' },   // off-grid: day 5 not configured
  ];
  const out = offGridLessons(lessons, configured);
  assert.equal(out.length, 2);
  assert.deepEqual(out.map((l) => l.subject), ['Fis', 'Sto']);
});

test('pool entries (null day/hour) are ignored', () => {
  const lessons = [
    { day: null, hour: null, subject: 'Pool' },
    { day: 0, hour: null, subject: 'Half' },
  ];
  assert.deepEqual(offGridLessons(lessons, configured), []);
});

test('slotKey matches the configured-slot encoding', () => {
  assert.equal(slotKey(2, 10), '2-10');
});
