/// <reference types="cypress" />

/**
 * Smoke specs for tabs that don't have a dedicated CRUD page (yet):
 *   - /diagnostics  -- Statistiche e diagnostica
 *   - /assignments  -- Cattedre
 *   - /coteaching   -- Compresenze
 *   - /schedule     -- Orario
 *   - /import       -- Import bulk
 *   - /runs         -- Runs
 *
 * Each test asserts the page renders, the heading is present, and
 * no top-level error banner appears. The deeper page-specific
 * interactions get their own specs as we expand coverage.
 */

const TABS = [
  { path: '/diagnostics', heading: /Statistiche e diagnostica/i },
  { path: '/assignments', heading: /Cattedre/i },
  { path: '/coteaching',  heading: /Compresenze/i },
  { path: '/schedule',    heading: /Orario/i },
  { path: '/import',      heading: /Import bulk/i },
  { path: '/runs',        heading: /Runs/i },
];

describe('Minor-tabs smoke', () => {
  TABS.forEach(({ path, heading }) => {
    it(`${path} mounts with the expected heading`, () => {
      cy.visit(path);
      cy.contains(heading, { timeout: 15000 }).should('be.visible');
      cy.get('[data-testid="navbar"]').should('exist');
      cy.get('body').then(($body) => {
        expect($body.find('.error-banner, [data-error]').length,
               `${path} should not show error banner`).to.equal(0);
      });
    });
  });
});

describe('/runs refresh button', () => {
  it('clicking refresh fires GET /api/runs', () => {
    cy.intercept('GET', '**/api/runs**').as('runs');
    cy.visit('/runs');
    cy.get('[data-testid="runs-page"]', { timeout: 15000 })
      .should('exist');
    cy.get('[data-testid="runs-refresh-btn"]').click();
    cy.wait('@runs');
  });
});
