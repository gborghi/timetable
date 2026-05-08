/// <reference types="cypress" />

/**
 * /students -- studenti. Basic CRUD round-trip.
 * Tag-related interactions live in dedicated specs (later).
 */

import { clearDataset } from '../support/seed';

const BACKEND = (Cypress.env('backendUrl') as string)
  || 'http://127.0.0.1:8000';

function uniqueLast(prefix: string): string {
  return `${prefix}_${Date.now().toString().slice(-6)}`;
}

describe('Tab Studenti CRUD workflow (UI-only)', () => {
  beforeEach(() => {
    clearDataset();
    cy.visit('/students');
    cy.get('[data-testid="students-page"]', { timeout: 15000 })
      .should('exist');
  });

  it('creates a new student via the modal form', () => {
    const last = uniqueLast('Russo');

    cy.intercept('POST', '**/api/students').as('createStudent');

    cy.get('[data-testid="add-student-btn"]').click();
    cy.get('[data-testid="student-form"]').should('be.visible');
    cy.get('[data-testid="student-last-name-input"]').type(last);
    cy.get('[data-testid="student-first-name-input"]').type('Marco');
    cy.get('[data-testid="student-save-btn"]').click();

    cy.wait('@createStudent').its('response.statusCode')
      .should('be.oneOf', [200, 201]);
    cy.contains(last, { timeout: 15000 }).should('be.visible');
  });

  it('cancels create modal', () => {
    cy.get('[data-testid="add-student-btn"]').click();
    cy.get('[data-testid="student-form"]').should('be.visible');
    cy.get('[data-testid="student-cancel-btn"]').click();
    cy.get('[data-testid="student-form"]').should('not.exist');
  });

  it('edits an existing student', () => {
    const last = uniqueLast('Bianchi');
    cy.request('POST', `${BACKEND}/api/students`, {
      last_name: last, first_name: 'Anna', nickname: '',
      birth_date: null, gender: null, email: '',
      student_code: '', class_id: null, notes: '',
      tags: [],
    });
    cy.reload();
    cy.contains(last, { timeout: 15000 }).should('be.visible');

    cy.intercept('PUT', '**/api/students/*').as('updateStudent');

    cy.contains('tr', last)
      .find('[data-testid="student-edit-btn"]')
      .click();
    cy.get('[data-testid="student-form"]').should('be.visible');
    cy.get('[data-testid="student-last-name-input"]')
      .should('have.value', last);
    cy.get('[data-testid="student-first-name-input"]')
      .clear().type('Anna Maria');
    cy.get('[data-testid="student-save-btn"]').click();
    cy.wait('@updateStudent').its('response.statusCode')
      .should('be.oneOf', [200, 204]);
  });

  it('deletes a student (confirm accepted)', () => {
    const last = uniqueLast('Verdi');
    cy.request('POST', `${BACKEND}/api/students`, {
      last_name: last, first_name: 'Luigi', nickname: '',
      birth_date: null, gender: null, email: '',
      student_code: '', class_id: null, notes: '',
      tags: [],
    });
    cy.reload();
    cy.contains(last, { timeout: 15000 }).should('be.visible');

    cy.intercept('DELETE', '**/api/students/*').as('deleteStudent');
    cy.on('window:confirm', () => true);

    cy.contains('tr', last)
      .find('[data-testid="student-delete-btn"]')
      .click();

    cy.wait('@deleteStudent').its('response.statusCode')
      .should('be.oneOf', [200, 204]);
    cy.contains(last).should('not.exist');
  });
});
