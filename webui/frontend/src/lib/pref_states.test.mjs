import test from "node:test";
import assert from "node:assert/strict";
import { PREF_STATE_BADGE, prefCellAriaLabel } from "./pref_states.mjs";

test("prefCellAriaLabel: stato e peso in testo, non solo colore", () => {
  assert.equal(
    prefCellAriaLabel("Lab1", "soft", 100),
    "Lab1: SOFT (penalità) 100. Invio o click per passare allo stato successivo");
  assert.match(prefCellAriaLabel("Lab1", "preferred", -100), /preferita \(bonus\) 100\./);
  assert.match(prefCellAriaLabel("Lab1", "forbidden", 0), /vietata \(HARD\)\./);
  assert.match(prefCellAriaLabel("Lab1", "boh"), /consentita\./);
});

test("PREF_STATE_BADGE: ogni stato non di default ha un badge", () => {
  for (const s of ["soft", "preferred", "forbidden", "enforced"]) {
    assert.ok(PREF_STATE_BADGE[s]);
  }
  assert.equal(PREF_STATE_BADGE.allowed, "");
});
