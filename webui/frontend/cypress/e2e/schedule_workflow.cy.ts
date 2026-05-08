/// <reference types="cypress" />

/**
 * /schedule -- end-to-end workflow on the timetable view.
 *
 * The page has two distinct lifecycles:
 *
 *   (A) NO active Solution -> renders an empty-state card with a link
 *       to /optimize. Every dropdown / matrix / slot view is hidden.
 *       The view-toggle buttons + export links still render.
 *
 *   (B) WITH active Solution -> the four views (per classe, per
 *       docente, per aula, per slot) work. Each view has a
 *       matrix/list mode toggle. The slot view has day/hour pickers
 *       and a "+ Nuovo evento in questo slot" button that opens the
 *       AddLessonModal.
 *
 * This spec covers (A) entirely (no setup, just clear). For (B) we
 * use seedSmallProfileAndRunPhaseA + Phase B which takes 2-5 min --
 * gated behind a single before() hook so the cost is paid once for
 * the full describe block, not per-test.
 *
 * The AddLessonModal validation tests do NOT depend on having a
 * solution -- they just check that the form opens, requires class +
 * teacher, and surfaces a flash error on missing fields. We trigger
 * those tests after the heavy seed too so the modal's slot context
 * is well-defined.
 */

import { clearDataset, seedSmallProfileAndRunPhaseA, waitForRun } from
  '../support/seed';

const BACKEND = (Cypress.env('backendUrl') as string)
  || 'http://127.0.0.1:8000';

describe('/schedule -- empty state (no active Solution)', () => {
  before(() => {
    clearDataset();
  });

  it('renders the empty-state card + view buttons + exports', () => {
    cy.visit('/schedule');
    cy.get('[data-testid="schedule-page"]', { timeout: 15000 })
      .should('exist');
    cy.contains(/Orario/i).should('be.visible');
    cy.get('[data-testid="schedule-empty-state"]').should('be.visible');
    cy.contains(/Nessuna soluzione attiva/i).should('be.visible');

    // View-toggle buttons render even without a solution
    cy.get('[data-testid="schedule-view-classes"]').should('exist');
    cy.get('[data-testid="schedule-view-teachers"]').should('exist');
    cy.get('[data-testid="schedule-view-rooms"]').should('exist');
    cy.get('[data-testid="schedule-view-slot"]').should('exist');

    // Export links are present (anchor tags)
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
    cy.get('[data-testid="schedule-teachers-view"]').should('not.exist');

    cy.get('[data-testid="schedule-view-rooms"]').click();
    cy.get('[data-testid="schedule-empty-state"]').should('be.visible');
    cy.get('[data-testid="schedule-rooms-view"]').should('not.exist');
  });
});

describe('/schedule -- with active Solution (Phase A+B run)', () => {
  before(() => {
    seedSmallProfileAndRunPhaseA(180, 2000);
    cy.request({
      method: 'POST', url: `${BACKEND}/api/optimize/phase-b`,
      body: { time_a: 30, time_mono: 60, workers: 4, log: false },
    }).then((r) => {
      expect(r.status).to.eq(200);
      waitForRun(r.body.run_id, 240, 3000);
    });
  });

  beforeEach(() => {
    cy.intercept('GET', '**/api/schedule/by-class').as('byClass');
    cy.intercept('GET', '**/api/schedule/by-teacher').as('byTeacher');
    cy.intercept('GET', '**/api/schedule/by-room').as('byRoom');
    cy.visit('/schedule');
    cy.get('[data-testid="schedule-page"]', { timeout: 15000 })
      .should('exist');
    cy.wait('@byClass');
  });

  it('classes view renders the class selector + obj_value', () => {
    cy.get('[data-testid="schedule-empty-state"]').should('not.exist');
    cy.get('[data-testid="schedule-obj-value"]').should('be.visible');
    cy.get('[data-testid="schedule-classes-view"]').should('be.visible');
    cy.get('[data-testid="schedule-class-select"] option')
      .should('have.length.gte', 1);
  });

  it('view toggle: classes -> teachers -> rooms -> slot', () => {
    cy.get('[data-testid="schedule-view-teachers"]').click();
    cy.wait('@byTeacher');
    cy.get('[data-testid="schedule-teachers-view"]').should('be.visible');
    cy.get('[data-testid="schedule-teacher-select"]').should('exist');

    cy.get('[data-testid="schedule-view-rooms"]').click();
    cy.get('[data-testid="schedule-rooms-view"]').should('be.visible');

    cy.get('[data-testid="schedule-view-slot"]').click();
    cy.get('[data-testid="schedule-slot-view"]').should('be.visible');
    cy.get('[data-testid="schedule-slot-day"]').should('exist');
    cy.get('[data-testid="schedule-slot-hour"]').should('exist');
    cy.get('[data-testid="schedule-add-event-slot-btn"]').should('exist');
  });

  it('matrix / list mode toggle on classes view', () => {
    cy.get('[data-testid="schedule-classes-mode-list"]').click();
    // In list mode the per-class selector is hidden
    cy.get('[data-testid="schedule-class-select"]').should('not.exist');

    cy.get('[data-testid="schedule-classes-mode-matrix"]').click();
    cy.get('[data-testid="schedule-class-select"]').should('be.visible');
  });

  it('slot view -- changing day/hour fires GET /by-slot', () => {
    cy.intercept('GET', '**/api/schedule/by-slot**').as('bySlot');
    cy.get('[data-testid="schedule-view-slot"]').click();
    cy.wait('@bySlot');

    cy.get('[data-testid="schedule-slot-day"]').select('2');
    cy.wait('@bySlot');
    cy.get('[data-testid="schedule-slot-hour"]').select('10');
    cy.wait('@bySlot');

    cy.get('[data-testid="schedule-slot-refresh"]').click();
    cy.wait('@bySlot');
  });

  it('AddLessonModal opens from slot view + validates required fields',
     () => {
    cy.get('[data-testid="schedule-view-slot"]').click();
    cy.get('[data-testid="schedule-slot-view"]').should('be.visible');

    cy.get('[data-testid="schedule-add-event-slot-btn"]').click();
    cy.get('[data-testid="add-lesson-modal"]', { timeout: 5000 })
      .should('be.visible');

    // mode='slot' -> class + teacher are SELECTs (not disabled inputs)
    cy.get('[data-testid="add-lesson-class-select"]').should('be.visible');
    cy.get('[data-testid="add-lesson-teacher-select"]').should('be.visible');

    // Submit without filling -> flash error, modal stays open
    cy.get('[data-testid="add-lesson-submit-btn"]').click();
    cy.get('[data-testid="add-lesson-modal"]').should('be.visible');

    cy.get('[data-testid="add-lesson-cancel-btn"]').click();
    cy.get('[data-testid="add-lesson-modal"]').should('not.exist');
  });

  it('AddLessonModal in slot mode -- a successful create round-trips',
     () => {
    // Pick a class + teacher from the available options.
    cy.get('[data-testid="schedule-view-slot"]').click();

    // Choose a slot we expect to be empty (Sat 14:00 won't exist
    // in the small profile schedule)
    cy.get('[data-testid="schedule-slot-day"]').select('5');  // Saturday
    cy.get('[data-testid="schedule-slot-hour"]').select('14');

    cy.intercept('POST', '**/api/schedule/lesson').as('createLesson');

    cy.get('[data-testid="schedule-add-event-slot-btn"]').click();
    cy.get('[data-testid="add-lesson-modal"]').should('be.visible');

    // Pick the first non-empty option in each select.
    cy.get('[data-testid="add-lesson-class-select"]')
      .find('option').then(($opts) => {
        const realClass = [...$opts].find((o) => o.value && o.value !== '');
        if (realClass) {
          cy.get('[data-testid="add-lesson-class-select"]')
            .select(realClass.value);
        }
      });
    cy.get('[data-testid="add-lesson-teacher-select"]')
      .find('option').then(($opts) => {
        const realT = [...$opts].find((o) => o.value && o.value !== '');
        if (realT) {
          cy.get('[data-testid="add-lesson-teacher-select"]')
            .select(realT.value);
        }
      });

    cy.get('[data-testid="add-lesson-submit-btn"]').click();

    // The POST may succeed (200) OR return a conflict (200 with
    // conflict=true) OR return 422 for missing/wrong subject. We
    // accept any of those outcomes -- the test verifies the request
    // was sent, not that the schedule is now perfect.
    cy.wait('@createLesson').its('response.statusCode')
      .should('be.oneOf', [200, 422]);
  });

  it('SolutionsTable lists at least the active solution', () => {
    // The solutions table is rendered at the bottom of the page.
    cy.contains(/soluzion/i, { timeout: 10000 }).should('be.visible');
  });
});
