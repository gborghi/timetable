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
  // Click the first "Nuova" / "Aggiungi" button
  await page.getByRole('button', { name: /Nuova|Aggiungi/i })
    .first().click();
  await page.locator('input[type="text"]').first().fill(TEST_ROOM_NAME);
  await page.locator('input[type="number"]').first().fill('28');
  await page.getByRole('button', { name: /Salva|Crea|OK/i }).click();
  await expect(page.getByText(TEST_ROOM_NAME)).toBeVisible();
});
