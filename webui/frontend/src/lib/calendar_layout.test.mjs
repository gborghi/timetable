// Unit tests for the WeeklyCalendarView calendar-grid layout helpers.
// Run with `node --test src/lib/calendar_layout.test.mjs` (the
// `npm test` script invokes this file alongside constraint_levels).

import test from "node:test";
import assert from "node:assert/strict";

import {
  PX_PER_HOUR,
  BG_START_DEFAULT,
  BG_END_DEFAULT,
  timeToHours,
  bgRangeFor,
  pxFromTime,
  pxDuration,
  gridHeight,
  pxToTime,
  compareTimes,
  makeSlot,
  reindexSlots,
  clampToOpenWindow,
} from "./calendar_layout.mjs";

test("timeToHours: parses HH:MM into fractional hours", () => {
  assert.equal(timeToHours("08:00"), 8);
  assert.equal(timeToHours("08:30"), 8.5);
  assert.equal(timeToHours("14:15"), 14.25);
  assert.equal(timeToHours("00:00"), 0);
  assert.equal(timeToHours("23:45"), 23.75);
});

test("timeToHours: returns 0 for malformed input (no NaN)", () => {
  assert.equal(timeToHours(""), 0);
  assert.equal(timeToHours(null), 0);
  assert.equal(timeToHours(undefined), 0);
  assert.equal(timeToHours("garbage"), 0);
});

test("bgRangeFor: empty input -> default 7-19 window", () => {
  assert.deepEqual(bgRangeFor([]), {
    lo: BG_START_DEFAULT,
    hi: BG_END_DEFAULT,
  });
  assert.deepEqual(bgRangeFor(null), { lo: 7, hi: 19 });
});

test("bgRangeFor: typical school day (8-14) stays inside 7-19", () => {
  const days = [
    { slots: [
      { start_time: "08:00", end_time: "09:00" },
      { start_time: "13:00", end_time: "14:00" },
    ] },
  ];
  // hi must remain 19 (the default), not shrink to 14.
  assert.deepEqual(bgRangeFor(days), { lo: 7, hi: 19 });
});

test("bgRangeFor: evening slots expand the upper bound", () => {
  const days = [
    { slots: [
      { start_time: "18:00", end_time: "21:30" },
    ] },
  ];
  assert.equal(bgRangeFor(days).hi, 22);  // ceil(21.5) = 22
});

test("bgRangeFor: pre-dawn slots expand the lower bound", () => {
  const days = [
    { slots: [
      { start_time: "06:30", end_time: "08:00" },
    ] },
  ];
  assert.equal(bgRangeFor(days).lo, 6);  // floor(6.5) = 6
});

test("pxFromTime: aligns 08:00 at the right offset for default range", () => {
  const range = { lo: 7, hi: 19 };
  // 08:00 = (8 - 7) * 40 = 40px down from the top of the body
  assert.equal(pxFromTime("08:00", range), 40);
  assert.equal(pxFromTime("07:00", range), 0);
  assert.equal(pxFromTime("13:30", range), 6.5 * PX_PER_HOUR);
});

test("pxDuration: 1-hour slot is exactly PX_PER_HOUR pixels tall", () => {
  const slot = { start_time: "08:00", end_time: "09:00" };
  assert.equal(pxDuration(slot), PX_PER_HOUR);
});

test("pxDuration: 90-minute lab is 1.5x as tall as a 1-hour slot", () => {
  const lab = { start_time: "08:00", end_time: "09:30" };
  const std = { start_time: "10:00", end_time: "11:00" };
  assert.equal(pxDuration(lab), 1.5 * pxDuration(std));
});

test("pxDuration: very short slots have a 24px floor", () => {
  // a 5-minute slot: 5/60 * 40 = 3.3px -> floored to 24
  const tiny = { start_time: "08:00", end_time: "08:05" };
  assert.equal(pxDuration(tiny), 24);
});

test("gridHeight: matches (hi - lo) * PX_PER_HOUR", () => {
  assert.equal(gridHeight({ lo: 7, hi: 19 }), 12 * PX_PER_HOUR);
  assert.equal(gridHeight({ lo: 6, hi: 22 }), 16 * PX_PER_HOUR);
});

test("pxToTime: round-trips with pxFromTime under 15-min snap", () => {
  const range = { lo: 7, hi: 19 };
  // 09:00 -> 80px -> snaps back to 09:00
  assert.equal(pxToTime(80, range), "09:00");
  // 09:07 (just past 9) snaps to 09:00 (closest 15-min boundary)
  assert.equal(pxToTime((2 + 7 / 60) * PX_PER_HOUR, range), "09:00");
  // 09:08 snaps UP to 09:15
  assert.equal(pxToTime((2 + 8 / 60) * PX_PER_HOUR, range), "09:15");
});

test("pxToTime: clamps to the bg window (no negative or 24+ hours)", () => {
  const range = { lo: 7, hi: 19 };
  // -200px clamps to range.lo
  assert.equal(pxToTime(-200, range), "07:00");
  // 9999px clamps to range.hi
  assert.equal(pxToTime(9999, range), "19:00");
});

test("compareTimes: orders HH:MM strings numerically", () => {
  assert.ok(compareTimes("08:00", "09:00") < 0);
  assert.ok(compareTimes("09:00", "08:00") > 0);
  assert.equal(compareTimes("10:30", "10:30"), 0);
  // sorts past 09:00 vs 10:00 (string vs numeric difference)
  assert.ok(compareTimes("09:30", "10:00") < 0);
});

test("makeSlot: produces a self-consistent record", () => {
  const s = makeSlot("08:30", "09:30", 0);
  assert.equal(s.slot_index, 0);
  assert.equal(s.start_time, "08:30");
  assert.equal(s.end_time, "09:30");
  assert.equal(s.label, "1ª ora");
  // legacy_hour_number = floor(start) so the engine's hour codes
  // align with the slot start.
  assert.equal(s.legacy_hour_number, 8);
});

test("reindexSlots: sorts by start_time and renumbers slot_index", () => {
  const slots = [
    { slot_index: 99, start_time: "10:00", end_time: "11:00" },
    { slot_index: 99, start_time: "08:00", end_time: "09:00" },
    { slot_index: 99, start_time: "09:00", end_time: "10:00" },
  ];
  const out = reindexSlots(slots);
  assert.deepEqual(out.map((s) => s.start_time),
                    ["08:00", "09:00", "10:00"]);
  assert.deepEqual(out.map((s) => s.slot_index), [0, 1, 2]);
  // does not mutate the input
  assert.equal(slots[0].slot_index, 99);
});

test("clampToOpenWindow: no conflict -> returns unchanged window", () => {
  const out = clampToOpenWindow("10:00", "11:00", [
    { start_time: "08:00", end_time: "09:00" },
    { start_time: "12:00", end_time: "13:00" },
  ]);
  assert.deepEqual(out, { start_time: "10:00", end_time: "11:00" });
});

test("clampToOpenWindow: conflict -> shrinks to nearest free side", () => {
  // Existing slot 09:30-10:30. Candidate 09:00-11:00 overlaps both
  // sides; left room (09:30 - 09:00 = 30 min) >= right room
  // (11:00 - 10:30 = 30 min, ties go to left), so shrink the END
  // to 09:30.
  const out = clampToOpenWindow("09:00", "11:00", [
    { start_time: "09:30", end_time: "10:30" },
  ]);
  assert.equal(out.start_time, "09:00");
  assert.equal(out.end_time, "09:30");
});

test("clampToOpenWindow: full overlap -> returns null (caller drops)", () => {
  const out = clampToOpenWindow("09:30", "10:00", [
    { start_time: "09:00", end_time: "10:30" },
  ]);
  assert.equal(out, null);
});

test("variable slots per day: SAT short morning vs MON full day", () => {
  // Realistic Tab Ore variable-slots scenario: lun 6 slots 8-14,
  // sab 4 slots 8-12. Auto-fitted background still spans 7-19 by
  // default (school day window), but pxDuration / pxFromTime
  // correctly position SAT events as 4 contiguous events at the
  // top, with NO event between 12-14 (the matching gridlines are
  // background-only, non-clickable).
  const days = [
    { legacy_day_number: 1, slots: [
      { slot_index: 0, start_time: "08:00", end_time: "09:00",
        legacy_hour_number: 8 },
      { slot_index: 1, start_time: "09:00", end_time: "10:00",
        legacy_hour_number: 9 },
      { slot_index: 2, start_time: "10:00", end_time: "11:00",
        legacy_hour_number: 10 },
      { slot_index: 3, start_time: "11:00", end_time: "12:00",
        legacy_hour_number: 11 },
      { slot_index: 4, start_time: "12:00", end_time: "13:00",
        legacy_hour_number: 12 },
      { slot_index: 5, start_time: "13:00", end_time: "14:00",
        legacy_hour_number: 13 },
    ] },
    { legacy_day_number: 6, slots: [
      { slot_index: 0, start_time: "08:00", end_time: "09:00",
        legacy_hour_number: 8 },
      { slot_index: 1, start_time: "09:00", end_time: "10:00",
        legacy_hour_number: 9 },
      { slot_index: 2, start_time: "10:00", end_time: "11:00",
        legacy_hour_number: 10 },
      { slot_index: 3, start_time: "11:00", end_time: "12:00",
        legacy_hour_number: 11 },
    ] },
  ];
  const range = bgRangeFor(days);
  // No slot extends beyond 14 -> hi stays at the default 19.
  assert.deepEqual(range, { lo: 7, hi: 19 });
  // MON has 6 events; SAT has 4 events -- each list maps to
  // exactly the configured slots (rendered in the template).
  assert.equal(days[0].slots.length, 6);
  assert.equal(days[1].slots.length, 4);
  // The 4 SAT events all sit between 8-12, none between 12-14.
  const satTops = days[1].slots.map(
    (s) => pxFromTime(s.start_time, range));
  assert.deepEqual(satTops, [40, 80, 120, 160]);  // 8:00..11:00
});
