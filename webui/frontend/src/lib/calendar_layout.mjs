// Pure helpers for the WeeklyCalendarView calendar-grid layout.
// Extracted to a plain ES module so they can be unit-tested without
// having to mount the Svelte component.

export const PX_PER_HOUR = 40;
export const BG_START_DEFAULT = 7;
export const BG_END_DEFAULT = 19;

/** Parse "HH:MM" into a fractional hour number (e.g. "08:30" -> 8.5).
 * Returns 0 on a malformed input so callers never see NaN. */
export function timeToHours(t) {
  if (!t || typeof t !== "string") return 0;
  const parts = t.split(":");
  const h = parseInt(parts[0], 10);
  const m = parseInt(parts[1], 10);
  return (Number.isFinite(h) ? h : 0) + (Number.isFinite(m) ? m / 60 : 0);
}

/** Compute the auto-fitted background hour range for a list of
 * active days. Always includes the [BG_START_DEFAULT, BG_END_DEFAULT]
 * window so the calendar looks balanced even when all slots fall in
 * a narrow band; expands beyond that window if any slot starts
 * earlier or ends later. Returns { lo, hi } as integer hours. */
export function bgRangeFor(activeDays) {
  let lo = BG_START_DEFAULT;
  let hi = BG_END_DEFAULT;
  for (const d of activeDays || []) {
    for (const s of d.slots || []) {
      lo = Math.min(lo, Math.floor(timeToHours(s.start_time)));
      hi = Math.max(hi, Math.ceil(timeToHours(s.end_time)));
    }
  }
  return { lo, hi };
}

/** Pixel offset (from the top of the body grid) for an event whose
 * start_time string is `t`, given the chosen background range. */
export function pxFromTime(t, range, pxPerHour = PX_PER_HOUR) {
  return (timeToHours(t) - range.lo) * pxPerHour;
}

/** Pixel height for a slot { start_time, end_time }, with a 24px
 * floor so very short slots stay clickable. */
export function pxDuration(slot, pxPerHour = PX_PER_HOUR) {
  const dt = timeToHours(slot.end_time) - timeToHours(slot.start_time);
  return Math.max(24, dt * pxPerHour);
}

/** Pixel height of the entire body grid. */
export function gridHeight(range, pxPerHour = PX_PER_HOUR) {
  return (range.hi - range.lo) * pxPerHour;
}

/** Inverse of pxFromTime: convert a pixel offset back to an HH:MM
 * string, snapping to ``snapMinutes`` (default 15 min). Clamps the
 * result inside the [range.lo*60, range.hi*60] minute window so the
 * caller never sees -01:00 or 25:00. */
export function pxToTime(
  yPx, range, pxPerHour = PX_PER_HOUR, snapMinutes = 15,
) {
  const totalMin = (yPx / pxPerHour + range.lo) * 60;
  const lo = range.lo * 60;
  const hi = range.hi * 60;
  const clamped = Math.max(lo, Math.min(hi, totalMin));
  const snapped = Math.round(clamped / snapMinutes) * snapMinutes;
  const h = Math.floor(snapped / 60);
  const m = snapped % 60;
  return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}`;
}

/** Compare two HH:MM strings numerically. Returns negative / 0 /
 * positive following the usual Comparator contract. */
export function compareTimes(a, b) {
  return timeToHours(a) - timeToHours(b);
}

/** Build a fresh slot record from a [start_time, end_time] pair.
 * The legacy_hour_number is set to floor(start) so the engine's
 * legacy hour codes line up with the slot's start hour (the same
 * convention the seed migration uses). The label defaults to
 * "${idx+1}ª ora" so newly created slots match the existing UI. */
export function makeSlot(startTime, endTime, slotIndex) {
  const [h] = startTime.split(":").map((x) => parseInt(x, 10));
  return {
    slot_index: slotIndex,
    start_time: startTime,
    end_time: endTime,
    label: `${slotIndex + 1}ª ora`,
    legacy_hour_number: Number.isFinite(h) ? h : 0,
  };
}

/** Sort the slots of a single day by start_time and re-number their
 * slot_index 0..N-1 so the engine's hour_idx contract holds. Returns
 * a new array; does NOT mutate the input. */
export function reindexSlots(slots) {
  const sorted = [...(slots || [])].sort(
    (a, b) => compareTimes(a.start_time, b.start_time));
  return sorted.map((s, i) => ({ ...s, slot_index: i }));
}

/** Edit-mode overlap clamp: given a candidate [start, end] window
 * and the OTHER existing slots in the same day, clamp the window so
 * it does not overlap any of them. Returns null if the candidate
 * has zero or negative duration after clamping (caller should drop
 * it in that case). */
export function clampToOpenWindow(start, end, otherSlots) {
  let s = timeToHours(start);
  let e = timeToHours(end);
  if (e <= s) return null;
  for (const o of otherSlots || []) {
    const os = timeToHours(o.start_time);
    const oe = timeToHours(o.end_time);
    // overlap: shrink to the closer side of the conflicting slot.
    if (s < oe && e > os) {
      // pick the side with more remaining room.
      const leftRoom = os - s;
      const rightRoom = e - oe;
      if (leftRoom >= rightRoom) {
        e = Math.min(e, os);
      } else {
        s = Math.max(s, oe);
      }
    }
    if (e <= s) return null;
  }
  const fmt = (h) => {
    const totalMin = Math.round(h * 60);
    const hh = Math.floor(totalMin / 60);
    const mm = totalMin % 60;
    return `${String(hh).padStart(2, "0")}:${String(mm).padStart(2, "0")}`;
  };
  return { start_time: fmt(s), end_time: fmt(e) };
}
