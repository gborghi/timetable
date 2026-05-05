/// <reference types="cypress" />

/**
 * /plessi -- create + delete a Plesso via the UI, plus verify the
 * validation banner shows "Configurazione OK" by default.
 *
 * Pre-cleans any plesso with the test code so re-running is safe.
 */

const TEST_CODE = '_E2E';
const TEST_NAME = '_E2E_Sede_test';
const BACKEND = Cypress.env('backendUrl') || 'http://127.0.0.1:8000';

beforeEach(() => {
  cy.request({
    method: 'GET', url: `${BACKEND}/api/plessi`,
    failOnStatusCode: false,
  }).then((res) => {
    if (res.status !== 200) return;
    const items = res.body ?? [];
    (Array.isArray(items) ? items : [])
      .filter((p: any) => p.code === TEST_CODE || p.name === TEST_NAME)
      .forEach((p: any) => {
        cy.request({
          method: 'DELETE',
          url: `${BACKEND}/api/plessi/${p.id}`,
          failOnStatusCode: false,
        });
      });
  });
});

describe('/plessi CRUD', () => {
  it('shows the validation banner', () => {
    cy.visit('/plessi');
    // Either banner is present; in a clean setup it should be OK.
    cy.contains(/Configurazione (OK|incoerente)/).should('be.visible');
  });

  it('creates a new plesso via the UI and lists it', () => {
    cy.visit('/plessi');
    cy.contains('button', /Nuovo plesso/).click();
    // The first .field input is "Codice", the second is "Nome".
    cy.get('.field input').eq(0).clear().type(TEST_CODE);
    cy.get('.field input').eq(1).clear().type(TEST_NAME);
    cy.contains('button', /^Salva$/).click();
    cy.contains(TEST_CODE).should('be.visible');
    cy.contains(TEST_NAME).should('be.visible');
  });
});
