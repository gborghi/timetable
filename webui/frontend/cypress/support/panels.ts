/// <reference types="cypress" />

/**
 * Helper per i <Panel> del redesign (src/lib/components/Panel.svelte).
 *
 * Il pannello e' un accordion: quando e' chiuso il contenuto **non e'
 * nel DOM** (`{#if open}`), a differenza di un <details> che si limita
 * a nasconderlo. Quindi ogni spec che tocca qualcosa dentro un
 * pannello deve prima aprirlo:
 *
 *   import { expandPanel } from '../support/panels';
 *   expandPanel('optimize-advanced');
 *   cy.get('[data-testid="phase-b-scope"]').select('week');
 *
 * `cypress.config.ts` ha `supportFile: false`: niente comandi
 * `cy.*` custom, questi sono normali moduli ES importati dagli spec
 * (stesso schema di `cypress/support/seed.ts`).
 *
 * Lo stato aperto/chiuso vive in localStorage (`pt_panel_<id>`), che
 * Cypress azzera fra un test e l'altro: per questo l'apertura va
 * rifatta in ogni `it()` (o nel `beforeEach`) e non una volta sola.
 */

/**
 * Apre il pannello con quell'`id` se e' chiuso, e lascia il DOM
 * pronto per le asserzioni sul contenuto. Idempotente: se e' gia'
 * aperto non fa nulla, cosi' si puo' chiamare senza sapere il default
 * (es. `carica-scuola` nasce aperto).
 */
export function expandPanel(id: string): Cypress.Chainable {
  return cy.get(`[data-panel-id="${id}"]`, { timeout: 15000 })
    .find('button[aria-expanded]')
    .first()
    .then(($btn) => {
      if ($btn.attr('aria-expanded') !== 'true') cy.wrap($btn).click();
    })
    .then(() => cy.get(`[data-panel-id="${id}"] button[aria-expanded="true"]`)
                   .should('exist'));
}

/** Chiude il pannello (idempotente). Serve ai test sul persist. */
export function collapsePanel(id: string): Cypress.Chainable {
  return cy.get(`[data-panel-id="${id}"]`, { timeout: 15000 })
    .find('button[aria-expanded]')
    .first()
    .then(($btn) => {
      if ($btn.attr('aria-expanded') === 'true') cy.wrap($btn).click();
    })
    .then(() => cy.get(`[data-panel-id="${id}"] button[aria-expanded="false"]`)
                   .should('exist'));
}
