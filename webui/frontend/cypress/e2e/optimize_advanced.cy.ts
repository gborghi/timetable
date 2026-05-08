/// <reference types="cypress" />

/**
 * /optimize -- AdvancedTechniquesCard.
 *
 * The card groups Hall pre-check, ALNS, VNS, Lagrangian, and
 * Column Generation. ALNS / VNS / Lagrangian / CG kick off async
 * runs (POST → run_id), while Hall is sync diagnostic.
 *
 * This spec covers, with stubbed POSTs so no solver actually runs:
 *   - card mounts + dropdowns have the canonical option sets
 *     (cgMode 3 options, cgGranularity 9 + auto, branching 2)
 *   - each launch button POSTs the right path with the parameters
 *     the user typed
 *   - Hall sync POST surfaces the report banner
 *
 * The existing optimize_dropdowns.cy.ts and optimize_phase_b_dropdowns.cy.ts
 * cover Step 1 / Step 3 dropdowns; this spec is dedicated to the
 * advanced techniques card which has its own state.
 */

describe('Tab Optimize advanced techniques', () => {
  beforeEach(() => {
    // Empty runs/state stubs so the page mounts without backend.
    cy.intercept('GET', '**/api/optimize/runs*', { body: [] });
    cy.intercept('GET', '**/api/dataset/state', {
      body: { last_profile: '', solutions: 0, assignments: 0 },
    });
    cy.intercept('GET', '**/api/dataset/available-profiles',
                 { body: [] });
    cy.intercept('GET', '**/api/optimize/decomposition/recommend',
                 { statusCode: 409, body: {} });

    cy.visit('/optimize');
    cy.get('[data-testid="advanced-techniques-card"]', { timeout: 15000 })
      .should('exist').scrollIntoView();
  });

  describe('dropdowns', () => {
    it('cgMode dropdown lists the 3 modes with iterative-diversified '
       + 'as default', () => {
      cy.get('[data-testid="adv-cg-mode"]')
        .should('have.value', 'iterative-diversified')
        .find('option')
        .then(($opts) => {
          const values = [...$opts].map((o) => (o as HTMLOptionElement).value);
          expect(values).to.include.members([
            'iterative-diversified',
            'branch-and-price',
            'auto',
          ]);
        });
    });

    it('cgGranularity dropdown lists all 10 (auto + 9 strategies)', () => {
      cy.get('[data-testid="adv-cg-granularity"]')
        .should('have.value', 'auto')
        .find('option')
        .then(($opts) => {
          const values = [...$opts].map((o) => (o as HTMLOptionElement).value);
          expect(values).to.include.members([
            'auto',
            'teacher',
            'teacher-day',
            'teacher-class',
            'teacher-class-subject',
            'teacher-subject',
            'class',
            'class-day',
            'day',
            'curriculum',
          ]);
        });
    });

    it('cgBranching dropdown has ryan_foster (default) + variable', () => {
      cy.get('[data-testid="adv-cg-branching"]')
        .should('have.value', 'ryan_foster')
        .find('option')
        .then(($opts) => {
          const values = [...$opts].map((o) => (o as HTMLOptionElement).value);
          expect(values).to.include.members(['ryan_foster', 'variable']);
        });
    });
  });

  describe('Hall pre-check', () => {
    it('POSTs to /api/diagnostics/hall-check and shows report on '
       + 'success', () => {
      cy.intercept('POST', '**/api/diagnostics/hall-check', {
        statusCode: 200,
        body: {
          ok: true,
          n_classes: 5, n_teachers: 8,
          violations: [],
          stats: { total_demand_hours: 100, total_supply_hours: 144 },
        },
      }).as('hallCheck');

      cy.get('[data-testid="adv-hall-samples"]').clear().type('128');
      cy.get('[data-testid="adv-hall-run"]').click();
      cy.wait('@hallCheck').its('request.body').should((body: any) => {
        expect(body.n_samples).to.eq(128);
        expect(body.sync).to.eq(true);
      });
      cy.contains(/Feasible \(Hall OK\)/i).should('be.visible');
    });

    it('renders violations when the report flags them', () => {
      cy.intercept('POST', '**/api/diagnostics/hall-check', {
        statusCode: 200,
        body: {
          ok: false,
          n_classes: 3, n_teachers: 2,
          violations: [{ msg: 'Materia X: 0 docenti qualificati' }],
          stats: { total_demand_hours: 50, total_supply_hours: 36 },
        },
      });
      cy.get('[data-testid="adv-hall-run"]').click();
      cy.contains(/INFEASIBILE/).should('be.visible');
      cy.contains('Materia X: 0 docenti qualificati')
        .should('be.visible');
    });
  });

  describe('metaheuristics launches', () => {
    it('ALNS launch POSTs /api/optimize/meta/alns with the form params',
       () => {
      cy.intercept('POST', '**/api/optimize/meta/alns', {
        statusCode: 200, body: { run_id: 4242 },
      }).as('launchAlns');

      cy.get('[data-testid="adv-alns-budget"]').clear().type('120');
      cy.get('[data-testid="adv-alns-t0"]').clear().type('10');
      cy.get('[data-testid="adv-alns-alpha"]').clear().type('0.99');
      cy.get('[data-testid="adv-alns-run"]').click();
      cy.wait('@launchAlns').its('request.body').should((body: any) => {
        expect(body.budget_s).to.eq(120);
        expect(body.alns_T0).to.eq(10);
        expect(body.alns_alpha).to.eq(0.99);
      });
      cy.contains(/ALNS run #4242 avviato/i,
                  { timeout: 8000 }).should('be.visible');
    });

    it('VNS launch POSTs /api/optimize/meta/vns', () => {
      cy.intercept('POST', '**/api/optimize/meta/vns', {
        statusCode: 200, body: { run_id: 5555 },
      }).as('launchVns');

      cy.get('[data-testid="adv-vns-budget"]').clear().type('90');
      cy.get('[data-testid="adv-vns-run"]').click();
      cy.wait('@launchVns').its('request.body').should((body: any) => {
        expect(body.budget_s).to.eq(90);
      });
      cy.contains(/VNS run #5555/).should('be.visible');
    });

    it('Lagrangian launch POSTs /api/optimize/meta/lagrangian with all '
       + 'subgradient parameters', () => {
      cy.intercept('POST', '**/api/optimize/meta/lagrangian', {
        statusCode: 200, body: { run_id: 7777 },
      }).as('launchLag');

      cy.get('[data-testid="adv-lag-budget"]').clear().type('45');
      cy.get('[data-testid="adv-lag-max-iter"]').clear().type('12');
      cy.get('[data-testid="adv-lag-tolerance"]').clear().type('0.005');
      cy.get('[data-testid="adv-lag-alpha0"]').clear().type('0.7');
      cy.get('[data-testid="adv-lag-run"]').click();
      cy.wait('@launchLag').its('request.body').should((body: any) => {
        expect(body.budget_s).to.eq(45);
        expect(body.lagrangian_max_iter).to.eq(12);
        expect(body.lagrangian_tolerance).to.eq(0.005);
        expect(body.lagrangian_alpha_0).to.eq(0.7);
      });
      cy.contains(/Lagrangian run #7777/).should('be.visible');
    });
  });

  describe('Column Generation launch', () => {
    it('CG launch POSTs /api/optimize/column-generation with mode + '
       + 'granularity + branching the user picked', () => {
      cy.intercept('POST', '**/api/optimize/column-generation', {
        statusCode: 200, body: { run_id: 9090 },
      }).as('launchCg');

      cy.get('[data-testid="adv-cg-mode"]').select('branch-and-price');
      cy.get('[data-testid="adv-cg-granularity"]').select('teacher-class');
      cy.get('[data-testid="adv-cg-branching"]').select('variable');
      cy.get('[data-testid="adv-cg-budget"]').clear().type('150');
      cy.get('[data-testid="adv-cg-patterns"]').clear().type('5');
      cy.get('[data-testid="adv-cg-run"]').click();
      cy.wait('@launchCg').its('request.body').should((body: any) => {
        expect(body.mode).to.eq('branch-and-price');
        expect(body.granularity).to.eq('teacher-class');
        expect(body.branching_strategy).to.eq('variable');
        expect(body.time_budget_s).to.eq(150);
        expect(body.patterns_per_teacher).to.eq(5);
      });
      cy.contains(/Column Generation run #9090/).should('be.visible');
    });

    it('CG with auto mode + auto granularity submits the auto values',
       () => {
      cy.intercept('POST', '**/api/optimize/column-generation', {
        statusCode: 200, body: { run_id: 9091 },
      }).as('launchCgAuto');

      cy.get('[data-testid="adv-cg-mode"]').select('auto');
      cy.get('[data-testid="adv-cg-granularity"]').select('auto');
      cy.get('[data-testid="adv-cg-run"]').click();
      cy.wait('@launchCgAuto').its('request.body').should((body: any) => {
        expect(body.mode).to.eq('auto');
        expect(body.granularity).to.eq('auto');
      });
    });

    it('every granularity option submits its exact value', () => {
      const granularities = [
        'teacher', 'teacher-day', 'teacher-class',
        'teacher-class-subject', 'teacher-subject',
        'class', 'class-day', 'day', 'curriculum',
      ];
      cy.intercept('POST', '**/api/optimize/column-generation', (req) => {
        req.reply({ statusCode: 200, body: { run_id: 1 } });
      }).as('launchCgEach');

      granularities.forEach((g, i) => {
        cy.get('[data-testid="adv-cg-granularity"]').select(g);
        cy.get('[data-testid="adv-cg-run"]').click();
        cy.wait('@launchCgEach').its('request.body.granularity')
          .should('eq', g);
      });
    });
  });

  describe('errors', () => {
    it('surfaces backend 500 error as a flash without crashing', () => {
      cy.intercept('POST', '**/api/optimize/meta/vns', {
        statusCode: 500, body: { detail: 'mock failure' },
      });
      cy.get('[data-testid="adv-vns-run"]').click();
      cy.contains(/Errore.*mock failure|Errore/i,
                  { timeout: 5000 }).should('be.visible');
      // Card still mounted, button re-enabled.
      cy.get('[data-testid="adv-vns-run"]').should('not.be.disabled');
    });
  });
});
