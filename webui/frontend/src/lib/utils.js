// Frontend utility helpers shared across pages.

import { writable } from 'svelte/store';

/**
 * Deep-clone with the modern API. Falls back to the JSON trick for the
 * unusual case where the runtime doesn't expose structuredClone (very
 * old browsers, Jest without polyfill). Replaces the
 *   editing = JSON.parse(JSON.stringify(row))
 * pattern duplicated in every page.
 */
export function cloneRow(row) {
  if (row == null) return row;
  if (typeof structuredClone === 'function') {
    try { return structuredClone(row); } catch { /* fall through */ }
  }
  return JSON.parse(JSON.stringify(row));
}

/**
 * Run an async task while a Svelte writable boolean tracks busy state.
 * The boolean stays true until the promise resolves OR rejects, so the
 * caller can guard buttons via `disabled={$busy}`.
 *
 *   const busy = writable(false);
 *   runWithBusy(busy, async () => { ... });
 *
 * Returns the result of `fn()` (or re-throws).
 */
export async function runWithBusy(busyStore, fn) {
  busyStore.set(true);
  try {
    return await fn();
  } finally {
    busyStore.set(false);
  }
}

/**
 * Tiny factory for a busy store. Same shape Svelte writables but with
 * `.run(fn)` convenience method.
 *
 *   const busy = busyStore();
 *   ...
 *   {#if $busy}...{/if}
 *   await busy.run(async () => api.put(...));
 */
export function busyStore() {
  const s = writable(false);
  return {
    subscribe: s.subscribe,
    set: s.set,
    update: s.update,
    run: (fn) => runWithBusy(s, fn),
  };
}

/**
 * Format a Date / ISO string safely. Used by tables and pickers when
 * birth_date / created_at fields come back as strings.
 */
export function fmtDate(d) {
  if (d == null || d === '') return '';
  try {
    const dt = (d instanceof Date) ? d : new Date(d);
    if (Number.isNaN(dt.getTime())) return String(d);
    const y = dt.getFullYear();
    const m = String(dt.getMonth() + 1).padStart(2, '0');
    const da = String(dt.getDate()).padStart(2, '0');
    return `${y}-${m}-${da}`;
  } catch { return String(d); }
}

/**
 * Debounce: returns a wrapped fn that delays calls until `ms` of
 * inactivity. Used by query bars in lists to avoid re-fetching on
 * every keystroke.
 */
export function debounce(fn, ms = 250) {
  let h = null;
  return (...args) => {
    if (h) clearTimeout(h);
    h = setTimeout(() => fn(...args), ms);
  };
}
