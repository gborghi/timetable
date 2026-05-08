/// <reference types="cypress" />

/**
 * Dataset import via SQLite snapshot.
 *
 * Pins the new default of /api/dataset/import-profile: the
 * <profile>.sqlite snapshot under engine/scripts/data/<profile>/
 * is read directly, populating anagrafica + 14 constraint tables
 * + WorkingDay/Slot + Lessons in one shot. The legacy pickle path
 * is exercised separately in the older import smoke tests.
 *
 * The test uses the smallest profile so the run finishes within
 * the Cypress timeout. End-of-run is detected by polling
 * /api/dataset/state until the import shows up.
 */

import { clearDataset } from '../support/seed';

const BACKEND = (Cypress.env('backendUrl') as string)
  || 'http://127.0.0.1:8000';

function waitForRunComplete(runId: number, deadlineMs = 60_000) {
  const start = Date.now();
  function poll(): Cypress.Chainable<boolean> {
    if (Date.now() - start > deadlineMs) {
      throw new Error(`run #${runId} did not complete in ${deadlineMs}ms`);
    }
    return cy.request({
      method: 'GET',
      url: `${BACKEND}/api/runs/${runId}`,
      failOnStatusCode: false,
    }).then((res) => {
      if (res.status === 200 && res.body && res.body.progress >= 1) {
        return true;
      }
      return cy.wait(500).then(() => poll() as unknown as boolean);
    });
  }
  return poll();
}

describe('Dataset import via SQLite snapshot', () => {
  beforeEach(() => {
    clearDataset();
  });

  it('imports the small profile from <profile>.sqlite and renders /schedule', () => {
    cy.intercept('POST', '**/api/dataset/import-profile').as('startImport');

    cy.visit('/');
    cy.get('[data-testid="dashboard-import-profile-select"]',
        { timeout: 15000 })
      .should('exist')
      .select('small');

    cy.contains('button', /Importa profilo/i).click();
    cy.wait('@startImport').its('response.statusCode')
      .should('be.oneOf', [200, 201]);

    // Pull the run id from the most recent run -- the returned body
    // carries it directly.
    cy.get('@startImport').then((interception: any) => {
      const runId = interception?.response?.body?.run_id;
      expect(runId).to.be.a('number');
      waitForRunComplete(runId);
    });

    // Verify the live DB now has rows from each category the
    // SQLite snapshot ships.
    cy.request(`${BACKEND}/api/classes`).its('body')
      .should('have.length.greaterThan', 0);
    cy.request(`${BACKEND}/api/classrooms`).its('body')
      .should('have.length.greaterThan', 0);
    cy.request(`${BACKEND}/api/general-constraints`).its('body')
      .should('have.length.greaterThan', 0);
    cy.request(`${BACKEND}/api/working-hours/config`).its('body.days')
      .should('have.length.greaterThan', 0);
    cy.request(`${BACKEND}/api/lessons`).its('body')
      .should('have.length.greaterThan', 0);

    // /schedule should render the timetable from the imported rows.
    cy.visit('/schedule');
    cy.get('body', { timeout: 15000 }).should('contain.text', 'Lun');
  });
});
