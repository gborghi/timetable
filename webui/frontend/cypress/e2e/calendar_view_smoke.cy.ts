/// <reference types="cypress" />

/**
 * WeeklyCalendarView smoke E2E.
 *
 * Two paths:
 *
 *   1. Tab Ore (/ore) -- the calendar is in EDIT mode and must
 *      render at least one day column with the configured slots
 *      drawn as `cal-event` rectangles.
 *
 *   2. Tab Docenti (/teachers) -- opening the edit modal of any
 *      teacher must show the WeeklyCalendarView in VIEW mode with
 *      the same legend (libero, SOFT, HARD, PREFERRED, ENFORCED)
 *      and at least one event rectangle.
 *
 * The component implementation lives in
 * `webui/frontend/src/lib/components/WeeklyCalendarView.svelte`
 * (commits 3236b10 and 811fe3d). If it stops mounting -- e.g. a
 * regression in the working-hours config fetch on mount -- this
 * test catches it.
 */

import {
  seedMiniScenario,
  clearDataset,
} from '../support/seed';

const BACKEND = (Cypress.env('backendUrl') as string)
  || 'http://127.0.0.1:8000';

before(() => {
  // Reset working-hours config to the engine default so the calendar
  // has something deterministic to render. Best-effort.
  cy.request({
    method: 'POST',
    url: `${BACKEND}/api/working-hours/reset`,
    failOnStatusCode: false,
    body: {},
  });
});

describe('WeeklyCalendarView in Tab Ore (edit mode)', () => {
  it('renders the weekly grid with the default 6-slot config', () => {
    cy.intercept('GET', '**/api/working-hours/config').as('whConfig');
    cy.visit('/ore');
    cy.wait('@whConfig').its('response.statusCode').should('eq', 200);

    // Page heading.
    cy.contains('Ore di lavoro').should('be.visible');

    // Calendar grid present.
    cy.get('.weekly-calendar', { timeout: 10000 }).should('be.visible');

    // Day columns: at least 1 (default config has lun-sab = 6).
    cy.get('.cal-day-col').should('have.length.gte', 1);

    // Slots rendered as event rectangles. The default ships with
    // 6 slots/day; even after a reset there must be >= 1 event.
    cy.get('.cal-event', { timeout: 10000 })
      .should('have.length.gte', 1);
  });

  it('Lista (legacy) view toggle still works', () => {
    cy.visit('/ore');
    cy.contains(/Lista|legacy|tabella/i).then(($el) => {
      // Optional: the toggle isn't critical, just verify the page
      // doesn't crash if we click it when it exists.
      if ($el.length) {
        cy.wrap($el).click({ force: true });
      }
    });
  });
});

describe('WeeklyCalendarView in Tab Docenti edit modal (view mode)', () => {
  before(() => {
    seedMiniScenario();
  });

  it('opening "Modifica" on a teacher row mounts the calendar', () => {
    cy.visit('/teachers');
    cy.contains('button', /Modifica/i, { timeout: 15000 })
      .first()
      .click();

    // Modal title -- the seed teacher names use generic strings, so
    // we don't assert on them. Instead assert the calendar is
    // present with its legend.
    //
    // scrollIntoView() is mandatory, not cosmetic: the calendar sits
    // ~680px down a 2100px-tall modal body, and the modal wrapper is
    // `position: fixed`. In the default 1000x660 viewport Cypress
    // therefore considers it "overflowed by other elements" and
    // `be.visible` can never pass without scrolling first.
    cy.get('.weekly-calendar', { timeout: 10000 })
      .scrollIntoView()
      .should('be.visible');
    cy.contains(/Disponibilita oraria/i).should('be.visible');

    // Legend: 5 labels. Asserted on the calendar's text content and
    // not with cy.contains(/^libero$/i): every label is a bare text
    // node sitting next to its colour swatch, so the enclosing
    // <span>'s own text is "\n  libero\n  " and an anchored regex can
    // never match it.
    cy.get('.weekly-calendar')
      .should('contain.text', 'libero')
      .and('contain.text', 'SOFT')
      .and('contain.text', 'HARD')
      .and('contain.text', 'PREFERRED')
      .and('contain.text', 'ENFORCED');

    // Event rectangles rendered (slots from working-hours config).
    cy.get('.cal-event').should('have.length.gte', 1);
  });
});

describe('WeeklyCalendarView is wired to the working-hours config', () => {
  // Seeds its own data: this block needs a teacher row to click, and
  // the seed is not inherited from the describe above (each block
  // starts from clearDataset()).
  before(() => {
    seedMiniScenario();
  });

  after(() => {
    clearDataset();
  });

  // If /api/working-hours/config returns 0 active days, the calendar
  // shows the "Nessun giorno lavorativo configurato" empty state with
  // a link back to /ore. This is the failure mode the user hit when
  // the engine migrated DAYS/HOURS away from hardcoded constants.
  it('empty config -> empty-state message with /ore link', () => {
    cy.intercept('GET', '**/api/working-hours/config', {
      statusCode: 200,
      body: {
        days: [],
        // The component forwards every key it doesn't read, so the
        // rest of the WorkingHoursConfigOut shape can be empty.
      },
    }).as('emptyConfig');

    cy.visit('/teachers');
    cy.contains('button', /Modifica/i, { timeout: 15000 })
      .first()
      .click();

    // Same modal-scroll caveat as the test above.
    cy.contains(/Nessun giorno lavorativo|Vai al tab/i,
                { timeout: 10000 })
      .scrollIntoView()
      .should('be.visible');
    cy.contains('a', /^Ore$/).should('have.attr', 'href', '/ore');
  });
});
