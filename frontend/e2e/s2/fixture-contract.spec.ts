import { expect, test } from "@playwright/test";

async function dismissChanges(page: import("@playwright/test").Page) {
  const dialog = page.getByRole("dialog", { name: "Since you were last here" });
  if (await dialog.isVisible()) {
    await dialog.getByRole("button", { name: "Close" }).click();
  }
}

test.describe("S2 fixture-contract E2E", () => {
  test("DoD Meridian fixture expectations render the required exact review states", async ({ page }) => {
    await page.goto("/", { waitUntil: "networkidle" });
    await dismissChanges(page);

    const richmondRow = page.getByRole("row", { name: /Richmond Refinery, scope 1, 22400 tonnes/i });
    await expect(richmondRow).toBeVisible();
    await expect(richmondRow).toContainText("22,400");
    await expect(richmondRow).toContainText("13 examined · 2 findings · 9 with client");

    const bakersfieldProcessRow = page.getByRole("row", { name: /Bakersfield Plant, scope 1, 3240 tonnes/i });
    await expect(bakersfieldProcessRow).toContainText("Process emissions");
    await expect(bakersfieldProcessRow).toContainText("nothing started");

    await richmondRow.click();
    const noEvidenceRow = page.getByRole("row", { name: /Assigned primary identifier.*no evidence held/i });
    await expect(noEvidenceRow).toContainText("S1-STC-100");
    await expect(noEvidenceRow.getByRole("button", { name: "Request" })).toBeVisible();
    await expect(noEvidenceRow.getByRole("button", { name: "Unobtainable" })).toBeVisible();
    await expect(noEvidenceRow.getByRole("button", { name: "By procedure" })).toBeVisible();
    await noEvidenceRow.click();
    await expect(page.getByRole("heading", { name: /Assigned primary identifier/ })).toHaveCount(0);

    await page.getByRole("row", { name: /Higher heating value.*partially held/i }).click();
    const coverageGrid = page.getByRole("grid", { name: /6 of 9 held/ });
    await expect(coverageGrid.locator('[role="row"]')).toHaveCount(3);
    await expect(coverageGrid).toContainText("cut-off");

    await page.getByRole("button", { name: /Richmond Refinery · Stationary combustion/ }).click();
    await page.getByRole("row", { name: /Normalizes.*examination invalidated/i }).click();
    await expect(page.getByText("client restated 12 Aug")).toBeVisible();
  });

  test("normal evidence-held Examine mode renders evidence, record, notes, findings, and rail", async ({ page }) => {
    await page.goto("/", { waitUntil: "networkidle" });
    await dismissChanges(page);

    await page.getByRole("row", { name: /Richmond Refinery, scope 1, 22400 tonnes/i }).click();
    await page.getByRole("row", { name: /Actual fuel burned.*evidence held/i }).click();

    await expect(page.getByRole("heading", { name: /Actual fuel burned/ })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Evidence" })).toBeVisible();
    await expect(page.getByText("Governing source")).toBeVisible();
    await expect(page.getByText("Other source")).toBeVisible();
    await expect(page.getByText("Trace", { exact: true })).toBeVisible();
    await expect(page.getByText(/retained supporting workpaper/)).toBeVisible();
    await expect(page.getByRole("button", { name: "Open original" })).toBeVisible();
    await expect(page.getByText("limited assurance record")).toBeVisible();
    await expect(page.getByText(/Claire Qiu/)).toBeVisible();
    await expect(page.getByText(/Aug 8, 2026/)).toBeVisible();
    await expect(page.getByRole("button", { name: "A - no exceptions" })).toBeVisible();
    await expect(page.getByRole("textbox", { name: "Examination note" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Notes on this item" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Findings on this item" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "This item", exact: true })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Who" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Blocked by this" })).toBeVisible();
    await expect(page.getByRole("status", { name: /evidence held/ })).toBeVisible();

    await page.getByRole("button", { name: "A - no exceptions" }).click();
    await page.getByRole("button", { name: "Record & next" }).click();
    await expect(page.getByText(/Record a technique before concluding/)).toBeVisible();
    await expect(page.getByRole("heading", { name: /Actual fuel burned/ })).toBeVisible();
  });

  test("partial Examine mode preserves the record shell and adds coverage movement", async ({ page }) => {
    await page.goto("/", { waitUntil: "networkidle" });
    await dismissChanges(page);

    await page.getByRole("row", { name: /Richmond Refinery, scope 1, 22400 tonnes/i }).click();
    await page.getByRole("row", { name: /Higher heating value.*partially held/i }).click();

    await expect(page.getByRole("heading", { name: /Higher heating value/ })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Sufficiency" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Notes on this item" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Findings on this item" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "This item", exact: true })).toBeVisible();

    const coverageGrid = page.getByRole("grid", { name: /6 of 9 held/ });
    await coverageGrid.focus();
    const initialCell = await coverageGrid.getAttribute("aria-activedescendant");
    await page.keyboard.press("ArrowRight");
    await expect(coverageGrid).not.toHaveAttribute("aria-activedescendant", initialCell ?? "");
  });

  test("no-evidence rows stay inline and surface the engagement dependency state", async ({ page }) => {
    await page.goto("/", { waitUntil: "networkidle" });
    await dismissChanges(page);

    await page.getByRole("row", { name: /Richmond Refinery, scope 1, 22400 tonnes/i }).click();
    const noEvidenceRow = page.getByRole("row", { name: /Assigned primary identifier.*no evidence held/i });
    await noEvidenceRow.click();

    await expect(page.getByRole("heading", { name: /Richmond Refinery · Scope 1 · Stationary combustion/ })).toBeVisible();
    await expect(page.getByRole("heading", { name: /Assigned primary identifier/ })).toHaveCount(0);
    await noEvidenceRow.getByRole("button", { name: "Request" }).click();
    await expect(page.getByRole("status", { name: /Fixture mode: recording is not durable/ })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Request Builder" })).toBeVisible();
    await expect(page.getByRole("heading", { name: /Assigned primary identifier/ })).toHaveCount(0);
  });

  test("Wave 2 journey keeps partial, no-evidence, and evidence-held flows distinct", async ({ page }) => {
    await page.goto("/", { waitUntil: "networkidle" });
    await dismissChanges(page);

    await page.getByRole("row", { name: /Richmond Refinery, scope 1, 22400 tonnes/i }).click();
    await expect(page.getByRole("heading", { name: /Richmond Refinery · Scope 1 · Stationary combustion/ })).toBeVisible();
    await expect(page.getByTestId("s2-requirement-group-activity")).toBeVisible();
    await expect(page.getByTestId("s2-requirement-group-factors")).toBeVisible();
    await expect(page.getByTestId("s2-requirement-group-boundary")).toBeVisible();
    await expect(page.getByTestId("s2-requirement-group-calculation")).toBeVisible();

    await page.getByRole("row", { name: /Higher heating value.*partially held/i }).click();
    await expect(page.getByRole("heading", { name: /Higher heating value/ })).toBeVisible();
    await expect(page.getByRole("grid", { name: /6 of 9 held/ })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Sufficiency" })).toBeVisible();
    await expect(page.locator(".s2-technique").first()).toBeFocused();
    await page.keyboard.press("1");
    await page.keyboard.press("Enter");
    await expect(page.getByRole("heading", { name: /Emission factors expressed/ })).toBeVisible();
    await expect(page.locator(".s2-technique").first()).toBeFocused();

    await page.getByRole("button", { name: /Richmond Refinery · Stationary combustion/ }).click();
    await expect(page.getByRole("heading", { name: /Richmond Refinery · Scope 1 · Stationary combustion/ })).toBeVisible();

    const noEvidenceRow = page.getByRole("row", { name: /Assigned primary identifier.*no evidence held/i });
    await noEvidenceRow.click();
    await expect(page.getByRole("heading", { name: /Richmond Refinery · Scope 1 · Stationary combustion/ })).toBeVisible();
    await expect(noEvidenceRow.getByRole("button", { name: "Request" })).toBeVisible();
    await expect(noEvidenceRow.getByRole("button", { name: "Unobtainable" })).toBeVisible();
    await expect(noEvidenceRow.getByRole("button", { name: "By procedure" })).toBeVisible();

    await page.getByRole("row", { name: /Normalizes.*examination invalidated/i }).click();
    await expect(page.getByRole("heading", { name: /Normalizes/ })).toBeVisible();
    await expect(page.getByText("examination invalidated")).toBeVisible();
  });

  test("Wave 3 outbound request loop rejects internal IDs and keeps request states distinct", async ({ page }) => {
    await page.goto("/", { waitUntil: "networkidle" });
    await dismissChanges(page);

    await page.getByRole("row", { name: /Richmond Refinery, scope 1, 22400 tonnes/i }).click();
    const noEvidenceRow = page.getByRole("row", { name: /Assigned primary identifier.*no evidence held/i });
    await noEvidenceRow.getByRole("button", { name: "Request" }).click();

    await expect(page.getByRole("heading", { name: "Request Builder" })).toBeVisible();
    await expect(page.getByText("S1-STC-100")).toHaveCount(2);
    const askWording = page.getByRole("textbox", { name: /Ask wording/ }).first();
    await askWording.fill("Please provide S1-STC-100 support.");
    await expect(page.getByText(/Client-facing wording cannot include Field_IDs/)).toBeVisible();
    await expect(page.getByRole("button", { name: "Send" })).toBeDisabled();

    await askWording.fill("Please provide the source list for the selected stationary combustion support.");
    await page.getByRole("button", { name: "Preview message" }).click();
    await expect(page.getByRole("dialog", { name: "Preview message" })).toBeVisible();
    await page.getByRole("button", { name: "Close preview" }).click();
    await page.getByRole("button", { name: "Save draft" }).click();
    await expect(page.getByText("Working")).toBeVisible();

    await page.getByRole("button", { name: "Open requests" }).click();
    await expect(page.getByRole("heading", { name: "Open Requests" })).toBeVisible();
    await expect(page.getByText("drafted").first()).toBeVisible();
    await expect(page.getByText("sent").first()).toBeVisible();
    await expect(page.getByText("partially answered").first()).toBeVisible();
    await expect(page.getByText("answered").first()).toBeVisible();
    await expect(page.getByText("superseded").first()).toBeVisible();
    await expect(page.getByText("withdrawn").first()).toBeVisible();
    await expect(page.getByText(/days overdue/).first()).toBeVisible();

    const draftedRow = page.getByRole("row", { name: /REQ-003, drafted/i });
    await draftedRow.getByRole("button", { name: "Simulate failed send" }).click();
    await expect(page.getByRole("row", { name: /REQ-003, drafted/i })).toBeVisible();
  });

  test("Wave 3 findings loop groups, dedupes, and keeps withdrawn rows visible", async ({ page }) => {
    await page.goto("/", { waitUntil: "networkidle" });
    await dismissChanges(page);

    await page.getByRole("row", { name: /Richmond Refinery, scope 1, 22400 tonnes/i }).click();
    await page.getByRole("row", { name: /Actual fuel burned.*evidence held/i }).click();
    await page.getByRole("button", { name: "Raise a finding" }).nth(1).click();

    await expect(page.getByRole("heading", { name: "Findings" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Misstatements" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Nonconformities" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Clarification requests" })).toBeVisible();
    await expect(page.getByRole("row", { name: /Reported annual quantity exceeds.*magnitude 185 tonnes/i })).toBeVisible();
    await expect(page.getByRole("row", { name: /AR4 global warming potentials applied/i }).getByText("n/a")).toBeVisible();
    await expect(page.getByText(/Data not retained for the remaining months/)).toBeVisible();
    await expect(page.getByText("Clarify support for selected requirement")).toHaveCount(1);

    const findingRow = page.getByRole("row", { name: /Annual quantity extrapolated/i });
    await findingRow.getByRole("checkbox").check();
    await page.getByRole("button", { name: "Put selected to client" }).click();
    await expect(page.getByRole("row", { name: /Annual quantity extrapolated.*put to client/i })).toBeVisible();
    await findingRow.getByRole("button", { name: "Withdraw" }).click();
    await expect(page.getByRole("row", { name: /Annual quantity extrapolated.*withdrawn/i })).toBeVisible();
    await expect(page.getByRole("row", { name: /Annual quantity extrapolated.*withdrawn/i }).getByRole("button", { name: "Reconsider" })).toBeVisible();
  });

  test("Wave 4 documents filter by line and preserve Satisfies semantics", async ({ page }) => {
    await page.goto("/", { waitUntil: "networkidle" });
    await dismissChanges(page);

    await page.getByRole("button", { name: "Documents" }).click();
    await expect(page.getByRole("heading", { name: "Documents" })).toBeVisible();
    await expect(page.getByText("the reported inventory")).toBeVisible();
    await expect(page.getByText("the methodology profile")).toBeVisible();
    await expect(page.getByRole("row", { name: /Refrigerant service log/i }).getByText("needs triage")).toBeVisible();
    await page.getByRole("row", { name: /Carson gas invoices/i }).click();
    await expect(page.getByText(/Absent: remaining requested months/)).toBeVisible();

    await page.getByLabel("Line").selectOption({ label: "Richmond Refinery · Stationary combustion" });
    await expect(page.getByRole("row", { name: /Fuel analysis certificate.*satisfies 6/i })).toBeVisible();
    await page.getByRole("row", { name: /Fuel analysis certificate/i }).click();
    await expect(page.getByRole("region", { name: "Selected document" })).toContainText("Satisfies: S1-STC-020, S1-STC-030");
    await expect(page.getByRole("button", { name: /Upload on client behalf unavailable/ })).toBeDisabled();

    await page.getByLabel("Line").selectOption("all");
    await page.getByLabel("Request").selectOption("REQ-002");
    await expect(page.getByRole("row", { name: /Fuel analysis certificate/i })).toBeVisible();
  });

  test("Wave 4 change slide-over auto-opens, follows an item, restores focus, and marks seen", async ({ page }) => {
    await page.goto("/", { waitUntil: "networkidle" });

    const dialog = page.getByRole("dialog", { name: "Since you were last here" });
    await expect(dialog).toBeVisible();
    await expect(dialog.locator("details")).toHaveCount(4);
    await dialog.getByRole("link", { name: "Open document" }).click();
    await expect(page).toHaveURL(/#documents$/);
    await dialog.getByRole("button", { name: "Close" }).click();
    await expect(page.getByRole("button", { name: /changes since you were last here/ })).toBeFocused();

    await page.getByRole("button", { name: /changes since you were last here/ }).click();
    await expect(dialog).toBeVisible();
    await dialog.getByRole("button", { name: "Mark all seen" }).click();
    await expect(dialog).toHaveCount(0);
    await page.getByRole("button", { name: /0 changes since you were last here/ }).click();
    await expect(page.getByRole("heading", { name: "Nothing changed" })).toBeVisible();
  });

  test("Wave 4 analytical procedures and coverage checks keep first-year and no-pass framing", async ({ page }) => {
    await page.goto("/", { waitUntil: "networkidle" });
    await dismissChanges(page);

    await page.getByRole("button", { name: "Analytical procedures" }).click();
    await expect(page.getByRole("heading", { name: "Analytical Procedures" })).toBeVisible();
    await expect(page.getByLabel("Analytical summary").locator("> div")).toHaveCount(4);
    await expect(page.getByRole("row", { name: /Scope 1 total against facility activity.*Expected/i })).toBeVisible();
    await expect(page.getByRole("row", { name: /Mobile combustion against fleet count/i }).getByText("shape, not quantity")).toBeVisible();
    await expect(page.getByRole("row", { name: /Small source threshold screen.*below threshold/i })).toBeVisible();
    await expect(page.getByRole("button", { name: "Year-on-year procedures unavailable" })).toBeDisabled();
    await expect(page.getByText(/passed/i)).toHaveCount(0);

    await page.getByRole("button", { name: "Check Coverage" }).click();
    await expect(page.getByRole("heading", { name: "Check Coverage" })).toBeVisible();
    await expect(page.getByLabel("Coverage summary").locator("> div")).toHaveCount(4);
    await expect(page.getByText("Rules rendered")).toBeVisible();
    await expect(page.getByText("16")).toBeVisible();
    await expect(page.getByText("source shape unavailable").first()).toBeVisible();
    await page.getByRole("button", { name: "Export for the file" }).click();

    await page.getByRole("button", { name: "Live mode" }).click();
    await expect(page.getByText("89")).toBeVisible();
    await expect(page.getByText("60")).toBeVisible();
    await expect(page.getByText("Duplicate platform findings")).toBeVisible();
    await expect(page.getByText("0").first()).toBeVisible();
    await page.getByRole("button", { name: "Live mode" }).click();
    await expect(page.getByText("Duplicate platform findings")).toBeVisible();
    await expect(page.getByText(/passed/i)).toHaveCount(0);
  });
});
