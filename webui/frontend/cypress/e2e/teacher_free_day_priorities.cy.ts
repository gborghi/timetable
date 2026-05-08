/// <reference types="cypress" />

/**
 * Teacher 3-priority free-day preferences workflow.
 *
 * Verifies the new "Giorni liberi (priorita' 1-3)" section in the
 * teacher edit modal:
 *   - Three dropdowns (1a/2a/3a scelta) bind to local state.
 *   - On save the PATCH endpoint stores the rows in
 *     /api/teachers/{id}/free-day-preferences with priority 1..3.
 *   - Re-opening the teacher loads the rows back into the dropdowns.
 *   - Picking the same day twice surfaces an inline error message.
 */

import { clearDataset } from '../support/seed';

const BACKEND = (Cypress.env('backendUrl') as string)
  || 'http://127.0.0.1:8000';

function uniqueLastName(prefix: string): string {
  return `${prefix}_${Date.now().toString().slice(-6)}`;
}

describe('Tab Docenti 3-priority free-day preferences', () => {
  beforeEach(() => {
    clearDataset();
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

  it('saves the 3 priorities then reloads them on edit', () => {
    const last = uniqueLastName('Bianchi');

    // Seed teacher via API (focus on the priorities flow).
    cy.request('POST', `${BACKEND}/api/teachers`, {
      name: `${last} Anna`,
      last_name: last,
      first_name: 'Anna',
      subjects: [],
    }).then((res) => {
      const teacherId = res.body.id;
      expect(teacherId).to.be.a('number');

      cy.visit('/teachers');
      cy.get('[data-testid="teachers-page"]', { timeout: 15000 })
        .should('exist');
      cy.contains(last, { timeout: 15000 }).should('be.visible');

      // Click Modifica on the row to open the modal.
      cy.contains('[data-entity="teachers"]', last)
        .find('[data-testid="teacher-edit-btn"]').click({ force: true });
      cy.get('[data-testid="teacher-form"]').should('be.visible');

      // Set the 3 priorities: Mon, Wed, Fri.
      cy.get('[data-test="free-day-priorities"]').within(() => {
        cy.get('[data-test="free-day-priority-1"]').select('1');
        cy.get('[data-test="free-day-priority-2"]').select('3');
        cy.get('[data-test="free-day-priority-3"]').select('5');
      });

      cy.intercept('PATCH',
        `**/api/teachers/${teacherId}/free-day-preferences`)
        .as('patchFdp');

      cy.get('[data-testid="teacher-save-btn"]').click();

      cy.wait('@patchFdp').then((interception) => {
        expect(interception.response?.statusCode).to.eq(200);
        const body = interception.request.body as {
          preferences: Array<{ day: number; priority: number }>;
        };
        expect(body.preferences).to.deep.equal([
          { day: 1, priority: 1 },
          { day: 3, priority: 2 },
          { day: 5, priority: 3 },
        ]);
      });

      // Verify via API that the rows landed.
      cy.request(
        'GET',
        `${BACKEND}/api/teachers/${teacherId}/free-day-preferences`,
      ).then((r) => {
        expect(r.status).to.eq(200);
        expect(r.body).to.have.length(3);
        const byPri = new Map<number, number>(
          (r.body as Array<{ day: number; priority: number }>)
            .map((row) => [row.priority, row.day]));
        expect(byPri.get(1)).to.eq(1);
        expect(byPri.get(2)).to.eq(3);
        expect(byPri.get(3)).to.eq(5);
      });

      // Reopen the modal: dropdowns must reflect the saved values.
      cy.contains('[data-entity="teachers"]', last)
        .find('[data-testid="teacher-edit-btn"]').click({ force: true });
      cy.get('[data-testid="teacher-form"]').should('be.visible');
      cy.get('[data-test="free-day-priority-1"]').should('have.value', '1');
      cy.get('[data-test="free-day-priority-2"]').should('have.value', '3');
      cy.get('[data-test="free-day-priority-3"]').should('have.value', '5');
    });
  });

  it('flags duplicate-day combinations inline', () => {
    const last = uniqueLastName('Neri');

    cy.request('POST', `${BACKEND}/api/teachers`, {
      name: `${last} Marco`,
      last_name: last,
      first_name: 'Marco',
      subjects: [],
    });

    cy.visit('/teachers');
    cy.get('[data-testid="teachers-page"]', { timeout: 15000 })
      .should('exist');
    cy.contains(last, { timeout: 15000 }).should('be.visible');

    cy.contains('[data-entity="teachers"]', last)
      .find('[data-testid="teacher-edit-btn"]').click({ force: true });
    cy.get('[data-testid="teacher-form"]').should('be.visible');

    // Duplicate Monday on priority 1 and 2 -> error visible.
    cy.get('[data-test="free-day-priority-1"]').select('1');
    cy.get('[data-test="free-day-priority-2"]').select('1');
    cy.get('[data-test="free-day-priority-error"]').should('be.visible');

    // Disambiguate -> error disappears.
    cy.get('[data-test="free-day-priority-2"]').select('2');
    cy.get('[data-test="free-day-priority-error"]').should('not.exist');
  });
});
