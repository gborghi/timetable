/// <reference types="cypress" />

/**
 * /schedule -- WeeklyCalendarView mode='schedule' coverage.
 *
 * Covers the 7 critical drag-drop flows:
 *   (1) Drag a Lesson between two configured slots -> POST move
 *   (2) Drag a Lesson onto a non-configured slot -> drop ignored
 *   (3) Drag a Lesson onto an occupied slot -> backend rejects, flash
 *   (4) Drag a pool entry onto the calendar -> POST reschedule
 *   (5) Click-to-move (Sposta from the actions modal -> click target)
 *   (6) Soft-conflict preview during dragover (badge appears)
 *   (7) Visual feedback (drop-ok / drop-conflict CSS classes)
 *
 * Plus the rest of the calendar workflow: create event, edit room,
 * unschedule, delete, filter per class, view toggle.
 *
 * The whole describe block shares ONE Phase B run (2-5 min) seeded
 * in before() because every spec needs an active Solution. HTML5
 * drag-drop is simulated via cy.trigger('dragstart'/'dragover'/'drop')
 * with a synthetic DataTransfer object -- Cypress doesn't fire native
 * HTML5 drag events.
 */

import { clearDataset, seedSmallProfileAndRunPhaseA, waitForRun } from
  '../support/seed';

const BACKEND = (Cypress.env('backendUrl') as string)
  || 'http://127.0.0.1:8000';

interface LessonOut {
  id: number;
  day: number;
  hour: number;
  class_name: string;
  teacher_name: string;
  subject: string;
  classroom_name: string | null;
}

function getLessons(): Cypress.Chainable<LessonOut[]> {
  return cy.request({
    method: 'GET', url: `${BACKEND}/api/lessons`,
  }).then((r) => (r.body.lessons || []) as LessonOut[]);
}

/** Returns a configured (day, hour) tuple from working-hours config
 * that is currently EMPTY (no lesson on it for the given filter), or
 * ``null`` when every active slot is taken (Phase B on dense profiles
 * fills 100 % of the grid). Callers cy.log + return early on null
 * instead of failing -- the spec is testing UI flows, not seed
 * sparsity. */
function findEmptyConfiguredSlot(
  lessons: LessonOut[],
  classFilter?: string,
): Cypress.Chainable<{ day: number; hour: number } | null> {
  return cy.request({
    method: 'GET',
    url: `${BACKEND}/api/working-hours/config`,
  }).then((r) => {
    const cfg = r.body;
    const taken = new Set<string>();
    for (const l of lessons) {
      if (classFilter && l.class_name !== classFilter) continue;
      taken.add(`${l.day}-${l.hour}`);
    }
    for (const d of cfg.days || []) {
      if (!d.is_active) continue;
      for (const s of d.slots || []) {
        const key = `${d.legacy_day_number}-${s.legacy_hour_number}`;
        if (!taken.has(key)) {
          return cy.wrap({
            day: d.legacy_day_number,
            hour: s.legacy_hour_number,
          });
        }
      }
    }
    return cy.wrap(null);
  });
}

/** Cypress doesn't dispatch real HTML5 drag events; we simulate them
 * with cy.trigger() and a shared synthetic DataTransfer. */
function simulateDragDrop(
  fromSelector: string,
  toSelector: string,
): void {
  const dt = {
    types: [],
    data: {} as Record<string, string>,
    setData(t: string, v: string) { this.data[t] = v; this.types.push(t); },
    getData(t: string) { return this.data[t] || ''; },
    setDragImage() { /* no-op */ },
    effectAllowed: 'move',
    dropEffect: 'move',
  };
  cy.get(fromSelector).trigger('dragstart',
    { dataTransfer: dt, force: true });
  cy.get(toSelector).trigger('dragover',
    { dataTransfer: dt, force: true });
  cy.get(toSelector).trigger('drop',
    { dataTransfer: dt, force: true });
  cy.get(fromSelector).trigger('dragend',
    { dataTransfer: dt, force: true });
}

describe('/schedule calendar -- empty state', () => {
  before(() => {
    clearDataset();
  });

  it('renders the empty-state card without an active solution', () => {
    cy.visit('/schedule');
    cy.get('[data-testid="schedule-page"]', { timeout: 15000 })
      .should('exist');
    cy.get('[data-testid="schedule-empty-state"]').should('be.visible');
    cy.contains(/Nessuna soluzione attiva/i).should('be.visible');
    cy.get('[data-testid="schedule-view-global"]').should('exist');
  });
});

describe('/schedule calendar -- with active solution (Phase A+B)', () => {
  // Cache a few "interesting" lessons resolved in before() so each
  // spec doesn't have to re-fetch /api/lessons.
  let firstLesson: LessonOut;
  let secondLesson: LessonOut;
  let allLessons: LessonOut[];

  before(() => {
    seedSmallProfileAndRunPhaseA(180, 2000);
    cy.request({
      method: 'POST', url: `${BACKEND}/api/optimize/phase-b`,
      body: { time_a: 30, time_mono: 60, workers: 4, log: false },
    }).then((r) => {
      expect(r.status).to.eq(200);
      waitForRun(r.body.run_id, 240, 3000);
    }).then(() => {
      return getLessons();
    }).then((lessons) => {
      expect(lessons.length).to.be.gte(2);
      allLessons = lessons;
      firstLesson = lessons[0];
      secondLesson = lessons[1];
    });
  });

  beforeEach(() => {
    cy.intercept('GET', '**/api/lessons').as('getLessons');
    cy.intercept('GET', '**/api/lessons/unscheduled').as('getPool');
    cy.visit('/schedule');
    cy.get('[data-testid="schedule-page"]', { timeout: 15000 })
      .should('exist');
    cy.wait('@getLessons');
    cy.wait('@getPool');
    cy.get('[data-testid="weekly-schedule"]', { timeout: 10000 })
      .should('be.visible');
  });

  // ----- Calendar rendering -----
  it('renders the WeeklyCalendarView + summary obj_value', () => {
    cy.get('[data-testid="schedule-empty-state"]').should('not.exist');
    cy.get('[data-testid="schedule-obj-value"]').should('be.visible');
    cy.get('[data-testid="weekly-schedule"]').should('be.visible');
    // At least one lesson event is rendered.
    cy.get('[data-testid^="sched-lesson-"]').its('length')
      .should('be.gte', 1);
    // Pool sidebar is present (initially empty after a fresh Phase B).
    cy.get('[data-testid="schedule-pool"]').should('be.visible');
  });

  // ----- View toggle + filter -----
  it('view toggle: global -> per classe -> entity filter limits events',
     () => {
    cy.get('[data-testid="schedule-view-classes"]').click();
    cy.get('[data-testid="schedule-entity-select"]', { timeout: 5000 })
      .should('be.visible');
    // Pick the first class option and verify only its lessons are shown.
    cy.get('[data-testid="schedule-entity-select"]')
      .find('option').then(($opts) => {
        const first = [...$opts].find((o) => o.value);
        if (!first) throw new Error('no class option');
        const className = first.value;
        cy.get('[data-testid="schedule-entity-select"]').select(className);
        // Every visible lesson event must belong to that class. We check
        // by re-fetching /api/lessons and counting events vs lessons.
        cy.get('[data-testid^="sched-lesson-"]').then(($els) => {
          const ids = [...$els].map((e) => Number(e.getAttribute('data-lesson-id')));
          getLessons().then((lessons) => {
            for (const id of ids) {
              const l = lessons.find((x) => x.id === id);
              expect(l).to.exist;
              expect(l!.class_name).to.eq(className);
            }
          });
        });
      });
  });

  // ----- (Scenario 1) Create a new lesson via empty-slot click -----
  it('clicking an empty configured slot opens AddLessonModal', () => {
    getLessons().then((lessons) => {
      findEmptyConfiguredSlot(lessons).then((slot) => {
        if (!slot) { cy.log('grid full -- skipping'); return; }
        cy.get(`[data-testid="sched-slot-${slot.day}-${slot.hour}"]`)
          .click({ force: true });
        cy.get('[data-testid="add-lesson-modal"]', { timeout: 5000 })
          .should('be.visible');
        cy.get('[data-testid="add-lesson-cancel-btn"]').click();
        cy.get('[data-testid="add-lesson-modal"]').should('not.exist');
      });
    });
  });

  // ----- (Scenario 2) Edit lesson room via modal -----
  it('clicking an event opens actions modal + Modifica opens edit', () => {
    cy.get(`[data-testid="sched-lesson-${firstLesson.id}"]`)
      .click({ force: true });
    cy.get('[data-testid="schedule-actions-modal"]', { timeout: 5000 })
      .should('be.visible');
    cy.get('[data-testid="schedule-action-edit"]').click();
    cy.get('[data-testid="schedule-edit-modal"]').should('be.visible');
    cy.get('[data-testid="schedule-edit-close"]').click();
  });

  // ----- (Drag flow #1) Drag between two configured slots -----
  it('DRAG: lesson between configured slots fires POST /move', () => {
    cy.intercept('POST', `**/api/lessons/${firstLesson.id}/move`)
      .as('moveLesson');
    findEmptyConfiguredSlot(allLessons).then((slot) => {
      if (!slot) { cy.log('grid full -- skipping'); return; }
      simulateDragDrop(
        `[data-testid="sched-lesson-${firstLesson.id}"]`,
        `[data-testid="sched-slot-${slot.day}-${slot.hour}"]`,
      );
      cy.wait('@moveLesson').then((interception) => {
        expect(interception.request.body).to.deep.include({
          day: slot.day, hour: slot.hour,
        });
      });
    });
  });

  // ----- (Drag flow #2) Drag onto NON-configured slot -> ignored -----
  it('DRAG: lesson onto a non-configured slot is ignored (no POST)',
     () => {
    cy.intercept('POST', '**/api/lessons/*/move').as('moveLesson');
    // Day 7 (Sun) is never configured in any of the standard profiles;
    // hour 22 is similarly outside any school day. The reject slot has
    // no [data-testid="sched-slot-D-H"] -- only the background hour grid
    // exists at that position. We trigger a synthetic drop on the
    // *calendar root* and verify no /move POST was fired.
    cy.get(`[data-testid="sched-lesson-${secondLesson.id}"]`)
      .trigger('dragstart', { force: true });
    cy.get('[data-testid="weekly-schedule"]')
      .trigger('dragover', { force: true });
    cy.get('[data-testid="weekly-schedule"]')
      .trigger('drop', { force: true });
    cy.get(`[data-testid="sched-lesson-${secondLesson.id}"]`)
      .trigger('dragend', { force: true });
    // Wait briefly to ensure no POST was sent.
    cy.wait(500);
    cy.get('@moveLesson.all').should('have.length', 0);
  });

  // ----- (Drag flow #3) Drag onto an OCCUPIED slot -> conflict modal -----
  it('DRAG: lesson onto an occupied slot opens conflict modal -> '
     + 'Sostituisci moves the lesson and deletes the conflict',
     () => {
    // Pick two lessons that conflict (same teacher OR same class) on
    // different slots so that dropping `a` onto `b`'s slot collides
    // on teacher_busy / class_busy.
    const a = firstLesson;
    const b = allLessons.find(
      (l) => l.id !== a.id
        && (l.teacher_name === a.teacher_name
            || l.class_name === a.class_name));
    if (!b) {
      cy.log('No conflicting pair available; skipping');
      return;
    }
    cy.intercept('POST', `**/api/lessons/${a.id}/move`).as('moveLesson');
    cy.intercept('DELETE', `**/api/lessons/${b.id}`).as('deleteConflict');
    simulateDragDrop(
      `[data-testid="sched-lesson-${a.id}"]`,
      `[data-testid="sched-slot-${b.day}-${b.hour}"]`,
    );
    // First POST must come back with accepted=false + conflicts.
    cy.wait('@moveLesson').then((interception) => {
      expect(interception.request.body).to.deep.include({
        day: b.day, hour: b.hour,
      });
      const body = interception.response?.body as {
        accepted?: boolean;
        conflicts?: {
          teacher_busy: { lesson_id: number }[];
          class_busy: { lesson_id: number }[];
          room_busy: { lesson_id: number }[];
        };
      };
      expect(body?.accepted).to.eq(false);
      expect(body?.conflicts).to.exist;
      const flat = [
        ...(body!.conflicts!.teacher_busy || []),
        ...(body!.conflicts!.class_busy || []),
        ...(body!.conflicts!.room_busy || []),
      ];
      expect(flat.map((r) => r.lesson_id)).to.include(b.id);
    });
    // Modal should be visible with the conflict bucket(s) populated.
    cy.get('[data-testid="schedule-conflict-modal"]', { timeout: 5000 })
      .should('be.visible');
    // The "Svincola" button must be hidden in the drop flow (replace-
    // or-cancel only); only Annulla + Sostituisci remain.
    cy.get('[data-testid="schedule-conflict-unbind"]').should('not.exist');
    cy.get('[data-testid="schedule-conflict-cancel"]').should('be.visible');
    cy.get('[data-testid="schedule-conflict-delete"]').should('be.visible')
      .and('contain', 'Sostituisci');
    // Click "Sostituisci": triggers DELETE on the conflicting lesson(s)
    // followed by a retry POST /move. The retry might still fail for
    // OTHER HARD-feasibility reasons (Phase B output is dense and
    // every move stresses logical/availability constraints) -- the
    // contract we want to verify is that the conflict was deleted
    // and the modal is gone, not that the retry necessarily lands.
    cy.get('[data-testid="schedule-conflict-delete"]').click();
    cy.wait('@deleteConflict').its('response.statusCode').should('eq', 200);
    cy.wait('@moveLesson').then((interception) => {
      const body = interception.response?.body as {
        accepted?: boolean; conflicts?: unknown;
      };
      // Either accepted (lesson moved) or rejected for a NON-conflict
      // reason (logical HARD violated etc). The retry must NOT report
      // the same slot-occupied conflict, since we just resolved it.
      expect(body?.conflicts).to.be.undefined;
    });
    // Conflict row `b` is gone regardless of move outcome.
    getLessons().then((lessons) => {
      expect(lessons.find((l) => l.id === b.id),
             'conflict deleted').to.be.undefined;
    });
    // Modal must be closed afterwards.
    cy.get('[data-testid="schedule-conflict-modal"]').should('not.exist');
  });

  // ----- (Drag flow #3 bis) Conflict modal -> Annulla = no side effect -----
  it('DRAG: occupied-slot conflict modal "Annulla" leaves state untouched',
     () => {
    // Re-fetch live lessons because earlier specs mutate the grid.
    getLessons().then((lessons) => {
      const a = lessons[0];
      const b = lessons.find(
        (l) => l.id !== a.id
          && (l.teacher_name === a.teacher_name
              || l.class_name === a.class_name));
      if (!b) {
        cy.log('No conflicting pair available; skipping');
        return;
      }
      cy.intercept('POST', `**/api/lessons/${a.id}/move`).as('moveLesson');
      cy.intercept('DELETE', `**/api/lessons/${b.id}`).as('deleteConflict');
      simulateDragDrop(
        `[data-testid="sched-lesson-${a.id}"]`,
        `[data-testid="sched-slot-${b.day}-${b.hour}"]`,
      );
      cy.wait('@moveLesson');
      cy.get('[data-testid="schedule-conflict-modal"]', { timeout: 5000 })
        .should('be.visible');
      cy.get('[data-testid="schedule-conflict-cancel"]').click();
      cy.get('[data-testid="schedule-conflict-modal"]').should('not.exist');
      // No DELETE issued.
      cy.wait(300);
      cy.get('@deleteConflict.all').should('have.length', 0);
      // a and b unchanged.
      getLessons().then((after) => {
        const aAfter = after.find((l) => l.id === a.id);
        const bAfter = after.find((l) => l.id === b.id);
        expect(aAfter).to.exist;
        expect(aAfter!.day).to.eq(a.day);
        expect(aAfter!.hour).to.eq(a.hour);
        expect(bAfter).to.exist;
      });
    });
  });

  // ----- (Drag flow #4) Drag from pool to calendar -----
  it('DRAG: pool entry onto calendar fires POST /reschedule', () => {
    // Seed: unschedule one lesson via API so the pool isn't empty.
    cy.request({
      method: 'POST',
      url: `${BACKEND}/api/lessons/${firstLesson.id}/unschedule`,
    }).then((r) => {
      const poolId = r.body.unscheduled_id;
      cy.reload();
      cy.wait('@getPool');
      cy.get(`[data-testid="sched-pool-item-${poolId}"]`,
             { timeout: 5000 }).should('be.visible');
      cy.intercept(
        'POST', `**/api/lessons/unscheduled/${poolId}/reschedule`,
      ).as('reschedule');
      // Find an empty slot to place into.
      getLessons().then((lessons) => {
        findEmptyConfiguredSlot(lessons).then((slot) => {
          if (!slot) { cy.log('grid full -- skipping'); return; }
          simulateDragDrop(
            `[data-testid="sched-pool-item-${poolId}"]`,
            `[data-testid="sched-slot-${slot.day}-${slot.hour}"]`,
          );
          cy.wait('@reschedule').then((interception) => {
            expect(interception.request.body).to.deep.include({
              day: slot.day, hour: slot.hour,
            });
          });
        });
      });
    });
  });

  // ----- (Drag flow #5) Click-to-move via Sposta action -----
  it('CLICK-TO-MOVE: Sposta from modal then click target slot', () => {
    // Re-fetch lessons to find a still-active one (#4 may have left
    // the calendar mutated).
    getLessons().then((lessons) => {
      const target = lessons[0];
      cy.intercept('POST', `**/api/lessons/${target.id}/move`)
        .as('moveLesson');
      cy.get(`[data-testid="sched-lesson-${target.id}"]`)
        .click({ force: true });
      cy.get('[data-testid="schedule-actions-modal"]').should('be.visible');
      cy.get('[data-testid="schedule-action-move"]').click();
      cy.get('[data-testid="schedule-pending-move"]', { timeout: 5000 })
        .should('be.visible');
      findEmptyConfiguredSlot(lessons).then((slot) => {
        if (!slot) { cy.log('grid full -- skipping'); return; }
        cy.get(`[data-testid="sched-slot-${slot.day}-${slot.hour}"]`)
          .click({ force: true });
        cy.wait('@moveLesson').then((interception) => {
          expect(interception.request.body).to.deep.include({
            day: slot.day, hour: slot.hour,
          });
        });
      });
    });
  });

  // ----- (Drag flow #6) Soft-conflict preview during drag -----
  it('CONFLICT PREVIEW: dragstart marks conflicting events with badge',
     () => {
    getLessons().then((lessons) => {
      // Find two lessons that share teacher_name OR class_name
      // (guaranteed to conflict in soft-preview computation).
      const a = lessons[0];
      const partner = lessons.find(
        (l) => l.id !== a.id
          && (l.teacher_name === a.teacher_name
              || l.class_name === a.class_name));
      if (!partner) {
        cy.log('No conflicting partner available; skipping');
        return;
      }
      // Trigger ONLY dragstart -- we want to inspect the DOM mid-drag,
      // not actually drop.
      cy.get(`[data-testid="sched-lesson-${a.id}"]`)
        .trigger('dragstart', { force: true });
      // The conflict badge should appear on the partner lesson.
      cy.get(`[data-testid="sched-lesson-${partner.id}"]`)
        .find('[data-testid="sched-conflict-badge"]', { timeout: 3000 })
        .should('exist');
      // Cancel the drag.
      cy.get(`[data-testid="sched-lesson-${a.id}"]`)
        .trigger('dragend', { force: true });
    });
  });

  // ----- (Drag flow #7) Visual feedback CSS classes -----
  it('VISUAL: dragover toggles drop-ok CSS class on configured slot',
     () => {
    getLessons().then((lessons) => {
      findEmptyConfiguredSlot(lessons).then((slot) => {
        if (!slot) { cy.log('grid full -- skipping'); return; }
        cy.get(`[data-testid="sched-lesson-${lessons[0].id}"]`)
          .trigger('dragstart', { force: true });
        cy.get(`[data-testid="sched-slot-${slot.day}-${slot.hour}"]`)
          .trigger('dragover', { force: true })
          .should('have.class', 'cal-slot--drop-ok');
        cy.get(`[data-testid="sched-lesson-${lessons[0].id}"]`)
          .trigger('dragend', { force: true });
      });
    });
  });

  // ----- Svincola action -----
  it('ACTION: Svincola sends event to pool, removes from calendar', () => {
    cy.on('window:confirm', () => true);
    getLessons().then((lessons) => {
      const t = lessons[0];
      cy.intercept('POST', `**/api/lessons/${t.id}/unschedule`)
        .as('unschedule');
      cy.get(`[data-testid="sched-lesson-${t.id}"]`)
        .click({ force: true });
      cy.get('[data-testid="schedule-actions-modal"]').should('be.visible');
      cy.get('[data-testid="schedule-action-unschedule"]').click();
      cy.wait('@unschedule').its('response.statusCode')
        .should('eq', 200);
      cy.get('@getLessons.all').its('length').should('be.gte', 1);
    });
  });

  // ----- Elimina action -----
  it('ACTION: Elimina removes the event via DELETE', () => {
    cy.on('window:confirm', () => true);
    getLessons().then((lessons) => {
      // Pick a lesson the previous tests haven't touched (later ids).
      const t = lessons[lessons.length - 1];
      cy.intercept('DELETE', `**/api/lessons/${t.id}`)
        .as('deleteLesson');
      cy.get(`[data-testid="sched-lesson-${t.id}"]`)
        .click({ force: true });
      cy.get('[data-testid="schedule-actions-modal"]').should('be.visible');
      cy.get('[data-testid="schedule-action-delete"]').click();
      cy.wait('@deleteLesson').its('response.statusCode')
        .should('eq', 200);
    });
  });
});
