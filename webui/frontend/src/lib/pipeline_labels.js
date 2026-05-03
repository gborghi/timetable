/**
 * Single source of truth for human-readable labels of the pipeline
 * step keys used by `/api/optimize/full-pipeline`. Imported by both the
 * Workflow tab (where the user ticks/reorders steps) and the Runs tab
 * (which surfaces "current_step" under the progress bar).
 *
 * Keep in sync with the `valid` set inside `optimization.py
 * run_full_pipeline.target` (and of course with the keys the backend
 * emits in `runs.current_step`).
 */
export const PIPELINE_LABEL = {
  hall_check: 'Pre-check Hall (diagnostico)',
  phase_a: '2) Assegnazione (Phase A)',
  decomp_spectral: '3a) Decomposizione spettrale',
  decomp_temporal: '3b) Decomposizione temporale (per giorno)',
  decomp_metis: '3c) Decomposizione METIS (k-way)',
  decomp_curriculum: '3d) Decomposizione per curriculum',
  phase_b: '3) Schedulazione orario (Phase B)',
  cg: 'Column Generation (alternativo a Phase B)',
  lagrangian: 'Lagrangian Relaxation (subgradient)',
  lns: '4) LNS',
  alns: '4-bis) ALNS (Adaptive LNS)',
  sa: '5) SA',
  ts: '6) TS',
  vns: '6-bis) VNS (Variable Neighbourhood Search)',
  ils: '7) ILS',
  rooms: '8) Assegna aule (indipendente)',
};

/** Resolve a step key to its human label, falling back to the key. */
export function pipelineStepLabel(key) {
  if (!key) return '';
  return PIPELINE_LABEL[key] || key;
}
