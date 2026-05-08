/// <reference types="cypress" />

/**
 * /subjects -- create / edit / delete via UI plus the
 * Pesi cl. concorso toggle (the secondary view).
 */

import { clearDataset } from '../support/seed';

const BACKEND = (Cypress.env('backendUrl') as string)
  || 'http://127.0.0.1:8000';

function uniqueName(prefix: string): string {
  return `${prefix}_${Date.now().toString().slice(-6)}`;
}

describe('Tab Materie CRUD workflow (UI-only)', () => {
  beforeEach(() => {
    clearDataset();
    cy.visit('/subjects');
    cy.get('[data-testid="subjects-page"]', { timeout: 15000 })
      .should('exist');
  });

  it('creates a new subject via the modal form', () => {
    const name = uniqueName('Mat');

    cy.intercept('POST', '**/api/subjects').as('createSubject');

    cy.get('[data-testid="add-subject-btn"]').click();
    cy.get('[data-testid="subject-form"]').should('be.visible');
    cy.get('[data-testid="subject-name-input"]').type(name);
    cy.get('[data-testid="subject-pretty-name-input"]')
      .type(`${name} pretty`);
    cy.get('[data-testid="subject-save-btn"]').click();

    cy.wait('@createSubject').its('response.statusCode')
      .should('be.oneOf', [200, 201]);
    cy.contains(name, { timeout: 15000 }).should('be.visible');
  });

  it('cancels create modal', () => {
    cy.get('[data-testid="add-subject-btn"]').click();
    cy.get('[data-testid="subject-form"]').should('be.visible');
    cy.get('[data-testid="subject-cancel-btn"]').click();
    cy.get('[data-testid="subject-form"]').should('not.exist');
  });

  it('edits an existing subject', () => {
    const name = uniqueName('Fis');
    cy.request('POST', `${BACKEND}/api/subjects`, {
      name, pretty_name: name, notes: '',
      distribute_days_weight: 0, dual_hours_weight: 0,
      no_sixth_hour_weight: 0,
      preferred_band_start: null, preferred_band_end: null,
      preferred_band_weight: 0,
      classroom_prefs: [],
    });
    cy.reload();
    cy.contains(name, { timeout: 15000 }).should('be.visible');

    cy.intercept('PUT', '**/api/subjects/*').as('updateSubject');

    cy.contains('tr', name)
      .find('[data-testid="subject-edit-btn"]')
      .click();
    cy.get('[data-testid="subject-form"]').should('be.visible');
    cy.get('[data-testid="subject-name-input"]').should('have.value', name);
    cy.get('[data-testid="subject-save-btn"]').click();
    cy.wait('@updateSubject').its('response.statusCode')
      .should('be.oneOf', [200, 204]);
  });

  it('deletes a subject (confirm accepted)', () => {
    const name = uniqueName('Chim');
    cy.request('POST', `${BACKEND}/api/subjects`, {
      name, pretty_name: name, notes: '',
      distribute_days_weight: 0, dual_hours_weight: 0,
      no_sixth_hour_weight: 0,
      preferred_band_start: null, preferred_band_end: null,
      preferred_band_weight: 0,
      classroom_prefs: [],
    });
    cy.reload();
    cy.contains(name, { timeout: 15000 }).should('be.visible');

    cy.intercept('DELETE', '**/api/subjects/*').as('deleteSubject');
    cy.on('window:confirm', () => true);

    cy.contains('tr', name)
      .find('[data-testid="subject-delete-btn"]')
      .click();
    cy.wait('@deleteSubject').its('response.statusCode')
      .should('be.oneOf', [200, 204]);
    cy.contains(name).should('not.exist');
  });

  it('toggles between subject list and Pesi cl. concorso view', () => {
    cy.contains(/Pesi cl\. concorso/i).should('exist');
    cy.get('[data-testid="subjects-toggle-weights"]').click();
    cy.contains(/Vista materie/i).should('exist');
    cy.get('[data-testid="subjects-toggle-weights"]').click();
    cy.contains(/Pesi cl\. concorso/i).should('exist');
  });
});
