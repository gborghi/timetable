/// <reference types="cypress" />

/**
 * /classes -- create / edit / delete via UI, plus the
 * WeeklyCalendarView mounting check that is shared with /teachers.
 *
 * The "create class" form requires name + year + section + a
 * subjects[] block. We send the minimum payload the backend
 * accepts (a single subject) so the test focuses on the UI form
 * rather than the curriculum/grid feature.
 */

import { clearDataset } from '../support/seed';

const BACKEND = (Cypress.env('backendUrl') as string)
  || 'http://127.0.0.1:8000';

function uniqueName(prefix: string): string {
  return `${prefix}_${Date.now().toString().slice(-6)}`;
}

describe('Tab Classi CRUD workflow (UI-only)', () => {
  beforeEach(() => {
    clearDataset();
    cy.request({
      method: 'POST',
      url: `${BACKEND}/api/working-hours/reset`,
      failOnStatusCode: false,
      body: {},
    });
    cy.visit('/classes');
    cy.get('[data-testid="classes-page"]', { timeout: 15000 })
      .should('exist');
  });

  it('creates a new class via the modal form', () => {
    const name = uniqueName('1Z');

    cy.intercept('POST', '**/api/classes').as('createClass');

    cy.get('[data-testid="add-class-btn"]').click();
    cy.get('[data-testid="class-form"]').should('be.visible');
    cy.get('[data-testid="class-name-input"]').type(name);
    cy.get('[data-testid="class-year-input"]').clear().type('1');
    cy.get('[data-testid="class-section-input"]').type('Z');
    cy.get('[data-testid="class-save-btn"]').click();

    cy.wait('@createClass').then((interception) => {
      expect([200, 201]).to.include(
        interception.response?.statusCode || 0);
    });
    cy.contains(name, { timeout: 15000 }).should('be.visible');
  });

  it('cancels the create modal without saving', () => {
    cy.get('[data-testid="add-class-btn"]').click();
    cy.get('[data-testid="class-form"]').should('be.visible');
    cy.get('[data-testid="class-cancel-btn"]').click();
    cy.get('[data-testid="class-form"]').should('not.exist');
  });

  it('edits an existing class via Modifica', () => {
    const name = uniqueName('2Y');
    cy.request('POST', `${BACKEND}/api/classes`, {
      name, year: 2, section: 'Y',
      curriculum: 'Generico', n_students: 22,
      subjects: [{ subject: 'Italiano', hours_per_week: 4 }],
      unavailability: [],
    });
    cy.reload();
    cy.contains(name, { timeout: 15000 }).should('be.visible');

    cy.intercept('PUT', '**/api/classes/*').as('updateClass');

    cy.contains('tr', name)
      .find('[data-testid="class-edit-btn"]')
      .click();
    cy.get('[data-testid="class-form"]').should('be.visible');
    cy.get('[data-testid="class-name-input"]').should('have.value', name);
    cy.get('[data-testid="class-save-btn"]').click();
    cy.wait('@updateClass').its('response.statusCode')
      .should('be.oneOf', [200, 204]);
  });

  it('deletes a class via Elimina (confirm accepted)', () => {
    const name = uniqueName('3X');
    cy.request('POST', `${BACKEND}/api/classes`, {
      name, year: 3, section: 'X',
      curriculum: 'Generico', n_students: 22,
      subjects: [{ subject: 'Storia', hours_per_week: 2 }],
      unavailability: [],
    });
    cy.reload();
    cy.contains(name, { timeout: 15000 }).should('be.visible');

    cy.intercept('DELETE', '**/api/classes/*').as('deleteClass');
    cy.on('window:confirm', () => true);

    cy.contains('tr', name)
      .find('[data-testid="class-delete-btn"]')
      .click();
    cy.wait('@deleteClass').its('response.statusCode')
      .should('be.oneOf', [200, 204]);
    cy.contains(name).should('not.exist');
  });

  it('class edit modal mounts the WeeklyCalendarView', () => {
    const name = uniqueName('4W');
    cy.request('POST', `${BACKEND}/api/classes`, {
      name, year: 4, section: 'W',
      curriculum: 'Generico', n_students: 22,
      subjects: [{ subject: 'Matematica', hours_per_week: 4 }],
      unavailability: [],
    });
    cy.reload();
    cy.contains(name, { timeout: 15000 }).should('be.visible');

    cy.contains('tr', name)
      .find('[data-testid="class-edit-btn"]')
      .click();
    cy.get('.weekly-calendar', { timeout: 10000 }).should('be.visible');
    cy.get('.cal-event').should('have.length.gte', 1);
  });
});
