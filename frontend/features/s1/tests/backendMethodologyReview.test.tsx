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
import { BackendMethodologyReview, aiStatusWords, dropReasonWords, statusWord } from "../components/BackendMethodologyReview";

const BASE = "/engagements/e1/methodology-review";
const by = { name: "M. Osei", login: "mosei" };

/** The API's GET answer (docs/api_contract.md), field ids and all. */
function fixture(ai: Record<string, unknown> = {}): Record<string, unknown> {
  const def = { group_label: "x", user_added: false };
  return {
    ai: { enabled: true, reason_code: null, reason: null, ...ai },
    groups: [
      { group: "boundary", label: "Organizational boundary" },
      { group: "gwp", label: "GWP factors source" },
      { group: "factors", label: "Emission factors source" },
    ],
    row_groups: ["entities", "factor:scope1", "factor:scope2"],
    catalog: [
      { ...def, field_id: "consolidation_approach", group: "boundary", label: "Consolidation approach", kind: "enum", allowed: ["Equity Share", "Financial Control", "Operational Control"] },
      { ...def, field_id: "reporting_period", group: "boundary", label: "Reporting period", kind: "text" },
      {
        ...def,
        field_id: "gwp",
        group: "gwp",
        label: "GWP",
        kind: "gwp",
        allowed: { set: ["AR4", "AR5", "AR6"], horizon: ["100-year", "20-year"] },
        allowed_labels: { set: { AR5: "AR5 (IPCC Fifth Assessment)" } },
        parts: [
          { key: "set", label: "Set", kind: "enum" },
          { key: "horizon", label: "Horizon", kind: "enum" },
        ],
      },
      {
        ...def,
        field_id: "entity:abc123",
        group: "boundary",
        label: "Entity row",
        kind: "entity",
        user_added: true,
        parts: [
          { key: "name", label: "Name", kind: "text" },
          { key: "facilities", label: "Facilities", kind: "list" },
          { key: "equity_share_pct", label: "Equity share", kind: "percent" },
        ],
      },
      { ...def, field_id: "factor:scope1:r1", group: "factors", label: "Scope 1 factor row 1", kind: "factor", user_added: true },
      { ...def, field_id: "weird", group: "boundary", label: "Brand new field", kind: "hologram" },
    ],
    fields: [
      {
        field_id: "consolidation_approach",
        user_added: false,
        suggestion: { value: "Operational Control", quote: "We use the operational control approach.", document_id: "d1", file_name: "GHG report.pdf", source_reference: "page 4", origin: "ai", model: "m", request_id: "r", suggested_at: "2026-11-01T10:00:00Z" },
        decision: null,
        history: [],
      },
      {
        field_id: "reporting_period",
        user_added: false,
        suggestion: null,
        decision: { status: "edited", value: "FY2025", by, at: "2026-11-02T10:00:00Z" },
        history: [{ at: "2026-11-02T10:00:00Z", by, action: "edit" }],
      },
      { field_id: "gwp", user_added: false, suggestion: null, decision: { status: "rejected", value: null, reason: "Wrong set", by, at: "2026-11-02T10:00:00Z" }, history: [] },
      { field_id: "entity:abc123", user_added: true, suggestion: null, decision: null, history: [{ at: "2026-11-03T10:00:00Z", by, action: "add_row" }] },
      { field_id: "factor:scope1:r1", user_added: true, suggestion: null, decision: null, history: [{ at: "2026-11-03T10:00:00Z", by, action: "add_row" }] },
      { field_id: "weird", user_added: false, suggestion: null, decision: { status: "frobnicated", value: "x", by, at: "2026-11-02T10:00:00Z" }, history: [] },
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
  it("renders the API's group headings, then each field with value, suggestion chip, quote, status word and who decided", async () => {
    const { onOpenDocument, onActivity } = await open();
    expect(screen.getAllByRole("heading", { level: 3 }).map((h) => h.textContent)).toEqual(["Organizational boundary", "GWP factors source", "Emission factors source"]);
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
    const gwp = row("GWP");
    expect(within(gwp).getByText("Rejected")).toBeTruthy();
    expect(within(gwp).getByText("Reason: Wrong set")).toBeTruthy();
    expect(onActivity).toHaveBeenCalledWith(expect.arrayContaining([expect.objectContaining({ who: "M. Osei", what: expect.stringContaining("Reporting period") })]));
  });

  it("shows Accept and Reject only on a pending field, Revert only on a decided one, Edit always", async () => {
    await open();
    const pending = row("Consolidation approach");
    expect(within(pending).getByRole("button", { name: /^Accept:/ })).toBeTruthy();
    expect(within(pending).getByRole("button", { name: /^Reject:/ })).toBeTruthy();
    expect(within(pending).queryByRole("button", { name: /^Revert:/ })).toBeNull();
    for (const label of ["Reporting period", "GWP"]) {
      const decided = row(label);
      expect(within(decided).queryByRole("button", { name: /^Accept:/ })).toBeNull();
      expect(within(decided).queryByRole("button", { name: /^Reject:/ })).toBeNull();
      expect(within(decided).getByRole("button", { name: /^Revert:/ })).toBeTruthy();
      expect(within(decided).getByRole("button", { name: /^Edit:/ })).toBeTruthy();
    }
  });

  it("accepts, rejects with a reason, edits with an allowed value and reverts, sending no actor", async () => {
    await open();
    fireEvent.click(within(row("Consolidation approach")).getByRole("button", { name: "Accept: Consolidation approach" }));
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

  it("builds a multi-part editor from the catalog's parts, with display names for allowed values", async () => {
    await open();
    fireEvent.click(within(row("GWP")).getByRole("button", { name: "Edit: GWP" }));
    const set = screen.getByLabelText("GWP: Set") as HTMLSelectElement;
    expect(Array.from(set.options).map((o) => o.textContent)).toEqual(["Choose", "AR4", "AR5 (IPCC Fifth Assessment)", "AR6"]);
    fireEvent.change(set, { target: { value: "AR6" } });
    fireEvent.change(screen.getByLabelText("GWP: Horizon"), { target: { value: "100-year" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(calls()).toContainEqual([`${BASE}/gwp/edit`, expect.objectContaining({ body: { value: { set: "AR6", horizon: "100-year" } } })]));
  });

  it("edits a blank new entity row from its parts, typing the list and the percent", async () => {
    await open();
    fireEvent.click(within(row("Entity row")).getByRole("button", { name: "Edit: Entity row" }));
    fireEvent.change(screen.getByLabelText("Entity row: Name"), { target: { value: "Acme Ltd" } });
    fireEvent.change(screen.getByLabelText("Entity row: Facilities"), { target: { value: "North plant, South plant" } });
    fireEvent.change(screen.getByLabelText("Entity row: Equity share"), { target: { value: "60" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() =>
      expect(calls()).toContainEqual([
        `${BASE}/entity%3Aabc123/edit`,
        expect.objectContaining({ body: { value: { name: "Acme Ltd", facilities: ["North plant", "South plant"], equity_share_pct: 60 } } }),
      ])
    );
  });

  it("adds a row for each row group the API lists, and removes only rows the reviewer added", async () => {
    await open();
    fireEvent.click(screen.getByRole("button", { name: "Add Scope 1 factor row" }));
    await waitFor(() => expect(calls()).toContainEqual([`${BASE}/rows`, expect.objectContaining({ body: { group: "factor:scope1" } })]));
    expect(within(row("Consolidation approach")).queryByRole("button", { name: /Remove row/ })).toBeNull();
    fireEvent.click(within(row("Scope 1 factor row 1")).getByRole("button", { name: /Remove row/ }));
    await waitFor(() => expect(calls()).toContainEqual([`${BASE}/factor%3Ascope1%3Ar1`, expect.objectContaining({ method: "DELETE" })]));
  });

  it("limits what can be typed as the server does: text length, 20 facility names of 100 characters", async () => {
    await open();
    fireEvent.click(within(row("Reporting period")).getByRole("button", { name: "Edit: Reporting period" }));
    expect((screen.getByLabelText("Value: Reporting period") as HTMLInputElement).maxLength).toBe(2000);
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));

    fireEvent.click(within(row("Entity row")).getByRole("button", { name: "Edit: Entity row" }));
    expect((screen.getByLabelText("Entity row: Name") as HTMLInputElement).maxLength).toBe(2000);
    const many = Array.from({ length: 21 }, (_, i) => `Plant ${i}`).join(", ");
    fireEvent.change(screen.getByLabelText("Entity row: Facilities"), { target: { value: many } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    expect((await screen.findByRole("alert")).textContent).toBe("Facilities: at most 20 names of 100 characters each.");
    expect(calls().some(([p]) => String(p).includes("/edit"))).toBe(false);
  });

  it("shows the sentence when adding a row is refused", async () => {
    await open();
    mock.fail[`POST ${BASE}/rows`] = new ApiError(409, "This engagement already has 200 rows.", null, null);
    fireEvent.click(screen.getByRole("button", { name: "Add entity" }));
    expect((await screen.findByRole("alert")).textContent).toBe("This engagement already has 200 rows.");
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
      dropped: { quote_not_on_document: 2, some_new_reason: 1 },
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
    expect(summary.textContent).toContain("2: Quote not found in the document");
    expect(summary.textContent).toContain("1 field kept your decision");
    expect(summary.textContent).toContain("1: some new reason");
    expect(summary.textContent).toContain("GHG report.pdf (only the start was read)");
    expect(summary.textContent).toContain("Cost $0.03");
    expect(calls()).toContainEqual([`${BASE}/prefill`, expect.objectContaining({ method: "POST" })]);
  });

  it("words every drop code M2 sends", () => {
    const words: Record<string, string> = {
      empty_value: "No value given",
      unknown_line: "Cited a line that isn't in the document",
      quote_not_on_document: "Quote not found in the document",
      ambiguous_quote: "Quote appears in more than one place",
      value_not_in_quote: "Value isn't in the quoted text",
      unknown_document: "Cited a document that wasn't read",
      invalid_value: "Value isn't one of the allowed options",
      unknown_field: "Not a methodology field",
    };
    for (const [code, text] of Object.entries(words)) expect(dropReasonWords(code)).toBe(text);
  });

  it("shows Claude's refusal sentence from the prefill", async () => {
    await open();
    mock.fail[`POST ${BASE}/prefill`] = new ApiError(409, "Upload the company's GHG inventory report first.", null, null);
    fireEvent.click(screen.getByRole("button", { name: "Read the client's reports with Claude" }));
    fireEvent.click(screen.getByRole("button", { name: "Read the reports" }));
    expect((await screen.findByRole("alert")).textContent).toBe("Upload the company's GHG inventory report first.");
  });

  it.each([
    ["off", "Off: an administrator turns it on."],
    ["cap_reached", "Monthly limit reached."],
    ["no_documents", "No report documents yet."],
    ["not_built", "Suggestions are not built yet."],
    ["a_code_from_the_future", "Some other sentence."],
  ])("states the AI status with the server's sentence and disables the button: %s", async (code, reason) => {
    await open(vi.fn(), fixture({ enabled: false, reason_code: code, reason }));
    expect(screen.getByText(reason)).toBeTruthy();
    expect((screen.getByRole("button", { name: "Read the client's reports with Claude" }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("enables the button when the AI is on", async () => {
    await open();
    expect((screen.getByRole("button", { name: "Read the client's reports with Claude" }) as HTMLButtonElement).disabled).toBe(false);
    expect(aiStatusWords({ enabled: true, reason_code: null, reason: null })).toBeNull();
  });

  it("copes with a status or field kind it does not know", async () => {
    await open();
    expect(statusWord("frobnicated")).toBe("Status unknown");
    const weird = row("Brand new field");
    expect(within(weird).getByText("Status unknown")).toBeTruthy();
    // The row still offers Edit and Revert; the server decides what is allowed.
    expect(within(weird).getByRole("button", { name: "Edit: Brand new field" })).toBeTruthy();
  });
});
