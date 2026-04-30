import { writable, derived, get, type Writable } from "svelte/store";
import { api } from "./api";
import type { DatasetState } from "./types";

// Dataset counters surfaced in the header pills + Dashboard cards.
export const datasetState: Writable<DatasetState> = writable({
  classes: 0,
  teachers: 0,
  subjects: 0,
  assignments: 0,
  classrooms: 0,
  solutions: 0,
  curricula: 0,
  students: 0,
  groups: 0,
  active_solution: null,
});

// Toast: shape is { msg, tone, action? }. `action` is an optional
//   { label, fn }
// the Toast component renders as an inline button (used by UNDO).
export type ToastTone = "info" | "success" | "warning" | "error";

export interface ToastAction {
  label: string;
  fn?: () => void | Promise<void>;
}

export interface Toast {
  msg: string;
  tone: ToastTone;
  action?: ToastAction | null;
}

export const toast: Writable<Toast | null> = writable(null);
let toastTimer: ReturnType<typeof setTimeout> | undefined;

export interface FlashOpts {
  ms?: number;
  action?: ToastAction;
  persistent?: boolean;
}

/**
 * Flash a toast. `optsOrMs` accepts either a number (ms TTL) or an
 * options object: { ms, action: { label, fn }, persistent }.
 */
export function flash(
  msg: string,
  tone: ToastTone = "info",
  optsOrMs: number | FlashOpts = 3500,
): void {
  if (toastTimer) clearTimeout(toastTimer);
  let ms = 3500;
  let action: ToastAction | null = null;
  let persistent = false;
  if (typeof optsOrMs === "number") {
    ms = optsOrMs;
  } else if (optsOrMs && typeof optsOrMs === "object") {
    if (typeof optsOrMs.ms === "number") ms = optsOrMs.ms;
    if (optsOrMs.action) action = optsOrMs.action;
    if (optsOrMs.persistent) persistent = true;
  }
  toast.set({ msg, tone, action });
  if (!persistent) {
    toastTimer = setTimeout(() => toast.set(null), ms);
  }
}

/** Clear any active toast immediately. Used by UNDO confirmations. */
export function clearToast(): void {
  if (toastTimer) clearTimeout(toastTimer);
  toast.set(null);
}

// Mutation counter: bumped after every successful CRUD write. Pages
// can subscribe to it to invalidate their lists. Centralised so
// individual pages don't need to call refreshDataset() manually.
export const mutationCounter: Writable<number> = writable(0);
export function bumpMutation(): void {
  mutationCounter.update((n) => n + 1);
}

// `datasetState` auto-refreshes when mutationCounter changes (debounced
// by a small idle so multiple concurrent mutations coalesce).
let datasetRefreshTimer: ReturnType<typeof setTimeout> | null = null;
function scheduleRefresh(): void {
  if (datasetRefreshTimer) clearTimeout(datasetRefreshTimer);
  datasetRefreshTimer = setTimeout(() => {
    refreshDataset();
  }, 120);
}
mutationCounter.subscribe(() => scheduleRefresh());

export async function refreshDataset(): Promise<void> {
  try {
    const s = await api.get<DatasetState>("/api/dataset/state");
    datasetState.set(s);
  } catch {
    // No flash here -- the network-status store already surfaces the
    // disconnect.
  }
}

export const datasetEmpty = derived(datasetState, ($s) =>
  ($s.classes ?? 0) === 0 && ($s.teachers ?? 0) === 0,
);

// ----- Network status ---------------------------------------------------
export const networkOnline: Writable<boolean> = writable(true);
let pingTimer: ReturnType<typeof setInterval> | null = null;
let pingInFlight = false;

async function pingHealth(): Promise<void> {
  if (pingInFlight) return;
  pingInFlight = true;
  try {
    await api.get("/api/health", { retry: false });
    if (!get(networkOnline)) networkOnline.set(true);
  } catch {
    if (get(networkOnline)) networkOnline.set(false);
  } finally {
    pingInFlight = false;
  }
}

export function startNetworkMonitor(intervalMs = 30000): void {
  if (typeof window === "undefined") return;
  if (pingTimer) return;
  setTimeout(() => {
    pingHealth();
  }, 500);
  pingTimer = setInterval(pingHealth, intervalMs);
}

export function stopNetworkMonitor(): void {
  if (pingTimer) clearInterval(pingTimer);
  pingTimer = null;
}
