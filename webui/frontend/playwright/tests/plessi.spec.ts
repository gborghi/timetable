import { test, expect } from '@playwright/test';

/**
 * Playwright parity for cypress/e2e/plessi_create.cy.ts.
 */

const BACKEND = process.env.BACKEND_URL || 'http://127.0.0.1:8000';
const TEST_CODE = '_E2E_PW';
const TEST_NAME = '_E2E_PW_Sede';

test.beforeEach(async ({ request }) => {
  try {
    const r = await request.get(`${BACKEND}/api/plessi`);
    if (!r.ok()) return;
    const items = (await r.json()) || [];
    for (const p of items) {
      if (p.code === TEST_CODE || p.name === TEST_NAME) {
        await request.delete(`${BACKEND}/api/plessi/${p.id}`);
      }
    }
  } catch {
    /* ignore -- the test will surface failure later */
  }
});

test('shows validation banner', async ({ page }) => {
  await page.goto('/plessi');
  await expect(
    page.getByText(/Configurazione (OK|incoerente)/),
  ).toBeVisible();
});

test('create a plesso via /plessi', async ({ page }) => {
  await page.goto('/plessi');
  await page.getByRole('button', { name: /Nuovo plesso/ }).click();
  await page.locator('.field input').nth(0).fill(TEST_CODE);
  await page.locator('.field input').nth(1).fill(TEST_NAME);
  await page.getByRole('button', { name: 'Salva', exact: true })
    .click();
  await expect(
    page.getByRole('cell', { name: TEST_CODE, exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole('cell', { name: TEST_NAME, exact: true }),
  ).toBeVisible();
});
