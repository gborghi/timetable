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
