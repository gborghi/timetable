/// <reference types="cypress" />

/**
 * /groups -- create a new StudyGroup via the UI.
 *
 * Steps:
 *   1. Visit /groups.
 *   2. Click "+ Nuovo gruppo".
 *   3. Fill the modal (name, kind).
 *   4. Save.
 *   5. Verify the new row appears in the list.
 *
 * The test pre-cleans by deleting any group with the same test
 * name via the backend API, so the test is idempotent across runs.
 *
 * Prereqs (manual): see navigation.cy.ts header.
 */

const TEST_GROUP_NAME = '_E2E_Spagnolo_test';
const BACKEND = Cypress.env('backendUrl') || 'http://127.0.0.1:8000';

beforeEach(() => {
  // Delete any existing group with the test name (best-effort).
  cy.request({
    method: 'GET',
    url: `${BACKEND}/api/groups`,
    failOnStatusCode: false,
  }).then((res) => {
    if (res.status !== 200) return;
    const items = res.body.items ?? res.body ?? [];
    const stale = (Array.isArray(items) ? items : []).filter(
      (g: any) => g.name === TEST_GROUP_NAME,
    );
    stale.forEach((g: any) => {
      cy.request({
        method: 'DELETE',
        url: `${BACKEND}/api/groups/${g.id}`,
        failOnStatusCode: false,
      });
    });
  });
});

describe('/groups CRUD', () => {
  it('creates a new study group via the UI', () => {
    cy.visit('/groups');
    cy.contains('button', 'Nuovo gruppo').click();
    // Modal should open
    cy.get('.modal, [role="dialog"], .field').should('exist');
    // Fill the name input
    cy.get('input[type="text"]').first().clear().type(TEST_GROUP_NAME);
    // Save
    cy.contains('button', 'Salva').click();
    // The new group appears in the list
    cy.contains(TEST_GROUP_NAME).should('be.visible');
  });
});
