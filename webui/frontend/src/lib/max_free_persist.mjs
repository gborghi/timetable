/**
 * Casella «Docenti a orario pieno: al massimo N giorni liberi».
 * I default (N, S) arrivano dal preset del motore
 * (GET /api/optimize/presets/max-free-days): qui non c'è nessun numero.
 * La scelta dell'utente resta in localStorage tra un reload e l'altro.
 */

export const MAX_FREE_STORAGE_KEY = 'pt_optimize_max_free';

const FIELDS = ['max_free_if_full', 'max_free_days', 'full_time_hours',
  'max_free_exclude', 'max_free_only'];

/** Valori iniziali dal preset del server. */
export function fromPreset(preset) {
  return {
    max_free_if_full: Boolean(preset?.enabled_by_default),
    max_free_days: preset?.max_free,
    full_time_hours: preset?.threshold,
    max_free_exclude: '',
    max_free_only: '',
  };
}

/** Sovrappone il salvato (solo campi noti e validi) ai default. */
export function mergeSaved(defaults, saved) {
  const out = { ...defaults };
  if (!saved || typeof saved !== 'object') return out;
  if (typeof saved.max_free_if_full === 'boolean') out.max_free_if_full = saved.max_free_if_full;
  for (const k of ['max_free_days', 'full_time_hours']) {
    const v = saved[k];
    if (Number.isInteger(v) && v >= 0) out[k] = v;
  }
  for (const k of ['max_free_exclude', 'max_free_only']) {
    if (typeof saved[k] === 'string') out[k] = saved[k];
  }
  return out;
}

export function pick(step) {
  const o = {};
  for (const k of FIELDS) o[k] = step[k];
  return o;
}

export function loadMaxFree(defaults, storage = globalThis.localStorage) {
  try {
    const raw = storage?.getItem(MAX_FREE_STORAGE_KEY);
    return mergeSaved(defaults, raw ? JSON.parse(raw) : null);
  } catch {
    return { ...defaults };
  }
}

export function saveMaxFree(step, storage = globalThis.localStorage) {
  try {
    storage?.setItem(MAX_FREE_STORAGE_KEY, JSON.stringify(pick(step)));
  } catch { /* storage pieno o negato: si perde solo la memoria */ }
}
