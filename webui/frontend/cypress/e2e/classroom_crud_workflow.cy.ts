/// <reference types="cypress" />

/**
 * /classrooms -- create / edit / delete via UI plus the
 * Plesso assignment dropdown (the field that populates from
 * /api/plessi). Catches regressions where the modal mounts but
 * the plesso select is empty or stuck.
 */

import { clearDataset } from '../support/seed';

const BACKEND = (Cypress.env('backendUrl') as string)
  || 'http://127.0.0.1:8000';

function uniqueName(prefix: string): string {
  return `${prefix}_${Date.now().toString().slice(-6)}`;
}

describe('Tab Aule CRUD workflow (UI-only)', () => {
  beforeEach(() => {
    clearDataset();
    cy.request({
      method: 'POST',
      url: `${BACKEND}/api/working-hours/reset`,
      failOnStatusCode: false,
      body: {},
    });
    cy.visit('/classrooms');
    cy.get('[data-testid="classrooms-page"]', { timeout: 15000 })
      .should('exist');
  });

  it('creates a new classroom via the modal form', () => {
    const name = uniqueName('Aula');

    cy.intercept('POST', '**/api/classrooms').as('createClassroom');

    cy.get('[data-testid="add-classroom-btn"]').click();
    cy.get('[data-testid="classroom-form"]').should('be.visible');
    cy.get('[data-testid="classroom-name-input"]').type(name);
    cy.get('[data-testid="classroom-capacity-input"]')
      .clear().type('25');
    cy.get('[data-testid="classroom-save-btn"]').click();

    cy.wait('@createClassroom').its('response.statusCode')
      .should('be.oneOf', [200, 201]);
    cy.contains(name, { timeout: 15000 }).should('be.visible');
  });

  it('cancels create modal', () => {
    cy.get('[data-testid="add-classroom-btn"]').click();
    cy.get('[data-testid="classroom-form"]').should('be.visible');
    cy.get('[data-testid="classroom-cancel-btn"]').click();
    cy.get('[data-testid="classroom-form"]').should('not.exist');
  });

  it('edits an existing classroom', () => {
    const name = uniqueName('Lab');
    cy.request('POST', `${BACKEND}/api/classrooms`, {
      name, kind: 'standard', capacity: 30,
      multi_class: false, multi_class_max: 1, multi_class_pref: 1,
      subject_prefs: [], class_prefs: [], unavailability: [], tags: [],
    });
    cy.reload();
    cy.contains(name, { timeout: 15000 }).should('be.visible');

    cy.intercept('PUT', '**/api/classrooms/*').as('updateClassroom');

    cy.contains('tr', name)
      .find('[data-testid="classroom-edit-btn"]')
      .click();
    cy.get('[data-testid="classroom-form"]').should('be.visible');
    cy.get('[data-testid="classroom-name-input"]').should('have.value', name);
    cy.get('[data-testid="classroom-capacity-input"]')
      .clear().type('40');
    cy.get('[data-testid="classroom-save-btn"]').click();
    cy.wait('@updateClassroom').its('response.statusCode')
      .should('be.oneOf', [200, 204]);
  });

  it('deletes a classroom (confirm accepted)', () => {
    const name = uniqueName('Palestra');
    cy.request('POST', `${BACKEND}/api/classrooms`, {
      name, kind: 'standard', capacity: 30,
      multi_class: false, multi_class_max: 1, multi_class_pref: 1,
      subject_prefs: [], class_prefs: [], unavailability: [], tags: [],
    });
    cy.reload();
    cy.contains(name, { timeout: 15000 }).should('be.visible');

    cy.intercept('DELETE', '**/api/classrooms/*').as('deleteClassroom');
    cy.on('window:confirm', () => true);

    cy.contains('tr', name)
      .find('[data-testid="classroom-delete-btn"]')
      .click();
    cy.wait('@deleteClassroom').its('response.statusCode')
      .should('be.oneOf', [200, 204]);
    cy.contains(name).should('not.exist');
  });

  it('plesso select populates when a plesso exists', () => {
    const plessoCode = 'TST';
    cy.request({
      method: 'POST',
      url: `${BACKEND}/api/plessi`,
      failOnStatusCode: false,
      body: { code: plessoCode, name: 'Test plesso' },
    });

    const name = uniqueName('Aula');
    cy.request('POST', `${BACKEND}/api/classrooms`, {
      name, kind: 'standard', capacity: 25,
      multi_class: false, multi_class_max: 1, multi_class_pref: 1,
      subject_prefs: [], class_prefs: [], unavailability: [], tags: [],
    });
    cy.reload();
    cy.contains(name, { timeout: 15000 }).should('be.visible');

    cy.contains('tr', name)
      .find('[data-testid="classroom-edit-btn"]')
      .click();
    cy.get('[data-testid="classroom-plesso-select"]')
      .should('be.visible')
      .find('option')
      .should('have.length.gte', 1);
  });

  it('classroom edit modal mounts the WeeklyCalendarView', () => {
    const name = uniqueName('Aula');
    cy.request('POST', `${BACKEND}/api/classrooms`, {
      name, kind: 'standard', capacity: 25,
      multi_class: false, multi_class_max: 1, multi_class_pref: 1,
      subject_prefs: [], class_prefs: [], unavailability: [], tags: [],
    });
    cy.reload();
    cy.contains(name, { timeout: 15000 }).should('be.visible');

    cy.contains('tr', name)
      .find('[data-testid="classroom-edit-btn"]')
      .click();
    cy.get('.weekly-calendar', { timeout: 10000 }).should('be.visible');
    cy.get('.cal-event').should('have.length.gte', 1);
  });
});
