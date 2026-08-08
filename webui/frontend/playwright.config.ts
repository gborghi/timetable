import { defineConfig, devices } from '@playwright/test';

/**
 * Playwright config for piTantum E2E tests.
 *
 * Tests live in `playwright/tests/`. Run with:
 *   cd webui/frontend
 *   npm run test:e2e:playwright
 *
 * Prerequisites: backend at :8000, frontend at :5173 (see Cypress
 * config for the boot recipe). Playwright is the secondary runner;
 * Cypress is the primary one — see package.json scripts.
 */
export default defineConfig({
  testDir: './playwright/tests',
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: 1,
  reporter: 'list',
  use: {
    baseURL: 'http://127.0.0.1:4173',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  projects: [
    {
      name: 'chromium',
      use: {
        ...devices['Desktop Chrome'],
        // Use system Chromium directly (headless-shell download was failing).
        launchOptions: {
          executablePath: '/Applications/Chromium.app/Contents/MacOS/Chromium',
          args: ['--headless=new'],
        },
      },
    },
  ],
});
