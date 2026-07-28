// A lesson whose (day, hour) does not match a slot configured in Tab Ore
// has no cell in WeeklyCalendarView, so it is never rendered — it simply
// vanishes from the timetable view. That hides real data (e.g. after the
// school week is edited to drop an hour that still has placed lessons).
// This helper surfaces those lessons so the UI can warn instead of
// silently swallowing them.

export interface GridLesson {
  day: number | null;
  hour: number | null;
  [k: string]: unknown;
}

/** The "day-hour" key used to index configured slots. */
export function slotKey(day: number, hour: number): string {
  return day + '-' + hour;
}

/**
 * Lessons that carry a concrete (day, hour) whose slot is NOT present in
 * `configuredSlots` (a Set of "day-hour" keys derived from Tab Ore).
 * Pool/unscheduled entries (null day or hour) are ignored — they are not
 * expected to occupy the grid.
 */
export function offGridLessons<T extends GridLesson>(
  lessons: readonly T[],
  configuredSlots: ReadonlySet<string>,
): T[] {
  const out: T[] = [];
  for (const l of lessons) {
    if (l.day == null || l.hour == null) continue;
    if (!configuredSlots.has(slotKey(l.day, l.hour))) out.push(l);
  }
  return out;
}
