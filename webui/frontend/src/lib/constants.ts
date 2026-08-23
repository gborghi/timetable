import type { RoomKind } from "./types";

export const DAYS: readonly number[] = [1, 2, 3, 4, 5, 6];
export const HOURS: readonly number[] = [8, 9, 10, 11, 12, 13];

export const DAY_NAMES_IT: Record<number, string> = {
  1: "Lun", 2: "Mar", 3: "Mer", 4: "Gio", 5: "Ven", 6: "Sab",
};

export const DAY_NAMES_EN: readonly string[] = [
  "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday",
];

/** Italian label for each English day name. The backend persists
 * teacher.free_day in English (e.g. "Saturday"); use this map to
 * render the value in the UI without changing the wire format. */
export const DAY_NAMES_EN_TO_IT: Record<string, string> = {
  Monday:    "Lunedi",
  Tuesday:   "Martedi",
  Wednesday: "Mercoledi",
  Thursday:  "Giovedi",
  Friday:    "Venerdi",
  Saturday:  "Sabato",
};

/** One day from GET /api/working-hours/config. Codes/labels are
 * display-only; the engine key is ``legacy_day_number``. */
export interface CalendarDay {
  id?: number;
  code?: string;
  label?: string;
  position?: number;
  legacy_day_number: number;
  is_active?: boolean;
  slots?: Array<{ legacy_hour_number?: number }>;
}

export interface CalendarConfig {
  days?: CalendarDay[];
  max_slots_per_day?: number;
}

function _activeDays(config: CalendarConfig | null | undefined): CalendarDay[] {
  return (config?.days || []).filter((d) => d && d.is_active !== false);
}

/** Configured day IDs in display order. Falls back to lun–sab 1..6. */
export function calendarDays(config: CalendarConfig | null | undefined): number[] {
  const days = _activeDays(config);
  if (days.length) return days.map((d) => d.legacy_day_number);
  return [...DAYS];
}

/** Uniform hour codes from the first active day. Falls back to 8..13. */
export function calendarHours(config: CalendarConfig | null | undefined): number[] {
  const days = _activeDays(config);
  const first = days.find((d) => (d.slots || []).length);
  if (first?.slots?.length) {
    return first.slots
      .map((s) => s.legacy_hour_number)
      .filter((h): h is number => typeof h === "number");
  }
  return [...HOURS];
}

/** Display label for a day ID. Rename-safe: looks up the configured
 * entity, then the lun–sab preset, then the numeric ID. */
export function calendarDayName(
  dayId: number,
  config: CalendarConfig | null | undefined,
): string {
  const d = _activeDays(config).find((x) => x.legacy_day_number === dayId)
    ?? (config?.days || []).find((x) => x.legacy_day_number === dayId);
  if (d) return d.label || d.code || String(dayId);
  return DAY_NAMES_IT[dayId] || String(dayId);
}

export interface RoomKindOption {
  value: RoomKind;
  label: string;
}

export const ROOM_KINDS: readonly RoomKindOption[] = [
  { value: "standard",        label: "Aula standard" },
  { value: "lab_chimica",     label: "Lab chimica" },
  { value: "lab_fisica",      label: "Lab fisica" },
  { value: "lab_informatica", label: "Lab informatica" },
  { value: "lab_linguistico", label: "Lab linguistico" },
  { value: "palestra",        label: "Palestra" },
  { value: "biblioteca",      label: "Biblioteca" },
  { value: "aula_speciale",   label: "Aula speciale" },
];

/**
 * Default values for teacher records and CP-SAT optimisation profiles.
 * Centralised so the UI doesn't sprinkle "magic numbers" across pages.
 */
export const TEACHER_DEFAULTS = {
  // Italian high-school cattedra: 18 hours per week (full-time).
  max_hours: 18,
  completion_hours: 0,
  exemption_hours: 0,
  disposizione_hours: 0,
  // No more than 5 consecutive hours teaching the same day.
  max_consecutive: 5,
  // Nessuna compresenza: il docente prenota sempre un'aula propria.
  // Il preset 'sempre' va scelto esplicitamente (tipicamente sostegno).
  compresenza: "mai",
  // Free day for teachers without an explicit preference.
  free_day: "Saturday",
  // Penalty weights for "no buchi" / "no day with 5h" / "no day with 1h"
  // soft constraints. Higher weight = stronger preference.
  pref_no_buchi_weight: 10,
  pref_no_five_weight: 30,
  pref_no_one_weight: 80,
} as const;

/** Default values for the optimisation wizard step 1 (CP-SAT profile). */
export const OPTIMIZE_DEFAULTS = {
  profile: "small",
  mode: "aggregated",
  margin: 0.05,
  base_max_hours: TEACHER_DEFAULTS.max_hours,
} as const;
