import { defineConfig, devices } from "@playwright/test";

/**
 * TEST-002 end-to-end smoke test. Runs against an already-running stack
 * (`docker compose up` locally / in CI): web on E2E_BASE_URL, Mailpit on
 * E2E_MAILPIT_URL. See e2e/README.md.
 */
export default defineConfig({
  testDir: "./e2e",
  timeout: 120_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  reporter: [["list"], ["html", { open: "never", outputFolder: "playwright-report" }]],
  globalSetup: "./e2e/global-setup.ts",
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://localhost:3000",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [
    {
      name: "chromium",
      use: {
        ...devices["Desktop Chrome"],
        // Optional: a preinstalled Chromium instead of `npx playwright install chromium`.
        launchOptions: process.env.E2E_CHROMIUM_PATH ? { executablePath: process.env.E2E_CHROMIUM_PATH } : {},
      },
    },
  ],
});
