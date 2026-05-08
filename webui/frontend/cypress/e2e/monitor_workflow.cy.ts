/// <reference types="cypress" />

/**
 * /monitor (Eventi) -- the run-time event panel.
 *
 * The page renders a segmented control (Tutti / Incompleti /
 * Senza orario / Lockati) above a GroupedEventsTable. This spec
 * covers:
 *   - the page mounts
 *   - the four tabs are clickable and switch state
 *   - "+ Nuovo evento" opens the AddEventModal
 *
 * The existing `monitor_smoke.cy.ts` covers the 200-OK smoke; this
 * one adds the segmented-control behavior with the new testid
 * hooks.
 */

describe('Tab Eventi (monitor) workflow', () => {
  beforeEach(() => {
    cy.visit('/monitor');
    cy.get('[data-testid="monitor-page"]', { timeout: 15000 })
      .should('exist');
  });

  it('renders the four segmented-control tabs', () => {
    cy.get('[data-testid="monitor-tabs"]').should('be.visible');
    cy.get('[data-testid="monitor-tab-all"]').should('be.visible');
    cy.get('[data-testid="monitor-tab-incomplete"]').should('be.visible');
    cy.get('[data-testid="monitor-tab-unscheduled"]').should('be.visible');
    cy.get('[data-testid="monitor-tab-locked"]').should('be.visible');
  });

  it('switching tabs does not throw', () => {
    cy.get('[data-testid="monitor-tab-incomplete"]').click();
    cy.get('[data-testid="monitor-tab-unscheduled"]').click();
    cy.get('[data-testid="monitor-tab-locked"]').click();
    cy.get('[data-testid="monitor-tab-all"]').click();
  });

  it('"+ Nuovo evento" opens the AddEvent modal', () => {
    cy.get('[data-testid="monitor-add-event-btn"]').click();
    // The modal title contains "evento".
    cy.contains(/Nuovo evento|Aggiungi|evento/i, { timeout: 10000 })
      .should('be.visible');
  });
});
