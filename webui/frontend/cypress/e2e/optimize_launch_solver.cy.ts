/// <reference types="cypress" />

/**
 * /optimize -- launch Phase B from the UI.
 *
 * Setup: imports the `small` profile + runs Phase A so the DB
 * has a complete Assignment set. Then opens /optimize and clicks
 * the "Avvia Phase B" button.
 *
 * Verification:
 *   1. Click triggers a POST to /api/optimize/phase-b -> returns
 *      a run_id. We catch the network call via cy.intercept and
 *      use the returned id to poll the run row.
 *   2. Wait until the run is `done` (timeout: 5 minutes -- the
 *      `small` profile's Phase B is typically <60s).
 *   3. Verify Lessons exist via GET /api/schedule/active or the
 *      monitor's event-rows endpoint.
 *
 * The test is SLOW (~2 min total) and tagged accordingly. CI runs
 * with --browser chromium --headless.
 */

import { seedSmallProfileAndRunPhaseA, waitForRun } from
  '../support/seed';

const BACKEND = (Cypress.env('backendUrl') as string)
  || 'http://127.0.0.1:8000';

before(() => {
  // Seeds + runs Phase A; ~30-60s the first time on a fresh DB.
  seedSmallProfileAndRunPhaseA(120, 2000);
});

describe('/optimize launches Phase B from the UI', () => {
  it('clicks "Avvia Phase B" + run completes + lessons appear',
     {
       defaultCommandTimeout: 300_000,   // 5 min for the run
     },
     () => {
       cy.visit('/optimize');
       // Watch POST /api/optimize/phase-b so we can grab the run_id.
       cy.intercept('POST', '**/api/optimize/phase-b').as('launchB');
       // Click the "Avvia Phase B" button (the page in step 3 has
       // exactly one button with that label).
       cy.contains('button', /Avvia Phase B/i).click();
       cy.wait('@launchB').then((interception) => {
         expect(interception.response?.statusCode).to.eq(200);
         const runId = (interception.response?.body as any).run_id;
         expect(runId).to.be.a('number');
         // Poll until done (small profile's Phase B ~60s).
         waitForRun(runId, 240, 3000);
       });
       // After the run is done, GET schedule lessons -- must be
       // non-empty (small profile has ~10 classes x ~30h = 300
       // lesson slots).
       cy.request(`${BACKEND}/api/schedule/active`).then((r) => {
         expect(r.status).to.eq(200);
         const body = r.body;
         const lessons = body.lessons ?? body.events ?? body;
         const arr = Array.isArray(lessons) ? lessons : [];
         expect(arr.length, 'expected at least 100 lessons after '
                + 'Phase B on small profile').to.be.greaterThan(100);
       });
     });
});
