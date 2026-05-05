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

## Docker-compose orchestration

A reusable stack is shipped at the repo root (`docker-compose.test.yml`):

```bash
# From the repo root
docker compose -f docker-compose.test.yml up -d --build

# Wait for both services to be healthy (~10-30s the first time)
docker compose -f docker-compose.test.yml ps

# Run the E2E suites against the stack
cd webui/frontend
npm run test:e2e:cypress     # or: npm run test:e2e:playwright

# Tear down (the SQLite DB is in a tmpfs volume; -v wipes it)
docker compose -f docker-compose.test.yml down -v
```

The stack:
- `backend` (image `pitantum-backend:test`): python:3.11-slim with
  the engine + schedule modules on PYTHONPATH, uvicorn on :8000,
  health endpoint `/api/health` polled every 5s.
- `frontend` (image `pitantum-frontend:test`): node:20-alpine with
  `npm ci` + `vite dev --host 0.0.0.0`, depends on backend healthy.

The Dockerfiles live next to each app (`webui/backend/Dockerfile`,
`webui/frontend/Dockerfile`); both are minimal and meant for E2E
only -- production-grade images are a separate concern.

## CI

Workflow source: [`docs/ci_e2e_workflow.yml.txt`](../../docs/ci_e2e_workflow.yml.txt).

Two parallel jobs (`cypress` + `playwright`), each with the same
shape:

1. Build the docker-compose stack (`docker compose up -d --build`).
2. Poll until both services report `healthy` (60 retries x 5s).
3. `npm ci` on the host, install `chromium` for Playwright.
4. Run the E2E suite (`npm run test:e2e:cypress` / `:playwright`).
5. Upload artifacts on failure: cypress screenshots/videos /
   playwright-report / compose logs.
6. Tear down the stack with `down -v`.

Triggers:
- `pull_request` to `main` when frontend, backend, engine, schedule
  or compose files change.
- `workflow_dispatch` for manual runs from the GitHub UI.

Per-job timeout: 25 minutes.

### Activating the workflow

The yaml file is shipped at `docs/ci_e2e_workflow.yml.txt` (NOT
under `.github/workflows/` directly) because the OAuth token used
to push commits does not carry the `workflow` scope. To enable the
CI:

```bash
mkdir -p .github/workflows
cp docs/ci_e2e_workflow.yml.txt .github/workflows/e2e.yml
git add .github/workflows/e2e.yml
git commit -m "ci: enable e2e workflow"
# Push with a token that has the `workflow` scope, OR use the
# GitHub web UI to upload the file under .github/workflows/.
git push
```

To debug locally exactly the way CI does:
```bash
docker compose -f docker-compose.test.yml up -d --build
cd webui/frontend
npm ci
npm run test:e2e:cypress
docker compose -f docker-compose.test.yml down -v
```

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
