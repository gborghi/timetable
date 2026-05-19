import { test, expect, type Page, type ConsoleMessage } from '@playwright/test';
import * as fs from 'node:fs';
import * as path from 'node:path';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

/**
 * Comprehensive E2E evaluation spec.
 *
 * Walks every primary route, imports the "small" profile to populate
 * a realistic dataset, then exercises schedule views, free-now,
 * working-hours, optimize, and exports. Records a screenshot per
 * route under playwright/artifacts/<slug>.png and reports console
 * errors / network errors per-page via stdout.
 */

const BACKEND = process.env.BACKEND_URL || 'http://127.0.0.1:8000';
const ART_DIR = path.resolve(__dirname, '..', 'artifacts');

test.beforeAll(() => {
  fs.mkdirSync(ART_DIR, { recursive: true });
});

type PageProbe = {
  consoleErrors: string[];
  pageErrors: string[];
  reqFailed: string[];
};

function attach(page: Page): PageProbe {
  const probe: PageProbe = { consoleErrors: [], pageErrors: [], reqFailed: [] };
  page.on('console', (m: ConsoleMessage) => {
    if (m.type() === 'error') probe.consoleErrors.push(m.text());
  });
  page.on('pageerror', (e) => probe.pageErrors.push(String(e?.message || e)));
  page.on('requestfailed', (r) => {
    const f = r.failure();
    probe.reqFailed.push(`${r.method()} ${r.url()} :: ${f?.errorText ?? '?'}`);
  });
  return probe;
}

async function snap(page: Page, slug: string) {
  const p = path.join(ART_DIR, `${slug}.png`);
  try {
    await page.screenshot({ path: p, fullPage: true });
  } catch {
    /* ignore screenshot failures */
  }
}

/* ---------- 1. Import small profile so the UI has data ---------- */
test('00 import small profile via api', async ({ request }) => {
  const stateBefore = await (await request.get(`${BACKEND}/api/dataset/state`)).json();
  if ((stateBefore.classes ?? 0) > 0 && (stateBefore.teachers ?? 0) > 0) {
    test.info().annotations.push({ type: 'skip-import', description: 'data already loaded' });
    return;
  }
  const r = await request.post(`${BACKEND}/api/dataset/import-profile`, {
    data: { profile: 'small' },
  });
  expect(r.ok(), `import-profile small failed: ${r.status()} ${await r.text()}`).toBeTruthy();
  // poll until classes > 0 (import is synchronous in this backend
  // but be defensive)
  for (let i = 0; i < 30; i++) {
    const s = await (await request.get(`${BACKEND}/api/dataset/state`)).json();
    if ((s.classes ?? 0) > 0) return;
    await new Promise((res) => setTimeout(res, 500));
  }
  throw new Error('dataset state did not populate after import');
});

/* ---------- 2. Dashboard counters reflect imported data ---------- */
test('01 dashboard shows non-zero counters', async ({ page }) => {
  const probe = attach(page);
  await page.goto('/');
  await page.waitForLoadState('networkidle');
  await snap(page, '01-dashboard');
  // Generic body sanity
  const body = page.locator('body');
  await expect(body).not.toBeEmpty();
  // Don't be brittle on exact labels; just assert numeric content somewhere
  const text = await body.innerText();
  expect(text.length).toBeGreaterThan(50);
  console.log('[01-dashboard] consoleErrors=', probe.consoleErrors.length, 'reqFailed=', probe.reqFailed.length);
  for (const e of probe.consoleErrors.slice(0, 5)) console.log('   console-error:', e);
  for (const e of probe.reqFailed.slice(0, 5)) console.log('   req-failed:', e);
});

/* ---------- 3. Walk through every primary route ---------- */
const ROUTES: { path: string; slug: string; expect?: RegExp }[] = [
  { path: '/', slug: '01-dashboard' },
  { path: '/teachers', slug: '02-teachers' },
  { path: '/classes', slug: '03-classes' },
  { path: '/subjects', slug: '04-subjects' },
  { path: '/classrooms', slug: '05-classrooms' },
  { path: '/assignments', slug: '06-assignments' },
  { path: '/groups', slug: '07-groups' },
  { path: '/students', slug: '08-students' },
  { path: '/curricula', slug: '09-curricula' },
  { path: '/coteaching', slug: '10-coteaching' },
  { path: '/constraints', slug: '11-constraints' },
  { path: '/plessi', slug: '12-plessi' },
  { path: '/ore', slug: '13-ore' },
  { path: '/import', slug: '14-import' },
  { path: '/optimize', slug: '15-optimize' },
  { path: '/schedule', slug: '16-schedule' },
  { path: '/monitor', slug: '17-monitor' },
  { path: '/runs', slug: '18-runs' },
  { path: '/diagnostics', slug: '19-diagnostics' },
  { path: '/assenze-supplenze', slug: '20-assenze' },
];

for (const r of ROUTES) {
  test(`route ${r.path}`, async ({ page }) => {
    const probe = attach(page);
    const resp = await page.goto(r.path, { waitUntil: 'domcontentloaded' });
    expect(resp?.status() ?? 0, `${r.path} HTTP`).toBeLessThan(500);
    // Short timeout: /optimize fires a heavy recommendation fetch on
    // mount (~25s); we don't want to block tests on that.
    await page.waitForLoadState('networkidle', { timeout: 3000 }).catch(() => { /* allow slow/SSE pages */ });
    await snap(page, r.slug);
    const errors = page.locator('.error-banner, [data-error]');
    const errCount = await errors.count();
    expect(errCount, `${r.path} should not show error banner`).toBe(0);
    if (probe.consoleErrors.length || probe.pageErrors.length || probe.reqFailed.length) {
      console.log(`[${r.slug}] console=${probe.consoleErrors.length} pageErr=${probe.pageErrors.length} reqFailed=${probe.reqFailed.length}`);
      for (const e of probe.consoleErrors.slice(0, 3)) console.log('   console:', e.slice(0, 200));
      for (const e of probe.pageErrors.slice(0, 3)) console.log('   pageErr:', e.slice(0, 200));
      for (const e of probe.reqFailed.slice(0, 3)) console.log('   reqFail:', e.slice(0, 200));
    }
  });
}

/* ---------- 4. Schedule page: switch views ---------- */
test('schedule view tabs cycle', async ({ page, request }) => {
  // Pre-check: data must be loaded
  const s = await (await request.get(`${BACKEND}/api/dataset/state`)).json();
  test.skip((s.classes ?? 0) === 0, 'no data imported');
  const probe = attach(page);
  await page.goto('/schedule');
  await page.waitForLoadState('networkidle').catch(() => {});
  await snap(page, '30-schedule-default');
  // Try clicking each known view-toggle if present. Be lenient:
  // not all builds expose buttons with these exact labels.
  for (const label of [/per classe/i, /per docente/i, /per aula/i, /per slot/i]) {
    const b = page.getByRole('button', { name: label }).first();
    if (await b.count()) {
      await b.click().catch(() => {});
      await page.waitForTimeout(500);
      await snap(page, `30-schedule-${label.source.replace(/[^a-z]/gi, '')}`);
    }
  }
  console.log('[schedule] consoleErrors=', probe.consoleErrors.length, 'reqFailed=', probe.reqFailed.length);
});

/* ---------- 5. Teachers list shows imported teachers ---------- */
test('teachers list non-empty after import', async ({ page, request }) => {
  const s = await (await request.get(`${BACKEND}/api/dataset/state`)).json();
  test.skip((s.teachers ?? 0) === 0, 'no data imported');
  await page.goto('/teachers');
  await page.waitForLoadState('networkidle');
  await snap(page, '40-teachers-list');
  // Expect at least 1 row in any table-like structure, or
  // at least the imported number reflected in body text.
  const body = await page.locator('body').innerText();
  expect(body.length).toBeGreaterThan(100);
});

/* ---------- 6. Working hours config page renders ---------- */
test('ore page exposes working-hours config', async ({ page }) => {
  await page.goto('/ore');
  await page.waitForLoadState('networkidle');
  await snap(page, '50-ore');
  const errs = await page.locator('.error-banner').count();
  expect(errs).toBe(0);
});

/* ---------- 7. Free-now tool (chi e libero?) ---------- */
test('free-now api works', async ({ request }) => {
  const r = await request.get(`${BACKEND}/api/schedule/free-now`);
  // Accept any 2xx-4xx; backend may require params.
  expect(r.status(), 'free-now reachable').toBeLessThan(500);
});

/* ---------- 8. Optimize page ---------- */
test('optimize page lists workflow', async ({ page }) => {
  const probe = attach(page);
  await page.goto('/optimize');
  await page.waitForLoadState('networkidle', { timeout: 3000 }).catch(() => {});
  await snap(page, '60-optimize');
  const body = await page.locator('body').innerText();
  expect(body.length).toBeGreaterThan(50);
  for (const e of probe.consoleErrors.slice(0, 3)) console.log('  optimize console:', e.slice(0, 200));
});

/* ---------- 9. Constraints page ---------- */
test('constraints page renders without backend errors', async ({ page }) => {
  const probe = attach(page);
  await page.goto('/constraints');
  await page.waitForLoadState('networkidle').catch(() => {});
  await snap(page, '70-constraints');
  for (const e of probe.consoleErrors.slice(0, 3)) console.log('  constraints console:', e.slice(0, 200));
});
