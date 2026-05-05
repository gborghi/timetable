/// <reference types="cypress" />

/**
 * Cypress smoke test: open the home page and verify the title.
 *
 * Prerequisites:
 *   - Backend running at http://127.0.0.1:8000
 *   - Frontend dev server running at http://127.0.0.1:5173
 *
 * Run with:
 *   cd webui/frontend
 *   npm run dev          (in another terminal)
 *   cd ../..
 *   cd webui/backend && .venv/Scripts/python -m uvicorn backend.main:app --port 8000
 *   cd webui/frontend
 *   npm run test:e2e:cypress
 */

describe('piTantum smoke', () => {
  it('home page loads with brand title', () => {
    cy.visit('/');
    cy.title().should('match', /piTantum|Tempus Tantum/i);
    // SvelteKit hydrates client-side; the body must be non-empty
    // after JS runs. Wait up to 10s for the app shell.
    cy.get('body').should('not.be.empty');
    // No top-level error banner.
    cy.get('.error-banner, [data-error]').should('not.exist');
  });
});
