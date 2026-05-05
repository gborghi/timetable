/// <reference types="cypress" />

/**
 * Reusable seed helpers for Cypress E2E tests.
 *
 * The "mini scenario" used by FU-C / FU-D / FU-E:
 *   - 2 classes (3A, 4A)
 *   - 4 teachers (1 mat, 1 ita, 1 storia, 1 sci)
 *   - 4 manual cattedre (one per (teacher, class, subject))
 *   - 2 classrooms (Aula1 cap=24, Aula2 cap=35)
 *
 * No Solution / Lesson rows are created here -- those require a
 * solver run. Tests that need them call `seedAndRunPhaseB()` which
 * triggers /api/optimize/phase-b and polls the run row.
 *
 * Idempotent: every helper begins with a POST /api/dataset/clear
 * so the test starts from a fresh DB regardless of prior state.
 */

const BACKEND = (Cypress.env('backendUrl') as string)
  || 'http://127.0.0.1:8000';

export interface MiniScenario {
  classes: { id: number; name: string }[];
  teachers: { id: number; name: string }[];
  classrooms: { id: number; name: string }[];
}

/**
 * Wipe the live DB. Best-effort: if /api/dataset/clear isn't
 * available the function logs and continues (the tests will
 * surface the inconsistency more clearly).
 */
export function clearDataset(): Cypress.Chainable {
  return cy.request({
    method: 'POST',
    url: `${BACKEND}/api/dataset/clear`,
    failOnStatusCode: false,
    body: {},
  });
}

/**
 * Build the mini scenario via POST endpoints. Returns a chainable
 * yielding the resolved IDs.
 */
export function seedMiniScenario(): Cypress.Chainable<MiniScenario> {
  const out: MiniScenario = {
    classes: [], teachers: [], classrooms: [],
  };
  return clearDataset().then(() => {
    // Classrooms
    return cy.request('POST', `${BACKEND}/api/classrooms`, {
      name: 'Aula1', kind: 'standard', capacity: 24,
      multi_class: false, multi_class_max: 1, multi_class_pref: 1,
      subject_prefs: [], class_prefs: [], unavailability: [],
      tags: [],
    });
  }).then((r) => {
    out.classrooms.push({ id: r.body.id, name: r.body.name });
    return cy.request('POST', `${BACKEND}/api/classrooms`, {
      name: 'Aula2', kind: 'standard', capacity: 35,
      multi_class: false, multi_class_max: 1, multi_class_pref: 1,
      subject_prefs: [], class_prefs: [], unavailability: [],
      tags: [],
    });
  }).then((r) => {
    out.classrooms.push({ id: r.body.id, name: r.body.name });
    // Classes
    return cy.request('POST', `${BACKEND}/api/classes`, {
      name: '3A', year: 3, section: 'A',
      curriculum: 'Scientifico', n_students: 22,
      subjects: {}, unavailability: [],
    });
  }).then((r) => {
    out.classes.push({ id: r.body.id, name: r.body.name });
    return cy.request('POST', `${BACKEND}/api/classes`, {
      name: '4A', year: 4, section: 'A',
      curriculum: 'Scientifico', n_students: 28,
      subjects: {}, unavailability: [],
    });
  }).then((r) => {
    out.classes.push({ id: r.body.id, name: r.body.name });
    // Teachers (4 with different subject groups)
    const teacherSpecs = [
      ['Prof Mat', 'A027', 'Matematica'],
      ['Prof Ita', 'A012', 'Italiano'],
      ['Prof Sto', 'A019', 'Storia'],
      ['Prof Sci', 'A050', 'Scienzenaturali'],
    ];
    return cy.wrap(teacherSpecs).each(([name, group, _subj]) => {
      cy.request('POST', `${BACKEND}/api/teachers`, {
        name, group, max_hours: 18, free_day: null,
        glibero_pref: [], unavailability: [],
        compatible_classes: [], compatible_curricula: [],
      }).then((r) => {
        out.teachers.push({ id: r.body.id, name: r.body.name });
      });
    });
  }).then(() => out);
}

/**
 * Seed via /api/dataset/import-profile + Phase A. Heavier than
 * seedMiniScenario(): yields a real school with curricula +
 * classrooms + students + a complete `Assignment` row set, ready
 * for a Phase B run.
 *
 * Used by FU-D (launch-solver) and FU-E (conflict-pill) which
 * need a populated DB the solver can actually consume.
 */
export function seedSmallProfileAndRunPhaseA(
    timeoutSeconds = 90,
    pollMs = 2000): Cypress.Chainable {
  return clearDataset().then(() => {
    return cy.request({
      method: 'POST',
      url: `${BACKEND}/api/dataset/import-profile`,
      body: {
        profile: 'small',
        seed_curricula: true,
        seed_classrooms: true,
        seed_students: true,
        margin: 0.25,
      },
      timeout: 60000,
    });
  }).then(() => {
    // Phase A (assignment criterion=balance_weight)
    return cy.request({
      method: 'POST',
      url: `${BACKEND}/api/optimize/assignment`,
      body: {
        time_limit_s: 30, workers: 4, log: false,
        criterion: 'balance_weight',
      },
    });
  }).then((r) => {
    const runId = r.body.run_id;
    expect(runId).to.be.a('number');
    return waitForRun(runId, timeoutSeconds, pollMs);
  });
}


/**
 * Poll /api/optimize/runs/<id> until status in ('done', 'failed',
 * 'cancelled'). Returns the final run dict. Throws on timeout.
 */
export function waitForRun(runId: number,
    timeoutSeconds: number,
    pollMs: number = 2000): Cypress.Chainable<any> {
  const deadline = Date.now() + timeoutSeconds * 1000;
  function poll(): any {
    return cy.request({
      method: 'GET',
      url: `${BACKEND}/api/optimize/runs/${runId}`,
      failOnStatusCode: false,
    }).then((r: any) => {
      const run = r.body;
      const status = run.status as string;
      if (['done', 'completed', 'success'].includes(status)) {
        return cy.wrap(run);
      }
      if (['failed', 'error', 'cancelled', 'canceled']
          .includes(status)) {
        throw new Error(
          `run ${runId} ended with status=${status}: `
          + `${JSON.stringify(run.error || run.metrics_json
                              || run)}`);
      }
      if (Date.now() > deadline) {
        throw new Error(
          `run ${runId} did not finish within ${timeoutSeconds}s `
          + `(last status=${status})`);
      }
      return cy.wait(pollMs).then(() => poll());
    });
  }
  return poll();
}


/**
 * Manually attach 4 cattedre (one teacher per class+subject) using
 * the /api/assignments/manual endpoint.
 *
 * Pre-condition: `seedMiniScenario()` has been called.
 */
export function seedAssignments(scenario: MiniScenario):
    Cypress.Chainable {
  const subjects = ['Matematica', 'Italiano', 'Storia',
    'Scienzenaturali'];
  const pairs = scenario.classes.flatMap((cl, ci) =>
    subjects.map((subj, si) => ({
      class_name: cl.name,
      subject: subj,
      teacher_name: scenario.teachers[si].name,
      locked: false,
      hours: 4,
    })),
  );
  return cy.wrap(pairs).each((p) => {
    cy.request({
      method: 'PUT',
      url: `${BACKEND}/api/assignments/manual`,
      body: p,
      failOnStatusCode: false,
    });
  });
}
