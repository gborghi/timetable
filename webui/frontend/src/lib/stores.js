import { writable, derived } from 'svelte/store';
import { api } from './api.js';

export const datasetState = writable({
  classes: 0, teachers: 0, subjects: 0,
  assignments: 0, classrooms: 0, solutions: 0,
  active_solution: null
});

export const toast = writable(null);
let toastTimer;
export function flash(msg, tone = 'info', ms = 3500) {
  clearTimeout(toastTimer);
  toast.set({ msg, tone });
  toastTimer = setTimeout(() => toast.set(null), ms);
}

export async function refreshDataset() {
  try {
    const s = await api.get('/api/dataset/state');
    datasetState.set(s);
  } catch (e) {
    flash('Backend non raggiungibile: ' + e.message, 'error');
  }
}

export const datasetEmpty = derived(datasetState, ($s) =>
  ($s.classes ?? 0) === 0 && ($s.teachers ?? 0) === 0
);
