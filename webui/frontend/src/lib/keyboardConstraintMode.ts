// Shared keyboard-shortcut handling for color-state matrices.
//
// While the user holds one of the shortcut keys, clicking (or
// drag-painting) any cell in a matrix that opted-in via
// `startKeyboardConstraintMode()` sets the cell directly to the
// corresponding state, instead of going through the click-cycle.
//
// Mapping (case insensitive):
//   H -> HARD       (forbidden / non-disponibile, rosso)
//   P -> PREFERRED  (bonus, blu)
//   E -> ENFORCED   (must, verde scuro)
//   D -> DISLIKED   (SOFT positive penalty, giallo)
//   A -> ALLOWED    (free / consentito senza vincolo, verde chiaro)
//   N -> NORMAL     (alias of A: clear / reset cella)
//
// The actual state name produced depends on the matrix variant -- see
// `shortcutToMatrixState()` (AvailabilityMatrix-style: free/soft/hard/
// preferred/enforced) and `shortcutToRoomState()` (ClassroomGrid-style:
// allowed/soft/preferred/forbidden/enforced).
//
// Lifecycle: every matrix calls `startKeyboardConstraintMode()` on
// mount and the returned cleanup fn on destroy. The window listeners
// are installed once on the first mount and removed when the last
// matrix unmounts (ref-counted).

import { writable, type Writable } from "svelte/store";

export type ConstraintShortcut =
  | "h"
  | "p"
  | "e"
  | "d"
  | "a"
  | "n"
  | null;

/** Currently-held shortcut key (or null). Subscribed by matrices and
 *  by the small legend component. */
export const heldKey: Writable<ConstraintShortcut> = writable(null);

const KEY_MAP: Record<string, Exclude<ConstraintShortcut, null>> = {
  h: "h", H: "h",
  p: "p", P: "p",
  e: "e", E: "e",
  d: "d", D: "d",
  a: "a", A: "a",
  n: "n", N: "n",
};

let _refCount = 0;
let _cleanup: (() => void) | null = null;

function _shouldIgnore(target: EventTarget | null): boolean {
  // Don't intercept when the user is typing in an input / textarea /
  // contenteditable. Otherwise typing the letter "h" in a name field
  // would change the matrix state.
  const t = target as HTMLElement | null;
  if (!t || !t.tagName) return false;
  if (/^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName)) return true;
  if (t.isContentEditable) return true;
  return false;
}

/**
 * Register the global key listeners (idempotent / ref-counted).
 * Returns a cleanup function that the caller MUST call on destroy.
 */
export function startKeyboardConstraintMode(): () => void {
  if (typeof window === "undefined") return () => {};
  _refCount++;
  if (_refCount === 1) {
    const onDown = (ev: KeyboardEvent): void => {
      if (_shouldIgnore(ev.target)) return;
      const k = KEY_MAP[ev.key];
      if (k) heldKey.set(k);
    };
    const onUp = (ev: KeyboardEvent): void => {
      const k = KEY_MAP[ev.key];
      if (k) heldKey.set(null);
    };
    const onBlur = (): void => heldKey.set(null);
    window.addEventListener("keydown", onDown);
    window.addEventListener("keyup", onUp);
    window.addEventListener("blur", onBlur);
    _cleanup = () => {
      window.removeEventListener("keydown", onDown);
      window.removeEventListener("keyup", onUp);
      window.removeEventListener("blur", onBlur);
      heldKey.set(null);
    };
  }
  let released = false;
  return () => {
    if (released) return;
    released = true;
    _refCount--;
    if (_refCount <= 0) {
      _refCount = 0;
      if (_cleanup) {
        _cleanup();
        _cleanup = null;
      }
    }
  };
}

// ============================================================
// State mapping per matrix variant
// ============================================================

export type AvailabilityState =
  | "free"
  | "soft"
  | "hard"
  | "preferred"
  | "enforced";

export type RoomState =
  | "allowed"
  | "soft"
  | "preferred"
  | "forbidden"
  | "enforced";

/**
 * Resolve the held shortcut to an AvailabilityMatrix-style state.
 * Returns null if no shortcut is held (caller falls back to its own
 * click-cycle).
 */
export function shortcutToMatrixState(
  k: ConstraintShortcut,
): AvailabilityState | null {
  switch (k) {
    case "h":
      return "hard";
    case "p":
      return "preferred";
    case "e":
      return "enforced";
    case "d":
      return "soft";
    case "a":
    case "n":
      return "free";
    default:
      return null;
  }
}

/** Resolve the held shortcut to a ClassroomGrid-style state. */
export function shortcutToRoomState(
  k: ConstraintShortcut,
): RoomState | null {
  switch (k) {
    case "h":
      return "forbidden";
    case "p":
      return "preferred";
    case "e":
      return "enforced";
    case "d":
      return "soft";
    case "a":
    case "n":
      return "allowed";
    default:
      return null;
  }
}

// ============================================================
// Static metadata for the legend UI
// ============================================================

export interface ShortcutLegendItem {
  key: "H" | "P" | "E" | "D" | "A" | "N";
  shortcut: Exclude<ConstraintShortcut, null>;
  label: string;       // human-readable
  swatch: string;      // tailwind classes for the colour swatch
}

export const LEGEND_ITEMS: readonly ShortcutLegendItem[] = [
  { key: "H", shortcut: "h",
    label: "HARD",
    swatch: "bg-red-300 border-red-500" },
  { key: "P", shortcut: "p",
    label: "PREFERITO",
    swatch: "bg-sky-200 border-sky-400" },
  { key: "E", shortcut: "e",
    label: "ENFORCED",
    swatch: "bg-emerald-700 border-emerald-900" },
  { key: "D", shortcut: "d",
    label: "DISLIKED (soft +)",
    swatch: "bg-amber-200 border-amber-400" },
  { key: "A", shortcut: "a",
    label: "ALLOWED (libero)",
    swatch: "bg-emerald-50 border-emerald-300" },
  { key: "N", shortcut: "n",
    label: "RESET",
    swatch: "bg-emerald-50 border-emerald-300" },
];
