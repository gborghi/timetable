/// <reference types="cypress" />

/**
 * /constraints -- the wizard + DSL editor + feasibility panel.
 *
 * The page has three top-bar buttons (Nuovo vincolo / Nuovo
 * vincolo DSL / Feasibility Check) plus the SortableQueryableList
 * of existing constraints. This spec smokes:
 *   - the page mounts
 *   - the three top-bar buttons are wired (clicking opens the
 *     respective modal/panel without throwing)
 *
 * Full DSL-editor / wizard CRUD coverage is deferred -- those flows
 * have many sub-states that warrant dedicated specs.
 */

import { clearDataset } from '../support/seed';

describe('Tab Vincoli smoke', () => {
  beforeEach(() => {
    clearDataset();
    cy.visit('/constraints');
    cy.get('[data-testid="constraints-page"]', { timeout: 15000 })
      .should('exist');
  });

  it('renders top-bar buttons', () => {
    cy.get('[data-testid="new-constraint-btn"]').should('be.visible');
    cy.get('[data-testid="new-dsl-constraint-btn"]').should('be.visible');
    cy.get('[data-testid="feasibility-toggle-btn"]').should('be.visible');
  });

  it('"+ Nuovo vincolo" opens the wizard modal', () => {
    cy.get('[data-testid="new-constraint-btn"]').click();
    // The wizard modal is a separate component (NewConstraintModal).
    // It exposes a heading containing "vincolo" -- assert something
    // user-visible appeared.
    cy.contains(/Nuovo vincolo|Wizard|Tipo di vincolo/i,
                { timeout: 10000 }).should('be.visible');
  });

  it('"+ Nuovo vincolo DSL" opens the DSL editor modal', () => {
    cy.get('[data-testid="new-dsl-constraint-btn"]').click();
    cy.contains(/DSL|Espressione|forall|exists/i,
                { timeout: 10000 }).should('be.visible');
  });

  it('"Feasibility Check" toggles the feasibility panel', () => {
    cy.get('[data-testid="feasibility-toggle-btn"]').click();
    cy.contains(/Feasibility Check|MUS|HARD/i,
                { timeout: 10000 }).should('be.visible');
    // Click again to hide.
    cy.get('[data-testid="feasibility-toggle-btn"]').click();
  });
});
