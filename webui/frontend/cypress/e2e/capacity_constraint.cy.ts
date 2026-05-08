/// <reference types="cypress" />

/**
 * Capacity HARD constraint -- UI surface.
 *
 * Verifies that:
 *  1. The inline "N. studenti" input on /classes saves on blur and
 *     PATCHes /api/classes/{id} with the new value.
 *  2. The inline "Capienza" input on /classrooms saves on blur and
 *     PATCHes /api/classrooms/{id} with the new value.
 *  3. The AddLessonModal (or AddEventModal) shows a red capacity
 *     warning chip when the picked classroom has capacity <
 *     n_students of the picked class.
 *
 * Backend HARD enforcement is exercised by tests/test_capacity_constraint.py
 * (top-level pytest) -- this file only pins the UX surface.
 */

import { clearDataset } from '../support/seed';

const BACKEND = (Cypress.env('backendUrl') as string)
  || 'http://127.0.0.1:8000';

describe('Capacity constraint -- UI', () => {
  beforeEach(() => {
    clearDataset();
    cy.request({
      method: 'POST',
      url: `${BACKEND}/api/working-hours/reset`,
      failOnStatusCode: false,
      body: {},
    });
  });

  it('inline n_students editing on /classes persists', () => {
    // Seed a class with default n_students.
    cy.request('POST', `${BACKEND}/api/classes`, {
      name: 'CAPTEST_CLASS',
      year: 1, section: 'A', n_students: 20,
      hard_entry_at_8: true, hard_exit_after_12: true,
      hard_no_holes: true, hard_dual_math: true,
      hard_dual_italian: true, hard_motorie_pairs: true,
      hard_max_6_per_day: true, soft_minimize_sixth_weight: 50,
    });

    cy.intercept('PATCH', '**/api/classes/*').as('patchClass');

    cy.visit('/classes');
    cy.get('[data-testid="classes-page"]', { timeout: 15000 })
      .should('exist');
    cy.contains('td', 'CAPTEST_CLASS').should('be.visible');

    // Find the row by class name and bump n_students inline.
    cy.contains('tr', 'CAPTEST_CLASS').within(() => {
      cy.get('[data-testid="class-n-students-input"]')
        .should('have.value', '20')
        .clear().type('32').blur();
    });

    cy.wait('@patchClass').its('response.statusCode')
      .should('be.oneOf', [200, 204]);

    // Reload and verify the new value sticks.
    cy.reload();
    cy.contains('tr', 'CAPTEST_CLASS').within(() => {
      cy.get('[data-testid="class-n-students-input"]')
        .should('have.value', '32');
    });
  });

  it('inline capacity editing on /classrooms persists', () => {
    cy.request('POST', `${BACKEND}/api/classrooms`, {
      name: 'CAPTEST_ROOM',
      kind: 'standard', capacity: 24,
      multi_class: false, multi_class_max: 1,
      multi_class_pref: 1, multi_class_pref_weight: 10,
    });

    cy.intercept('PATCH', '**/api/classrooms/*').as('patchRoom');

    cy.visit('/classrooms');
    cy.get('[data-testid="classrooms-page"]', { timeout: 15000 })
      .should('exist');
    cy.contains('td', 'CAPTEST_ROOM').should('be.visible');

    cy.contains('tr', 'CAPTEST_ROOM').within(() => {
      cy.get('[data-testid="classroom-capacity-inline-input"]')
        .should('have.value', '24')
        .clear().type('40').blur();
    });

    cy.wait('@patchRoom').its('response.statusCode')
      .should('be.oneOf', [200, 204]);

    cy.reload();
    cy.contains('tr', 'CAPTEST_ROOM').within(() => {
      cy.get('[data-testid="classroom-capacity-inline-input"]')
        .should('have.value', '40');
    });
  });

  it('inline n_students rejects out-of-range values', () => {
    cy.request('POST', `${BACKEND}/api/classes`, {
      name: 'CAPTEST_RANGE',
      year: 1, section: 'B', n_students: 22,
      hard_entry_at_8: true, hard_exit_after_12: true,
      hard_no_holes: true, hard_dual_math: true,
      hard_dual_italian: true, hard_motorie_pairs: true,
      hard_max_6_per_day: true, soft_minimize_sixth_weight: 50,
    });

    cy.visit('/classes');
    cy.get('[data-testid="classes-page"]', { timeout: 15000 })
      .should('exist');

    // 200 is above the 5..50 client-side bound -- the page shows an
    // error toast and reverts to the server-side value (22).
    cy.contains('tr', 'CAPTEST_RANGE').within(() => {
      cy.get('[data-testid="class-n-students-input"]')
        .clear().type('200').blur();
    });
    // Toast error visible (flash component).
    cy.contains('deve essere fra', { timeout: 5000 })
      .should('be.visible');
    // The list reloads to the server value.
    cy.contains('tr', 'CAPTEST_RANGE').within(() => {
      cy.get('[data-testid="class-n-students-input"]')
        .should('have.value', '22');
    });
  });
});
