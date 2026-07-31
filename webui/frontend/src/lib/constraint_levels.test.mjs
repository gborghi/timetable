/**
 * Smoke tests for $lib/constraint_levels.ts — the single source of truth
 * for the 5-state taxonomy (HARD/SOFT/PREFERRED/ENFORCED/ALLOWED).
 *
 * Uses Node's built-in test runner (node:test) plus type-stripping so we
 * don't need a TS toolchain. Run with:
 *
 *   node --experimental-strip-types --test webui/frontend/src/lib/constraint_levels.test.mjs
 */

import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  LEVELS, LOGICAL_KINDS, LEVEL_LABEL, LEVEL_PILL_CLASS, LEVEL_CELL_CLASS,
  DEFAULT_PENALTY, LEVEL_GLOSS, LEGEND_LEVELS,
  kindFromRule, levelPill, levelLabel, levelCellClass,
  payloadFromKind, clampPenalty,
} from './constraint_levels.ts';

test('LEVELS includes the 5 canonical states + forbidden alias', () => {
  for (const k of ['allowed', 'soft', 'preferred', 'hard', 'enforced', 'forbidden']) {
    assert.ok(LEVELS.includes(k), `missing level: ${k}`);
  }
});

test('LOGICAL_KINDS has exactly 4 kinds (no allowed/forbidden)', () => {
  assert.deepEqual([...LOGICAL_KINDS].sort(),
                   ['enforced', 'hard', 'preferred', 'soft']);
});

test('LEVEL_LABEL covers every LEVELS entry', () => {
  for (const lv of LEVELS) {
    assert.ok(LEVEL_LABEL[lv], `LEVEL_LABEL missing for ${lv}`);
  }
});

test('LEVEL_PILL_CLASS and LEVEL_CELL_CLASS cover every LEVELS entry', () => {
  for (const lv of LEVELS) {
    assert.ok(LEVEL_PILL_CLASS[lv], `LEVEL_PILL_CLASS missing for ${lv}`);
    assert.ok(LEVEL_CELL_CLASS[lv], `LEVEL_CELL_CLASS missing for ${lv}`);
  }
});

test('DEFAULT_PENALTY signs match domain semantics', () => {
  // SOFT: positive penalty (we want LESS of these violations).
  assert.ok(DEFAULT_PENALTY.soft > 0);
  // PREFERRED: negative penalty (we want MORE of these — reward).
  assert.ok(DEFAULT_PENALTY.preferred < 0);
  // HARD/ENFORCED/ALLOWED: zero (handled by is_hard or no objective term).
  assert.equal(DEFAULT_PENALTY.hard, 0);
  assert.equal(DEFAULT_PENALTY.enforced, 0);
  assert.equal(DEFAULT_PENALTY.allowed, 0);
});

test('kindFromRule trusts explicit rule.kind when valid', () => {
  assert.equal(kindFromRule({ kind: 'hard' }),      'hard');
  assert.equal(kindFromRule({ kind: 'soft' }),      'soft');
  assert.equal(kindFromRule({ kind: 'preferred' }), 'preferred');
  assert.equal(kindFromRule({ kind: 'enforced' }),  'enforced');
});

test('kindFromRule falls back to is_hard for legacy rows', () => {
  assert.equal(kindFromRule({ is_hard: true }), 'hard');
});

test('kindFromRule infers PREFERRED from negative soft_penalty (legacy)', () => {
  assert.equal(kindFromRule({ is_hard: false, soft_penalty: -100 }), 'preferred');
});

test('kindFromRule defaults to soft when nothing matches', () => {
  assert.equal(kindFromRule({}), 'soft');
  assert.equal(kindFromRule(null), 'soft');
});

test('levelPill returns the pill class or fallback', () => {
  assert.equal(levelPill('hard'), 'pill-c-hard');
  assert.equal(levelPill('preferred'), 'pill-c-preferred');
  assert.equal(levelPill('garbage'), 'pill');
});

test('levelLabel uppercases unknown levels', () => {
  assert.equal(levelLabel('hard'), 'HARD');
  assert.equal(levelLabel('mystery'), 'MYSTERY');
  assert.equal(levelLabel(null), '?');
});

test('levelCellClass returns Tailwind tokens or empty', () => {
  assert.match(levelCellClass('hard'), /bg-c-hard-bg/);
  assert.equal(levelCellClass('garbage'), '');
});

test('payloadFromKind: HARD/ENFORCED set is_hard=true', () => {
  const ph = payloadFromKind('hard', 'aula:LAB', 1);
  assert.equal(ph.is_hard, true);
  assert.equal(ph.kind, 'hard');
  assert.equal(ph.expression, 'aula:LAB');

  const pe = payloadFromKind('enforced', 'aula:GYM', 1);
  assert.equal(pe.is_hard, true);
});

test('payloadFromKind: SOFT clamps to positive penalty', () => {
  const p = payloadFromKind('soft', 'docente:X', -50);
  assert.equal(p.is_hard, false);
  assert.equal(p.soft_penalty, 50);
});

test('payloadFromKind: PREFERRED clamps to negative penalty', () => {
  const p = payloadFromKind('preferred', 'aula:LAB1', 30);
  assert.equal(p.is_hard, false);
  assert.equal(p.soft_penalty, -30);
});

test('payloadFromKind: invalid penalty falls back to 100', () => {
  const p = payloadFromKind('soft', 'x', 'NaN');
  assert.equal(p.soft_penalty, 100);
});

test('payloadFromKind: extra fields are merged', () => {
  const p = payloadFromKind('soft', 'x', 10, { class_id: 7 });
  assert.equal(p.class_id, 7);
});

test('clampPenalty enforces sign per level', () => {
  assert.equal(clampPenalty('soft', 50),  50);   // already positive: keep
  assert.equal(clampPenalty('soft', -50), 50);   // flip to positive
  assert.equal(clampPenalty('preferred', -50), -50);  // already negative
  assert.equal(clampPenalty('preferred', 50),  -50);  // flip to negative
});

test('clampPenalty falls back to DEFAULT_PENALTY on non-numeric', () => {
  // Note: Number('') is 0 (finite), so empty strings are NOT a fallback
  // trigger. Only true non-numerics like 'x' or undefined produce NaN.
  assert.equal(clampPenalty('soft', 'x'),       DEFAULT_PENALTY.soft);
  assert.equal(clampPenalty('preferred', 'xx'), DEFAULT_PENALTY.preferred);
  assert.equal(clampPenalty('hard', undefined), DEFAULT_PENALTY.hard);
});

test('clampPenalty leaves other levels untouched (sign-wise)', () => {
  assert.equal(clampPenalty('hard', 0), 0);
  assert.equal(clampPenalty('allowed', 999), 999);
});

test('LEVEL_GLOSS covers every LEVELS entry (legenda pagina Vincoli)', () => {
  for (const lv of LEVELS) {
    assert.ok(LEVEL_GLOSS[lv], `LEVEL_GLOSS missing for ${lv}`);
  }
});

test('LEGEND_LEVELS lists the 5 canonical states, forbidden excluded', () => {
  assert.deepEqual([...LEGEND_LEVELS],
                   ['hard', 'soft', 'preferred', 'enforced', 'allowed']);
});
