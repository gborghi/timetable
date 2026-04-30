import { writable, derived, get } from 'svelte/store';
import { api } from './api.js';

// Dataset counters surfaced in the header pills + Dashboard cards.
export const datasetState = writable({
  classes: 0, teachers: 0, subjects: 0,
  assignments: 0, classrooms: 0, solutions: 0,
  active_solution: null
});

// Toast: shape is { msg, tone, action? }. `action` is an optional
//   { label, fn }
// the Toast component renders as an inline button (used by UNDO).
export const toast = writable(null);
let toastTimer;

/**
 * Flash a toast. `optsOrMs` accepts either a number (ms TTL) or an
 * options object: { ms, action: { label, fn }, persistent }.
 */
export function flash(msg, tone = 'info', optsOrMs = 3500) {
  clearTimeout(toastTimer);
  let ms = 3500;
  let action = null;
  let persistent = false;
  if (typeof optsOrMs === 'number') {
    ms = optsOrMs;
  } else if (optsOrMs && typeof optsOrMs === 'object') {
    if (typeof optsOrMs.ms === 'number') ms = optsOrMs.ms;
    if (optsOrMs.action) action = optsOrMs.action;
    if (optsOrMs.persistent) persistent = true;
  }
  toast.set({ msg, tone, action });
  if (!persistent) {
    toastTimer = setTimeout(() => toast.set(null), ms);
  }
}

/** Clear any active toast immediately. Used by UNDO confirmations. */
export function clearToast() {
  clearTimeout(toastTimer);
  toast.set(null);
}

// Mutation counter: bumped after every successful CRUD write. Pages
// can subscribe to it to invalidate their lists. Centralised so
// individual pages don't need to call refreshDataset() manually.
export const mutationCounter = writable(0);
export function bumpMutation() {
  mutationCounter.update((n) => n + 1);
}

// `datasetState` auto-refreshes when mutationCounter changes (debounced
// by a small idle so multiple concurrent mutations coalesce).
let datasetRefreshTimer = null;
function scheduleRefresh() {
  if (datasetRefreshTimer) clearTimeout(datasetRefreshTimer);
  datasetRefreshTimer = setTimeout(() => { refreshDataset(); }, 120);
}
mutationCounter.subscribe(() => scheduleRefresh());

export async function refreshDataset() {
  try {
    const s = await api.get('/api/dataset/state');
    datasetState.set(s);
  } catch (e) {
    // No flash here -- the network-status store already surfaces the
    // disconnect. flash() during init creates noise on first load if
    // the backend is briefly unreachable.
  }
}

export const datasetEmpty = derived(datasetState, ($s) =>
  ($s.classes ?? 0) === 0 && ($s.teachers ?? 0) === 0
);

// ----- Network status ----------------------------------------------------
//
// Periodic /api/health ping to detect when the backend is unreachable.
// `networkOnline` is true at boot and flips to false after the FIRST
// failed ping; flips back to true on the first successful ping.

export const networkOnline = writable(true);
let pingTimer = null;
let pingInFlight = false;

async function pingHealth() {
  if (pingInFlight) return;
  pingInFlight = true;
  try {
    await api.get('/api/health', { retry: false });
    if (!get(networkOnline)) networkOnline.set(true);
  } catch {
    if (get(networkOnline)) networkOnline.set(false);
  } finally {
    pingInFlight = false;
  }
}

export function startNetworkMonitor(intervalMs = 30000) {
  if (typeof window === 'undefined') return;
  if (pingTimer) return;
  // Initial probe (deferred to next tick so the app boots first)
  setTimeout(() => { pingHealth(); }, 500);
  pingTimer = setInterval(pingHealth, intervalMs);
}

export function stopNetworkMonitor() {
  if (pingTimer) clearInterval(pingTimer);
  pingTimer = null;
}
