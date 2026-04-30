// Frontend utility helpers shared across pages.

import { writable, type Writable } from "svelte/store";

/**
 * Deep-clone with the modern API. Falls back to the JSON trick for the
 * unusual case where the runtime doesn't expose structuredClone (very
 * old browsers, Jest without polyfill). Replaces the
 *   editing = JSON.parse(JSON.stringify(row))
 * pattern duplicated in every page.
 */
export function cloneRow<T>(row: T): T {
  if (row == null) return row;
  if (typeof structuredClone === "function") {
    try {
      return structuredClone(row);
    } catch {
      /* fall through */
    }
  }
  return JSON.parse(JSON.stringify(row)) as T;
}

/**
 * Run an async task while a Svelte writable boolean tracks busy state.
 * The boolean stays true until the promise resolves OR rejects, so the
 * caller can guard buttons via `disabled={$busy}`.
 *
 * Returns the result of `fn()` (or re-throws).
 */
export async function runWithBusy<T>(
  busyStore: Writable<boolean>,
  fn: () => Promise<T>,
): Promise<T> {
  busyStore.set(true);
  try {
    return await fn();
  } finally {
    busyStore.set(false);
  }
}

export interface BusyStore extends Writable<boolean> {
  /** Convenience: run an async fn while the store is `true`. */
  run<T>(fn: () => Promise<T>): Promise<T>;
}

/**
 * Tiny factory for a busy store. Same shape as Svelte writables but with
 * a `.run(fn)` convenience method.
 *
 *   const busy = busyStore();
 *   {#if $busy}...{/if}
 *   await busy.run(async () => api.put(...));
 */
export function busyStore(): BusyStore {
  const s = writable(false);
  return {
    subscribe: s.subscribe,
    set: s.set,
    update: s.update,
    run<T>(fn: () => Promise<T>): Promise<T> {
      return runWithBusy(s, fn);
    },
  };
}

/**
 * Format a Date / ISO string safely. Used by tables and pickers when
 * birth_date / created_at fields come back as strings.
 */
export function fmtDate(d: Date | string | null | undefined): string {
  if (d == null || d === "") return "";
  try {
    const dt = d instanceof Date ? d : new Date(d);
    if (Number.isNaN(dt.getTime())) return String(d);
    const y = dt.getFullYear();
    const m = String(dt.getMonth() + 1).padStart(2, "0");
    const da = String(dt.getDate()).padStart(2, "0");
    return `${y}-${m}-${da}`;
  } catch {
    return String(d);
  }
}

/**
 * Debounce: returns a wrapped fn that delays calls until `ms` of
 * inactivity. Used by query bars in lists to avoid re-fetching on
 * every keystroke.
 */
export function debounce<F extends (...args: never[]) => unknown>(
  fn: F,
  ms = 250,
): (...args: Parameters<F>) => void {
  let h: ReturnType<typeof setTimeout> | null = null;
  return (...args: Parameters<F>) => {
    if (h) clearTimeout(h);
    h = setTimeout(() => fn(...args), ms);
  };
}
