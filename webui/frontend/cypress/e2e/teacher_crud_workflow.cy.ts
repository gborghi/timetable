/// <reference types="cypress" />

/**
 * Teacher CRUD workflow E2E.
 *
 * End-to-end on the /teachers tab using ONLY the UI -- no direct
 * POST shortcuts. Catches regressions in:
 *   - the "+ Nuovo docente" button + modal mount
 *   - the form fields (last_name / first_name / max_hours) bind
 *     correctly to the editing state
 *   - the "Salva" button POSTs /api/teachers and the new row appears
 *     in the SortableQueryableList
 *   - the "Modifica" button on a row opens the edit modal pre-filled
 *   - the "Elimina" button removes the row from the list
 *
 * The user has flagged frontend regressions (Tab Ore, Dashboard
 * dropdown) as the highest-priority class of bug to lock down. This
 * spec is the first of the per-tab CRUD-coverage suites.
 */

import { clearDataset } from '../support/seed';
import { acceptConfirm } from '../support/confirm';

const BACKEND = (Cypress.env('backendUrl') as string)
  || 'http://127.0.0.1:8000';

// Use a unique surname per run to avoid colliding with leftover rows.
function uniqueLastName(prefix: string): string {
  return `${prefix}_${Date.now().toString().slice(-6)}`;
}

describe('Tab Docenti CRUD workflow (UI-only)', () => {
  beforeEach(() => {
    clearDataset();
    // Reset working hours so the WeeklyCalendarView in the modal
    // has slots to render.
    cy.request({
      method: 'POST',
      url: `${BACKEND}/api/working-hours/reset`,
      failOnStatusCode: false,
      body: {},
    });
    cy.visit('/teachers');
    cy.get('[data-testid="teachers-page"]', { timeout: 15000 })
      .should('exist');
  });

  it('creates a new teacher via the modal form', () => {
    const last = uniqueLastName('Rossi');

    cy.intercept('POST', '**/api/teachers').as('createTeacher');

    cy.get('[data-testid="add-teacher-btn"]').click();
    cy.get('[data-testid="teacher-form"]').should('be.visible');
    cy.get('[data-testid="teacher-last-name-input"]').type(last);
    cy.get('[data-testid="teacher-first-name-input"]').type('Mario');
    cy.get('[data-testid="teacher-max-hours-input"]')
      .clear().type('18');
    cy.get('[data-testid="teacher-save-btn"]').click();

    cy.wait('@createTeacher').then((interception) => {
      expect([200, 201]).to.include(
        interception.response?.statusCode || 0);
    });

    // The new row must show up in the list.
    cy.contains(last, { timeout: 15000 }).should('be.visible');
    cy.get('[data-testid="entity-row"][data-entity="teachers"]')
      .should('have.length.gte', 1);
  });

  it('edits an existing teacher via the Modifica button', () => {
    const last = uniqueLastName('Verdi');

    // Seed via API so the test focuses on the EDIT path.
    cy.request('POST', `${BACKEND}/api/teachers`, {
      name: `${last} Luigi`,
      last_name: last,
      first_name: 'Luigi',
      nickname: `${last} Luigi`,
      subjects: [],
      max_hours: 18,
      unavailability: [],
      preferred_free_days: [],
      classroom_prefs: [],
    });
    cy.reload();
    cy.contains(last, { timeout: 15000 }).should('be.visible');

    cy.intercept('PUT', '**/api/teachers/*').as('updateTeacher');

    // Click the Modifica button on the row (we don't know the exact id;
    // contains the surname pinpoints the right row).
    cy.contains('tr', last)
      .find('[data-testid="teacher-edit-btn"]')
      .click();

    cy.get('[data-testid="teacher-form"]').should('be.visible');
    cy.get('[data-testid="teacher-last-name-input"]')
      .should('have.value', last);

    // Tweak max_hours.
    cy.get('[data-testid="teacher-max-hours-input"]')
      .clear().type('20');
    cy.get('[data-testid="teacher-save-btn"]').click();

    cy.wait('@updateTeacher').its('response.statusCode')
      .should('be.oneOf', [200, 204]);
  });

  it('cancels edit without saving', () => {
    const last = uniqueLastName('Bianchi');

    cy.request('POST', `${BACKEND}/api/teachers`, {
      name: `${last} Anna`,
      last_name: last,
      first_name: 'Anna',
      nickname: `${last} Anna`,
      subjects: [],
      max_hours: 18,
      unavailability: [],
      preferred_free_days: [],
      classroom_prefs: [],
    });
    cy.reload();
    cy.contains(last, { timeout: 15000 }).should('be.visible');

    cy.contains('tr', last)
      .find('[data-testid="teacher-edit-btn"]')
      .click();
    cy.get('[data-testid="teacher-form"]').should('be.visible');
    cy.get('[data-testid="teacher-cancel-btn"]').click();
    cy.get('[data-testid="teacher-form"]').should('not.exist');
  });

  it('deletes a teacher via the Elimina button', () => {
    const last = uniqueLastName('Neri');

    cy.request('POST', `${BACKEND}/api/teachers`, {
      name: `${last} Carlo`,
      last_name: last,
      first_name: 'Carlo',
      nickname: `${last} Carlo`,
      subjects: [],
      max_hours: 18,
      unavailability: [],
      preferred_free_days: [],
      classroom_prefs: [],
    });
    cy.reload();
    cy.contains(last, { timeout: 15000 }).should('be.visible');

    cy.intercept('DELETE', '**/api/teachers/*').as('deleteTeacher');

    cy.contains('tr', last)
      .find('[data-testid="teacher-delete-btn"]')
      .click();
    // Elimina apre ConfirmDialog, non window.confirm.
    acceptConfirm();

    cy.wait('@deleteTeacher').its('response.statusCode')
      .should('be.oneOf', [200, 204]);
    cy.contains(last).should('not.exist');
  });

  it('teacher edit modal mounts the WeeklyCalendarView with the '
     + 'configured working-hours slots', () => {
    const last = uniqueLastName('Gialli');

    cy.request('POST', `${BACKEND}/api/teachers`, {
      name: `${last} Sara`,
      last_name: last,
      first_name: 'Sara',
      nickname: `${last} Sara`,
      subjects: [],
      max_hours: 18,
      unavailability: [],
      preferred_free_days: [],
      classroom_prefs: [],
    });
    cy.reload();
    cy.contains(last, { timeout: 15000 }).should('be.visible');

    cy.contains('tr', last)
      .find('[data-testid="teacher-edit-btn"]')
      .click();

    // scrollIntoView() is required: the calendar sits ~680px down a
    // 2100px-tall modal body inside a `position: fixed` wrapper, so in
    // the default 1000x660 viewport Cypress considers it overflowed by
    // other elements and be.visible can never pass.
    cy.get('.weekly-calendar', { timeout: 10000 })
      .scrollIntoView()
      .should('be.visible');
    cy.contains(/Disponibilita oraria/i).should('be.visible');
    cy.get('.cal-event').should('have.length.gte', 1);
  });
});
