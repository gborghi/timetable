/// <reference types="cypress" />

/**
 * /assenze-supplenze -- absences and substitutes panel.
 *
 * The page only operates when there is an active solution; in a
 * fresh DB it shows the "Nessuna soluzione attiva" hint. The test
 * smokes both branches:
 *   - clean DB -> no-active-solution hint visible
 *   - week navigation buttons (prev / next / oggi) wired
 */

import { clearDataset } from '../support/seed';

describe('Tab Assenze e supplenze smoke', () => {
  beforeEach(() => {
    clearDataset();
    cy.visit('/assenze-supplenze');
    cy.get('[data-testid="absences-page"]', { timeout: 15000 })
      .should('exist');
  });

  it('week navigation header is wired', () => {
    cy.get('[data-testid="absences-week-input"]').should('be.visible');
    cy.get('[data-testid="absences-prev-week"]').should('be.visible');
    cy.get('[data-testid="absences-next-week"]').should('be.visible');
    cy.get('[data-testid="absences-today"]').should('be.visible');
  });

  it('without an active solution the hint is shown', () => {
    cy.contains(/Nessuna soluzione attiva|importa o calcola/i,
                { timeout: 10000 }).should('be.visible');
  });

  it('prev / next week buttons fire a coverage reload', () => {
    cy.intercept('GET', '**/api/coverage/week**').as('coverageWeek');
    cy.get('[data-testid="absences-prev-week"]').click();
    cy.wait('@coverageWeek');
    cy.get('[data-testid="absences-next-week"]').click();
    cy.wait('@coverageWeek');
    cy.get('[data-testid="absences-today"]').click();
    cy.wait('@coverageWeek');
  });
});
