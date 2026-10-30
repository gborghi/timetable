/**
 * Etichette italiane di step, kind e stato dei run.
 *   node --experimental-strip-types --test webui/frontend/src/lib/pipeline_labels.test.mjs
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  PIPELINE_LABEL,
  runKindLabel,
  runStatusLabel,
  pipelineStepLabel,
} from './pipeline_labels.js';

test('Phase A/B visibili come Fase A/B', () => {
  assert.match(PIPELINE_LABEL.phase_a, /Fase A/);
  assert.doesNotMatch(PIPELINE_LABEL.phase_a, /Phase/);
  assert.match(PIPELINE_LABEL.phase_b, /Fase B/);
  assert.doesNotMatch(pipelineStepLabel('cg'), /Phase/);
});

test('kind diagnostici usano i titoli già scritti in Statistiche', () => {
  assert.equal(runKindLabel('diag_hall'), 'Pre-check fattibilità (Hall)');
  assert.equal(runKindLabel('diag_bipartite'), 'Analisi bipartito');
  assert.equal(runKindLabel('diag_correlations'), 'Correlazioni e regressioni');
  assert.equal(runKindLabel('diag_distributions'), 'Distribuzioni');
  assert.equal(runKindLabel('phase_b'), PIPELINE_LABEL.phase_b);
  assert.equal(runKindLabel('partial'), 'Orario parziale');
  assert.equal(runKindLabel(''), '');
  assert.equal(runKindLabel('imported'), 'imported');
});

test('stati dei run in italiano, con le parole già usate', () => {
  assert.equal(runStatusLabel('pending'), 'in coda');
  assert.equal(runStatusLabel('running'), 'in corso');
  assert.equal(runStatusLabel('done'), 'completato');
  assert.equal(runStatusLabel('failed'), 'fallito');
  assert.equal(runStatusLabel('cancelled'), 'annullato');
  assert.equal(runStatusLabel(''), '');
  assert.equal(runStatusLabel('mystery'), 'mystery');
});
