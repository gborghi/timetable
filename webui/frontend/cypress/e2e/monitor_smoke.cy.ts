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
    // The monitor page renders some chrome regardless of data state:
    // segmented tab filter (Tutti / Incompleti / Lockati), table
    // headers, etc. Just check the page mounted without throwing.
    cy.get('.error-banner, [data-error]').should('not.exist');
  });
});
