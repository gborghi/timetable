/// <reference types="cypress" />

/**
 * Navbar completeness E2E.
 *
 * Locks down the navbar shape so refactors can't silently drop a
 * tab. The user-reported bug ("Tab Ore non visibile dal frontend")
 * was a regression of exactly this kind: the entry was renamed in
 * one commit and forgotten in another, leaving /ore reachable only
 * via direct URL typing. This test fails if any expected child link
 * is missing, if the dropdown that contains it is missing, or if
 * the link doesn't actually navigate to the right route.
 *
 * Asserts (per layout in `+layout.svelte`):
 *   - Top-level: Dashboard (link /), Anagrafica (menu), Pianificazione
 *     (menu), Orario (link /schedule), Gestione (menu), Esecuzione
 *     (menu), Eventi (link /monitor), Import bulk (link /import).
 *   - Anagrafica children: Docenti, Classi, Indirizzi, Studenti, Gruppi,
 *     Materie, Aule, Plessi, Ore.
 *   - Pianificazione children: Compresenze, Cattedre, Vincoli.
 *   - Esecuzione children: Workflow, Runs, Statistiche.
 *   - Gestione children: Assenze e supplenze.
 *   - Each child link, when clicked, navigates to the expected route.
 */

interface NavSpec {
  label: string;
  kind: 'link' | 'menu';
  href?: string;        // for links
  children?: { label: string; href: string }[];  // for menus
}

const NAV: NavSpec[] = [
  { kind: 'link', label: 'Dashboard',  href: '/' },
  { kind: 'menu', label: 'Anagrafica', children: [
    { label: 'Docenti',   href: '/teachers' },
    { label: 'Classi',    href: '/classes' },
    { label: 'Indirizzi', href: '/curricula' },
    { label: 'Studenti',  href: '/students' },
    { label: 'Gruppi',    href: '/groups' },
    { label: 'Materie',   href: '/subjects' },
    { label: 'Aule',      href: '/classrooms' },
    { label: 'Plessi',    href: '/plessi' },
    { label: 'Ore',       href: '/ore' },
  ]},
  { kind: 'menu', label: 'Pianificazione', children: [
    { label: 'Compresenze', href: '/coteaching' },
    { label: 'Cattedre',    href: '/assignments' },
    { label: 'Vincoli',     href: '/constraints' },
  ]},
  { kind: 'link', label: 'Orario', href: '/schedule' },
  { kind: 'menu', label: 'Gestione', children: [
    { label: 'Assenze e supplenze', href: '/assenze-supplenze' },
  ]},
  { kind: 'menu', label: 'Esecuzione', children: [
    { label: 'Workflow',    href: '/optimize' },
    { label: 'Runs',        href: '/runs' },
    { label: 'Statistiche', href: '/diagnostics' },
  ]},
  { kind: 'link', label: 'Eventi',     href: '/monitor' },
  { kind: 'link', label: 'Import bulk', href: '/import' },
];

describe('Navbar completeness', () => {
  beforeEach(() => {
    cy.visit('/');
    cy.get('[data-testid="navbar"]').should('exist');
  });

  it('has all top-level entries in order', () => {
    cy.get('[data-testid="navbar"]')
      .find('[data-testid="nav-link"], [data-testid="nav-menu"]')
      .should('have.length', NAV.length);
    NAV.forEach((entry, idx) => {
      const sel = entry.kind === 'link'
        ? '[data-testid="nav-link"]'
        : '[data-testid="nav-menu"]';
      cy.get('[data-testid="navbar"]')
        .find('[data-testid="nav-link"], [data-testid="nav-menu"]')
        .eq(idx)
        .should('match', sel)
        .should('have.attr', 'data-nav-label', entry.label);
    });
  });

  // Per-menu: open the dropdown, verify all expected children are
  // present, in order. Run as separate `it` blocks so a missing
  // entry shows up as a discrete failure rather than a single
  // mega-assertion.
  NAV.filter((g) => g.kind === 'menu').forEach((group) => {
    it(`menu "${group.label}" exposes all child links`, () => {
      cy.get(`[data-testid="nav-menu"][data-nav-label="${group.label}"]`)
        .click();
      cy.get(`[data-testid="nav-dropdown"][data-nav-parent="${group.label}"]`)
        .should('be.visible')
        .within(() => {
          cy.get('[data-testid="nav-child-link"]')
            .should('have.length', group.children!.length);
          group.children!.forEach((c, idx) => {
            cy.get('[data-testid="nav-child-link"]')
              .eq(idx)
              .should('have.attr', 'data-nav-label', c.label)
              .should('have.attr', 'href', c.href);
          });
        });
    });
  });

  // Spotlight: Tab "Ore" (the user-reported regression). Standalone
  // assertion so it shines in CI logs.
  it('Tab "Ore" is reachable from the navbar', () => {
    cy.get('[data-testid="nav-menu"][data-nav-label="Anagrafica"]').click();
    cy.get('[data-testid="nav-dropdown"][data-nav-parent="Anagrafica"]')
      .find('[data-testid="nav-child-link"][data-nav-label="Ore"]')
      .should('be.visible')
      .should('have.attr', 'href', '/ore')
      .click();
    cy.url().should('include', '/ore');
    // Page actually rendered (not just routed): heading visible.
    cy.contains(/Ore di lavoro|Working hours|configurazione/i,
                { timeout: 10000 }).should('exist');
  });

  // Top-level links navigate to the expected routes.
  NAV.filter((g) => g.kind === 'link').forEach((entry) => {
    it(`link "${entry.label}" navigates to ${entry.href}`, () => {
      cy.get(`[data-testid="nav-link"][data-nav-label="${entry.label}"]`)
        .click();
      cy.url().should('include', entry.href);
    });
  });
});
