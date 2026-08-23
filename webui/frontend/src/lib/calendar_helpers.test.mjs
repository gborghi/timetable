import test from "node:test";
import assert from "node:assert/strict";

import {
  SLOT_STACK_CAP,
  mountedCardCount,
  primaryLesson,
  slotRenderPlan,
} from "./calendar_helpers.mjs";

const L = (id, extra = {}) => ({ id, subject: "Matematica", ...extra });

test("slotRenderPlan: empty slot", () => {
  assert.deepEqual(slotRenderPlan([]), {
    visible: [], overflow: [], collapsed: false,
  });
});

test("slotRenderPlan: few global lessons stay fully painted", () => {
  const rows = [L(1), L(2)];
  const plan = slotRenderPlan(rows, { type: null, id: null });
  assert.equal(plan.collapsed, false);
  assert.deepEqual(plan.visible.map((l) => l.id), [1, 2]);
  assert.equal(plan.overflow.length, 0);
});

test("slotRenderPlan: global overflow past SLOT_STACK_CAP", () => {
  const rows = Array.from({ length: SLOT_STACK_CAP + 4 }, (_, i) => L(i + 1));
  const plan = slotRenderPlan(rows, { type: null });
  assert.equal(plan.collapsed, true);
  assert.equal(plan.visible.length, SLOT_STACK_CAP);
  assert.equal(plan.overflow.length, 4);
  assert.deepEqual(plan.visible.map((l) => l.id), [1, 2, 3]);
});

test("slotRenderPlan: filtered view collapses to the primary lesson", () => {
  const rows = [
    L(1, { subject: "Sostegno" }),
    L(2, { subject: "Matematica" }),
    L(3, { subject: "Sostegno" }),
  ];
  const plan = slotRenderPlan(rows, { type: "class", id: "1A" });
  assert.equal(plan.collapsed, true);
  assert.equal(primaryLesson(rows).id, 2);
  assert.deepEqual(plan.visible.map((l) => l.id), [2]);
  assert.deepEqual(plan.overflow.map((l) => l.id), [1, 3]);
});

test("mountedCardCount: 90-class global slot mounts only SLOT_STACK_CAP", () => {
  assert.equal(mountedCardCount(0), 0);
  assert.equal(mountedCardCount(2), 2);
  assert.equal(mountedCardCount(90), SLOT_STACK_CAP);
  assert.equal(mountedCardCount(90, { type: "class" }), 1);
  // 6 days × 6 hours × 90 classes would have been 3240 cards.
  const slots = Array.from({ length: 36 }, () => 90);
  const mounted = slots.reduce(
    (n, size) => n + mountedCardCount(size, { type: null }), 0);
  assert.equal(mounted, 36 * SLOT_STACK_CAP);
  assert.ok(mounted < 200);
});
