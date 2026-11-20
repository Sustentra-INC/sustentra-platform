import { existsSync } from "node:fs";
import path from "node:path";

import { expect, test } from "@playwright/test";

import { ADMIN_STATE_FILE } from "./global-setup";

/**
 * TEST-008 smoke: the core path of the product, end to end through the real UI, API and
 * database: create an engagement -> upload a fixture bill -> the bill is read -> accept a value
 * -> the accepted value survives a reload -> the recalculation shows a figure for it.
 *
 * It continues smoke.spec.ts (which runs first and saves the org admin's signed-in session), so
 * it needs no second email sign-in. The bill is a fictional text-layer PDF the rule readers read
 * in full (no Textract, no Claude): s1-test-suite/stationary_combustion/documents/SC-01. Its
 * expected values are in s1-test-suite/stationary_combustion/expected/SC-01.expected.json.
 *
 *   facility   Harborview Cold Storage LLC, 210 Dock Street, Erie, PA 16507
 *   period     2024-01-03 to 2024-02-01
 *   quantity   1,284 therm = 128.4 MMBtu of natural gas  ->  about 6.8 tCO2e
 */

const BILL = path.join(__dirname, "..", "..", "s1-test-suite", "stationary_combustion", "documents", "SC-01_lakeshore_gas_single_meter_therms.pdf");
const BILL_NAME = "SC-01_lakeshore_gas_single_meter_therms.pdf";
const FACILITY = "Harborview Cold Storage LLC";
const LINE = `Natural Gas, ${FACILITY}`;

// A step that cannot work fails in seconds, not at the end of the test timeout.
test.use({ storageState: ADMIN_STATE_FILE, actionTimeout: 15_000 });
test.setTimeout(60_000);

test("create an engagement -> upload a bill -> accept a value -> see the recalculation", async ({ page }) => {
  expect(existsSync(ADMIN_STATE_FILE), "smoke.spec.ts must run first: it saves the admin's session").toBe(true);

  await test.step("create an engagement with one facility whose address matches the bill", async () => {
    await page.goto("/?view=setup");
    await page.getByLabel("New engagement name").fill("E2E core path");
    await page.getByRole("button", { name: "Create", exact: true }).click();
    await page.getByLabel("Company name").fill(FACILITY);
    await page.getByLabel("Reporting period start").fill("2024-01-01");
    await page.getByLabel("Reporting period end").fill("2024-12-31");
    await page.getByRole("button", { name: "Add facility" }).click();
    await page.getByLabel("Facility name").fill(FACILITY);
    await page.getByLabel("Street address").fill("210 Dock Street, Erie, PA 16507");
    // Setup saves on its own; wait for the server to have it before leaving the page.
    await expect(page.getByRole("status", { name: "Setup save state" }).filter({ hasText: "Saved" })).toBeVisible();
  });

  await test.step("upload the bill and wait until it is read", async () => {
    await page.getByRole("button", { name: "Upload", exact: true }).click();
    const dialog = page.getByRole("dialog", { name: "Upload evidence" });
    await dialog.getByLabel(/choose files/i).setInputFiles(BILL);
    // The upload list reports the batch's status; poll it (expect retries) instead of sleeping.
    await expect(dialog.getByText("1 of 1 file uploaded and read")).toBeVisible({ timeout: 30_000 });
    await expect(dialog.getByText("1 of 1 done")).toBeVisible();
    await dialog.getByRole("button", { name: "View in Evidence" }).click();
  });

  await test.step("the bill is filed on the facility's natural gas line", async () => {
    await expect(page.getByText("1 document", { exact: true }).first()).toBeVisible();
    await page.getByRole("button", { name: LINE, exact: true }).click();
    await page.getByRole("button", { name: BILL_NAME, exact: true }).click();
  });

  await test.step("the quantity was read as the bill prints it, and Accept saves it", async () => {
    await expect(page.getByText("= 128.4 MMBtu, used in the calculation")).toBeVisible();
    await expect(page.getByRole("button", { name: "Select Activity quantity: 1,284 therm, to review" })).toBeVisible();
    await page.getByRole("button", { name: "Accept", exact: true }).click();
    await expect(page.getByRole("button", { name: "Select Activity quantity: 1,284 therm, accepted" })).toBeVisible();
  });

  await test.step("after a reload the quantity still reads accepted, by this reviewer", async () => {
    await page.reload();
    await expect(page.getByRole("button", { name: "Select Activity quantity: 1,284 therm, accepted" })).toBeVisible();
    await expect(page.getByText(/admin-.+@smoke\.test · accepted as read/)).toBeVisible();
  });

  await test.step("accept the rest of the bill's values: the calculation needs the fuel and the period", async () => {
    await page.getByRole("button", { name: /^Accept all/ }).click();
    await expect(page.getByRole("button", { name: /^Accept all/ })).toHaveCount(0);
    await expect(page.getByRole("button", { name: /^Select Fuel type: natural_gas, accepted/ })).toBeVisible();
  });

  await test.step("Verification results recomputes the natural gas line", async () => {
    await page.getByRole("button", { name: "Verification results" }).click();
    const lines = page.getByRole("region", { name: "Calculation by line" });
    await expect(page.getByText("1 recomputed line")).toBeVisible();
    // 128.4 MMBtu x 53.06 kg CO2/MMBtu (EPA 2025, natural gas) plus CH4 and N2O: about 6.8 tCO2e.
    await expect(lines).toContainText(/Recomputed\s*6\.8/);
  });
});
