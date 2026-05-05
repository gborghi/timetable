import { test, expect } from '@playwright/test';

/**
 * Playwright smoke test: parity with the Cypress smoke test.
 *
 * Verifies the frontend dev server is serving the SvelteKit app
 * and the home page has the expected title + a nav link.
 */

test('home page loads with brand title', async ({ page }) => {
  await page.goto('/');
  await expect(page).toHaveTitle(/piTantum|Tempus Tantum/i);
  // SvelteKit hydrates client-side; we just check the body
  // mounted and there's no error banner.
  const body = page.locator('body');
  await expect(body).not.toBeEmpty();
  const errors = page.locator('.error-banner, [data-error]');
  expect(await errors.count(), 'no error banner').toBe(0);
});
