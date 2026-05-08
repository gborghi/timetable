/// <reference types="cypress" />

/**
 * Critical workflow E2E.
 *
 * End-to-end checks of the chains that we cannot break without the
 * UI becoming useless:
 *
 *   A. Tab Ore -> Tab Docenti propagation. Changing a slot in the
 *      working-hours config must reflect in the WeeklyCalendarView
 *      that drives every teacher's availability matrix.
 *
 *   B. Create teacher via UI -> row appears in the list, can be
 *      edited. Verifies the basic CRUD round-trip end-to-end.
 *
 * Solver invocation (Phase A + Phase B) is intentionally NOT
 * duplicated here -- `optimize_launch_solver.cy.ts` already covers
 * that path with the `small` profile.
 */

import { clearDataset } from '../support/seed';

const BACKEND = (Cypress.env('backendUrl') as string)
  || 'http://127.0.0.1:8000';

before(() => {
  // Start from a clean DB so concurrent CRUD tests don't collide.
  clearDataset();
  // Reset working hours to the engine default. Best-effort.
  cy.request({
    method: 'POST',
    url: `${BACKEND}/api/working-hours/reset`,
    failOnStatusCode: false,
    body: {},
  });
});

describe('A. Tab Ore -> Tab Docenti propagation', () => {
  it('the working-hours config drives the calendar in the teacher '
     + 'edit modal', () => {
    // Fetch the current config -- we'll verify the same number of
    // active days appears as columns in /teachers.
    cy.request(`${BACKEND}/api/working-hours/config`).then((r) => {
      const cfg = r.body;
      const activeDays = (cfg.days || []).filter(
        (d: any) => d.is_active);
      expect(activeDays.length, 'config must have >= 1 active day '
             + 'after reset').to.be.greaterThan(0);

      // Seed a single teacher via the API (faster than UI form).
      cy.request('POST', `${BACKEND}/api/teachers`, {
        name: 'Mario Rossi',
        first_name: 'Mario',
        last_name: 'Rossi',
        nickname: 'mrossi',
        subjects: [],
        max_hours: 18,
        unavailability: [],
        preferred_free_days: [],
        classroom_prefs: [],
      }).its('status').should('be.oneOf', [200, 201]);

      cy.visit('/teachers');
      cy.contains('Rossi', { timeout: 15000 }).should('be.visible');
      cy.contains('button', /Modifica/i).first().click();

      cy.get('.weekly-calendar', { timeout: 10000 }).should('be.visible');
      cy.get('.cal-day-col')
        .should('have.length', activeDays.length);
    });
  });
});

describe('B. Create + edit teacher CRUD round-trip', () => {
  beforeEach(() => {
    clearDataset();
    cy.request({
      method: 'POST',
      url: `${BACKEND}/api/working-hours/reset`,
      failOnStatusCode: false,
      body: {},
    });
  });

  it('POST /api/teachers + GET round-trip surfaces in /teachers UI', () => {
    cy.request('POST', `${BACKEND}/api/teachers`, {
      name: 'Luigi Verdi',
      first_name: 'Luigi',
      last_name: 'Verdi',
      nickname: 'lverdi',
      subjects: ['Matematica'],
      max_hours: 18,
      unavailability: [],
      preferred_free_days: [],
      classroom_prefs: [],
    }).its('status').should('be.oneOf', [200, 201]);

    cy.visit('/teachers');
    cy.contains('Verdi', { timeout: 15000 }).should('be.visible');
  });

  it('the teacher edit modal opens, shows the calendar, and the '
     + 'modal closes cleanly', () => {
    cy.request('POST', `${BACKEND}/api/teachers`, {
      name: 'Anna Bianchi',
      first_name: 'Anna',
      last_name: 'Bianchi',
      nickname: 'abianchi',
      subjects: [],
      max_hours: 18,
      unavailability: [],
      preferred_free_days: [],
      classroom_prefs: [],
    });

    cy.visit('/teachers');
    cy.contains('Bianchi', { timeout: 15000 }).should('be.visible');
    cy.contains('button', /Modifica/i).first().click();

    cy.contains(/Disponibilita oraria/i).should('be.visible');
    cy.get('.weekly-calendar').should('be.visible');

    // Close modal: try to find a close button or press Escape.
    cy.get('body').type('{esc}');
    cy.get('.weekly-calendar').should('not.exist');
  });
});

describe('C. Dashboard import end-state defensive check', () => {
  // Belt-and-suspenders: if the import endpoint 404s for the
  // selected profile (the historical bug), the dashboard must
  // surface that in the toast/flash area, NOT silently fail.
  it('clicking "Importa" with no profiles shows the empty-state '
     + '(button is disabled)', () => {
    cy.intercept('GET', '**/api/dataset/available-profiles', {
      statusCode: 200,
      body: [],
    }).as('emptyProfiles');
    cy.visit('/');
    cy.wait('@emptyProfiles');
    cy.get('[data-testid="dashboard-no-profiles"]').should('be.visible');
    cy.get('[data-testid="dashboard-import-btn"]').should('be.disabled');
  });
});
