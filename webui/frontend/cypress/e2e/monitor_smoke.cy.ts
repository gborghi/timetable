/// <reference types="cypress" />

/**
 * /monitor -- smoke that the page loads and either shows lessons
 * (when a Solution is active) or an "import a profile" empty state.
 * Doesn't assume specific data; the test runs against whatever the
 * dev DB happens to have.
 */

describe('/monitor smoke', () => {
  it('renders without errors', () => {
    cy.visit('/monitor');
    cy.get('body').should('not.be.empty');
    // The monitor page exposes a few standard elements: a filter
    // input (top), and either a table/grid or an empty-state
    // message. We assert at least one of them is present.
    cy.get('body').then(($body) => {
      const hasEvents = $body.text().match(/lezion|orario|monitor/i);
      const hasEmpty = $body.text().match(/nessun|importa|profilo/i);
      expect(
        hasEvents || hasEmpty,
        'monitor should show events OR an empty/import state',
      ).to.exist;
    });
  });
});
