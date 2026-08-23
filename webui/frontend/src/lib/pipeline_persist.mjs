/**
 * Persist the optimize full-pipeline order + per-step toggles.
 * Reload of /optimize used to reset both; localStorage keeps the
 * last user arrangement without a backend AppState row.
 */

import { PIPELINE_LABEL } from './pipeline_labels.js';

export const PIPELINE_STORAGE_KEY = 'pt_optimize_pipeline';

/** Canonical default: same order/toggles the page shipped with. */
export const DEFAULT_PIPELINE = [
  { key: 'hall_check',        enabled: true  },
  { key: 'phase_a',           enabled: true  },
  { key: 'decomp_spectral',   enabled: true  },
  { key: 'decomp_temporal',   enabled: false },
  { key: 'decomp_metis',      enabled: false },
  { key: 'decomp_curriculum', enabled: false },
  { key: 'phase_b',           enabled: true  },
  { key: 'cg',                enabled: false },
  { key: 'lns',               enabled: true  },
  { key: 'alns',              enabled: true  },
  { key: 'sa',                enabled: true  },
  { key: 'ts',                enabled: true  },
  { key: 'vns',               enabled: false },
  { key: 'lagrangian',        enabled: false },
  { key: 'ils',               enabled: true  },
  { key: 'rooms',             enabled: false },
];

const KNOWN = new Set(Object.keys(PIPELINE_LABEL));

/**
 * Merge a saved list onto the default: keep saved order + enabled
 * for known keys, drop unknowns, append any new default steps.
 * @param {unknown} saved
 * @param {{key:string, enabled:boolean}[]} [defaults]
 * @returns {{key:string, enabled:boolean}[]}
 */
export function sanitizePipeline(saved, defaults = DEFAULT_PIPELINE) {
  const base = defaults.map((d) => ({ key: d.key, enabled: !!d.enabled }));
  const byKey = new Map(base.map((d) => [d.key, d]));
  const out = [];
  const seen = new Set();
  if (Array.isArray(saved)) {
    for (const row of saved) {
      const key = row && typeof row === 'object' ? row.key : null;
      if (!key || !KNOWN.has(key) || !byKey.has(key) || seen.has(key)) continue;
      seen.add(key);
      out.push({ key, enabled: !!row.enabled });
    }
  }
  for (const d of base) {
    if (!seen.has(d.key)) out.push({ key: d.key, enabled: d.enabled });
  }
  return out;
}

/** @param {Storage} [storage] */
export function loadPipeline(storage) {
  const store = storage || (typeof localStorage === 'undefined' ? null : localStorage);
  if (!store) return sanitizePipeline(null);
  try {
    const raw = store.getItem(PIPELINE_STORAGE_KEY);
    if (!raw) return sanitizePipeline(null);
    return sanitizePipeline(JSON.parse(raw));
  } catch {
    return sanitizePipeline(null);
  }
}

/** @param {{key:string, enabled:boolean}[]} list @param {Storage} [storage] */
export function savePipeline(list, storage) {
  const store = storage || (typeof localStorage === 'undefined' ? null : localStorage);
  if (!store) return;
  try {
    store.setItem(PIPELINE_STORAGE_KEY, JSON.stringify(sanitizePipeline(list)));
  } catch { /* quota / private mode */ }
}
