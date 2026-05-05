import { test, expect } from '@playwright/test';

/**
 * Playwright parity for cypress/e2e/groups_create.cy.ts -- creates
 * a study group via the UI form.
 *
 * Uses BACKEND_URL env (defaults to :8000) for the data cleanup
 * pre-step. Skips the test gracefully when the backend is
 * unreachable.
 */

const BACKEND = process.env.BACKEND_URL || 'http://127.0.0.1:8000';
const TEST_GROUP_NAME = '_E2E_PW_test';

test.beforeEach(async ({ request }) => {
  // Best-effort: GET groups, DELETE any with the test name.
  try {
    const r = await request.get(`${BACKEND}/api/groups`);
    if (!r.ok()) return;
    const body = await r.json();
    const items = (body.items ?? body) || [];
    for (const g of items) {
      if (g.name === TEST_GROUP_NAME) {
        await request.delete(`${BACKEND}/api/groups/${g.id}`);
      }
    }
  } catch {
    // backend not reachable -- the test will simply fail later
    // with a more meaningful UI assertion. We don't abort here.
  }
});

test('create a study group via /groups', async ({ page }) => {
  await page.goto('/groups');
  await page.getByRole('button', { name: /Nuovo gruppo/i }).click();
  // Fill the first text input in the modal
  const nameInput = page.locator('input[type="text"]').first();
  await nameInput.fill(TEST_GROUP_NAME);
  await page.getByRole('button', { name: /^Salva$/i }).click();
  // Verify the new group appears in the list
  await expect(page.getByText(TEST_GROUP_NAME)).toBeVisible();
});
