import { defineConfig, devices } from '@playwright/test';

// Runs in CI against a real backend (see .github/workflows/ci.yml): the
// workspace this was written in cannot download browsers.
export default defineConfig({
  testDir: './e2e',
  timeout: 60_000,
  retries: 0,
  // Specs share one seeded database; run them one after another.
  workers: 1,
  // In CI, failures become GitHub annotations (readable via the API, not just the log page).
  reporter: process.env.CI ? [['github'], ['list']] : [['list']],
  use: {
    baseURL: process.env.E2E_BASE_URL ?? 'http://localhost:4173',
    trace: 'retain-on-failure',
  },
  projects: [
    { name: 'chromium', use: { ...devices['Desktop Chrome'] }, testIgnore: /dayend\.spec/ },
    // Closing a day changes shop-wide state (counted items get a starting point),
    // so day end runs only after every other spec has finished.
    {
      name: 'day-end',
      use: { ...devices['Desktop Chrome'] },
      testMatch: /dayend\.spec/,
      dependencies: ['chromium'],
    },
  ],
});
