import { test, expect } from '@playwright/test';

/**
 * Playwright parity for cypress/e2e/classrooms_create.cy.ts.
 */

const BACKEND = process.env.BACKEND_URL || 'http://127.0.0.1:8000';
const TEST_ROOM_NAME = '_E2E_PW_Aula';

test.beforeEach(async ({ request }) => {
  try {
    const r = await request.get(`${BACKEND}/api/classrooms`);
    if (!r.ok()) return;
    const body = await r.json();
    const items = (body.items ?? body) || [];
    for (const cl of items) {
      if (cl.name === TEST_ROOM_NAME) {
        await request.delete(`${BACKEND}/api/classrooms/${cl.id}`);
      }
    }
  } catch {
    /* ignore -- the test will surface failure later */
  }
});

test('create a classroom via /classrooms', async ({ page }) => {
  await page.goto('/classrooms');
  // The page has multiple "Nuova/Salva" elements; use the
  // .btn-primary class to scope to the canonical buttons.
  await page.locator('button.btn-primary')
    .filter({ hasText: /Nuova aula/ }).click();
  await page.locator('.field input').first().fill(TEST_ROOM_NAME);
  await page.locator('input[type="number"]').first().fill('28');
  // The Save button is also btn-primary inside the modal.
  // Use exact match on "Salva" to skip the page header's
  // "Salva vista".
  await page.getByRole('button', { name: 'Salva', exact: true })
    .click();
  await expect(page.getByText(TEST_ROOM_NAME)).toBeVisible();
});
