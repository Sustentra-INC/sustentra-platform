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
    expect((await get()).fields.filter((f) => !(f as unknown as { shown: boolean }).shown).map((f) => (f as unknown as { field_id: string }).field_id).sort()).toEqual(["boundary:acquisitions", "boundary:leased_space", "calculation:estimation", "calculation:source_records", "scope2:instruments"]);
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
  describe("estimation method for missing data (a list, only if the company has a value)", () => {
    const LABEL = "Estimation method for missing data";
    const EST = "calculation:estimation";
    const edit = (value: unknown) => demoApi(`${BASE}/${EST}/edit`, { method: "POST", body: { value } });

    it("is hidden on a fresh engagement and offered under Add an item", async () => {
      await open();
      expect(screen.queryByText(LABEL, { selector: "span" })).toBeNull();
      expect(within(screen.getByRole("combobox", { name: "Add an item" })).getByRole("option", { name: LABEL })).toBeTruthy();
    });

    it("a prefill shows the entries with a quote and a link each", async () => {
      const onOpenDocument = await open();
      await prefillViaUi();
      const entries = row(LABEL);
      expect(within(entries).getByText("Utility invoices: Average of the adjacent months; Fuel cards: Prior-year consumption")).toBeTruthy();
      expect(within(entries).getByText(/Where fuel card data has gaps/)).toBeTruthy();
      expect(within(entries).getAllByRole("button", { name: /cascade_org_boundary_statement/ })).toHaveLength(2);
      fireEvent.click(within(entries).getAllByRole("button", { name: /cascade_org_boundary_statement/ })[1]);
      expect(onOpenDocument).toHaveBeenCalled();
    });

    it("adds, edits and removes entries in the editor, with non-ASCII text, and can empty the list", async () => {
      await open();
      fireEvent.change(screen.getByRole("combobox", { name: "Add an item" }), { target: { value: EST } });
      await waitFor(() => expect(within(row(LABEL)).getByText("Not checked yet")).toBeTruthy());
      fireEvent.click(within(row(LABEL)).getByRole("button", { name: `Edit: ${LABEL}` }));
      fireEvent.click(screen.getByRole("button", { name: "Add entry" }));
      fireEvent.change(screen.getByLabelText(`Source type 1: ${LABEL}`), { target: { value: "Br\u00e4ndstoff \u71c3\u6599" } });
      fireEvent.change(screen.getByLabelText(`Method 1: ${LABEL}`), { target: { value: "Vorjahr \u00d7 1,02" } });
      fireEvent.click(screen.getByRole("button", { name: "Add entry" }));
      fireEvent.change(screen.getByLabelText(`Source type 2: ${LABEL}`), { target: { value: "Meter readings" } });
      fireEvent.click(screen.getByRole("button", { name: "Save" })); // the second entry has no method
      expect((await screen.findByRole("alert")).textContent).toContain("Give every entry a source type and a method");
      fireEvent.click(screen.getByRole("button", { name: `Remove entry 2: ${LABEL}` }));
      fireEvent.click(screen.getByRole("button", { name: "Save" }));
      await waitFor(() => expect(within(row(LABEL)).getByText("Br\u00e4ndstoff \u71c3\u6599: Vorjahr \u00d7 1,02")).toBeTruthy());
      fireEvent.click(within(row(LABEL)).getByRole("button", { name: `Edit: ${LABEL}` }));
      fireEvent.click(screen.getByRole("button", { name: `Remove entry 1: ${LABEL}` }));
      fireEvent.click(screen.getByRole("button", { name: "Save" }));
      await waitFor(() => expect(within(row(LABEL)).getByText("No entries")).toBeTruthy());
    });

    it("refuses a repeated source type, a blank part and an eleventh entry", async () => {
      await open();
      await expect(edit([{ source_type: "Fuel", method: "a" }, { source_type: " fuel ", method: "b" }])).rejects.toMatchObject({ status: 422 });
      await expect(edit([{ source_type: "Fuel", method: "" }])).rejects.toMatchObject({ status: 422 });
      await expect(edit(Array.from({ length: 11 }, (_, i) => ({ source_type: `S${i}`, method: "a" })))).rejects.toMatchObject({ status: 422 });
      await expect(edit("average")).rejects.toMatchObject({ status: 422 });
    });
  });
  describe("multi-select rows: Scope 2 instrument types and source records", () => {
    const INSTR = "Scope 2 instrument types (market-based)";
    const RECORDS = "Source records";
    const edit = (id: string, value: unknown) => demoApi(`${BASE}/${encodeURIComponent(id)}/edit`, { method: "POST", body: { value } });

    it("instrument types stay hidden until a market-based category is Yes; source records until a value", async () => {
      await open();
      expect(screen.queryByText(INSTR, { selector: "span" })).toBeNull();
      expect(screen.queryByText(RECORDS, { selector: "span" })).toBeNull();
      await edit("category:market:steam", "No");
      cleanup();
      await open();
      expect(screen.queryByText(INSTR, { selector: "span" })).toBeNull(); // a No is not a market-based number
      await edit("category:market:steam", "Yes");
      cleanup();
      await open();
      expect(within(row(INSTR)).getByText("Not checked yet")).toBeTruthy();
      expect(screen.queryByText(RECORDS, { selector: "span" })).toBeNull();
    });

    it("a prefill shows both rows with a quote and a link for each option", async () => {
      await open();
      await prefillViaUi();
      expect(within(row(INSTR)).getByText("PPA or VPPA (the Tualatin Plant PPA); Residual mix")).toBeTruthy();
      expect(within(row(INSTR)).getByText(/Remaining market-based electricity uses the residual mix factor/)).toBeTruthy();
      expect(within(row(RECORDS)).getByText("Utility invoices; Fuel cards (fuel card statements)")).toBeTruthy();
      expect(within(row(RECORDS)).getAllByRole("button", { name: /cascade_org_boundary_statement/ })).toHaveLength(2);
    });

    it("selects and deselects options with the company's wording, None stands alone, and free additions work", async () => {
      await open();
      fireEvent.change(screen.getByRole("combobox", { name: "Add an item" }), { target: { value: "calculation:source_records" } });
      await waitFor(() => expect(within(row(RECORDS)).getByText("Not checked yet")).toBeTruthy());
      fireEvent.click(within(row(RECORDS)).getByRole("button", { name: `Edit: ${RECORDS}` }));
      fireEvent.click(screen.getByRole("checkbox", { name: `Meter readings: ${RECORDS}` }));
      fireEvent.change(screen.getByLabelText(`Company's wording for Meter readings: ${RECORDS}`), { target: { value: "Z\u00e4hlerst\u00e4nde \u8868\u8bfb\u6570" } });
      fireEvent.change(screen.getByLabelText(`Add another option: ${RECORDS}`), { target: { value: "Lieferscheine \u7eb8\u8d28" } });
      fireEvent.click(screen.getByRole("button", { name: "Add option" }));
      expect(screen.getByRole("checkbox", { name: `Lieferscheine \u7eb8\u8d28: ${RECORDS}` })).toBeTruthy();
      fireEvent.click(screen.getByRole("button", { name: "Save" }));
      await waitFor(() => expect(within(row(RECORDS)).getByText("Meter readings (Z\u00e4hlerst\u00e4nde \u8868\u8bfb\u6570); Lieferscheine \u7eb8\u8d28")).toBeTruthy());
      fireEvent.click(within(row(RECORDS)).getByRole("button", { name: `Edit: ${RECORDS}` }));
      fireEvent.click(screen.getByRole("checkbox", { name: `Meter readings: ${RECORDS}` })); // deselect
      fireEvent.click(screen.getByRole("button", { name: "Save" }));
      await waitFor(() => expect(within(row(RECORDS)).getByText("Lieferscheine \u7eb8\u8d28")).toBeTruthy());
    });

    it("None clears the other instrument types and choosing another clears None", async () => {
      await open();
      await edit("category:market:electricity", "Yes");
      cleanup();
      await open();
      fireEvent.click(within(row(INSTR)).getByRole("button", { name: `Edit: ${INSTR}` }));
      fireEvent.click(screen.getByRole("checkbox", { name: `PPA or VPPA: ${INSTR}` }));
      fireEvent.click(screen.getByRole("checkbox", { name: `None: ${INSTR}` }));
      expect((screen.getByRole("checkbox", { name: `PPA or VPPA: ${INSTR}` }) as HTMLInputElement).checked).toBe(false);
      fireEvent.click(screen.getByRole("checkbox", { name: `Residual mix: ${INSTR}` }));
      expect((screen.getByRole("checkbox", { name: `None: ${INSTR}` }) as HTMLInputElement).checked).toBe(false);
      expect(screen.queryByLabelText(`Add another option: ${INSTR}`)).toBeNull(); // no free additions here
    });

    it("refuses an option outside the list, a repeat, None with others, and an eleventh free option", async () => {
      await open();
      await expect(edit("scope2:instruments", [{ option: "Carbon offsets", wording: "" }])).rejects.toMatchObject({ status: 422 });
      await expect(edit("scope2:instruments", [{ option: "PPA or VPPA", wording: "" }, { option: " ppa or vppa", wording: "" }])).rejects.toMatchObject({ status: 422 });
      await expect(edit("scope2:instruments", [{ option: "None", wording: "" }, { option: "PPA or VPPA", wording: "" }])).rejects.toMatchObject({ status: 422 });
      await expect(edit("calculation:source_records", Array.from({ length: 11 }, (_, i) => ({ option: `Other ${i}`, wording: "" })))).rejects.toMatchObject({ status: 422 });
      await edit("calculation:source_records", [{ option: "utility invoices", wording: "" }]);
    });
  });
});
