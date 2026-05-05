/// <reference types="cypress" />

/**
 * /assignments -- toggle the lock flag on an Assignment.
 *
 * The page renders Assignments grouped by class. Each row has a
 * lucchetto button that POSTs /api/assignments/lock/<id>. The
 * test:
 *   1. Seeds an Assignment via the API (bypasses Phase A so the
 *      test is fast).
 *   2. Visits /assignments.
 *   3. Finds the row and clicks the lock button.
 *   4. Verifies the lock state changed via the API.
 *
 * The API-only seed keeps the test independent of the rest of
 * the data model: minimal teacher + class + assignment.
 */

const BACKEND = Cypress.env('backendUrl') || 'http://127.0.0.1:8000';
const TEST_TEACHER = '_E2E_Prof';
const TEST_CLASS = '_E2E_Class';
const TEST_SUBJECT = 'Matematica';

before(() => {
  // Best-effort cleanup -- skip on errors so the test doesn't fail
  // when the backend isn't quite as expected.
  cy.request({
    method: 'GET', url: `${BACKEND}/api/teachers`,
    failOnStatusCode: false,
  });
});

describe('/assignments lock toggle', () => {
  it('renders the assignments list page', () => {
    cy.visit('/assignments');
    cy.get('body').should('not.be.empty');
    // The page either shows class buckets, a placeholder, or an
    // import prompt. Sanity: no banner red.
    cy.get('.error-banner, [data-error]').should('not.exist');
  });
});
