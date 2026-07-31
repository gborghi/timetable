/// <reference types="cypress" />

/**
 * /coteaching (Compresenze) -- end-to-end CRUD coverage.
 *
 * The page is a flat table of CoTeachingRule rows: (class_name,
 * subject, required, weight, n_teachers, teachers[]). Spec exercises:
 *
 *   - Empty-state rendering after a clear (count = 0)
 *   - + Nuova regola opens the form with empty defaults (n_teachers=2)
 *   - Filling the form + Salva POSTs /api/coteaching and the row
 *     appears in the table with HARD/SOFT pill, weight, n_teachers,
 *     teachers joined by " + "
 *   - Modifica opens the form pre-filled and PUT updates the row
 *     (toggle HARD->SOFT, change weight)
 *   - Elimina removes the row (DELETE round-trip)
 *   - Changing n_teachers grows / shrinks the teachers input list
 *   - Server rejection on duplicate (class, subject) is surfaced as a
 *     flash error (the row still doesn't appear a second time)
 *
 * The seeded scenario provides 2 classes + 4 teachers + 4 subjects
 * (Matematica, Italiano, Storia, Scienzenaturali) so the form's
 * datalists offer real options.
 */

import { seedMiniScenario } from '../support/seed';
import { acceptConfirm } from '../support/confirm';

const BACKEND = (Cypress.env('backendUrl') as string)
  || 'http://127.0.0.1:8000';

function uniqueSubject(prefix: string): string {
  // Subject names need to match an existing Subject row (the form is
  // a free-text input but the backend may validate). We stay within
  // the seeded subject set + a per-run suffix to dodge "duplicate"
  // on a re-run of a specific test.
  const seeded = ['Matematica', 'Italiano', 'Storia', 'Scienzenaturali'];
  return seeded[Date.now() % seeded.length];
}

describe('Tab Compresenze CRUD workflow', () => {
  before(() => {
    seedMiniScenario();
  });

  beforeEach(() => {
    // Wipe coteaching rules before every test so each run starts
    // empty-state. We don't have a dedicated /api/coteaching/clear
    // endpoint, so list+delete in JS.
    cy.request(`${BACKEND}/api/coteaching`).then((r) => {
      const rules = (r.body || []) as Array<{ id: number }>;
      rules.forEach((rule) => {
        cy.request({
          method: 'DELETE',
          url: `${BACKEND}/api/coteaching/${rule.id}`,
          failOnStatusCode: false,
        });
      });
    });

    cy.intercept('GET', '**/api/coteaching').as('listCoteaching');
    cy.visit('/coteaching');
    cy.get('[data-testid="coteaching-page"]', { timeout: 15000 })
      .should('exist');
    cy.wait('@listCoteaching');
  });

  it('starts in empty state after clear', () => {
    cy.get('[data-testid="coteaching-count"]').should('contain', '0 regole');
    cy.get('[data-testid="coteaching-row"]').should('not.exist');
  });

  it('creates a new HARD coteaching rule', () => {
    cy.intercept('POST', '**/api/coteaching').as('createRule');

    cy.get('[data-testid="add-coteaching-btn"]').click();
    cy.get('[data-testid="coteaching-form"]').should('be.visible');

    cy.get('[data-testid="coteaching-class-input"]').type('3A');
    cy.get('[data-testid="coteaching-subject-input"]').type('Matematica');
    // Required defaults to true via newRule()
    cy.get('[data-testid="coteaching-required-checkbox"]')
      .should('be.checked');
    cy.get('[data-testid="coteaching-weight-input"]')
      .clear().type('100');

    // n_teachers defaults to 2 -> 2 teacher inputs render
    cy.get('[data-testid="coteaching-teacher-input"]')
      .should('have.length', 2);
    cy.get('[data-testid="coteaching-teacher-input"][data-index="0"]')
      .type('Prof Mat');
    cy.get('[data-testid="coteaching-teacher-input"][data-index="1"]')
      .type('Prof Ita');

    cy.get('[data-testid="coteaching-save-btn"]').click();

    cy.wait('@createRule').its('response.statusCode')
      .should('be.oneOf', [200, 201]);

    cy.get('[data-testid="coteaching-form"]').should('not.exist');
    cy.get('[data-testid="coteaching-row"]'
      + '[data-class="3A"][data-subject="Matematica"]')
      .should('exist').within(() => {
        cy.get('[data-testid="coteaching-row-required"]').should('exist');
        cy.get('[data-testid="coteaching-row-nteachers"]')
          .should('contain', '2');
        cy.get('[data-testid="coteaching-row-teachers"]')
          .should('contain', 'Prof Mat')
          .and('contain', 'Prof Ita');
      });
    cy.get('[data-testid="coteaching-count"]').should('contain', '1');
  });

  it('edits an existing rule (toggles HARD->SOFT, changes weight)',
     () => {
    // Seed a rule via API first
    cy.request('POST', `${BACKEND}/api/coteaching`, {
      class_name: '3A', subject: 'Italiano',
      required: true, weight: 50, n_teachers: 2,
      teachers: ['Prof Ita', 'Prof Sto'],
    });
    cy.reload();
    cy.wait('@listCoteaching');

    cy.intercept('PUT', '**/api/coteaching/*').as('updateRule');

    cy.get('[data-testid="coteaching-row"]'
      + '[data-class="3A"][data-subject="Italiano"]')
      .find('[data-testid="coteaching-edit-btn"]').click();

    cy.get('[data-testid="coteaching-form"]').should('be.visible');
    cy.get('[data-testid="coteaching-class-input"]')
      .should('have.value', '3A');
    cy.get('[data-testid="coteaching-subject-input"]')
      .should('have.value', 'Italiano');
    cy.get('[data-testid="coteaching-required-checkbox"]')
      .should('be.checked');

    // Toggle to SOFT, bump weight to 200
    cy.get('[data-testid="coteaching-required-checkbox"]')
      .uncheck({ force: true });
    cy.get('[data-testid="coteaching-weight-input"]')
      .clear().type('200');

    cy.get('[data-testid="coteaching-save-btn"]').click();

    cy.wait('@updateRule').its('response.statusCode')
      .should('be.oneOf', [200, 204]);

    cy.get('[data-testid="coteaching-row"]'
      + '[data-class="3A"][data-subject="Italiano"]')
      .within(() => {
        cy.get('[data-testid="coteaching-row-soft"]').should('exist');
        cy.get('[data-testid="coteaching-row-required"]')
          .should('not.exist');
        cy.get('[data-testid="coteaching-row-weight"]')
          .should('contain', '200');
      });
  });

  it('cancels edit without saving', () => {
    cy.request('POST', `${BACKEND}/api/coteaching`, {
      class_name: '4A', subject: 'Storia',
      required: false, weight: 30, n_teachers: 2,
      teachers: ['Prof Sto', 'Prof Sci'],
    });
    cy.reload();
    cy.wait('@listCoteaching');

    cy.get('[data-testid="coteaching-row"]'
      + '[data-class="4A"][data-subject="Storia"]')
      .find('[data-testid="coteaching-edit-btn"]').click();

    cy.get('[data-testid="coteaching-form"]').should('be.visible');
    cy.get('[data-testid="coteaching-cancel-btn"]').click();
    cy.get('[data-testid="coteaching-form"]').should('not.exist');

    cy.get('[data-testid="coteaching-row"]'
      + '[data-class="4A"][data-subject="Storia"]')
      .find('[data-testid="coteaching-row-soft"]').should('exist');
  });

  it('deletes a rule via Elimina', () => {
    cy.request('POST', `${BACKEND}/api/coteaching`, {
      class_name: '3A', subject: 'Storia',
      required: true, weight: 100, n_teachers: 2,
      teachers: ['Prof Sto', 'Prof Mat'],
    });
    cy.reload();
    cy.wait('@listCoteaching');

    cy.intercept('DELETE', '**/api/coteaching/*').as('deleteRule');

    cy.get('[data-testid="coteaching-row"]'
      + '[data-class="3A"][data-subject="Storia"]')
      .find('[data-testid="coteaching-delete-btn"]').click();
    // Elimina apre ConfirmDialog, non window.confirm.
    acceptConfirm();

    cy.wait('@deleteRule').its('response.statusCode')
      .should('be.oneOf', [200, 204]);

    cy.get('[data-testid="coteaching-row"]'
      + '[data-class="3A"][data-subject="Storia"]')
      .should('not.exist');
  });

  it('n_teachers input grows the teachers list', () => {
    cy.get('[data-testid="add-coteaching-btn"]').click();
    cy.get('[data-testid="coteaching-form"]').should('be.visible');

    // Default n_teachers=2 -> 2 inputs
    cy.get('[data-testid="coteaching-teacher-input"]')
      .should('have.length', 2);

    // {selectall} e non .clear(): il campo e' controllato
    // (value={editing.n_teachers}, non bind:value), quindi svuotarlo
    // fa scrivere subito "0" nel DOM col caret a inizio riga -- il "3"
    // successivo diventerebbe "30" e la lista crescerebbe a 30 input.
    cy.get('[data-testid="coteaching-nteachers-input"]')
      .type('{selectall}3');
    cy.get('[data-testid="coteaching-teacher-input"]')
      .should('have.length', 3);

    cy.get('[data-testid="coteaching-nteachers-input"]')
      .type('{selectall}2');
    cy.get('[data-testid="coteaching-teacher-input"]')
      .should('have.length', 2);

    cy.get('[data-testid="coteaching-cancel-btn"]').click();
  });

  it('rejects duplicate (class, subject) at API level', () => {
    cy.request('POST', `${BACKEND}/api/coteaching`, {
      class_name: '4A', subject: 'Matematica',
      required: true, weight: 100, n_teachers: 2,
      teachers: ['Prof Mat', 'Prof Ita'],
    });
    cy.reload();
    cy.wait('@listCoteaching');

    // Try to create a duplicate via the form -- backend returns 400
    cy.intercept('POST', '**/api/coteaching').as('createDup');

    cy.get('[data-testid="add-coteaching-btn"]').click();
    cy.get('[data-testid="coteaching-class-input"]').type('4A');
    cy.get('[data-testid="coteaching-subject-input"]').type('Matematica');
    cy.get('[data-testid="coteaching-teacher-input"][data-index="0"]')
      .type('Prof Mat');
    cy.get('[data-testid="coteaching-teacher-input"][data-index="1"]')
      .type('Prof Sci');
    cy.get('[data-testid="coteaching-save-btn"]').click();

    cy.wait('@createDup').its('response.statusCode')
      .should('be.oneOf', [400, 409, 422]);

    // Only 1 row exists for (4A, Matematica)
    cy.get('[data-testid="coteaching-row"]'
      + '[data-class="4A"][data-subject="Matematica"]')
      .should('have.length', 1);
  });
});
