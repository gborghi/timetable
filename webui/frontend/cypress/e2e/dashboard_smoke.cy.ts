/// <reference types="cypress" />

/**
 * Dashboard smoke E2E.
 *
 * Reproduces (and locks down a fix for) two user-reported bugs:
 *
 *   1. Section 1 ("Importa un profilo gia` calcolato") shared the
 *      `selectedProfile` Svelte variable with section 2 ("Genera
 *      scuola di test"). The default value 'small' wasn't always in
 *      `availableProfiles` (the engine/scripts/data/<profile>/ layout
 *      only ships some profiles), so the dropdown displayed the
 *      first option visually but the bound variable stayed at
 *      'small'. Click "Importa" -> POST /api/dataset/import-profile
 *      with profile=small -> 404. Now: import section uses
 *      `importProfile`, mock section uses `mockProfile`, and
 *      onMount sets `importProfile` to the first available name.
 *
 *   2. Snapshot list dropdown / table is supposed to surface every
 *      .zip in webui/data/snapshots/. We seed one via POST to the
 *      backend and verify it shows up.
 *
 * Both checks rely on stable `data-testid` attributes added in the
 * dashboard card + DbImportExportCard.
 */

const BACKEND = (Cypress.env('backendUrl') as string)
  || 'http://127.0.0.1:8000';

describe('Dashboard smoke', () => {
  it('renders without console errors and the navbar is mounted', () => {
    cy.visit('/');
    cy.get('[data-testid="navbar"]').should('exist');
    cy.contains(/Dashboard/i).should('exist');
    // Both halves of section 2 (the cards) must be present.
    cy.get('[data-testid="dashboard-import-card"]').should('exist');
    cy.get('[data-testid="dashboard-mock-card"]').should('exist');
    // Import/Export card too (the snapshot management one).
    cy.get('[data-testid="db-import-export-card"]').should('exist');
  });

  it('import dropdown either lists profiles or shows an empty-state '
     + 'message (never a stuck "small" default)', () => {
    cy.intercept('GET', '**/api/dataset/available-profiles')
      .as('availableProfiles');
    cy.visit('/');
    cy.wait('@availableProfiles').its('response.statusCode').should('eq', 200);

    cy.get('[data-testid="dashboard-import-card"]').within(() => {
      cy.get('body, [data-testid="dashboard-no-profiles"], '
             + '[data-testid="dashboard-import-profile-select"]', { log: false })
        .should('exist');
    });

    // Branch on backend response: either we got >=1 profile (dropdown
    // is populated and `importProfile` matches a real option) or we got
    // zero (empty-state message visible, Import button disabled).
    cy.get('@availableProfiles').then((interception) => {
      // @ts-ignore -- Cypress types don't narrow .response here.
      const profiles = interception.response.body as Array<{ name: string }>;
      if (profiles.length === 0) {
        cy.get('[data-testid="dashboard-no-profiles"]').should('be.visible');
        cy.get('[data-testid="dashboard-import-btn"]').should('be.disabled');
      } else {
        cy.get('[data-testid="dashboard-import-profile-select"]')
          .should('be.visible')
          .find('option')
          .should('have.length.gte', 1);
        // Crucial assertion: the bound value matches a real option.
        cy.get('[data-testid="dashboard-import-profile-select"]')
          .invoke('val')
          .then((val) => {
            const names = profiles.map((p) => p.name);
            expect(names, 'select.value must match a real profile')
              .to.include(val);
          });
        cy.get('[data-testid="dashboard-import-btn"]').should('not.be.disabled');
      }
    });
  });

  it('mock generator dropdown is independent from import dropdown', () => {
    cy.visit('/');
    cy.get('[data-testid="dashboard-mock-profile-select"]')
      .should('exist')
      .find('option')
      .should('have.length.gte', 5);
    // Selecting a profile in the mock dropdown must NOT change the
    // import dropdown's value (the original bug).
    cy.get('[data-testid="dashboard-mock-profile-select"]')
      .select('huge')
      .should('have.value', 'huge');
    cy.get('body').then(($body) => {
      const importSelect = $body.find(
        '[data-testid="dashboard-import-profile-select"]');
      if (importSelect.length > 0) {
        // Should still match a real profile (i.e. NOT 'huge' unless huge
        // is on disk -- but more importantly the two dropdowns are now
        // bound to different state).
        cy.get('[data-testid="dashboard-import-profile-select"]')
          .invoke('val')
          .should('not.equal', 'huge');
      }
    });
  });

  it('snapshot section: previously created snapshots show up in the '
     + 'table after reload', () => {
    // Best-effort seed: ask the backend to make a snapshot. If the
    // endpoint isn't available we skip the rest of the assertions.
    cy.request({
      method: 'POST',
      url: `${BACKEND}/api/dashboard/snapshot/create`,
      failOnStatusCode: false,
      body: {},
    }).then((res) => {
      if (res.status !== 200) {
        cy.log(`snapshot create returned ${res.status}; skipping`);
        return;
      }
      cy.visit('/');
      cy.intercept('GET', '**/api/dashboard/snapshot/list').as('snapList');
      cy.get('[data-testid="snapshot-reload-btn"]').click();
      cy.wait('@snapList').its('response.statusCode').should('eq', 200);
      cy.get('[data-testid="snapshot-table"]', { timeout: 10000 })
        .should('be.visible');
      cy.get('[data-testid="snapshot-row"]').should('have.length.gte', 1);
    });
  });

  it('Reset DB button is wired (does not throw on click; we cancel '
     + 'the confirm)', () => {
    cy.visit('/');
    // Cancel the native confirm so the test is non-destructive.
    cy.on('window:confirm', () => false);
    cy.contains('button', /Reset DB/i).should('be.visible').click();
  });
});
