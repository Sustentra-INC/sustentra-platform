import { expect, test } from "@playwright/test";

import { bodyText, requireEnv, testUploadFile } from "./helpers";

const runCloud = process.env.S1_RUN_CLOUD_E2E === "1";
const cloudApiUrl = process.env.S1_CLOUD_API_URL;
const engagementId = process.env.S1_E2E_ENGAGEMENT_ID ?? "ENG-S1-2025";

test.describe("S1 cloud real-pipeline E2E", () => {
  test.skip(!runCloud, "Set S1_RUN_CLOUD_E2E=1 plus S1_CLOUD_URL and S1_CLOUD_API_URL.");

  test("C01 deployment sanity and no fixture leakage", async ({ page }) => {
    requireEnv("S1_CLOUD_URL");
    await page.goto("/", { waitUntil: "networkidle" });
    const text = await bodyText(page);

    expect(text).not.toContain("S1 demo controls");
    for (const fixtureId of ["DOC-0001", "DOC-0002", "DOC-0003", "DOC-0004", "DOC-0005", "DOC-0006"]) {
      expect(text).not.toContain(fixtureId);
    }
  });

  test("C02 Vercel to Render API communication succeeds cross-origin", async ({ page }) => {
    requireEnv("S1_CLOUD_URL");
    requireEnv("S1_CLOUD_API_URL");
    const failed: string[] = [];
    page.on("requestfailed", (request) => failed.push(`${request.method()} ${request.url()} ${request.failure()?.errorText}`));
    page.on("response", (response) => {
      if (response.url().includes(cloudApiUrl ?? "") && response.status() >= 400) {
        failed.push(`${response.status()} ${response.url()}`);
      }
    });

    await page.goto("/", { waitUntil: "networkidle" });
    expect(failed).toEqual([]);
  });

  test("C03-C04 cloud upload and pipeline terminal state smoke", async ({ page, request }) => {
    requireEnv("S1_CLOUD_URL");
    const apiUrl = requireEnv("S1_CLOUD_API_URL");
    await page.goto("/", { waitUntil: "networkidle" });

    const file = testUploadFile(`natural-gas-utility-bill-s1-cloud-e2e-${Date.now()}.txt`);
    await page.locator('input[type="file"]').setInputFiles(file);
    await expect(page.getByText(file.name)).toBeVisible();

    const listResponse = await request.get(`${apiUrl}/v1/engagements/${encodeURIComponent(engagementId)}/documents`);
    await expect(listResponse).toBeOK();
    const documents = (await listResponse.json()).items as Array<Record<string, unknown>>;
    const uploaded = documents.find((item) => item.file_name === file.name);
    expect(uploaded?.document_id).toBeTruthy();

    await page.reload({ waitUntil: "networkidle" });
    await expect(page.getByText(file.name)).toBeVisible();
  });

  test("C05 cold-start behavior is a nightly hook", async () => {
    test.skip(!process.env.S1_CLOUD_COLD_START_WAIT_MINUTES, "Set S1_CLOUD_COLD_START_WAIT_MINUTES to enable cold-start checks.");
    test.skip(true, "Cold-start checks intentionally wait for Render idleness and belong in the nightly cloud suite.");
  });

  test("C09 Render restart persistence is an explicit release gate hook", async () => {
    test.skip(!process.env.S1_RENDER_RESTART_COMMAND, "Set S1_RENDER_RESTART_COMMAND to enable Render restart checks.");
    test.skip(true, "Render restart requires privileged deployment control; wire S1_RENDER_RESTART_COMMAND in release CI.");
  });

  test("C10 spin-down persistence is an explicit nightly hook", async () => {
    test.skip(!process.env.S1_CLOUD_SPIN_DOWN_WAIT_MINUTES, "Set S1_CLOUD_SPIN_DOWN_WAIT_MINUTES to enable spin-down checks.");
    test.skip(true, "Render natural spin-down is time-based and should run in nightly/release CI, not PR CI.");
  });

  test("C22 captures version compatibility diagnostics when endpoints exist", async ({ request }) => {
    const apiUrl = requireEnv("S1_CLOUD_API_URL");
    const health = await request.get(`${apiUrl}/health`);
    await expect(health).toBeOK();
    test.info().annotations.push({ type: "backend-health", description: JSON.stringify(await health.json()) });
    test.info().annotations.push({
      type: "frontend-version",
      description: process.env.VERCEL_GIT_COMMIT_SHA ?? process.env.S1_FRONTEND_COMMIT_SHA ?? "unknown",
    });
    test.info().annotations.push({
      type: "backend-version",
      description: process.env.S1_BACKEND_COMMIT_SHA ?? "unknown",
    });
  });
});
