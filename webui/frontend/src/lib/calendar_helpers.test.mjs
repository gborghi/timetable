import test from "node:test";
import assert from "node:assert/strict";

import {
  SLOT_STACK_CAP,
  mountedCardCount,
  primaryLesson,
  slotRenderPlan,
  splitClassName,
  classShortLabels,
  withDisplayLabels,
  lessonParts,
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

test("splitClassName: classe breve + indirizzo a parte", () => {
  assert.deepEqual(splitClassName("1A_Scientifico"), { short: "1A", indirizzo: "Scientifico" });
  assert.deepEqual(splitClassName("4B_ScienzeApplicate"), { short: "4B", indirizzo: "Scienze Applicate" });
  assert.deepEqual(splitClassName("1I_Linguistico_FRA_SPA"), { short: "1I", indirizzo: "Linguistico FRA SPA" });
  assert.deepEqual(splitClassName("3C"), { short: "3C", indirizzo: "" });
});

test("classShortLabels: '1A' solo se non ambiguo", () => {
  const m = classShortLabels(["1A_Scientifico", "1B_Classico", "1B_Scientifico"]);
  assert.equal(m.get("1A_Scientifico"), "1A");
  assert.equal(m.get("1B_Classico"), "1B_Classico");
  assert.equal(m.get("1B_Scientifico"), "1B_Scientifico");
});

test("withDisplayLabels + lessonParts usano le etichette, non i codici", () => {
  const [l] = withDisplayLabels(
    [{ class_name: "1A_Scientifico", subject: "Scienzemotorie", teacher_name: "Rossi" }],
    new Map([["Scienzemotorie", "Scienze motorie e sportive"]]),
    new Map([["1A_Scientifico", "1A"]]));
  assert.equal(l.class_name, "1A_Scientifico");
  assert.deepEqual(lessonParts(l, { type: null }), { primary: "1A", secondary: "Scienze motorie e sportive" });
  assert.deepEqual(lessonParts(l, { type: "class" }), { primary: "Scienze motorie e sportive", secondary: "Rossi" });
});
