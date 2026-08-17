import { defineConfig, devices } from "@playwright/test";
import { existsSync } from "node:fs";

const fixturePort = Number(process.env.S1_FIXTURE_PORT ?? 3100);
const fixtureUrl = process.env.S1_FIXTURE_URL ?? `http://127.0.0.1:${fixturePort}`;
const s2FixturePort = Number(process.env.S2_FIXTURE_PORT ?? 3200);
const s2FixtureUrl = process.env.S2_FIXTURE_URL ?? `http://127.0.0.1:${s2FixturePort}`;
const localUrl = process.env.S1_LOCAL_URL ?? "http://127.0.0.1:3000";
const cloudUrl = process.env.S1_CLOUD_URL ?? "http://example.invalid";
const shouldStartFixtureServer = process.env.S1_E2E_WEB_SERVER === "1";
const shouldStartS2FixtureServer = process.env.S2_E2E_WEB_SERVER === "1";
const localChromiumExecutable =
  "/Users/qinghuanyang/Library/Caches/ms-playwright/chromium-1187/chrome-mac/Chromium.app/Contents/MacOS/Chromium";
const executablePath =
  process.env.S1_PLAYWRIGHT_EXECUTABLE_PATH ??
  (existsSync(localChromiumExecutable) ? localChromiumExecutable : undefined);

export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  reporter: [["list"], ["html", { open: "never", outputFolder: "playwright-report" }]],
  use: {
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
    launchOptions: executablePath ? { executablePath } : undefined,
    ...devices["Desktop Chrome"],
  },
  webServer: shouldStartS2FixtureServer
    ? {
        command: `NEXT_PUBLIC_S2_FIXTURE=meridian NEXT_TELEMETRY_DISABLED=1 npm run dev -- --hostname 127.0.0.1 --port ${s2FixturePort}`,
        url: s2FixtureUrl,
        reuseExistingServer: !process.env.CI,
        timeout: 120_000,
      }
    : shouldStartFixtureServer
    ? {
        command: `NEXT_PUBLIC_S1_DATA_MODE=fixture NEXT_TELEMETRY_DISABLED=1 npm run dev -- --hostname 127.0.0.1 --port ${fixturePort}`,
        url: fixtureUrl,
        reuseExistingServer: !process.env.CI,
        timeout: 120_000,
      }
    : undefined,
  projects: [
    {
      name: "s1-fixture",
      testMatch: /s1\/fixture-contract\.spec\.ts/,
      use: { baseURL: fixtureUrl },
    },
    {
      name: "s1-local-backend",
      testMatch: /s1\/local-pipeline\.spec\.ts/,
      use: { baseURL: localUrl },
    },
    {
      name: "s1-cloud",
      testMatch: /s1\/cloud-pipeline\.spec\.ts/,
      use: { baseURL: cloudUrl },
    },
    {
      name: "s2-fixture",
      testMatch: /s2\/fixture-contract\.spec\.ts/,
      use: { baseURL: s2FixtureUrl },
    },
  ],
});
