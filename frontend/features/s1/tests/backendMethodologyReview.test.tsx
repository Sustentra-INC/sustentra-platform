/* @vitest-environment jsdom */
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mock = vi.hoisted(() => ({ data: null as unknown, fail: {} as Record<string, unknown> }));
vi.mock("../../../lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../../../lib/api")>()),
  api: vi.fn((path: string, options?: { method?: string }) => {
    const key = `${options?.method ?? "GET"} ${path}`;
    if (key in mock.fail) return Promise.reject(mock.fail[key]);
    if (path.endsWith("/prefill")) return Promise.resolve(mock.fail.prefillResult);
    return Promise.resolve(options?.method ? {} : mock.data);
  }),
}));

import { api, ApiError } from "../../../lib/api";
import type { MethodologyReviewData } from "../api/methodologyReview";
import { BackendMethodologyReview, aiStatusWords, statusWord } from "../components/BackendMethodologyReview";

const BASE = "/engagements/e1/methodology-review";
const by = { name: "M. Osei", login: "mosei" };

function fixture(ai: Partial<MethodologyReviewData["ai"]> = {}): Record<string, unknown> {
  return {
    ai: { enabled: true, provider: "anthropic", model: "m", month_spend_usd: 1, cap_usd: 50, reason_if_off: null, ...ai },
    catalog: [
      { field_id: "consolidation_approach", group: "boundary", label: "Consolidation approach", kind: "enum", allowed: ["Equity Share", "Financial Control", "Operational Control"] },
      { field_id: "reporting_period", group: "boundary", label: "Reporting period", kind: "text" },
      { field_id: "gwp", group: "methods", label: "GWP", kind: "gwp", allowed: { set: ["AR4", "AR5", "AR6"], horizon: ["100-year", "20-year"] } },
      { field_id: "factor:scope1:r1", group: "factors", label: "Scope 1 factor row 1", kind: "factor" },
      { field_id: "weird", group: "boundary", label: "Brand new field", kind: "hologram" },
    ],
    fields: [
      {
        field_id: "consolidation_approach",
        suggestion: { value: "Operational Control", quote: "We use the operational control approach.", document_id: "d1", file_name: "GHG report.pdf", source_reference: "page 4", origin: "ai", model: "m", request_id: "r", suggested_at: "2026-11-01T10:00:00Z" },
        decision: null,
        history: [],
      },
      {
        field_id: "reporting_period",
        suggestion: null,
        decision: { status: "edited", value: "FY2025", by, at: "2026-11-02T10:00:00Z" },
        history: [{ at: "2026-11-02T10:00:00Z", by, action: "edit" }],
      },
      { field_id: "gwp", suggestion: null, decision: null, history: [] },
      { field_id: "factor:scope1:r1", suggestion: null, decision: null, history: [{ at: "2026-11-03T10:00:00Z", by, action: "add_row" }] },
      { field_id: "weird", suggestion: null, decision: { status: "frobnicated", value: "x", by, at: "2026-11-02T10:00:00Z" }, history: [] },
    ],
  };
}

const calls = () => vi.mocked(api).mock.calls.filter(([, o]) => o && (o as { method?: string }).method);
const row = (label: string) => screen.getByText(label).closest("li") as HTMLElement;

async function open(onOpenDocument = vi.fn(), data: unknown = fixture()) {
  mock.data = data;
  const onActivity = vi.fn();
  render(<BackendMethodologyReview engagementId="e1" onOpenDocument={onOpenDocument} onActivity={onActivity} />);
  await screen.findByText("Consolidation approach");
  return { onOpenDocument, onActivity };
}

beforeEach(() => {
  vi.mocked(api).mockClear();
  mock.fail = {};
});

describe("Methodology review on real data", () => {
  it("renders each field with value, suggestion chip, quote, status word and who decided", async () => {
    const { onOpenDocument, onActivity } = await open();
    const approach = row("Consolidation approach");
    expect(within(approach).getByText("Suggested by Claude")).toBeTruthy();
    expect(within(approach).getByText("We use the operational control approach.")).toBeTruthy();
    expect(within(approach).getByText("Pending")).toBeTruthy();
    fireEvent.click(within(approach).getByRole("button", { name: "GHG report.pdf, page 4" }));
    expect(onOpenDocument).toHaveBeenCalledWith("d1");

    const period = row("Reporting period");
    expect(within(period).getByText("FY2025")).toBeTruthy();
    expect(within(period).getByText("Edited")).toBeTruthy();
    expect(within(period).getByText(/M\. Osei/)).toBeTruthy();
    expect(onActivity).toHaveBeenCalledWith([expect.objectContaining({ who: "M. Osei", what: expect.stringContaining("Reporting period") }), expect.objectContaining({ what: expect.stringContaining("add row") })]);
  });

  it("accepts, rejects with a reason, edits with an allowed value and reverts, sending no actor", async () => {
    await open();
    const approach = row("Consolidation approach");
    fireEvent.click(within(approach).getByRole("button", { name: "Accept: Consolidation approach" }));
    await waitFor(() => expect(calls()).toContainEqual([`${BASE}/consolidation_approach/accept`, expect.objectContaining({ method: "POST", body: {} })]));

    fireEvent.click(within(row("Consolidation approach")).getByRole("button", { name: "Reject: Consolidation approach" }));
    const reject = screen.getByRole("button", { name: "Reject" });
    expect((reject as HTMLButtonElement).disabled).toBe(true);
    fireEvent.change(screen.getByLabelText("Reason: Consolidation approach"), { target: { value: "Report says equity share" } });
    fireEvent.click(reject);
    await waitFor(() => expect(calls()).toContainEqual([`${BASE}/consolidation_approach/reject`, expect.objectContaining({ body: { reason: "Report says equity share" } })]));

    fireEvent.click(within(row("Consolidation approach")).getByRole("button", { name: "Edit: Consolidation approach" }));
    const select = screen.getByLabelText("Value: Consolidation approach") as HTMLSelectElement;
    expect(Array.from(select.options).map((o) => o.value)).toEqual(["", "Equity Share", "Financial Control", "Operational Control"]);
    fireEvent.change(select, { target: { value: "Financial Control" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(calls()).toContainEqual([`${BASE}/consolidation_approach/edit`, expect.objectContaining({ body: { value: "Financial Control" } })]));

    fireEvent.click(within(row("Reporting period")).getByRole("button", { name: "Revert: Reporting period" }));
    await waitFor(() => expect(calls()).toContainEqual([`${BASE}/reporting_period/revert`, expect.objectContaining({ method: "POST" })]));
  });

  it("edits a multi-part value from the catalog's allowed values per part", async () => {
    await open();
    fireEvent.click(within(row("GWP")).getByRole("button", { name: "Edit: GWP" }));
    // No stated value to start from: the parts come from the catalog.
    fireEvent.change(screen.getByLabelText("GWP: Set"), { target: { value: "AR6" } });
    fireEvent.change(screen.getByLabelText("GWP: Horizon"), { target: { value: "100-year" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(calls()).toContainEqual([`${BASE}/gwp/edit`, expect.objectContaining({ body: { value: { set: "AR6", horizon: "100-year" } } })]));
  });

  it("adds a factor row, and removes only user-added rows", async () => {
    await open();
    fireEvent.click(screen.getByRole("button", { name: "Add Scope 1 factor row" }));
    await waitFor(() => expect(calls()).toContainEqual([`${BASE}/rows`, expect.objectContaining({ body: { group: "factor:scope1" } })]));
    expect(within(row("Consolidation approach")).queryByRole("button", { name: /Remove row/ })).toBeNull();
    fireEvent.click(within(row("Scope 1 factor row 1")).getByRole("button", { name: /Remove row/ }));
    await waitFor(() => expect(calls()).toContainEqual([`${BASE}/factor%3Ascope1%3Ar1`, expect.objectContaining({ method: "DELETE" })]));
  });

  it("shows a refusal's sentence", async () => {
    await open();
    mock.fail[`POST ${BASE}/consolidation_approach/accept`] = new ApiError(409, "The engagement is archived.", null, null);
    fireEvent.click(within(row("Consolidation approach")).getByRole("button", { name: "Accept: Consolidation approach" }));
    expect((await screen.findByRole("alert")).textContent).toBe("The engagement is archived.");
  });

  it("asks before reading the reports, then shows what was suggested, dropped, read and spent", async () => {
    await open();
    mock.fail.prefillResult = {
      suggested: 4,
      dropped: { quote_not_found: 2, some_new_reason: 1 },
      kept_reviewer_decision: 1,
      documents_read: [{ document_id: "d1", file_name: "GHG report.pdf", truncated: true }],
      cost_usd: 0.0312,
      model: "m",
    };
    fireEvent.click(screen.getByRole("button", { name: "Read the client's reports with Claude" }));
    expect(calls().some(([p]) => String(p).endsWith("/prefill"))).toBe(false);
    expect(screen.getByRole("alertdialog").textContent).toMatch(/Suggestions need your review/);
    fireEvent.click(screen.getByRole("button", { name: "Read the reports" }));
    const summary = await screen.findByRole("status");
    await waitFor(() => expect(summary.textContent).toMatch(/4 suggested, 3 dropped/));
    expect(summary.textContent).toContain("2: the quote was not on the document");
    expect(summary.textContent).toContain("1: some new reason");
    expect(summary.textContent).toContain("GHG report.pdf (only the start was read)");
    expect(summary.textContent).toContain("Cost $0.03");
    expect(calls()).toContainEqual([`${BASE}/prefill`, expect.objectContaining({ method: "POST" })]);
  });

  it("shows Claude's refusal sentence from the prefill", async () => {
    await open();
    mock.fail[`POST ${BASE}/prefill`] = new ApiError(409, "Upload the company's GHG inventory report first.", null, null);
    fireEvent.click(screen.getByRole("button", { name: "Read the client's reports with Claude" }));
    fireEvent.click(screen.getByRole("button", { name: "Read the reports" }));
    expect((await screen.findByRole("alert")).textContent).toBe("Upload the company's GHG inventory report first.");
  });

  it.each([
    [{ enabled: false, reason_if_off: "switch_off" }, "Off: an administrator turns it on"],
    [{ enabled: true, month_spend_usd: 50, cap_usd: 50 }, "Monthly limit reached"],
    [{ enabled: false, reason_if_off: "no_documents" }, "No report documents yet"],
    [{ enabled: false, reason_if_off: "not_built" }, "AI suggestions are not available"],
  ])("states the AI status in words and disables the button: %j", async (ai, words) => {
    await open(vi.fn(), fixture(ai));
    expect(screen.getByText(words)).toBeTruthy();
    expect((screen.getByRole("button", { name: "Read the client's reports with Claude" }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("copes with a status or field kind it does not know", async () => {
    await open();
    expect(statusWord("frobnicated")).toBe("Status unknown");
    expect(aiStatusWords({ enabled: false, reason_if_off: "zzz" }, null)).toBe("AI suggestions are not available");
    const weird = row("Brand new field");
    expect(within(weird).getByText("Status unknown")).toBeTruthy();
    // The row still offers the actions; the server decides what is allowed.
    expect(within(weird).getByRole("button", { name: "Edit: Brand new field" })).toBeTruthy();
  });
});
