/// <reference types="cypress" />

/**
 * Navigation smoke: every top-level route loads without a 5xx
 * server error. Catches refactors that break a route silently.
 *
 * Prereqs (manual): backend on :8000, frontend on :5173.
 *   cd webui/backend && .venv/Scripts/python -m uvicorn backend.main:app --port 8000
 *   cd webui/frontend && npm run dev
 *
 * Run:   cd webui/frontend && npm run test:e2e:cypress
 */

const ROUTES = [
  '/',
  '/assignments',
  '/classes',
  '/classrooms',
  '/coteaching',
  '/curricula',
  '/groups',
  '/monitor',
  '/optimize',
  '/runs',
  '/students',
  '/subjects',
  '/teachers',
];

describe('Top-level navigation smoke', () => {
  ROUTES.forEach((path) => {
    it(`loads ${path}`, () => {
      cy.visit(path);
      // SvelteKit hydrates client-side; the doctype-only response
      // would still be 200 even if the JS bundle errors. Wait for
      // a body element with text.
      cy.get('body').should('not.be.empty');
      // No top-level red error banner.
      cy.get('body').then(($body) => {
        const errors = $body.find('.error-banner, [data-error]');
        expect(errors.length, `${path} should not show error banner`)
          .to.equal(0);
      });
    });
  });
});
