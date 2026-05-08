/// <reference types="cypress" />

/**
 * /optimize -- form dropdown coverage.
 *
 * The optimize page has many parameter dropdowns (mock profile,
 * mock mode, import profile, CP-SAT scope, Phase A mode, +
 * decomposition / metaheuristic / CG mode in advanced cards). This
 * spec smokes:
 *   - the page mounts with all main top-card dropdowns visible
 *   - mock profile + mode have the canonical option set
 *   - CP-SAT scope toggle drives the Phase A mode constraint
 *     (day -> always, week -> {skip, soft_hint})
 *   - import profile dropdown either lists profiles or shows the
 *     "(nessun pkl trovato)" hint
 *
 * The existing `optimize_phase_b_dropdowns.cy.ts` covers a subset;
 * this one targets the form-level invariants the user has flagged
 * as critical.
 */

describe('Tab Optimize dropdowns', () => {
  beforeEach(() => {
    cy.intercept('GET', '**/api/dataset/available-profiles')
      .as('availableProfiles');
    cy.visit('/optimize');
    cy.get('[data-testid="optimize-page"]', { timeout: 15000 })
      .should('exist');
  });

  it('mock profile dropdown has the 5 canonical sizes', () => {
    cy.get('[data-testid="optimize-mock-profile"]')
      .should('be.visible')
      .find('option')
      .then(($opts) => {
        const values = [...$opts].map((o) => (o as HTMLOptionElement).value);
        expect(values).to.include.members(
          ['small', 'medium', 'big', 'huge', 'superhuge']);
      });
  });

  it('mock mode dropdown has aggregated/tight/legacy', () => {
    cy.get('[data-testid="optimize-mock-mode"]')
      .find('option')
      .then(($opts) => {
        const values = [...$opts].map((o) => (o as HTMLOptionElement).value);
        expect(values).to.include.members(['aggregated', 'tight', 'legacy']);
      });
  });

  it('CP-SAT scope dropdown has day + week, default = day', () => {
    cy.get('[data-testid="optimize-cp-sat-scope"]')
      .should('have.value', 'day')
      .find('option')
      .then(($opts) => {
        const values = [...$opts].map((o) => (o as HTMLOptionElement).value);
        expect(values).to.include.members(['day', 'week']);
      });
  });

  it('Phase A mode dropdown coerces with CP-SAT scope', () => {
    // Initial state: scope=day -> phase_a_mode=always.
    cy.get('[data-testid="optimize-phase-a-mode"]')
      .should('have.value', 'always');

    // Switch scope to week -> phase_a_mode auto-flips to soft_hint
    // (per coercePhaseAModeForScope in the page).
    cy.get('[data-testid="optimize-cp-sat-scope"]').select('week');
    cy.get('[data-testid="optimize-phase-a-mode"]')
      .should('have.value', 'soft_hint');

    // Switch back to day -> always.
    cy.get('[data-testid="optimize-cp-sat-scope"]').select('day');
    cy.get('[data-testid="optimize-phase-a-mode"]')
      .should('have.value', 'always');
  });

  it('import-profile dropdown either lists profiles or shows '
     + 'the empty-state hint', () => {
    cy.wait('@availableProfiles').then((interception) => {
      // @ts-ignore -- response narrowing
      const profiles = interception.response.body as Array<{ name: string }>;
      if (profiles.length === 0) {
        cy.contains(/nessun pkl trovato/i).should('be.visible');
      } else {
        cy.get('[data-testid="optimize-import-profile"]')
          .should('not.be.disabled')
          .find('option')
          .should('have.length.gte', 1);
      }
    });
  });
});
