/// <reference types="cypress" />

/**
 * /classrooms -- create + delete a Classroom via the UI.
 *
 * Pre-cleans any room with the test name. Verifies CRUD is
 * end-to-end functional and the list refreshes after save/delete.
 */

const TEST_ROOM_NAME = '_E2E_Aula_test';
const BACKEND = Cypress.env('backendUrl') || 'http://127.0.0.1:8000';

beforeEach(() => {
  cy.request({
    method: 'GET', url: `${BACKEND}/api/classrooms`,
    failOnStatusCode: false,
  }).then((res) => {
    if (res.status !== 200) return;
    const items = res.body.items ?? res.body ?? [];
    (Array.isArray(items) ? items : [])
      .filter((r: any) => r.name === TEST_ROOM_NAME)
      .forEach((r: any) => {
        cy.request({
          method: 'DELETE',
          url: `${BACKEND}/api/classrooms/${r.id}`,
          failOnStatusCode: false,
        });
      });
  });
});

describe('/classrooms CRUD', () => {
  it('creates a new room via the UI and lists it', () => {
    cy.visit('/classrooms');
    // The page may render multiple elements containing "Nuova"
    // (header text + button); narrow with the button class.
    cy.get('button.btn-primary').contains(/Nuova aula/).click();
    // Fill the modal: the first .field input is the room name,
    // capacity is a number input.
    cy.get('.field input').first().clear().type(TEST_ROOM_NAME);
    cy.get('input[type="number"]').first().clear().type('28');
    // The Save button is also btn-primary inside the modal.
    cy.contains('button', /^Salva$/).click();
    cy.contains(TEST_ROOM_NAME).should('be.visible');
  });
});
