/// <reference types="cypress" />

/**
 * /plessi -- the school-sites manager. Three sections (plessi,
 * commuting rules, entity policies) but the one most likely to
 * regress is the basic plesso CRUD because it gates the
 * dropdowns elsewhere (classroom plesso_id, etc.).
 *
 * Note: there is an existing `plessi_create.cy.ts` smoke spec; this
 * one expands to a full CRUD round-trip with the new data-testid
 * hooks.
 */

import { clearDataset } from '../support/seed';
import { acceptConfirm } from '../support/confirm';

const BACKEND = (Cypress.env('backendUrl') as string)
  || 'http://127.0.0.1:8000';

function uniqueCode(prefix: string): string {
  return `${prefix}${Date.now().toString().slice(-4)}`;
}

describe('Tab Plessi CRUD workflow (UI-only)', () => {
  beforeEach(() => {
    clearDataset();
    cy.visit('/plessi');
    cy.get('[data-testid="plessi-page"]', { timeout: 15000 })
      .should('exist');
  });

  it('creates a new plesso via the inline form', () => {
    const code = uniqueCode('PLT');

    cy.intercept('POST', '**/api/plessi').as('createPlesso');

    cy.get('[data-testid="add-plesso-btn"]').click();
    cy.get('[data-testid="plesso-form"]').should('be.visible');
    cy.get('[data-testid="plesso-code-input"]').type(code);
    cy.get('[data-testid="plesso-name-input"]')
      .type(`Plesso ${code}`);
    cy.get('[data-testid="plesso-address-input"]')
      .type('Via Test 1');
    cy.get('[data-testid="plesso-save-btn"]').click();

    cy.wait('@createPlesso').its('response.statusCode')
      .should('be.oneOf', [200, 201]);
    cy.contains(code, { timeout: 15000 }).should('be.visible');
  });

  it('cancels create form', () => {
    cy.get('[data-testid="add-plesso-btn"]').click();
    cy.get('[data-testid="plesso-form"]').should('be.visible');
    cy.get('[data-testid="plesso-cancel-btn"]').click();
    cy.get('[data-testid="plesso-form"]').should('not.exist');
  });

  it('edits an existing plesso', () => {
    const code = uniqueCode('EDP');
    cy.request('POST', `${BACKEND}/api/plessi`, {
      code, name: `Plesso ${code}`,
      address: 'Via Editata 1', notes: '',
    });
    cy.reload();
    cy.contains(code, { timeout: 15000 }).should('be.visible');

    cy.intercept('PUT', '**/api/plessi/*').as('updatePlesso');

    cy.contains('tr', code)
      .find('[data-testid="plesso-edit-btn"]')
      .click();
    cy.get('[data-testid="plesso-form"]').should('be.visible');
    cy.get('[data-testid="plesso-name-input"]')
      .clear().type(`Plesso ${code} aggiornato`);
    cy.get('[data-testid="plesso-save-btn"]').click();

    cy.wait('@updatePlesso').its('response.statusCode')
      .should('be.oneOf', [200, 204]);
    cy.contains(`Plesso ${code} aggiornato`).should('be.visible');
  });

  it('deletes a plesso (confirm accepted)', () => {
    const code = uniqueCode('DEL');
    cy.request('POST', `${BACKEND}/api/plessi`, {
      code, name: `Plesso ${code}`,
      address: '', notes: '',
    });
    cy.reload();
    cy.contains(code, { timeout: 15000 }).should('be.visible');

    cy.intercept('DELETE', '**/api/plessi/*').as('deletePlesso');

    cy.contains('tr', code)
      .find('[data-testid="plesso-delete-btn"]')
      .click();
    // Elimina apre ConfirmDialog, non window.confirm.
    acceptConfirm();

    cy.wait('@deletePlesso').its('response.statusCode')
      .should('be.oneOf', [200, 204]);
    cy.contains(code).should('not.exist');
  });

  it('validation banner reflects the API state', () => {
    // Banner is either "Configurazione OK" or "Configurazione incoerente".
    // Both are valid -- just assert one of them is visible so a refactor
    // that forgets to render the banner gets caught.
    cy.contains(/Configurazione (OK|incoerente)/i, { timeout: 10000 })
      .should('be.visible');
  });
});
