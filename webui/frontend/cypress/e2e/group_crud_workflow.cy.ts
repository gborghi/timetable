/// <reference types="cypress" />

/**
 * /groups -- gruppi articolati. CRUD round-trip; the existing
 * `groups_create.cy.ts` only smokes the create path.
 */

import { clearDataset } from '../support/seed';

const BACKEND = (Cypress.env('backendUrl') as string)
  || 'http://127.0.0.1:8000';

function uniqueName(prefix: string): string {
  return `${prefix}_${Date.now().toString().slice(-6)}`;
}

describe('Tab Gruppi articolati CRUD workflow (UI-only)', () => {
  beforeEach(() => {
    clearDataset();
    cy.visit('/groups');
    cy.get('[data-testid="groups-page"]', { timeout: 15000 })
      .should('exist');
  });

  it('creates a new group via the modal form', () => {
    const name = uniqueName('Grp');

    cy.intercept('POST', '**/api/groups').as('createGroup');

    cy.get('[data-testid="add-group-btn"]').click();
    cy.get('[data-testid="group-form"]').should('be.visible');
    cy.get('[data-testid="group-name-input"]').type(name);
    cy.get('[data-testid="group-kind-select"]').select('language');
    cy.get('[data-testid="group-save-btn"]').click();

    cy.wait('@createGroup').its('response.statusCode')
      .should('be.oneOf', [200, 201]);
    cy.contains(name, { timeout: 15000 }).should('be.visible');
  });

  it('cancels create modal', () => {
    cy.get('[data-testid="add-group-btn"]').click();
    cy.get('[data-testid="group-form"]').should('be.visible');
    cy.get('[data-testid="group-cancel-btn"]').click();
    cy.get('[data-testid="group-form"]').should('not.exist');
  });

  it('edits an existing group', () => {
    const name = uniqueName('Edt');
    cy.request('POST', `${BACKEND}/api/groups`, {
      name, nickname: name, kind: 'splitting',
      description: '', notes: '',
      student_ids: [], subject_hours: [],
    });
    cy.reload();
    cy.contains(name, { timeout: 15000 }).should('be.visible');

    cy.intercept('PUT', '**/api/groups/*').as('updateGroup');

    cy.contains('tr', name)
      .find('[data-testid="group-edit-btn"]')
      .click();
    cy.get('[data-testid="group-form"]').should('be.visible');
    cy.get('[data-testid="group-name-input"]').should('have.value', name);
    cy.get('[data-testid="group-kind-select"]').select('religion');
    cy.get('[data-testid="group-save-btn"]').click();
    cy.wait('@updateGroup').its('response.statusCode')
      .should('be.oneOf', [200, 204]);
  });

  it('deletes a group (confirm accepted)', () => {
    const name = uniqueName('Del');
    cy.request('POST', `${BACKEND}/api/groups`, {
      name, nickname: name, kind: 'splitting',
      description: '', notes: '',
      student_ids: [], subject_hours: [],
    });
    cy.reload();
    cy.contains(name, { timeout: 15000 }).should('be.visible');

    cy.intercept('DELETE', '**/api/groups/*').as('deleteGroup');
    cy.on('window:confirm', () => true);

    cy.contains('tr', name)
      .find('[data-testid="group-delete-btn"]')
      .click();

    cy.wait('@deleteGroup').its('response.statusCode')
      .should('be.oneOf', [200, 204]);
    cy.contains(name).should('not.exist');
  });
});
