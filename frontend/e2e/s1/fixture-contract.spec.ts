import { expect, test } from "@playwright/test";

import {
  attachScreenshot,
  bodyText,
  clearFixtureFilter,
  expectNoForbiddenUx,
  GOLDEN_DOCUMENT_IDS,
  gotoS1,
  openRowMenu,
  selectRowMenuItem,
} from "./helpers";

test.describe("S1 fixture-contract E2E", () => {
  test("renders the July 30 + Aug 10 + Aug 12 Evidence Workspace contract", async ({ page }, testInfo) => {
    await gotoS1(page);
    const text = await bodyText(page);

    for (const documentId of GOLDEN_DOCUMENT_IDS) {
      await expect(page.getByText(documentId, { exact: true }).first()).toBeVisible();
    }

    await expect(page.getByText("SCE Manufacturing")).toBeVisible();
    await expect(page.getByText("ENG-S1-2025")).toBeVisible();
    await expect(page.getByText("NY Part 253")).toBeVisible();
    await expect(page.getByText("not yet evaluated")).toBeVisible();

    for (const countLabel of ["type review", "unaccepted types", "facility", "period", "blocked"]) {
      await expect(page.getByRole("button", { name: new RegExp(countLabel, "i") }).first()).toBeVisible();
    }

    const evidenceTable = page.locator("table", { hasText: "DOC-0001" }).first();
    const headers = await evidenceTable.locator("thead th").allInnerTexts();
    expect(headers).toHaveLength(9);
    expect(headers.slice(1)).toEqual([
      "Document",
      "Detected type",
      "Facility",
      "Period",
      "Fields found / expected for type",
      "Processing state",
      "Flags",
      "Actions",
    ]);

    await expect(page.locator("tr", { hasText: "DOC-0001" }).first().getByText("auto-accepted")).toBeVisible();
    await expect(page.locator("tr", { hasText: "DOC-0004" }).first().getByText("Unresolved").first()).toBeVisible();
    await expect(page.locator("tr", { hasText: "DOC-0006" }).first().getByText("Not facility-scoped")).toBeVisible();
    await expect(page.locator("tr", { hasText: "DOC-0005" }).first().getByText("Multiple (2)")).toBeVisible();
    await expect(page.getByRole("heading", { name: "Completeness" })).toBeVisible();
    await expect(page.getByText("Audit entries in this session are not retained.")).toBeVisible();
    await expect(page.getByText("This build cannot be used for a live engagement.")).toBeVisible();
    expectNoForbiddenUx(text);
    await attachScreenshot(page, testInfo, "s1-fixture-workspace");
  });

  test("supports filters, selection clearing, row menu keyboard, history, and working state", async ({ page }) => {
    await gotoS1(page);

    await page.getByRole("button", { name: /blocked/i }).click();
    await expect(page.getByText("Counts above are engagement-wide. The table below is filtered.")).toBeVisible();
    await expect(page.getByText("Clear filter")).toBeVisible();
    await clearFixtureFilter(page);
    await expect(page.getByText("DOC-0001", { exact: true }).first()).toBeVisible();

    const firstMenuTrigger = page.locator('button[aria-haspopup="menu"]').first();
    await firstMenuTrigger.focus();
    await page.keyboard.press("Enter");
    await expect(firstMenuTrigger).toHaveAttribute("aria-expanded", "true");
    await page.keyboard.press("ArrowDown");
    await page.keyboard.press("Escape");
    await expect(firstMenuTrigger).toHaveAttribute("aria-expanded", "false");
    await expect(firstMenuTrigger).toBeFocused();

    const menu = await openRowMenu(page, "DOC-0001");
    await expect(menu.getByText("Enter values manually")).toBeVisible();
    await expect(menu.getByText("History")).toBeVisible();
    await page.locator(".s1-menu__item", { hasText: "History" }).first().click();
    await expect(page.getByText("History")).toBeVisible();

    await expect(page.getByRole("button", { name: "Accept" }).first()).toBeVisible();
  });

  test("opens snippet-first Extraction Review with useful default source selection", async ({ page }, testInfo) => {
    await gotoS1(page);
    await selectRowMenuItem(page, "DOC-0001", "Open extraction review");

    await expect(page.getByText("Queue")).toBeVisible();
    await expect(page.getByText("Fields")).toBeVisible();
    await expect(page.getByText("Selected field source: page")).toBeVisible();
    await expect(page.getByText("PROVISIONAL").first()).toBeVisible();
    await expect(page.locator(".s1-correction-rail").getByText("Electricity consumed")).toBeVisible();
    await expect(page.locator(".s1-selected-source").getByText("Electricity consumed")).toBeVisible();

    await page.locator(".s1-field-row").first().focus();
    await page.keyboard.press("ArrowDown");
    await expect(page.locator('.s1-field-row[aria-current="true"]').first()).toBeVisible();
    await page.locator(".s1-field-row", { hasText: "Account number" }).click();
    await expect(page.locator(".s1-selected-source").getByRole("heading", { name: "Account number" })).toBeVisible();
    await attachScreenshot(page, testInfo, "s1-extraction-snippet");
  });

  test("opens whole-document manual entry and records human-keyed values without a second accept", async ({ page }, testInfo) => {
    await gotoS1(page);
    await selectRowMenuItem(page, "DOC-0004", "Enter values manually");

    await expect(page.getByText("Opened for manual entry — no machine read this document.")).toBeVisible();
    await expect(page.getByText("Every field is empty and enterable — extraction never ran on this document")).toBeVisible();
    await expect(page.locator(".s1-document-empty").getByText("No extracted span for any field on this document — extraction was blocked")).toBeVisible();
    await expect(page.getByText("Account number")).toBeVisible();
    await expect(page.getByText("Core-derived")).toBeVisible();
    await expect(page.getByText("Recommended").first()).toBeVisible();

    await page.getByRole("button", { name: "Key value" }).first().click();
    const input = page.locator("input.s1-inline-input");
    await expect(input).toBeFocused();
    await input.fill("12345");
    await page.keyboard.press("Enter");

    await expect(page.getByText("human-keyed").first()).toBeVisible();
    await expect(page.getByText("12345")).toBeVisible();
    await expect(page.getByRole("button", { name: "Accept" })).toHaveCount(0);
    await attachScreenshot(page, testInfo, "s1-extraction-manual");
  });

  test("renders Glossary as one page with vocabulary and live state enumerations", async ({ page }, testInfo) => {
    await gotoS1(page);
    await page.getByText("Glossary").click();

    await expect(page.getByRole("heading", { name: "Glossary" })).toBeVisible();
    await expect(page.getByText("The words are the contract. These terms are not interchangeable")).toBeVisible();

    for (const term of ["Document typing", "Classification", "Gap", "Finding", "Request", "Main evidence", "Supportive evidence", "Type review", "Fields extracted"]) {
      await expect(page.getByText(term, { exact: true })).toBeVisible();
    }

    for (const enumeration of ["processing", "review", "check", "field", "facilityResolution", "periodResolution", "valueProperty", "readiness", "disposition", "request"]) {
      await expect(page.getByText(enumeration, { exact: true })).toBeVisible();
    }

    await expect(page.getByText("Waived below threshold")).toBeVisible();
    await expect(page.getByText("unmapped:", { exact: false })).toHaveCount(0);
    await attachScreenshot(page, testInfo, "s1-glossary");
  });
});
