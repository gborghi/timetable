/// <reference types="cypress" />

/**
 * /constraints -- DSL editor + 4-step wizard + search/filter +
 * bulk delete workflow.
 *
 * Complements `constraints_smoke.cy.ts` (which only verifies the
 * three top-bar buttons mount). This spec walks the full creation
 * flow for both kinds of constraints, then exercises the advanced
 * search panel and the per-row delete.
 *
 * Each test starts from `clearDataset()` so the DB is fresh; entities
 * needed for the wizard owner-dropdowns (teachers, classes, rooms)
 * are seeded via the public POST endpoints.
 */

import { clearDataset } from '../support/seed';
import { acceptConfirm } from '../support/confirm';

const BACKEND = (Cypress.env('backendUrl') as string)
  || 'http://127.0.0.1:8000';

function seedTeacher(name = 'Prof Test', group = 'A027'): Cypress.Chainable<number> {
  return cy.request('POST', `${BACKEND}/api/teachers`, {
    name, group, max_hours: 18,
  }).then((r) => r.body.id as number);
}

function seedClass(name = '3A'): Cypress.Chainable<number> {
  return cy.request('POST', `${BACKEND}/api/classes`, {
    name, year: 3, section: 'A',
    curriculum: 'Scientifico', n_students: 22,
    subjects: [{ subject: 'Matematica', hours_per_week: 4 }],
    unavailability: [],
  }).then((r) => r.body.id as number);
}

function seedDsl(expression: string, opts: {
  level?: string; label?: string; weight?: number;
  scope?: string; ownerId?: number | null;
} = {}): Cypress.Chainable {
  return cy.request('POST', `${BACKEND}/api/constraints/general`, {
    expression,
    label: opts.label ?? null,
    level: opts.level ?? 'hard',
    weight: opts.weight ?? 100,
    scope: opts.scope ?? 'global',
    owner_id: opts.ownerId ?? null,
  });
}

/**
 * Wipe the GeneralConstraint (DSL) table. `clearDataset()` does not
 * touch it -- constraints survive a dataset clear by design -- so
 * without this the DSL rows seeded by one test keep piling up and the
 * row-count assertions of the later ones drift.
 */
function clearDsl(): Cypress.Chainable {
  return cy.request(`${BACKEND}/api/constraints/general`).then((r) => {
    const rows = (r.body ?? []) as { id: number }[];
    return cy.wrap(rows).each((row: any) => {
      cy.request({
        method: 'DELETE',
        url: `${BACKEND}/api/constraints/general/${row.id}`,
        failOnStatusCode: false,
      });
    });
  });
}

describe('Tab Vincoli workflow', () => {
  beforeEach(() => {
    clearDataset();
    clearDsl();
    cy.visit('/constraints');
    cy.get('[data-testid="constraints-page"]', { timeout: 15000 })
      .should('exist');
  });

  describe('DSL editor', () => {
    it('creates a DSL constraint via the modal and surfaces it in the '
       + 'DSL constraints table', () => {
      cy.get('[data-testid="new-dsl-constraint-btn"]').click();

      // The modal renders the expression textarea + level select.
      cy.get('[data-testid="dsl-expression"]', { timeout: 10000 })
        .should('be.visible')
        .type('forall l in lessons: l.hour >= 8');

      cy.get('[data-testid="dsl-level"]').select('hard');
      cy.get('[data-testid="dsl-label"]').type('test-dsl-label');

      // Wait for live-validate to resolve and the submit button to
      // become enabled. The debounce is 500ms.
      cy.get('[data-testid="dsl-submit"]', { timeout: 5000 })
        .should('not.be.disabled')
        .click();

      // Modal closes -> the page reloads dslConstraints and we see
      // the new row in the DSL table.
      cy.get('[data-testid="dsl-constraints-table"]', { timeout: 10000 })
        .should('be.visible')
        .contains('forall l in lessons: l.hour >= 8');
    });

    it('blocks submit on invalid syntax', () => {
      cy.get('[data-testid="new-dsl-constraint-btn"]').click();
      cy.get('[data-testid="dsl-expression"]', { timeout: 10000 })
        .should('be.visible')
        .type('this is not valid DSL @@@');
      // Live validate should mark it not-ok; the submit stays disabled.
      cy.get('[data-testid="dsl-submit"]', { timeout: 5000 })
        .should('be.disabled');
    });

    it('SOFT level reveals the weight input', () => {
      cy.get('[data-testid="new-dsl-constraint-btn"]').click();
      cy.get('[data-testid="dsl-expression"]', { timeout: 10000 })
        .should('be.visible');
      // HARD: no weight input yet.
      cy.get('[data-testid="dsl-weight"]').should('not.exist');
      cy.get('[data-testid="dsl-level"]').select('soft');
      cy.get('[data-testid="dsl-weight"]').should('be.visible');
    });

    it('deletes a pre-seeded DSL constraint via the row ✕', () => {
      seedDsl('forall l in lessons: l.hour >= 8',
              { label: 'doomed' }).then((r) => {
        const id = r.body.id;
        cy.reload();
        cy.get(`[data-testid="dsl-row-${id}"]`, { timeout: 10000 })
          .should('exist');
        cy.get(`[data-testid="dsl-delete-${id}"]`).click();
        // Il ✕ chiede conferma tramite ConfirmDialog.
        acceptConfirm();
        cy.get(`[data-testid="dsl-row-${id}"]`).should('not.exist');
      });
    });
  });

  describe('4-step wizard', () => {
    it('creates a teacher matrix_slot constraint end-to-end', () => {
      seedTeacher('Prof Test').then(() => {
        cy.reload();
        cy.get('[data-testid="constraints-page"]', { timeout: 15000 })
          .should('exist');
        cy.get('[data-testid="new-constraint-btn"]').click();

        // Step 1: scope=teacher (default), pick the only owner.
        cy.get('[data-testid="wizard-step-1"]', { timeout: 10000 })
          .should('be.visible');
        cy.get('[data-testid="wizard-scope"]').select('teacher');
        cy.get('[data-testid="wizard-owner"]')
          .find('option').should('have.length.gte', 2);
        cy.get('[data-testid="wizard-owner"]').select('Prof Test');
        cy.get('[data-testid="wizard-next"]').click();

        // Step 2: keep level=hard.
        cy.contains(/HARD/i).should('be.visible');
        cy.get('[data-testid="wizard-next"]').click();

        // Step 3: kind=matrix_slot (default for teacher), pick a slot.
        cy.get('[data-testid="wizard-step-3"]', { timeout: 5000 })
          .should('be.visible');
        cy.get('[data-testid="wizard-kind"]').should(
          'have.value', 'matrix_slot');
        cy.get('[data-testid="wizard-day"]').select('1');
        cy.get('[data-testid="wizard-hour"]').select('9');
        cy.get('[data-testid="wizard-next"]').click();

        // Step 4: submit.
        cy.contains(/Riepilogo|cella/i).should('be.visible');
        cy.get('[data-testid="wizard-submit"]').click();

        // Success indicator.
        cy.contains(/Vincolo creato|teacher_cell/i,
                    { timeout: 10000 }).should('be.visible');
      });
    });

    it('creates a teacher logical constraint end-to-end', () => {
      seedTeacher('Prof Logical').then(() => {
        cy.reload();
        cy.get('[data-testid="new-constraint-btn"]').click();

        cy.get('[data-testid="wizard-scope"]', { timeout: 10000 })
          .select('teacher');
        cy.get('[data-testid="wizard-owner"]').select('Prof Logical');
        cy.get('[data-testid="wizard-next"]').click();

        // Step 2: switch to soft, weight defaults to 100.
        // La ricerca e' ancorata a wizard-step-2: la legenda dei livelli
        // nell'hero della pagina contiene anch'essa una pill "SOFT", che
        // sta prima nel DOM e non ha nessun <label> antenato.
        cy.get('[data-testid="wizard-step-2"]', { timeout: 10000 })
          .contains('label', /SOFT/i)
          .find('input[type="radio"]').check({ force: true });
        cy.get('[data-testid="wizard-next"]').click();

        // Step 3: kind=logical, expression.
        cy.get('[data-testid="wizard-kind"]').select('logical');
        cy.get('[data-testid="wizard-expression"]').type('lun8 AND mar8');
        cy.get('[data-testid="wizard-next"]').click();

        // Step 4.
        cy.get('[data-testid="wizard-submit"]').click();
        cy.contains(/Vincolo creato|logical/i,
                    { timeout: 10000 }).should('be.visible');
      });
    });

    it('cycles scope categories and shows the matching owner '
       + 'dropdown', () => {
      cy.get('[data-testid="new-constraint-btn"]').click();
      cy.get('[data-testid="wizard-scope"]', { timeout: 10000 })
        .should('be.visible');

      // teacher -> Docente label.
      cy.get('[data-testid="wizard-scope"]').select('teacher');
      cy.contains('label', /Docente/).should('be.visible');

      // class -> Classe label.
      cy.get('[data-testid="wizard-scope"]').select('class');
      cy.contains('label', /Classe/).should('be.visible');

      // classroom -> Aula label.
      cy.get('[data-testid="wizard-scope"]').select('classroom');
      cy.contains('label', /Aula/).should('be.visible');

      // curriculum -> Indirizzo label.
      cy.get('[data-testid="wizard-scope"]').select('curriculum');
      cy.contains('label', /Indirizzo/).should('be.visible');
    });
  });

  describe('search/filter', () => {
    it('filters by entity type/id and surfaces only matching constraints',
       () => {
      seedTeacher('Prof Searchable').then((teacherId) => {
        // Create a global DSL constraint -- shouldn't match a
        // teacher-scoped search.
        seedDsl('forall l in lessons: l.hour >= 8',
                { label: 'global-dsl', scope: 'global' });
        // Create a teacher-scoped DSL: simple expression but tagged
        // with scope=teacher, owner_id=<id>. The constraint_search
        // adds ('teacher', owner_id) to the mention set, so the
        // search by that entity matches.
        seedDsl('forall l in lessons: l.hour <= 13',
                { label: 'teacher-dsl', scope: 'teacher',
                  ownerId: teacherId });

        cy.reload();
        cy.get('[data-testid="constraints-search-toggle"]').click();
        cy.get('[data-testid="search-entity-type"]', { timeout: 10000 })
          .select('teacher');
        cy.get('[data-testid="search-entity-id"]', { timeout: 5000 })
          .find('option').should('have.length.gte', 2);
        cy.get('[data-testid="search-entity-id"]')
          .select('Prof Searchable');
        cy.get('[data-testid="search-run"]').click();

        // The teacher-scoped one shows up; the global one does not.
        // Le asserzioni vanno confinate alla tabella dei risultati: le
        // due etichette compaiono comunque nella tabella DSL in fondo
        // alla pagina, che elenca tutti i GeneralConstraint e non
        // c'entra con la ricerca.
        cy.get('[data-testid="search-results-table"]', { timeout: 10000 })
          .should('be.visible')
          .and('contain.text', 'teacher-dsl')
          .and('not.contain.text', 'global-dsl');
      });
    });

    it('Reset clears the search panel state', () => {
      cy.get('[data-testid="constraints-search-toggle"]').click();
      cy.get('[data-testid="search-entity-type"]').select('class');
      cy.get('[data-testid="search-text"]').type('foo');
      cy.get('[data-testid="search-reset"]').click();
      cy.get('[data-testid="search-entity-type"]').should('have.value', '');
      cy.get('[data-testid="search-text"]').should('have.value', '');
    });

    it('bulk-deletes DSL rows individually via the row ✕ buttons', () => {
      // Seed 3 DSL constraints.
      seedDsl('forall l in lessons: l.hour >= 8', { label: 'a' });
      seedDsl('forall l in lessons: l.hour <= 13', { label: 'b' });
      seedDsl('forall l in lessons: l.day >= 1', { label: 'c' }).then(() => {
        cy.reload();
        cy.get('[data-testid="dsl-constraints-table"]', { timeout: 10000 })
          .should('be.visible');
        cy.get('[data-testid="dsl-constraints-table"] tbody tr')
          .should('have.length', 3);

        // Click each ✕ in turn, confermando ogni volta il
        // ConfirmDialog -- after each click the row count drops.
        cy.get('[data-testid^="dsl-delete-"]').first().click();
        acceptConfirm();
        cy.get('[data-testid="dsl-constraints-table"] tbody tr')
          .should('have.length', 2);
        cy.get('[data-testid^="dsl-delete-"]').first().click();
        acceptConfirm();
        cy.get('[data-testid="dsl-constraints-table"] tbody tr')
          .should('have.length', 1);
        cy.get('[data-testid^="dsl-delete-"]').first().click();
        acceptConfirm();
        // The whole table disappears when the list is empty.
        cy.get('[data-testid="dsl-constraints-table"]')
          .should('not.exist');
      });
    });
  });
});
