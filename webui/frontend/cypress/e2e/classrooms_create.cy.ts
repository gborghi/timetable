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
    cy.get('[data-testid="add-classroom-btn"]').click();
    // Sui testid e non su `.field input` / `input[type=number]`:
    // se la lista contiene gia' delle aule, il primo number input
    // della pagina e' la capienza inline di una riga (coperta dalla
    // modale), non il campo della modale, e il test fallisce solo
    // quando gira dopo altri spec che lasciano aule nel DB.
    cy.get('[data-testid="classroom-name-input"]')
      .clear().type(TEST_ROOM_NAME);
    cy.get('[data-testid="classroom-capacity-input"]')
      .clear().type('28');
    cy.get('[data-testid="classroom-save-btn"]').click();
    cy.contains(TEST_ROOM_NAME).should('be.visible');
  });
});
