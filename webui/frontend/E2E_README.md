# E2E test runners

Two complementary frameworks:

- **Cypress** (primary) -- interactive runner + headless mode.
- **Playwright** (secondary, parity) -- chromium-only, retain-on-failure
  trace for debugging.

## Manual run

Both frameworks need:

1. Backend running at `http://127.0.0.1:8000`:
   ```
   cd webui/backend
   .venv/Scripts/python -m uvicorn backend.main:app --port 8000
   ```
2. Frontend dev server at `http://127.0.0.1:5173`:
   ```
   cd webui/frontend
   npm run dev
   ```
3. A populated DB (e.g. import the `small` profile from the dashboard).

### Cypress

```bash
cd webui/frontend

# Headless run
npm run test:e2e:cypress

# Interactive (opens the runner GUI; useful for writing new tests)
npm run test:e2e:cypress:open
```

Test specs live in `cypress/e2e/*.cy.ts`. The `smoke.cy.ts` test
checks the home page; the others exercise CRUD on `/groups`,
`/classrooms`, and the navigation across all top-level routes.

### Playwright

```bash
cd webui/frontend
npm run test:e2e:playwright
```

Test specs in `playwright/tests/*.spec.ts`. Currently parity for
the most important Cypress tests (smoke, navigation, groups,
classrooms).

## CI considerations

The frameworks are NOT wired to CI yet. To wire them, an orchestrator
needs to:

1. Build the frontend (`npm run build`).
2. Start the backend with a test DB (env `PITANTUM_DB_URL=sqlite:///:memory:`).
3. Start the frontend preview (`npm run preview`).
4. Wait for both to be reachable.
5. Run `npm run test:e2e:cypress` (or `:playwright`).

A docker-compose recipe is the natural next step; not in scope yet.

## Adding tests

For a new workflow:

1. Decide which framework -- Cypress for the primary suite, Playwright
   for parity.
2. Add a spec under `cypress/e2e/*.cy.ts` or `playwright/tests/*.spec.ts`.
3. Pre-clean test data via the API (idempotent).
4. Drive the UI with role-based selectors when possible (`getByRole`
   in Playwright, `cy.contains` in Cypress).

The smoke + navigation tests are deliberately tolerant -- they check
"page loads, no error banner" rather than specific data. Use them as
templates for routes that don't have a clear empty/populated split.
