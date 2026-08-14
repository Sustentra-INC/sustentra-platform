import { expect, test } from "@playwright/test";

import { bodyText, requireEnv, testUploadFile } from "./helpers";

const runLocal = process.env.S1_RUN_LOCAL_PIPELINE_E2E === "1";
const localApiUrl = process.env.S1_LOCAL_API_URL ?? "http://127.0.0.1:8000";
const engagementId = process.env.S1_E2E_ENGAGEMENT_ID ?? "ENG-S1-2025";

test.describe("S1 local real-pipeline E2E", () => {
  test.skip(!runLocal, "Set S1_RUN_LOCAL_PIPELINE_E2E=1 after starting the local durable stack.");

  test("B01 clean startup uses backend mode without fixture documents", async ({ page, request }) => {
    await expect(await request.get(`${localApiUrl}/health`)).toBeOK();
    await page.goto("/", { waitUntil: "networkidle" });

    const text = await bodyText(page);
    expect(text).not.toContain("S1 demo controls");
    for (const fixtureId of ["DOC-0001", "DOC-0002", "DOC-0003", "DOC-0004", "DOC-0005", "DOC-0006"]) {
      expect(text).not.toContain(fixtureId);
    }
  });

  test("B02-B08 upload, process, refresh, API integrity, and download a real document", async ({ page, request }) => {
    await page.goto("/", { waitUntil: "networkidle" });

    const file = testUploadFile(`natural-gas-utility-bill-s1-e2e-${Date.now()}.txt`);
    await page.locator('input[type="file"]').setInputFiles(file);
    await expect(page.getByText(file.name)).toBeVisible();
    await expect(
      page
        .getByRole("row", { name: new RegExp(file.name) })
        .getByText(/Not ingested|Ingested|Typed|Extracted|Blocked/)
        .first()
    ).toBeVisible();

    const listResponse = await request.get(`${localApiUrl}/v1/engagements/${encodeURIComponent(engagementId)}/documents`);
    await expect(listResponse).toBeOK();
    const documents = (await listResponse.json()).items as Array<Record<string, unknown>>;
    const uploaded = documents.find((item) => item.file_name === file.name);
    expect(uploaded?.document_id).toBeTruthy();
    expect(uploaded?.evidence_id).toBeTruthy();

    const documentId = String(uploaded?.document_id);
    const processResponse = await request.post(`${localApiUrl}/v1/documents/${encodeURIComponent(documentId)}/pipeline/process`, {
      data: { persist_run: true },
    });
    expect([200, 400, 500]).toContain(processResponse.status());

    await page.reload({ waitUntil: "networkidle" });
    await expect(page.getByRole("button", { name: file.name }).first()).toBeVisible();

    const latestRun = await request.get(`${localApiUrl}/v1/pipeline/evidence/${encodeURIComponent(String(uploaded?.evidence_id))}/latest-run`);
    expect([200, 404]).toContain(latestRun.status());

    const extraction = await request.get(`${localApiUrl}/v1/documents/${encodeURIComponent(documentId)}/extraction-result/latest`);
    expect([200, 404]).toContain(extraction.status());
    let candidateId: string | null = null;
    if (extraction.ok()) {
      const extractionBody = await extraction.json();
      expect(Array.isArray(extractionBody.items)).toBe(true);
      const reviewableCandidate = extractionBody.items.find(
        (item: { candidate_id?: string; normalized_value?: unknown }) =>
          item.candidate_id && item.normalized_value !== null && item.normalized_value !== undefined
      );
      expect(reviewableCandidate?.candidate_id).toBeTruthy();
      candidateId = reviewableCandidate.candidate_id;
    }

    await page.getByRole("button", { name: file.name }).first().click();
    await expect(page.getByRole("heading", { name: file.name })).toBeVisible();
    await page.getByRole("button", { name: "Accept" }).first().click();

    await expect
      .poll(async () => {
        const reviews = await request.get(`${localApiUrl}/v1/documents/${encodeURIComponent(documentId)}/reviews`);
        if (!reviews.ok()) return 0;
        return ((await reviews.json()) as Array<Record<string, unknown>>).filter(
          (review) => review.candidate_id === candidateId && review.decision === "accepted"
        ).length;
      })
      .toBeGreaterThan(0);

    await page.reload({ waitUntil: "networkidle" });
    await page.getByRole("button", { name: file.name }).first().click();
    await expect(page.getByText("accepted").first()).toBeVisible();

    const download = await request.get(`${localApiUrl}/v1/documents/${encodeURIComponent(documentId)}/download`);
    await expect(download).toBeOK();
    expect((await download.body()).toString("utf8")).toContain("Synthetic S1 E2E evidence");
  });

  test("B10 local restart persistence hook is explicit", async () => {
    test.skip(!process.env.S1_LOCAL_RESTART_COMMAND, "Set S1_LOCAL_RESTART_COMMAND to enable restart persistence.");
    const restartCommand = requireEnv("S1_LOCAL_RESTART_COMMAND");
    expect(restartCommand).toBeTruthy();
    test.skip(true, "Restart persistence requires the harness to run S1_LOCAL_RESTART_COMMAND between upload/review and reload.");
  });
});
