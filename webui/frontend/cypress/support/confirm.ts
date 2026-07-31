/// <reference types="cypress" />

/**
 * Helper per il dialog di conferma dell'app.
 *
 * Le conferme NON passano piu' da window.confirm: `$lib/confirm`
 * pubblica la richiesta su uno store e ConfirmDialog.svelte la rende
 * come Modal, con i bottoni `confirm-ok` / `confirm-cancel`. Gli
 * `cy.on('window:confirm', ...)` degli spec piu' vecchi quindi non
 * intercettano nulla: la modale resta aperta e la chiamata di rete non
 * parte mai.
 *
 * `supportFile` e' disabilitato, quindi questi sono moduli ES normali
 * da importare negli spec, non comandi custom `cy.*`.
 */

/** Conferma il dialog aperto (attende che compaia). */
export function acceptConfirm(): Cypress.Chainable {
  return cy.get('[data-testid="confirm-ok"]', { timeout: 10000 })
    .should('be.visible')
    .click();
}

/** Annulla il dialog aperto. */
export function dismissConfirm(): Cypress.Chainable {
  return cy.get('[data-testid="confirm-cancel"]', { timeout: 10000 })
    .should('be.visible')
    .click();
}

/**
 * Conferma il dialog se c'e', altrimenti tira avanti. Serve dove
 * l'azione chiede conferma solo in certi stati.
 */
export function acceptConfirmIfAny(): Cypress.Chainable {
  return cy.get('body').then(($body) => {
    if ($body.find('[data-testid="confirm-ok"]').length > 0) {
      return acceptConfirm();
    }
    return cy.wrap(null);
  });
}

/** Compila e conferma un promptDialog(). */
export function acceptPrompt(value: string): Cypress.Chainable {
  cy.get('[data-testid="confirm-input"]', { timeout: 10000 })
    .should('be.visible')
    .clear()
    .type(value);
  return acceptConfirm();
}
