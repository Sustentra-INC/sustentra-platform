/* @vitest-environment jsdom */
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
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
      { ...def, field_id: "reporting_period", group: "boundary", label: "Reporting period", kind: "date_range" },
      { ...def, field_id: "exclusion:boundary", group: "boundary", label: "Excluded from boundary", kind: "text" },
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
        decision: { status: "edited", value: { start: "2025-01-01", end: "2025-12-31" }, by, at: "2026-11-02T10:00:00Z" },
        history: [{ at: "2026-11-02T10:00:00Z", by, action: "edit" }],
      },
      { field_id: "exclusion:boundary", user_added: false, suggestion: null, decision: null, history: [] },
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
  it("tells the reviewer the result lists the documents read", async () => {
    await open();
    fireEvent.click(screen.getByRole("button", { name: "Read the client's reports with Claude" }));
    expect(screen.getByRole("alertdialog").textContent).toMatch(/list the documents it read/);
  });

  it("words activity actions and adds Claude's suggestion", async () => {
    const { onActivity } = await open();
    const whats = (onActivity.mock.calls[0][0] as { what: string }[]).map((e) => e.what);
    expect(whats).toContain("Edited on methodology: Reporting period");
    expect(whats).toContain("Suggested by Claude on methodology: Consolidation approach");
  });

  it("does not send a non-numeric percent", async () => {
    await open();
    const r = row("Entity row");
    fireEvent.click(within(r).getByRole("button", { name: "Edit: Entity row" }));
    fireEvent.change(within(r).getByLabelText("Entity row: Equity share"), { target: { value: "abc" } });
    fireEvent.click(within(r).getByRole("button", { name: "Save" }));
    expect(within(r).getByRole("alert").textContent).toMatch(/enter a number/);
    expect(calls()).toHaveLength(0);
  });

  it("reloads the review after a refused action", async () => {
    await open();
    mock.fail[`POST ${BASE}/consolidation_approach/accept`] = new ApiError(409, "Already decided.", null, null);
    const gets = () => vi.mocked(api).mock.calls.filter(([p, o]) => p === BASE && !o).length;
    const before = gets();
    fireEvent.click(screen.getByRole("button", { name: "Accept: Consolidation approach" }));
    expect((await screen.findByRole("alert")).textContent).toBe("Already decided.");
    await waitFor(() => expect(gets()).toBe(before + 1));
  });

  it("says so when a stored quote was cut", async () => {
    const data = fixture() as { fields: { field_id: string; suggestion: Record<string, unknown> }[] };
    data.fields[0].suggestion.quote_truncated = true;
    await open(vi.fn(), data);
    expect(within(row("Consolidation approach")).getByText("(quote shortened)")).toBeTruthy();
  });

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
    expect(within(period).getByText("2025-01-01 to 2025-12-31")).toBeTruthy();
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
    fireEvent.click(within(row("Excluded from boundary")).getByRole("button", { name: "Edit: Excluded from boundary" }));
    expect((screen.getByLabelText("Value: Excluded from boundary") as HTMLInputElement).maxLength).toBe(2000);
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
    await waitFor(() => expect(summary.textContent).toMatch(/4 suggested, dropped: 2: /));
    expect(summary.textContent).toContain("2: Quote not found in the document, or shorter than 8 characters");
    expect(summary.textContent).toContain("1 field kept your decision");
    expect(summary.textContent).toContain("1: some new reason");
    expect(summary.textContent).toContain("GHG report.pdf (only the start was read)");
    expect(summary.textContent).toContain("Cost $0.03 (m)");
    expect(calls()).toContainEqual([`${BASE}/prefill`, expect.objectContaining({ method: "POST" })]);
  });

  it("words every drop code M2 sends", () => {
    const words: Record<string, string> = {
      empty_value: "No value given",
      unknown_line: "Cited a line that isn't in the document",
      quote_not_on_document: "Quote not found in the document, or shorter than 8 characters",
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
    "Claude is switched off. An administrator turns it on.",
    "Claude is not set up for this workspace.",
    "The monthly limit for Claude is reached.",
    "Upload the company's GHG inventory report, boundary statement or methodology document first.",
    "Claude is already reading reports for your organization. Try again in a minute.",
    "Claude's answer could not be used. Nothing was kept.",
  ])("shows the 409 sentence as the server words it: %s", async (sentence) => {
    await open();
    mock.fail[`POST ${BASE}/prefill`] = new ApiError(409, sentence, null, null);
    fireEvent.click(screen.getByRole("button", { name: "Read the client's reports with Claude" }));
    fireEvent.click(screen.getByRole("button", { name: "Read the reports" }));
    expect((await screen.findByRole("alert")).textContent).toBe(sentence);
  });

  it.each([
    "Claude could not be reached. Try again in a moment.",
    "Claude's suggestions could not be saved. Nothing was kept.",
  ])("shows the 502 sentence: %s", async (sentence) => {
    await open();
    mock.fail[`POST ${BASE}/prefill`] = new ApiError(502, sentence, null, null);
    fireEvent.click(screen.getByRole("button", { name: "Read the client's reports with Claude" }));
    fireEvent.click(screen.getByRole("button", { name: "Read the reports" }));
    expect((await screen.findByRole("alert")).textContent).toBe(sentence);
  });

  it("disables the prefill button while a request is in flight and sends one request", async () => {
    await open();
    let finish: (v: unknown) => void = () => {};
    mock.fail.prefillResult = new Promise((resolve) => (finish = resolve));
    fireEvent.click(screen.getByRole("button", { name: "Read the client's reports with Claude" }));
    const confirm = screen.getByRole("button", { name: "Read the reports" });
    fireEvent.click(confirm);
    fireEvent.click(confirm);
    const button = await screen.findByRole("button", { name: "Reading the reports…" });
    expect((button as HTMLButtonElement).disabled).toBe(true);
    expect(calls().filter(([p]) => String(p).endsWith("/prefill"))).toHaveLength(1);
    finish({ suggested: 0, dropped: {}, kept_reviewer_decision: 0, documents_read: [], cost_usd: 0, model: "m" });
    await waitFor(() => expect((screen.getByRole("button", { name: "Read the client's reports with Claude" }) as HTMLButtonElement).disabled).toBe(false));
  });

  it.each([
    ["off", "Off: an administrator turns it on."],
    ["cap_reached", "Monthly limit reached."],
    ["no_documents", "No report documents yet."],
    ["not_configured", "Claude is not set up for this workspace."],
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
  describe("source location after the file name", () => {
    const withRef = (source_reference: unknown, file_name = "GHG report.pdf") => {
      const d = fixture() as { fields: { suggestion: Record<string, unknown> | null }[] };
      d.fields[0].suggestion = { ...d.fields[0].suggestion!, source_reference, file_name };
      return d;
    };
    const link = (name: RegExp) => within(row("Consolidation approach")).getByRole("button", { name });

    it("shows the page of an object reference", async () => {
      await open(vi.fn(), withRef({ page_number: 4, text_snippet: "We use the operational control approach." }));
      expect(link(/^GHG report\.pdf, page 4$/)).toBeTruthy();
      expect(document.body.textContent).not.toContain("[object Object]");
    });

    it("shows the sheet and cell of a spreadsheet reference", async () => {
      await open(vi.fn(), withRef({ sheet_name: "Sheet1", cell_or_range: "B12" }, "Energy.xlsx"));
      expect(link(/^Energy\.xlsx, Sheet1, B12$/)).toBeTruthy();
    });

    it("shows only the file name when the reference is null, empty or has nothing usable", async () => {
      for (const ref of [null, {}, { page_number: "4" }, { page_number: 0 }]) {
        cleanup();
        await open(vi.fn(), withRef(ref));
        expect(link(/^GHG report\.pdf$/)).toBeTruthy();
        expect(document.body.textContent).not.toContain("[object Object]");
      }
    });

    it("still renders an old string reference", async () => {
      await open(vi.fn(), withRef("page 4"));
      expect(link(/^GHG report\.pdf, page 4$/)).toBeTruthy();
    });

    it("works with a non-ASCII file name and opens the document", async () => {
      const { onOpenDocument } = await open(vi.fn(), withRef({ page_number: 2 }, "Müller Käserei – Zürich 排放.pdf"));
      fireEvent.click(link(/^Müller Käserei – Zürich 排放\.pdf, page 2$/));
      expect(onOpenDocument).toHaveBeenCalledWith("d1");
    });
  });
  describe("row states", () => {
    type Wire = { fields: Record<string, unknown>[]; catalog: Record<string, unknown>[] };
    const OPTIONAL = "optional:acquisitions";
    const LABEL = "Acquisitions und Ver\u00e4u\u00dferungen \u2013 \u4e70\u5356";
    const withStates = (states: Record<string, string>, optional?: { shown: boolean; state: string; suggestion?: boolean }) => {
      const d = fixture() as unknown as Wire;
      d.fields = d.fields.map((f) => ({ ...f, display_state: states[f.field_id as string] ?? "has_value", shown: true }));
      if (optional) {
        d.catalog.push({ group_label: "x", user_added: false, field_id: OPTIONAL, group: "boundary", label: LABEL, kind: "text", required: false });
        d.fields.push({
          field_id: OPTIONAL,
          user_added: false,
          display_state: optional.state,
          shown: optional.shown,
          suggestion: optional.suggestion
            ? { value: "Sold the Kent plant", quote: "We sold the Kent plant in March.", document_id: "d1", file_name: "GHG report.pdf", source_reference: null, origin: "ai", model: "m", request_id: "r", suggested_at: "2026-11-01T10:00:00Z" }
            : null,
          decision: null,
          history: [],
        });
      }
      return d;
    };

    it("reads Not checked yet before Claude has run, and never Not set", async () => {
      const d = withStates({ reporting_period: "not_checked" });
      (d.fields[1] as { decision: unknown }).decision = null; // the fixture's reporting period is decided
      await open(vi.fn(), d);
      expect(within(row("Reporting period")).getByText("Not checked yet")).toBeTruthy();
      expect(document.body.textContent).not.toContain("Not set");
    });

    it("reads Not detected after a run that found nothing", async () => {
      const d = withStates({ reporting_period: "not_detected" });
      (d.fields[1] as { decision: unknown }).decision = null;
      await open(vi.fn(), d);
      expect(within(row("Reporting period")).getByText("Not detected")).toBeTruthy();
      expect(document.body.textContent).not.toContain("Not set");
    });

    it("keeps an optional row off the page and lists it under Add an item, in any script", async () => {
      await open(vi.fn(), withStates({}, { shown: false, state: "not_checked" }));
      expect(screen.queryByText(LABEL, { selector: "span" })).toBeNull();
      const add = screen.getByRole("combobox", { name: "Add an item" });
      expect(within(add).getByRole("option", { name: LABEL })).toBeTruthy();
    });

    it("asks the server to reveal the row when it is picked, and shows it as Not detected after the reload", async () => {
      await open(vi.fn(), withStates({}, { shown: false, state: "not_detected" }));
      mock.data = withStates({}, { shown: true, state: "not_detected" });
      fireEvent.change(screen.getByRole("combobox", { name: "Add an item" }), { target: { value: OPTIONAL } });
      await waitFor(() => expect(within(row(LABEL)).getByText("Not detected")).toBeTruthy());
      expect(calls().map(([path, o]) => `${(o as { method: string }).method} ${path}`)).toContain(`POST ${BASE}/${encodeURIComponent(OPTIONAL)}/reveal`);
      expect(screen.queryByRole("combobox", { name: "Add an item" })).toBeNull();
    });

    it("shows an optional row once a suggestion has arrived", async () => {
      await open(vi.fn(), withStates({}, { shown: true, state: "has_value", suggestion: true }));
      expect(within(row(LABEL)).getByText("Suggested by Claude")).toBeTruthy();
      expect(screen.queryByRole("combobox", { name: "Add an item" })).toBeNull();
    });

    it("offers Accept only where there is a suggestion; an empty row keeps Edit and Reject", async () => {
      const d = withStates({ reporting_period: "not_detected" });
      (d.fields[1] as { decision: unknown }).decision = null;
      await open(vi.fn(), d);
      const empty = row("Reporting period");
      expect(within(empty).queryByRole("button", { name: /^Accept:/ })).toBeNull();
      expect(within(empty).getByRole("button", { name: /^Edit:/ })).toBeTruthy();
      expect(within(empty).getByRole("button", { name: /^Reject:/ })).toBeTruthy();
      expect(within(row("Consolidation approach")).getByRole("button", { name: /^Accept:/ })).toBeTruthy();
    });

    it("copes with a server that sends no state at all", async () => {
      await open();
      expect(screen.getByText("Consolidation approach")).toBeTruthy();
    });
  });
  describe("reporting period as two dates", () => {
    const edit = () => fireEvent.click(within(row("Reporting period")).getByRole("button", { name: "Edit: Reporting period" }));
    const withPeriod = (decision: unknown) => {
      const d = fixture() as unknown as { fields: Record<string, unknown>[] };
      (d.fields[1] as { decision: unknown }).decision = decision;
      return d;
    };

    it("edits with two date inputs and sends both as dates", async () => {
      await open(vi.fn(), withPeriod(null));
      edit();
      expect((screen.getByLabelText("Start date: Reporting period") as HTMLInputElement).type).toBe("date");
      fireEvent.change(screen.getByLabelText("Start date: Reporting period"), { target: { value: "2025-01-01" } });
      fireEvent.change(screen.getByLabelText("End date: Reporting period"), { target: { value: "2025-12-31" } });
      fireEvent.click(screen.getByRole("button", { name: "Save" }));
      await waitFor(() =>
        expect(calls()).toContainEqual([`${BASE}/reporting_period/edit`, expect.objectContaining({ body: { value: { start: "2025-01-01", end: "2025-12-31" } } })])
      );
    });

    it("asks for both dates before it sends anything", async () => {
      await open(vi.fn(), withPeriod(null));
      edit();
      fireEvent.change(screen.getByLabelText("Start date: Reporting period"), { target: { value: "2025-01-01" } });
      fireEvent.click(screen.getByRole("button", { name: "Save" }));
      expect((await screen.findByRole("alert")).textContent).toContain("Enter both a start date and an end date.");
      expect(calls().some(([path]) => String(path).endsWith("/reporting_period/edit"))).toBe(false);
    });

    it("keeps an old text value, shows it as recorded, and starts the editor empty", async () => {
      await open(vi.fn(), withPeriod({ status: "edited", value: "Fiscal 2025 \u2013 Z\u00fcrich \u6392\u653e", by, at: "2026-11-02T10:00:00Z" }));
      const period = row("Reporting period");
      expect(within(period).getByText("Recorded as: Fiscal 2025 \u2013 Z\u00fcrich \u6392\u653e")).toBeTruthy();
      expect(within(period).getByText("Enter the start and end dates with Edit.")).toBeTruthy();
      edit();
      expect((screen.getByLabelText("Start date: Reporting period") as HTMLInputElement).value).toBe("");
      expect(document.body.textContent).not.toContain("[object Object]");
    });

    it("shows the server's sentence when the dates are refused", async () => {
      await open(vi.fn(), withPeriod(null));
      mock.fail[`POST ${BASE}/reporting_period/edit`] = new ApiError(422, "'Reporting period': the end date can't be before the start date.", null, null);
      edit();
      fireEvent.change(screen.getByLabelText("Start date: Reporting period"), { target: { value: "2025-12-31" } });
      fireEvent.change(screen.getByLabelText("End date: Reporting period"), { target: { value: "2025-01-01" } });
      fireEvent.click(screen.getByRole("button", { name: "Save" }));
      expect((await screen.findByRole("alert")).textContent).toContain("can't be before the start date");
    });
  });
  describe("list suggestions", () => {
    it("says when a quote was cut and when entries were left out", async () => {
      const d = fixture() as unknown as { catalog: Record<string, unknown>[]; fields: Record<string, unknown>[] };
      d.catalog.push({ group_label: "x", user_added: false, field_id: "calculation:estimation", group: "boundary", label: "Estimation method", kind: "entry_list", required: false });
      d.fields.push({
        field_id: "calculation:estimation",
        user_added: false,
        display_state: "has_value",
        shown: true,
        suggestion: {
          value: [{ source_type: "Fuel cards", method: "Prior year" }],
          quote: "fuel cards",
          document_id: "d1",
          file_name: "Report.pdf",
          source_reference: { page_number: 2 },
          evidence: [{ label: "Fuel cards", quote: "Where fuel cards have gaps", quote_truncated: true, document_id: "d1", file_name: "Report.pdf", source_reference: { page_number: 2 } }],
          entries_omitted: 3,
          origin: "ai",
          model: "m",
          request_id: "r",
          suggested_at: "2026-11-01T10:00:00Z",
        },
        decision: null,
        history: [],
      });
      await open(vi.fn(), d);
      const est = row("Estimation method");
      expect(within(est).getByText("(quote shortened)")).toBeTruthy();
      expect(within(est).getByText(/3 more entries were found but not shown/)).toBeTruthy();
      expect(within(est).getByRole("button", { name: "Report.pdf, page 2" })).toBeTruthy();
    });
  });
});

describe("entities and the boundary sentence", () => {
  const SENTENCE = "The boundary covers company-owned or leased buildings (offices, data centres, ATMs), vehicles and aircraft.";
  const evidenceFor = (value: unknown, quote: string) => ({
    value,
    quote,
    document_id: "d1",
    file_name: "Assertion.pdf",
    source_reference: { page_number: 2 },
    origin: "ai",
    model: "m",
    request_id: "r",
    suggested_at: "2026-11-01T10:00:00Z",
  });
  const entityParts = [
    { key: "name", label: "Entity name", kind: "text" },
    { key: "facilities", label: "Facilities", kind: "list" },
    { key: "equity_share_pct", label: "Equity share (%, if stated)", kind: "percent" },
    { key: "financial_control", label: "Financial control (%, if stated)", kind: "percent" },
    { key: "operational_control", label: "Operational control", kind: "enum", allowed: ["Yes", "No"] },
  ];
  const withBoundary = (sentence: string | null, entity: unknown = null) => {
    const d = fixture() as { catalog: Record<string, unknown>[]; fields: Record<string, unknown>[] };
    d.catalog.push({ group_label: "x", user_added: false, field_id: "boundary:entities", group: "boundary", label: "Entities and facilities in the boundary", kind: "text", required: true, value_note: "Boundary sentence only" });
    d.fields.push({
      field_id: "boundary:entities",
      user_added: false,
      display_state: sentence ? "has_value" : "not_detected",
      shown: true,
      suggestion: sentence ? evidenceFor(sentence, sentence) : null,
      decision: null,
      history: [],
    });
    const def = d.catalog.find((c) => c.field_id === "entity:abc123")!;
    def.parts = entityParts;
    if (entity) d.fields.find((f) => f.field_id === "entity:abc123")!.suggestion = evidenceFor(entity, "Café Québec Holdings Inc. is inside the boundary");
    return d;
  };

  it("shows the boundary sentence as the value, marked 'Boundary sentence only', with its quote, when no entity is named", async () => {
    await open(vi.fn(), withBoundary(SENTENCE));
    const r = row("Entities and facilities in the boundary");
    expect(within(r).getAllByText(SENTENCE).length).toBeGreaterThanOrEqual(1);
    expect(within(r).getByText("Boundary sentence only")).toBeTruthy();
    expect(within(r).queryByText("Not detected")).toBeNull();
    expect(within(r).getByRole("button", { name: "Assertion.pdf, page 2" })).toBeTruthy();
  });

  it("reads Not detected, not an invented sentence, when the document has none", async () => {
    await open(vi.fn(), withBoundary(null));
    const r = row("Entities and facilities in the boundary");
    expect(within(r).getByText("Not detected")).toBeTruthy();
    expect(within(r).queryByText("Boundary sentence only")).toBeNull();
  });

  it("does not call it 'the only' thing the report gives once an entity is named", async () => {
    const entity = { name: "Café Québec Holdings Inc.", facilities: [], equity_share_pct: null, financial_control: null, operational_control: "Yes" };
    await open(vi.fn(), withBoundary(SENTENCE, entity));
    expect(within(row("Entities and facilities in the boundary")).queryByText("Boundary sentence only")).toBeNull();
  });

  it("labels each percentage of an entity, shows a missing one as absent, and keeps the Yes / No", async () => {
    const entity = { name: "Café Québec Holdings Inc.", facilities: ["Kent"], equity_share_pct: 51, financial_control: null, operational_control: "Yes" };
    await open(vi.fn(), withBoundary(null, entity));
    const r = row("Entity row");
    expect(within(r).getByText("Café Québec Holdings Inc. · facilities: Kent · equity share 51% · operational control: Yes")).toBeTruthy();
    const none = { name: "Zürich Büro AG", facilities: [], equity_share_pct: null, financial_control: null, operational_control: "No" };
    cleanup();
    await open(vi.fn(), withBoundary(null, none));
    expect(within(row("Entity row")).getByText("Zürich Büro AG · operational control: No")).toBeTruthy();
  });

  it("lets the reviewer correct the name and leave both percentages blank, sending null for each", async () => {
    const entity = { name: "Café Québec Holdings", facilities: [], equity_share_pct: null, financial_control: null, operational_control: "Yes" };
    await open(vi.fn(), withBoundary(null, entity));
    const r = row("Entity row");
    fireEvent.click(within(r).getByRole("button", { name: "Edit: Entity row" }));
    expect((screen.getByLabelText("Entity row: Equity share (%, if stated)") as HTMLInputElement).value).toBe("");
    fireEvent.change(screen.getByLabelText("Entity row: Entity name"), { target: { value: "Café Québec Holdings, Inc." } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() =>
      expect(calls()).toContainEqual([
        `${BASE}/entity%3Aabc123/edit`,
        expect.objectContaining({
          body: { value: { name: "Café Québec Holdings, Inc.", facilities: [], equity_share_pct: null, financial_control: null, operational_control: "Yes" } },
        }),
      ])
    );
  });
});
