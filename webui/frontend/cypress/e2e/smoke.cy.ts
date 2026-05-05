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
    cy.title().should('match', /piTantum|Tempus Tantum|piTantum/i);
    // Sanity: there is at least one nav link to /assignments.
    cy.get('a[href*="/assignments"], a[href*="/orario"], a[href*="/dashboard"]')
      .should('exist');
  });
});
