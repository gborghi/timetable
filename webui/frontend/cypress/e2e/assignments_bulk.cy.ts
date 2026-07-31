/// <reference types="cypress" />

/**
 * /assignments -- bulk-action toolbar.
 *
 * Setup uses seedMiniScenario + seedAssignments (8 cattedre across
 * 2 classes, 4 subjects each). The new bulk toolbar appears when at
 * least one row checkbox is ticked and exposes:
 *   - Elimina        -> POST /api/assignments/bulk/delete
 *   - Blocca/Sblocca -> POST /api/assignments/bulk/lock
 *   - Cambia docente -> opens modal -> POST .../bulk/change-teacher
 *   - Imposta/Rimuovi POT -> POST .../bulk/set-flag
 *
 * This spec verifies:
 *   - toolbar hidden by default; appears after first row checked
 *   - per-class "select all" toggles every row in that card
 *   - bulk delete removes the selected rows + clears selection
 *   - bulk lock sets locked=true on selected rows
 *   - change-teacher modal opens and submits the right payload
 *   - 0-selection state hides the toolbar again after Deseleziona tutto
 */

import { seedMiniScenario, seedAssignments } from
  '../support/seed';
import { acceptConfirm } from '../support/confirm';

const BACKEND = (Cypress.env('backendUrl') as string)
  || 'http://127.0.0.1:8000';

describe('/assignments bulk actions', () => {
  beforeEach(() => {
    seedMiniScenario().then((scenario) => seedAssignments(scenario));
    cy.visit('/assignments');
    cy.get('[data-testid="assignments-page"]', { timeout: 15000 })
      .should('exist');
    // Wait until at least one class card appears.
    cy.get('[data-testid="assignments-class-card"]', { timeout: 10000 })
      .should('have.length.gte', 1);
  });

  it('toolbar is hidden until a row is selected', () => {
    cy.get('[data-testid="bulk-toolbar"]').should('not.exist');
  });

  it('shows toolbar with count after one row checkbox click', () => {
    cy.get('[data-testid="assignments-row-checkbox"]').first().check();
    cy.get('[data-testid="bulk-toolbar"]').should('be.visible');
    cy.get('[data-testid="bulk-selected-count"]')
      .should('contain.text', '1 cattedre selezionate');
  });

  it('per-class "select all" checks every row in that card', () => {
    cy.get('[data-testid="assignments-class-card"]').first()
      .within(() => {
        cy.get('[data-testid="assignments-class-select-all"]').check();
        cy.get('[data-testid="assignments-row-checkbox"]:checked')
          .should('have.length', 4);  // 4 subjects per class
      });
    cy.get('[data-testid="bulk-selected-count"]')
      .should('contain.text', '4 cattedre selezionate');
  });

  it('"Deseleziona tutto" clears the selection and hides the toolbar',
     () => {
    cy.get('[data-testid="assignments-row-checkbox"]').first().check();
    cy.get('[data-testid="bulk-toolbar"]').should('be.visible');
    cy.get('[data-testid="bulk-clear-selection"]').click();
    cy.get('[data-testid="bulk-toolbar"]').should('not.exist');
  });

  it('bulk delete removes the selected rows', () => {
    // Initial count -- snapshot via API.
    cy.request(`${BACKEND}/api/assignments`).then((r) => {
      const before = (r.body.items ?? r.body).length;
      cy.wrap(before).as('countBefore');
    });

    // Select 2 rows from the first class card.
    cy.get('[data-testid="assignments-class-card"]').first()
      .within(() => {
        cy.get('[data-testid="assignments-row-checkbox"]').eq(0).check();
        cy.get('[data-testid="assignments-row-checkbox"]').eq(1).check();
      });
    cy.get('[data-testid="bulk-selected-count"]')
      .should('contain.text', '2 cattedre');

    cy.intercept('POST', '**/api/assignments/bulk/delete')
      .as('bulkDelete');
    cy.get('[data-testid="bulk-delete-btn"]').click();
    // La cancellazione in blocco passa da ConfirmDialog, non
    // window.confirm: senza questo la POST non parte mai.
    acceptConfirm();
    cy.wait('@bulkDelete').its('request.body.ids')
      .should('have.length', 2);

    // Toolbar disappears (selection cleared) and the API count
    // dropped by 2.
    cy.get('[data-testid="bulk-toolbar"]', { timeout: 5000 })
      .should('not.exist');
    cy.get('@countBefore').then((before: any) => {
      cy.request(`${BACKEND}/api/assignments`).then((r) => {
        const after = (r.body.items ?? r.body).length;
        expect(after).to.eq(before - 2);
      });
    });
  });

  it('bulk lock toggles the locked flag on selected rows', () => {
    cy.get('[data-testid="assignments-class-card"]').first()
      .within(() => {
        cy.get('[data-testid="assignments-class-select-all"]').check();
      });

    cy.intercept('POST', '**/api/assignments/bulk/lock')
      .as('bulkLock');
    cy.get('[data-testid="bulk-lock-btn"]').click();
    cy.wait('@bulkLock').its('request.body').should((body: any) => {
      expect(body.locked).to.eq(true);
      expect(body.ids).to.have.length(4);
    });

    // Verify via API.
    cy.request(`${BACKEND}/api/assignments`).then((r) => {
      const items = (r.body.items ?? r.body) as any[];
      const locked = items.filter((a) => a.locked === true);
      expect(locked.length).to.be.gte(4);
    });
  });

  it('Cambia docente modal submits the bulk-change-teacher payload',
     () => {
    // Pick the second teacher in the dataset (Prof Ita) -- the first
    // class's Italiano row should be assignable.
    cy.get('[data-testid="assignments-class-card"]').first()
      .within(() => {
        // Pick the row whose subject is Italiano via data-subject.
        cy.get('[data-testid="assignments-row"][data-subject="Italiano"]')
          .find('[data-testid="assignments-row-checkbox"]').check();
      });
    cy.get('[data-testid="bulk-change-teacher-btn"]').click();
    cy.get('[data-testid="bulk-change-teacher-modal"]', { timeout: 5000 })
      .should('be.visible');

    // The teacher dropdown must contain at least the seeded teachers.
    cy.get('[data-testid="bulk-teacher-select"]').find('option')
      .should('have.length.gte', 2);
    cy.get('[data-testid="bulk-teacher-select"]').select('Prof Ita');

    cy.intercept('POST', '**/api/assignments/bulk/change-teacher')
      .as('bulkChange');
    cy.get('[data-testid="bulk-change-teacher-confirm"]').click();
    cy.wait('@bulkChange').its('request.body').should((body: any) => {
      expect(body.teacher_name).to.eq('Prof Ita');
      expect(body.ids).to.have.length(1);
    });

    // Modal closes; toolbar gone (selection cleared).
    cy.get('[data-testid="bulk-change-teacher-modal"]')
      .should('not.exist');
    cy.get('[data-testid="bulk-toolbar"]').should('not.exist');
  });

  it('Imposta POT POSTs is_potenziamento=true', () => {
    cy.get('[data-testid="assignments-row-checkbox"]').first().check();
    cy.intercept('POST', '**/api/assignments/bulk/set-flag')
      .as('bulkFlag');
    cy.get('[data-testid="bulk-potenziamento-on-btn"]').click();
    cy.wait('@bulkFlag').its('request.body').should((body: any) => {
      expect(body.flag).to.eq('is_potenziamento');
      expect(body.value).to.eq(true);
    });
  });
});
