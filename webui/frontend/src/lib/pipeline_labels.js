/**
 * Single source of truth for human-readable labels of the pipeline
 * step keys used by `/api/optimize/full-pipeline`. Imported by both the
 * Workflow tab (where the user ticks/reorders steps) and the Runs tab
 * (which surfaces "current_step" under the progress bar).
 *
 * Keep in sync with the `valid` set inside `optimization.py
 * run_full_pipeline.target` (and of course with the keys the backend
 * emits in `runs.current_step`).
 *
 * Le stringhe visibili usano l'italiano già presente nell'interfaccia
 * («Fase A», «Fase B», «in corso», «in coda», titoli delle diagnostiche).
 * Gli acronimi senza una glossa italiana già scritta nel frontend
 * restano sigle (LNS, SA, …): non si inventa un nome nuovo.
 */
export const PIPELINE_LABEL = {
  hall_check: 'Pre-check Hall (diagnostico)',
  phase_a: '2) Assegnazione (Fase A)',
  decomp_spectral: '3a) Decomposizione spettrale',
  decomp_temporal: '3b) Decomposizione temporale (per giorno)',
  decomp_metis: '3c) Decomposizione METIS (k-way)',
  decomp_curriculum: '3d) Decomposizione per curriculum',
  phase_b: '3) Schedulazione orario (Fase B)',
  cg: 'Column Generation (alternativo a Fase B)',
  lagrangian: 'Lagrangian Relaxation (subgradient)',
  lns: '4) LNS',
  alns: '4-bis) ALNS',
  sa: '5) SA',
  ts: '6) TS',
  vns: '6-bis) VNS',
  ils: '7) ILS',
  rooms: '8) Assegna aule (indipendente)',
};

/**
 * Stati dei run. Parole già usate nell'interfaccia:
 * «in coda» (barra di avanzamento), «in corso», «completato»,
 * «fallito», «annullato».
 */
export const RUN_STATUS_LABEL = {
  pending: 'in coda',
  running: 'in corso',
  done: 'completato',
  failed: 'fallito',
  cancelled: 'annullato',
  canceled: 'annullato',
};

/** Titoli già scritti nella pagina Statistiche, più i kind fratelli. */
const KIND_LABEL = {
  diag_hall: 'Pre-check fattibilità (Hall)',
  diag_montecarlo: 'Monte Carlo',
  diag_bipartite: 'Analisi bipartito',
  diag_correlations: 'Correlazioni e regressioni',
  diag_distributions: 'Distribuzioni',
  phase_b_temporal: '3b) Decomposizione temporale (per giorno)',
  phase_b_metis: '3c) Decomposizione METIS (k-way)',
  phase_b_spectral: '3a) Decomposizione spettrale',
  phase_b_curriculum: '3d) Decomposizione per curriculum',
  partial: 'Orario parziale',
};

/** Resolve a step key to its human label, falling back to the key. */
export function pipelineStepLabel(key) {
  if (!key) return '';
  return PIPELINE_LABEL[key] || key;
}

/** Etichetta italiana di `run.kind`. La chiave tecnica resta nel tooltip. */
export function runKindLabel(kind) {
  if (!kind) return '';
  return PIPELINE_LABEL[kind] || KIND_LABEL[kind] || kind;
}

/** Etichetta italiana di `run.status`. Lo stato grezzo resta nel tooltip. */
export function runStatusLabel(status) {
  if (!status) return '';
  return RUN_STATUS_LABEL[status] || status;
}
