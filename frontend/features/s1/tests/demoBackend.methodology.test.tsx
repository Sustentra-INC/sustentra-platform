/* @vitest-environment jsdom */
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../../../lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../../lib/api")>();
  // Imported when called, not while the mock is built: the demo backend itself imports lib/api.
  return { ...actual, api: vi.fn(async (path: string, options?: never) => (await import("../demo-backend")).demoApi(path, options)) };
});

import { demoApi } from "../demo-backend";
import { resetDemoMethodology } from "../demo-backend/methodology";
import { BackendMethodologyReview } from "../components/BackendMethodologyReview";
import { manufacturerEvidence } from "../fixtures/evidence/manufacturerEvidence";
import type { MethodologyRecord } from "../api/methodologyReview";

const BASE = "/engagements/ENG-CASCADE-2025/methodology-review";
const row = (label: string) => screen.getByText(label).closest("li") as HTMLElement;

type Wire = { fields: (MethodologyRecord & { field_id: string })[]; ai: { enabled: boolean } };
const get = () => demoApi<Wire>(BASE);

async function open(onOpenDocument = vi.fn()) {
  render(<BackendMethodologyReview engagementId="ENG-CASCADE-2025" onOpenDocument={onOpenDocument} />);
  await screen.findByText("Consolidation approach", {}, { timeout: 3000 });
  return onOpenDocument;
}

async function prefillViaUi() {
  fireEvent.click(screen.getByRole("button", { name: "Read the client's reports with Claude" }));
  fireEvent.click(screen.getByRole("button", { name: "Read the reports" }));
  await waitFor(() => expect(within(row("Consolidation approach")).getByText("Suggested by Claude")).toBeTruthy(), { timeout: 3000 });
}

beforeEach(() => resetDemoMethodology());
afterEach(cleanup);

describe("the demo backend's methodology review", () => {
  it("loads with Claude available and company statements already in", async () => {
    await open();
    expect(within(row("Reporting period")).getByText("Accepted")).toBeTruthy();
    expect(within(row("Consolidation approach")).getByText("Pending")).toBeTruthy();
    expect((await get()).ai.enabled).toBe(true);
    expect((await get()).fields.every((f) => !f.suggestion)).toBe(true);
  });

  it("prefill adds Claude suggestions with quotes and real documents, never pre-accepted, and twice adds no rows", async () => {
    const onOpenDocument = await open();
    await prefillViaUi();
    const ids = new Set(manufacturerEvidence.map((d) => d.documentId));
    const suggested = (await get()).fields.filter((f) => f.suggestion);
    expect(suggested.length).toBeGreaterThan(10);
    for (const f of suggested) {
      const s = f.suggestion!;
      expect(s.quote.length).toBeGreaterThanOrEqual(8);
      expect(ids.has(s.document_id)).toBe(true);
      expect(s.source_reference).toBeTruthy();
      expect(s.origin).toBe("ai");
      expect(f.decision?.status ?? "pending").toBe("pending");
      if (typeof s.value === "string" && ["Operational Control", "Equity Share", "Financial Control"].includes(s.value)) {
        expect(s.quote.toLowerCase()).toContain(s.value.toLowerCase());
      }
    }
    // Disagrees with the company's stated eGRID2023.
    expect(suggested.some((f) => JSON.stringify(f.suggestion!.value).includes("eGRID2021"))).toBe(true);

    fireEvent.click(within(row("Consolidation approach")).getByRole("button", { name: /^Cascade_|cascade_org_boundary_statement/ }));
    expect(onOpenDocument).toHaveBeenCalled();

    const before = (await get()).fields.length;
    await demoApi(`${BASE}/prefill`, { method: "POST", body: {} });
    expect((await get()).fields.length).toBe(before);
  });

  it("an accept sticks, with who and when, and revert restores pending with the suggestion", async () => {
    await open();
    await prefillViaUi();
    fireEvent.click(within(row("Consolidation approach")).getByRole("button", { name: "Accept: Consolidation approach" }));
    await waitFor(() => expect(within(row("Consolidation approach")).getByText("Accepted")).toBeTruthy(), { timeout: 3000 });

    const record = (await get()).fields.find((f) => f.field_id === "consolidation_approach")!;
    expect(record.decision).toMatchObject({ status: "accepted", value: "Operational Control", by: { name: "M. Osei" } });
    expect(record.decision!.at).toMatch(/^2026-11-12T/);

    await demoApi(`${BASE}/consolidation_approach/revert`, { method: "POST", body: {} });
    const reverted = (await get()).fields.find((f) => f.field_id === "consolidation_approach")!;
    expect(reverted.decision?.status).toBe("pending");
    expect(reverted.suggestion).not.toBeNull();
    expect(reverted.history.map((h) => h.action)).toEqual(["accept", "revert"]);
  });
  it("rows Claude has not looked at read Not checked yet, then Not detected after a prefill that found nothing for them", async () => {
    await open();
    expect(within(row("Indirect Biogenic")).getByText("Not checked yet")).toBeTruthy();
    expect(document.body.textContent).not.toContain("Not set");
    expect((await get()).fields.filter((f) => !(f as unknown as { shown: boolean }).shown).map((f) => (f as unknown as { field_id: string }).field_id).sort()).toEqual(["boundary:acquisitions", "boundary:leased_space", "gas:ch4", "gas:co2", "gas:hfcs", "gas:n2o", "gas:nf3", "gas:pfcs", "gas:sf6"]);
    await prefillViaUi();
    expect(within(row("Indirect Biogenic")).getByText("Not detected")).toBeTruthy();
    expect(within(row("Consolidation approach")).getByText("Suggested by Claude")).toBeTruthy();
  });

  it("a prefill after a reviewer's decision leaves the decision, and the row never reads Not detected", async () => {
    await open();
    await demoApi(`${BASE}/calculation:process/edit`, { method: "POST", body: { value: "Gas meter x 1.02 \u2013 Z\u00fcrich \u6392\u653e" } });
    cleanup();
    await open();
    await prefillViaUi();
    expect(within(row("Process-specific calculations")).getByText("Gas meter x 1.02 \u2013 Z\u00fcrich \u6392\u653e")).toBeTruthy();
    expect(within(row("Process-specific calculations")).queryByText("Not detected")).toBeNull();
  });

  it("refuses to reveal a row that is always shown, and an unknown one", async () => {
    await expect(demoApi(`${BASE}/reporting_period/reveal`, { method: "POST", body: {} })).rejects.toMatchObject({ status: 422 });
    await expect(demoApi(`${BASE}/nope/reveal`, { method: "POST", body: {} })).rejects.toMatchObject({ status: 404 });
  });
  it("an empty row has no Accept; after an Edit with a value it has a value", async () => {
    await open();
    expect(within(row("Indirect Biogenic")).queryByRole("button", { name: /^Accept:/ })).toBeNull();
    await demoApi(`${BASE}/category:biogenic:indirect/edit`, { method: "POST", body: { value: "No" } });
    const listed = (await get()).fields.find((f) => (f as unknown as { field_id: string }).field_id === "category:biogenic:indirect");
    expect((listed as unknown as { display_state: string }).display_state).toBe("has_value");
    cleanup();
    await open();
    expect(within(row("Indirect Biogenic")).queryByText("Not checked yet")).toBeNull();
  });
  it("the reporting period is two real dates with the end not before the start", async () => {
    const edit = (value: unknown) => demoApi(`${BASE}/reporting_period/edit`, { method: "POST", body: { value } });
    await expect(edit({ start: "2025-12-31", end: "2025-01-01" })).rejects.toMatchObject({ status: 422 });
    await expect(edit({ start: "2025-13-45", end: "2025-12-31" })).rejects.toMatchObject({ status: 422 });
    await expect(edit({ start: "2025-01-01" })).rejects.toMatchObject({ status: 422 });
    await expect(edit("January 1 to December 31, 2025")).rejects.toMatchObject({ status: 422 });
    await edit({ start: "2024-02-29", end: "2024-12-31" });
    await open();
    expect(within(row("Reporting period")).getByText("2024-02-29 to 2024-12-31")).toBeTruthy();
  });
  describe("acquisitions and leased space (only if the company has a value)", () => {
    const addItem = (label: string) =>
      fireEvent.change(screen.getByRole("combobox", { name: "Add an item" }), {
        target: { value: label === "Acquisitions and divestitures" ? "boundary:acquisitions" : "boundary:leased_space" },
      });

    it("are hidden on a fresh engagement and offered under Add an item", async () => {
      await open();
      expect(screen.queryByText("Acquisitions and divestitures", { selector: "span" })).toBeNull();
      const add = screen.getByRole("combobox", { name: "Add an item" });
      expect(within(add).getByRole("option", { name: "Acquisitions and divestitures" })).toBeTruthy();
      expect(within(add).getByRole("option", { name: "Treatment of leased space" })).toBeTruthy();
    });

    it("Add an item shows the row, it stays after a reload, and it reads Not detected once a run found nothing", async () => {
      await open();
      addItem("Acquisitions and divestitures");
      await waitFor(() => expect(within(row("Acquisitions and divestitures")).getByText("Not checked yet")).toBeTruthy());
      cleanup();
      await open(); // a reload
      expect(within(row("Acquisitions and divestitures")).getByText("Not checked yet")).toBeTruthy();
      await prefillViaUi();
      expect(within(row("Acquisitions and divestitures")).getByText("Not detected")).toBeTruthy();
    });

    it("a prefill that found a quote shows the leased-space row with Claude's suggestion; the silent one stays hidden", async () => {
      await open();
      await prefillViaUi();
      expect(within(row("Treatment of leased space")).getByText("Suggested by Claude")).toBeTruthy();
      expect(screen.queryByText("Acquisitions and divestitures", { selector: "span" })).toBeNull();
      expect(within(screen.getByRole("combobox", { name: "Add an item" })).queryByRole("option", { name: "Treatment of leased space" })).toBeNull();
    });

    it("saves an edit with non-ASCII text and refuses one over 2,000 characters", async () => {
      await open();
      const edit = (value: unknown) => demoApi(`${BASE}/boundary:acquisitions/edit`, { method: "POST", body: { value } });
      await expect(edit("x".repeat(2001))).rejects.toMatchObject({ status: 422 });
      await edit("Acquired M\u00fcller K\u00e4serei \u2013 Z\u00fcrich (\u745e\u58eb) in March 2025.");
      cleanup();
      await open();
      expect(within(row("Acquisitions and divestitures")).getByText("Acquired M\u00fcller K\u00e4serei \u2013 Z\u00fcrich (\u745e\u58eb) in March 2025.")).toBeTruthy();
    });
  });
  describe("GWP sets: the 500-year horizon and one row per extra set", () => {
    type WireField = { field_id: string; suggestion: { value: unknown } | null; decision: { value: unknown } | null; user_added: boolean };
    const gwpRows = async () => ((await get()).fields as unknown as WireField[]).filter((f) => f.field_id.startsWith("gwp:"));

    it("a prefill keeps the decided GWP field and adds the report's other set as its own row, once", async () => {
      await open();
      await prefillViaUi();
      const fixed = screen.getAllByText("GWP factors source").map((e) => e.closest("li")).find(Boolean) as HTMLElement; // the heading has the same words
      expect(within(fixed).getByText("Accepted")).toBeTruthy();
      expect(within(row("GWP set")).getByText("Suggested by Claude")).toBeTruthy();
      expect((await gwpRows()).map((r) => r.suggestion?.value)).toEqual([{ set: "AR6", horizon: "500-year" }]);
      fireEvent.click(screen.getByRole("button", { name: "Read the client's reports with Claude" }));
      fireEvent.click(screen.getByRole("button", { name: "Read the reports" }));
      await waitFor(() => expect(screen.getByRole("status").textContent).toMatch(/suggested/));
      expect(await gwpRows()).toHaveLength(1); // a second run adds no second copy
    });

    it("Add GWP set adds a blank row that takes the 500-year horizon and refuses an unknown one", async () => {
      await open();
      fireEvent.click(screen.getByRole("button", { name: "Add GWP set" }));
      await waitFor(() => expect(screen.getByText("GWP set")).toBeTruthy());
      const [added] = await gwpRows();
      expect(added.user_added).toBe(true);
      const edit = (value: unknown) => demoApi(`${BASE}/${encodeURIComponent(added.field_id)}/edit`, { method: "POST", body: { value } });
      await expect(edit({ set: "AR6", horizon: "50-year" })).rejects.toMatchObject({ status: 422 });
      await edit({ set: "AR6", horizon: "500-year" });
      expect((await gwpRows())[0].decision?.value).toEqual({ set: "AR6", horizon: "500-year" });
      await demoApi(`${BASE}/gwp/edit`, { method: "POST", body: { value: { set: "AR5", horizon: "500-year" } } });
    });
  });

  describe("gases covered (one row per gas, only if the company has a value)", () => {
    const GAS_LABELS = ["Gas: CO2", "Gas: CH4", "Gas: N2O", "Gas: HFCs", "Gas: PFCs", "Gas: SF6", "Gas: NF3"];

    it("are hidden on a fresh engagement and all seven are offered under Add an item", async () => {
      await open();
      for (const label of GAS_LABELS) expect(screen.queryByText(label, { selector: "span" })).toBeNull();
      const add = screen.getByRole("combobox", { name: "Add an item" });
      for (const label of GAS_LABELS) expect(within(add).getByRole("option", { name: label })).toBeTruthy();
    });

    it("Add an item shows a gas row with its own three choices, and it saves Not mentioned", async () => {
      await open();
      fireEvent.change(screen.getByRole("combobox", { name: "Add an item" }), { target: { value: "gas:pfcs" } });
      await waitFor(() => expect(within(row("Gas: PFCs")).getByText("Not checked yet")).toBeTruthy());
      fireEvent.click(within(row("Gas: PFCs")).getByRole("button", { name: "Edit: Gas: PFCs" }));
      const choices = within(screen.getByLabelText("Value: Gas: PFCs")).getAllByRole("option").map((o) => o.textContent);
      expect(choices).toEqual(["Choose", "Included", "Declared absent", "Not mentioned"]);
      fireEvent.change(screen.getByLabelText("Value: Gas: PFCs"), { target: { value: "Not mentioned" } });
      fireEvent.click(screen.getByRole("button", { name: "Save" }));
      await waitFor(() => expect(within(row("Gas: PFCs")).getByText("Not mentioned")).toBeTruthy());
    });

    it("a prefill shows only the gases it found, and the category values are refused for a gas", async () => {
      await open();
      await prefillViaUi();
      expect(within(row("Gas: CO2")).getByText("Suggested by Claude")).toBeTruthy();
      expect(within(row("Gas: NF3")).getByText("Suggested by Claude")).toBeTruthy();
      expect(screen.queryByText("Gas: CH4", { selector: "span" })).toBeNull();
      const edit = (id: string, value: unknown) => demoApi(`${BASE}/${id}/edit`, { method: "POST", body: { value } });
      await expect(edit("gas:co2", "Yes")).rejects.toMatchObject({ status: 422 });
      await expect(edit("gas:co2", "Not detected")).rejects.toMatchObject({ status: 422 });
      await expect(edit("category:scope1:mobile", "Included")).rejects.toMatchObject({ status: 422 });
    });
  });
});
