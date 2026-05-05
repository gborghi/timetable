import { test, expect } from '@playwright/test';

/**
 * Top-level navigation parity with cypress/e2e/navigation.cy.ts.
 * Loads each route and asserts no error banner.
 */

const ROUTES = [
  '/',
  '/assignments',
  '/classrooms',
  '/groups',
  '/monitor',
  '/teachers',
];

for (const path of ROUTES) {
  test(`loads ${path}`, async ({ page }) => {
    await page.goto(path);
    const body = page.locator('body');
    await expect(body).not.toBeEmpty();
    const errors = page.locator('.error-banner, [data-error]');
    expect(await errors.count(), `${path} should not error`).toBe(0);
  });
}
