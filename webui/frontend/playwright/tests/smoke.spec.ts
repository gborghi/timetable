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
  // At least one navigation link should exist.
  const navLink = page.locator(
    'a[href*="/assignments"], a[href*="/orario"], a[href*="/dashboard"]'
  );
  await expect(navLink.first()).toBeVisible();
});
