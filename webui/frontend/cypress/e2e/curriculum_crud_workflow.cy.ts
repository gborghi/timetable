/// <reference types="cypress" />

/**
 * /curricula -- indirizzi di studio. CRUD round-trip; the modal
 * also has tabs for hours-per-year and logical constraints, but
 * those need extensive setup so this spec stays at the basic
 * create/edit/delete level.
 */

import { clearDataset } from '../support/seed';

const BACKEND = (Cypress.env('backendUrl') as string)
  || 'http://127.0.0.1:8000';

function uniqueCode(prefix: string): string {
  return `${prefix}_${Date.now().toString().slice(-6)}`;
}

describe('Tab Indirizzi (curricula) CRUD workflow (UI-only)', () => {
  beforeEach(() => {
    clearDataset();
    cy.visit('/curricula');
    cy.get('[data-testid="curricula-page"]', { timeout: 15000 })
      .should('exist');
  });

  it('creates a new curriculum via the modal form', () => {
    const code = uniqueCode('SC');

    cy.intercept('POST', '**/api/curricula').as('createCurriculum');

    cy.get('[data-testid="add-curriculum-btn"]').click();
    cy.get('[data-testid="curriculum-form"]').should('be.visible');
    cy.get('[data-testid="curriculum-code-input"]').type(code);
    cy.get('[data-testid="curriculum-name-input"]')
      .type(`Indirizzo ${code}`);
    cy.get('[data-testid="curriculum-save-btn"]').click();

    cy.wait('@createCurriculum').its('response.statusCode')
      .should('be.oneOf', [200, 201]);
    cy.contains(code, { timeout: 15000 }).should('be.visible');
  });

  it('cancels create modal', () => {
    cy.get('[data-testid="add-curriculum-btn"]').click();
    cy.get('[data-testid="curriculum-form"]').should('be.visible');
    cy.get('[data-testid="curriculum-cancel-btn"]').click();
    cy.get('[data-testid="curriculum-form"]').should('not.exist');
  });

  it('edits an existing curriculum', () => {
    const code = uniqueCode('EC');
    cy.request('POST', `${BACKEND}/api/curricula`, {
      code, name: `Indirizzo ${code}`,
      description: '', notes: '', score: 1, hours: [],
    });
    cy.reload();
    cy.contains(code, { timeout: 15000 }).should('be.visible');

    cy.intercept('PUT', '**/api/curricula/*').as('updateCurriculum');

    cy.contains('tr', code)
      .find('[data-testid="curriculum-edit-btn"]')
      .click();
    cy.get('[data-testid="curriculum-form"]').should('be.visible');
    cy.get('[data-testid="curriculum-name-input"]')
      .clear().type(`Indirizzo ${code} aggiornato`);
    cy.get('[data-testid="curriculum-save-btn"]').click();
    cy.wait('@updateCurriculum').its('response.statusCode')
      .should('be.oneOf', [200, 204]);
  });

  it('deletes a curriculum (confirm accepted)', () => {
    const code = uniqueCode('DC');
    cy.request('POST', `${BACKEND}/api/curricula`, {
      code, name: `Indirizzo ${code}`,
      description: '', notes: '', score: 1, hours: [],
    });
    cy.reload();
    cy.contains(code, { timeout: 15000 }).should('be.visible');

    cy.intercept('DELETE', '**/api/curricula/*').as('deleteCurriculum');
    cy.on('window:confirm', () => true);

    cy.contains('tr', code)
      .find('[data-testid="curriculum-delete-btn"]')
      .click();

    cy.wait('@deleteCurriculum').its('response.statusCode')
      .should('be.oneOf', [200, 204]);
    cy.contains(code).should('not.exist');
  });
});
