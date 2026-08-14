import { expect, type Page, type TestInfo } from "@playwright/test";

export const GOLDEN_DOCUMENT_IDS = ["DOC-0001", "DOC-0002", "DOC-0003", "DOC-0004", "DOC-0005", "DOC-0006"];

export async function clearFixtureFilter(page: Page) {
  const clearFilter = page.getByRole("button", { name: "Clear filter" });
  if (await clearFilter.count()) await clearFilter.click();
}

export async function gotoS1(page: Page) {
  await page.goto("/", { waitUntil: "networkidle" });
  await clearFixtureFilter(page);
}

export async function bodyText(page: Page) {
  return page.locator("body").innerText();
}

export async function openRowMenu(page: Page, documentId: string) {
  const row = page.locator("tr", { hasText: documentId }).first();
  await expect(row).toBeVisible();
  const trigger = row.locator('button[aria-haspopup="menu"]');
  await trigger.click();
  await expect(trigger).toHaveAttribute("aria-expanded", "true");
  return page.locator(".s1-menu__panel").first();
}

export async function selectRowMenuItem(page: Page, documentId: string, label: string | RegExp) {
  await openRowMenu(page, documentId);
  await page.locator(".s1-menu__item", { hasText: label }).first().click();
}

export async function attachScreenshot(page: Page, testInfo: TestInfo, name: string) {
  const screenshot = await page.screenshot({ fullPage: true });
  await testInfo.attach(name, { body: screenshot, contentType: "image/png" });
}

export function expectNoForbiddenUx(text: string) {
  expect(text).not.toMatch(/\b\d{1,3}%\b/);
  expect(text).not.toMatch(/\ball clear\b/i);
  expect(text).not.toMatch(/\bcertainty bar\b/i);
  expect(text).not.toMatch(/\bconfidence score\b/i);
}

export function requireEnv(name: string) {
  const value = process.env[name];
  if (!value) throw new Error(`${name} is required for this E2E suite.`);
  return value;
}

export function testUploadFile(filename = "s1-e2e-supported.txt") {
  return {
    name: filename,
    mimeType: "text/plain",
    buffer: Buffer.from(
      [
        "Synthetic S1 E2E evidence",
        "National Fuel Gas Company - Natural Gas Utility Bill",
        "Customer: SCE Manufacturing",
        "Facility: Riverside Plant",
        "Service Address: 100 River Road, Buffalo, NY 14201",
        "Account Number: ACC-S1-E2E-001",
        "Service Period: Jan 1, 2025 to Jan 31, 2025",
        "From: 01/01/2025",
        "To: 01/31/2025",
        "Fuel Type: Natural Gas",
        "Usage Unit: MMBtu",
        "Total Usage: 28,100 MMBtu",
        "Supplier: National Fuel Gas Company",
      ].join("\n")
    ),
  };
}
