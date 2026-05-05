import { defineConfig } from 'cypress';

export default defineConfig({
  e2e: {
    // Frontend dev server (vite dev). The backend is expected at
    // http://127.0.0.1:8000 (see `webui/start.bat`).
    baseUrl: 'http://127.0.0.1:5173',
    supportFile: false,
    specPattern: 'cypress/e2e/**/*.cy.{ts,js}',
    fixturesFolder: 'cypress/fixtures',
    screenshotsFolder: 'cypress/screenshots',
    videosFolder: 'cypress/videos',
    video: false,
    // Conservative defaults: SvelteKit dev hot-reload can take a
    // moment after a backend mutation to repaint.
    defaultCommandTimeout: 10000,
    pageLoadTimeout: 30000,
  },
  env: {
    backendUrl: 'http://127.0.0.1:8000',
  },
});
