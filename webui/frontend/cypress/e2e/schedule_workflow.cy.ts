/// <reference types="cypress" />

/**
 * /schedule -- end-to-end workflow on the timetable page.
 *
 * The page has two distinct lifecycles:
 *
 *   (A) NO active Solution -> empty-state card with a link to
 *       /optimize. The view bar (Globale / Per classe / Per docente /
 *       Per aula), the export links and the "vista legacy" link still
 *       render; the calendar card does not.
 *
 *   (B) WITH an active Solution -> the calendar card renders and the
 *       non-global views expose the entity filter + selector.
 *
 * Storia di questo file: fino alla riscrittura della pagina il test
 * puntava alla vecchia UI a matrice (vista "per slot", toggle
 * matrice/lista, GET /api/schedule/by-teacher|by-room|by-slot). Quella
 * UI non esiste piu': ne resta solo la matrice 6x6 dietro
 * ``?legacy=true``, e i flussi drag-drop del calendario sono coperti
 * da schedule_calendar.cy.ts. Qui restano la struttura della pagina,
 * la vista legacy e il round-trip dell'AddLessonModal.
 *
 * Il blocco (B) NON rilancia Phase A+B (2-5 min): importa il profilo
 * "small" dallo snapshot SQLite, che arriva gia' con una Solution
 * attiva e le sue Lesson in circa un secondo.
 */

import { clearDataset } from '../support/seed';

const BACKEND = (Cypress.env('backendUrl') as string)
  || 'http://127.0.0.1:8000';

/** Import the "small" profile and wait for its run to finish. */
function importSmallProfile(deadlineMs = 120_000): void {
  cy.request('POST', `${BACKEND}/api/dataset/import-profile`, {
    profile: 'small', use_optimized: false,
    import_curricula: true, import_classrooms: true,
    import_students: false,
  }).then((r) => {
    const runId = r.body.run_id as number;
    const start = Date.now();
    const poll = (): Cypress.Chainable<boolean> => {
      if (Date.now() - start > deadlineMs) {
        throw new Error(`run #${runId} did not complete in ${deadlineMs}ms`);
      }
      // Il router dei run ha prefix /api/optimize.
      return cy.request({
        method: 'GET',
        url: `${BACKEND}/api/optimize/runs/${runId}`,
        failOnStatusCode: false,
      }).then((res) => {
        if (res.status === 200 && res.body && res.body.progress >= 1) {
          return true;
        }
        return cy.wait(500).then(() => poll() as unknown as boolean);
      });
    };
    poll();
  });
}

describe('/schedule -- empty state (no active Solution)', () => {
  before(() => {
    clearDataset();
  });

  it('renders the empty-state card + view bar + exports', () => {
    cy.visit('/schedule');
    cy.get('[data-testid="schedule-page"]', { timeout: 15000 })
      .should('exist');
    cy.contains(/Orario/i).should('be.visible');
    cy.get('[data-testid="schedule-empty-state"]').should('be.visible');
    cy.contains(/Nessuna soluzione attiva/i).should('be.visible');

    // View-toggle buttons render even without a solution.
    cy.get('[data-testid="schedule-view-global"]').should('exist');
    cy.get('[data-testid="schedule-view-classes"]').should('exist');
    cy.get('[data-testid="schedule-view-teachers"]').should('exist');
    cy.get('[data-testid="schedule-view-rooms"]').should('exist');

    // Export links are present (anchor tags).
    cy.get('[data-testid="schedule-export-xlsx-classes"]')
      .should('have.attr', 'href')
      .and('include', '/api/schedule/export/xlsx-classes');
    cy.get('[data-testid="schedule-export-pdf-teachers"]')
      .should('have.attr', 'href')
      .and('include', '/api/schedule/export/pdf-teachers');
  });

  it('clicking view buttons does not crash without a solution', () => {
    cy.visit('/schedule');
    cy.get('[data-testid="schedule-empty-state"]').should('be.visible');

    cy.get('[data-testid="schedule-view-teachers"]').click();
    cy.get('[data-testid="schedule-empty-state"]').should('be.visible');
    // Nessuna lezione -> nessun calendario, solo l'empty-state.
    cy.get('[data-testid="schedule-calendar-card"]').should('not.exist');

    cy.get('[data-testid="schedule-view-rooms"]').click();
    cy.get('[data-testid="schedule-empty-state"]').should('be.visible');
    cy.get('[data-testid="schedule-calendar-card"]').should('not.exist');
  });

  it('the legacy 6x6 matrix view is reachable and links back', () => {
    cy.visit('/schedule');
    cy.get('[data-testid="schedule-legacy-link"]').click();
    cy.contains(/Vista legacy/i, { timeout: 10000 }).should('be.visible');
    // Dalla legacy si torna al calendario, e il link legacy sparisce.
    cy.get('[data-testid="schedule-legacy-link"]').should('not.exist');
    cy.get('[data-testid="schedule-calendar-link"]').click();
    cy.get('[data-testid="schedule-legacy-link"]').should('exist');
  });
});

describe('/schedule -- with active Solution (imported profile)', () => {
  before(() => {
    clearDataset();
    importSmallProfile();
  });

  beforeEach(() => {
    cy.intercept('GET', '**/api/lessons*').as('listLessons');
    cy.visit('/schedule');
    cy.get('[data-testid="schedule-page"]', { timeout: 15000 })
      .should('exist');
    cy.wait('@listLessons');
  });

  it('global view renders the calendar + obj_value', () => {
    cy.get('[data-testid="schedule-empty-state"]').should('not.exist');
    cy.get('[data-testid="schedule-obj-value"]').should('be.visible');
    cy.get('[data-testid="schedule-calendar-card"]').should('be.visible');
    cy.get('.weekly-calendar').should('be.visible');
  });

  it('view toggle: global -> classe -> docente -> aula popola il '
     + 'selettore entita', () => {
    // In vista globale il filtro entita' non esiste.
    cy.get('[data-testid="schedule-entity-select"]').should('not.exist');

    for (const view of ['classes', 'teachers', 'rooms']) {
      cy.get(`[data-testid="schedule-view-${view}"]`).click();
      cy.get('[data-testid="schedule-entity-select"]', { timeout: 10000 })
        .should('be.visible')
        .find('option').should('have.length.gte', 1);
      cy.get('[data-testid="schedule-entity-filter"]').should('exist');
    }

    cy.get('[data-testid="schedule-view-global"]').click();
    cy.get('[data-testid="schedule-entity-select"]').should('not.exist');
  });

  it('the class filter limits the calendar to the chosen class', () => {
    // Il conteggio degli eventi e' l'unico segnale affidabile: nella
    // vista per classe le card NON ripetono il nome della classe (sta
    // nel titolo del calendario), quindi non si puo' asserire sul
    // testo dei singoli eventi.
    cy.get('[data-testid^="sched-lesson-"]').its('length')
      .then((globalCount) => {
        cy.get('[data-testid="schedule-view-classes"]').click();
        cy.get('[data-testid="schedule-entity-select"]', { timeout: 10000 })
          .find('option').first().then(($opt) => {
            const name = $opt.val() as string;
            cy.get('[data-testid="schedule-entity-select"]').select(name);
            cy.get('.weekly-calendar').should('contain.text', name);
            cy.get('[data-testid^="sched-lesson-"]')
              .should('have.length.greaterThan', 0)
              .and('have.length.lessThan', globalCount);
          });
      });
  });

  it('AddLessonModal opens from an empty slot and validates the '
     + 'required fields', () => {
    // Uno slot configurato ma vuoto: senza, il click apre il menu
    // azioni della lezione invece dell'AddLessonModal.
    cy.request(`${BACKEND}/api/working-hours/config`).then((cfgRes) => {
      cy.request(`${BACKEND}/api/lessons`).then((lesRes) => {
        const taken = new Set(
          ((lesRes.body.lessons || []) as { day: number; hour: number }[])
            .map((l) => `${l.day}-${l.hour}`));
        let slot: { day: number; hour: number } | null = null;
        for (const d of cfgRes.body.days || []) {
          if (!d.is_active) continue;
          for (const s of d.slots || []) {
            const key = `${d.legacy_day_number}-${s.legacy_hour_number}`;
            if (!taken.has(key) && !slot) {
              slot = { day: d.legacy_day_number,
                       hour: s.legacy_hour_number };
            }
          }
        }
        if (!slot) {
          cy.log('No empty configured slot; skipping');
          return;
        }
        cy.get(`[data-testid="sched-slot-${slot.day}-${slot.hour}"]`)
          .click();
        cy.get('[data-testid="add-lesson-modal"]', { timeout: 5000 })
          .should('be.visible');

        // Submit senza compilare: la modale resta aperta.
        cy.get('[data-testid="add-lesson-submit-btn"]').click();
        cy.get('[data-testid="add-lesson-modal"]').should('be.visible');

        cy.get('[data-testid="add-lesson-cancel-btn"]').click();
        cy.get('[data-testid="add-lesson-modal"]').should('not.exist');
      });
    });
  });

  it('SolutionsTable lists at least the active solution', () => {
    cy.contains(/soluzion/i, { timeout: 10000 }).should('be.visible');
  });
});
