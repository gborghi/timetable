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
