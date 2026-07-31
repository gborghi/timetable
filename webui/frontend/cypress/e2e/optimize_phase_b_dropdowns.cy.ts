/// <reference types="cypress" />

/**
 * /optimize -- Phase B card now exposes two new dropdowns introduced
 * by Phase 3 of the CP-SAT scope work:
 *
 *   1. "Scope del solver CP-SAT"   -> cp_sat_scope: 'day' | 'week'
 *   2. "Modalita Phase A"          -> phase_a_mode:  'always' | 'skip' | 'soft_hint'
 *
 * Cross-field rule (mirror of backend @model_validator):
 *   day  + always                                  (default, legacy)
 *   week + skip   OR  week + soft_hint
 *
 * This smoke test verifies, WITHOUT actually running the solver:
 *   - both dropdowns render
 *   - default payload to /api/optimize/phase-b carries
 *     cp_sat_scope='day' AND phase_a_mode='always'
 *   - selecting cp_sat_scope='week' auto-coerces phase_a_mode away
 *     from 'always' so the submitted payload is valid
 *
 * The POST is stubbed so the run never starts. Network is captured
 * via cy.intercept so we can assert on the request body.
 *
 * Since the redesign the Phase B card sits inside the "Modalita'
 * avanzata" <Panel>, whose content is not in the DOM while collapsed:
 * `visitOptimize()` visits and opens it.
 */

import { expandPanel } from '../support/panels';

function visitOptimize() {
  cy.visit('/optimize');
  expandPanel('optimize-advanced');
}

describe('/optimize Phase B Phase-3 dropdowns', () => {
  beforeEach(() => {
    // Stub the runs list -> empty (the page calls it on mount).
    cy.intercept('GET', '**/api/optimize/runs*', { body: [] });
    // Stub dataset state -> empty profile.
    cy.intercept('GET', '**/api/dataset/state', {
      body: { last_profile: '', solutions: 0, assignments: 0 },
    });
    // Stub the decomposition recommend best-effort fetch.
    cy.intercept('GET', '**/api/optimize/decomposition/recommend',
                 { statusCode: 409, body: {} });
    // Stub the Phase B POST so no solver work happens.
    cy.intercept('POST', '**/api/optimize/phase-b', {
      statusCode: 200,
      body: { run_id: 9999 },
    }).as('launchB');
  });

  it('renders both dropdowns with the correct default options', () => {
    visitOptimize();
    cy.contains('Scope del solver CP-SAT')
      .parent()
      .find('select')
      .should('have.value', 'day');
    cy.contains('Modalità Phase A')
      .parent()
      .find('select')
      .should('have.value', 'always');
  });

  it('default submit carries cp_sat_scope=day + phase_a_mode=always',
     () => {
       visitOptimize();
       cy.contains('button', /Avvia Phase B/i).click();
       cy.wait('@launchB').then((interception) => {
         const body = interception.request.body as Record<string, any>;
         expect(body.cp_sat_scope).to.eq('day');
         expect(body.phase_a_mode).to.eq('always');
       });
     });

  it('switching to week coerces phase_a_mode to soft_hint and submits ' +
     'a valid combination',
     () => {
       visitOptimize();
       cy.contains('Scope del solver CP-SAT')
         .parent()
         .find('select')
         .select('week');
       // Auto-coercion: phase_a_mode must NOT be 'always' anymore.
       cy.contains('Modalità Phase A')
         .parent()
         .find('select')
         .should('have.value', 'soft_hint');
       cy.contains('button', /Avvia Phase B/i).click();
       cy.wait('@launchB').then((interception) => {
         const body = interception.request.body as Record<string, any>;
         expect(body.cp_sat_scope).to.eq('week');
         expect(body.phase_a_mode).to.be.oneOf(['skip', 'soft_hint']);
       });
     });

  it('user can pick skip in week mode', () => {
    visitOptimize();
    cy.contains('Scope del solver CP-SAT')
      .parent()
      .find('select')
      .select('week');
    cy.contains('Modalità Phase A')
      .parent()
      .find('select')
      .select('skip');
    cy.contains('button', /Avvia Phase B/i).click();
    cy.wait('@launchB').then((interception) => {
      const body = interception.request.body as Record<string, any>;
      expect(body.cp_sat_scope).to.eq('week');
      expect(body.phase_a_mode).to.eq('skip');
    });
  });
});
