/* @vitest-environment jsdom */
import "@testing-library/jest-dom/vitest";
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
import { AssignTaskProvider } from "../../tasks/AssignTaskContext";
import type { EngagementConfig } from "../types";
import type { Ask } from "../types/requests";
import type { AskDraft } from "../requests/requestsStore";
import { menuItems, rowAction } from "./methodologyMenu";
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
const row = (label: string) => screen.getAllByText(label).map((e) => e.closest("li, tbody")).find(Boolean) as HTMLElement;

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
    fireEvent.click(screen.getByRole("button", { name: "Read the client's reports with Sustentra's AI" }));
    expect(screen.getByRole("alertdialog").textContent).toMatch(/list the documents it read/);
  });

  it("words activity actions and adds Claude's suggestion", async () => {
    const { onActivity } = await open();
    const whats = (onActivity.mock.calls[0][0] as { what: string }[]).map((e) => e.what);
    expect(whats).toContain("Edited on methodology: Reporting period");
    expect(whats).toContain("Suggested by Sustentra's AI on methodology: Consolidation approach");
  });

  it("does not send a non-numeric percent", async () => {
    await open();
    const r = row("Entity row");
    rowAction(r, "Edit", "Entity row");
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

  it("opens the explanation from the Suggested by Sustentra's AI button: why, evidence and checks, and an old suggestion says no reason was recorded", async () => {
    const data = fixture() as { fields: { field_id: string; explanation?: unknown }[] };
    data.fields[0].explanation = {
      reason: "The report states it uses the operational control approach under 'Organizational boundary'.",
      reason_note: null,
      read_at: "2026-11-01T10:00:00Z",
      model: "m",
      items: [{ label: null, reason: "The report states it uses the operational control approach under 'Organizational boundary'.", quote: "We use the operational control approach.", document_id: "d1", file_name: "GHG report.pdf", page: 4, location: "page 4", checks: ["The wording matched: 'operational control' → Operational Control."], implied: [] }],
    };
    const { onOpenDocument } = await open(vi.fn(), data);
    fireEvent.click(within(row("Consolidation approach")).getByRole("button", { name: "Suggested by Sustentra's AI" }));
    const dialog = screen.getByRole("dialog");
    expect(within(dialog).getByText(/The report states it uses the operational control approach/)).toBeInTheDocument();
    expect(within(dialog).getByText("The wording matched: 'operational control' → Operational Control.")).toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole("button", { name: "GHG report.pdf, page 4" }));
    expect(onOpenDocument).toHaveBeenCalledWith("d1", { fieldId: "consolidation_approach", entry: null, page: 4 });
    cleanup();
    await open(vi.fn()); // the same suggestion, saved with no reason and no explanation
    fireEvent.click(within(row("Consolidation approach")).getByRole("button", { name: "Suggested by Sustentra's AI" }));
    expect(screen.getByText("Reason not recorded for this suggestion. Re-read the reports to get one.")).toBeInTheDocument();
    expect(within(screen.getByRole("dialog")).getByText("We use the operational control approach.")).toBeInTheDocument();
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
    expect(within(approach).getByText("Suggested by Sustentra's AI")).toBeTruthy();
    expect(within(approach).getByText("We use the operational control approach.")).toBeTruthy();
    expect(within(approach).queryByText("Pending")).toBeNull(); // no Pending chip: a status chip only for Accepted, Edited, Rejected
    fireEvent.click(within(approach).getByRole("button", { name: "GHG report.pdf, page 4" }));
    expect(onOpenDocument).toHaveBeenCalledWith("d1", expect.objectContaining({ fieldId: expect.any(String) }));

    const period = row("Reporting period");
    expect(within(period).getByText("2025-01-01 to 2025-12-31")).toBeTruthy();
    expect(within(period).getByText("Edited")).toBeTruthy();
    expect(within(period).getByText(/M\. Osei/)).toBeTruthy();
    const gwp = row("GWP");
    expect(within(gwp).getByText("Rejected")).toBeTruthy();
    expect(within(gwp).getByText("Reason: Wrong set")).toBeTruthy();
    expect(onActivity).toHaveBeenCalledWith(expect.arrayContaining([expect.objectContaining({ who: "M. Osei", what: expect.stringContaining("Reporting period") })]));
  });

  it("shows Accept as the only visible action on a suggestion; Edit, Reject and the rest sit in the ⋯ menu, Revert only on a decided one", async () => {
    await open();
    const pending = row("Consolidation approach");
    expect(within(pending).getByRole("button", { name: /^Accept:/ })).toBeTruthy();
    expect(within(pending).queryByRole("button", { name: /^(Edit|Reject|Revert|Assign)/ })).toBeNull();
    expect(menuItems(pending, "Consolidation approach")).toEqual(["Edit", "Reject"]);
    const period = row("Reporting period");
    expect(within(period).queryByRole("button", { name: /^Accept:/ })).toBeNull();
    expect(menuItems(period, "Reporting period")).toEqual(["Edit", "Revert"]);
    // A rejected row has no value: it offers Add value, and Revert in the menu.
    const gwp = row("GWP");
    expect(within(gwp).getByRole("button", { name: "Add value: GWP" })).toBeTruthy();
    expect(menuItems(gwp, "GWP")).toEqual(["Revert"]);
  });

  it("opens the ⋯ menu from the keyboard: focus lands on the first item, arrows move, Escape closes and returns to the button", async () => {
    await open();
    const trigger = within(row("Consolidation approach")).getByRole("button", { name: "More actions: Consolidation approach" });
    trigger.focus();
    fireEvent.click(trigger);
    const items = screen.getAllByRole("menuitem");
    expect(document.activeElement).toBe(items[0]);
    fireEvent.keyDown(items[0], { key: "ArrowDown" });
    expect(document.activeElement).toBe(items[1]);
    fireEvent.keyDown(items[1], { key: "ArrowDown" });
    expect(document.activeElement).toBe(items[0]);
    fireEvent.keyDown(items[0], { key: "Escape" });
    expect(screen.queryByRole("menu")).toBeNull();
    expect(document.activeElement).toBe(trigger);
  });

  it("accepts, rejects with a reason, edits with an allowed value and reverts, sending no actor", async () => {
    await open();
    fireEvent.click(within(row("Consolidation approach")).getByRole("button", { name: "Accept: Consolidation approach" }));
    await waitFor(() => expect(calls()).toContainEqual([`${BASE}/consolidation_approach/accept`, expect.objectContaining({ method: "POST", body: {} })]));

    rowAction(row("Consolidation approach"), "Reject", "Consolidation approach");
    const reject = screen.getByRole("button", { name: "Reject" });
    expect((reject as HTMLButtonElement).disabled).toBe(true);
    fireEvent.change(screen.getByLabelText("Reason: Consolidation approach"), { target: { value: "Report says equity share" } });
    fireEvent.click(reject);
    await waitFor(() => expect(calls()).toContainEqual([`${BASE}/consolidation_approach/reject`, expect.objectContaining({ body: { reason: "Report says equity share" } })]));

    rowAction(row("Consolidation approach"), "Edit", "Consolidation approach");
    const select = screen.getByLabelText("Value: Consolidation approach") as HTMLSelectElement;
    expect(Array.from(select.options).map((o) => o.value)).toEqual(["", "Equity Share", "Financial Control", "Operational Control"]);
    fireEvent.change(select, { target: { value: "Financial Control" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(calls()).toContainEqual([`${BASE}/consolidation_approach/edit`, expect.objectContaining({ body: { value: "Financial Control" } })]));

    rowAction(row("Reporting period"), "Revert", "Reporting period");
    await waitFor(() => expect(calls()).toContainEqual([`${BASE}/reporting_period/revert`, expect.objectContaining({ method: "POST" })]));
  });

  it("builds a multi-part editor from the catalog's parts, with display names for allowed values", async () => {
    await open();
    rowAction(row("GWP"), "Edit", "GWP");
    const set = screen.getByLabelText("GWP: Set") as HTMLSelectElement;
    expect(Array.from(set.options).map((o) => o.textContent)).toEqual(["Choose", "AR4", "AR5 (IPCC Fifth Assessment)", "AR6"]);
    fireEvent.change(set, { target: { value: "AR6" } });
    fireEvent.change(screen.getByLabelText("GWP: Horizon"), { target: { value: "100-year" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(calls()).toContainEqual([`${BASE}/gwp/edit`, expect.objectContaining({ body: { value: { set: "AR6", horizon: "100-year" } } })]));
  });

  it("edits a blank new entity row from its parts, typing the list and the percent", async () => {
    await open();
    rowAction(row("Entity row"), "Edit", "Entity row");
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
    expect(menuItems(row("Consolidation approach"), "Consolidation approach")).not.toContain("Remove row");
    rowAction(row("Scope 1 factor row 1"), "Remove row", "Scope 1 factor row 1");
    await waitFor(() => expect(calls()).toContainEqual([`${BASE}/factor%3Ascope1%3Ar1`, expect.objectContaining({ method: "DELETE" })]));
  });

  it("limits what can be typed as the server does: text length, 20 facility names of 100 characters", async () => {
    await open();
    rowAction(row("Excluded from boundary"), "Edit", "Excluded from boundary");
    expect((screen.getByLabelText("Value: Excluded from boundary") as HTMLInputElement).maxLength).toBe(2000);
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));

    rowAction(row("Entity row"), "Edit", "Entity row");
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

  it("asks before reading the reports, then summarises what was found and what was set aside", async () => {
    await open();
    mock.fail.prefillResult = {
      suggested: 4,
      dropped: { quote_not_on_document: 2, some_new_reason: 1 },
      kept_reviewer_decision: 1,
      documents_read: [{ document_id: "d1", file_name: "GHG report.pdf", truncated: true }],
      cost_usd: 0.0312,
      model: "m",
    };
    fireEvent.click(screen.getByRole("button", { name: "Read the client's reports with Sustentra's AI" }));
    expect(calls().some(([p]) => String(p).endsWith("/prefill"))).toBe(false);
    expect(screen.getByRole("alertdialog").textContent).toMatch(/Suggestions need your review/);
    fireEvent.click(screen.getByRole("button", { name: "Read the reports" }));
    const summary = await screen.findByRole("region", { name: "Summary of the read" });
    // 3 set aside (2 + 1), listed by reason in plain words under Details; no cost, no model, no codes.
    await waitFor(() => expect(summary.textContent).toContain("3 set aside"));
    expect(summary.textContent).not.toMatch(/Cost|\$0|quote_not_on_document|some_new_reason/);
    fireEvent.click(within(summary).getByRole("button", { name: /Details/ }));
    expect(summary.textContent).toContain("2 · Quote not found in the document, or shorter than 8 characters");
    expect(summary.textContent).toContain("1 · some new reason");
    expect(calls()).toContainEqual([`${BASE}/prefill`, expect.objectContaining({ method: "POST" })]);
  });

  it("says so when nothing changed since the last read and the AI was not asked again", async () => {
    await open();
    mock.fail.prefillResult = {
      suggested: 0,
      dropped: {},
      kept_reviewer_decision: 0,
      documents_read: [],
      cost_usd: 0,
      model: null,
      reused: true,
      read_at: "2026-11-20T10:00:00Z",
    };
    fireEvent.click(screen.getByRole("button", { name: "Read the client's reports with Sustentra's AI" }));
    fireEvent.click(screen.getByRole("button", { name: "Read the reports" }));
    const note = await screen.findByText(/Nothing changed since/);
    expect(note.textContent).toMatch(/^Already read by Sustentra's AI on Nov 20, 2026\. Nothing changed since, so it was not read again\.$/);
    expect(note.textContent).not.toMatch(/Claude/);
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
    fireEvent.click(screen.getByRole("button", { name: "Read the client's reports with Sustentra's AI" }));
    fireEvent.click(screen.getByRole("button", { name: "Read the reports" }));
    expect((await screen.findByRole("alert")).textContent).toBe("Upload the company's GHG inventory report first.");
  });

  it.each([
    "Sustentra's AI is switched off. An administrator turns it on.",
    "Sustentra's AI is not set up for this workspace.",
    "The monthly limit for Sustentra's AI is reached.",
    "Upload the company's GHG inventory report, boundary statement or methodology document first.",
    "Sustentra's AI is already reading reports for your organization. Try again in a minute.",
    "The AI's answer could not be used. Nothing was kept.",
  ])("shows the 409 sentence as the server words it: %s", async (sentence) => {
    await open();
    mock.fail[`POST ${BASE}/prefill`] = new ApiError(409, sentence, null, null);
    fireEvent.click(screen.getByRole("button", { name: "Read the client's reports with Sustentra's AI" }));
    fireEvent.click(screen.getByRole("button", { name: "Read the reports" }));
    expect((await screen.findByRole("alert")).textContent).toBe(sentence);
  });

  it.each([
    "Sustentra's AI could not be reached. Try again in a moment.",
    "The AI's suggestions could not be saved. Nothing was kept.",
  ])("shows the 502 sentence: %s", async (sentence) => {
    await open();
    mock.fail[`POST ${BASE}/prefill`] = new ApiError(502, sentence, null, null);
    fireEvent.click(screen.getByRole("button", { name: "Read the client's reports with Sustentra's AI" }));
    fireEvent.click(screen.getByRole("button", { name: "Read the reports" }));
    expect((await screen.findByRole("alert")).textContent).toBe(sentence);
  });

  it("disables the prefill button while a request is in flight and sends one request", async () => {
    await open();
    let finish: (v: unknown) => void = () => {};
    mock.fail.prefillResult = new Promise((resolve) => (finish = resolve));
    fireEvent.click(screen.getByRole("button", { name: "Read the client's reports with Sustentra's AI" }));
    const confirm = screen.getByRole("button", { name: "Read the reports" });
    fireEvent.click(confirm);
    fireEvent.click(confirm);
    const button = await screen.findByRole("button", { name: "Reading the reports…" });
    expect((button as HTMLButtonElement).disabled).toBe(true);
    expect(calls().filter(([p]) => String(p).endsWith("/prefill"))).toHaveLength(1);
    finish({ suggested: 0, dropped: {}, kept_reviewer_decision: 0, documents_read: [], cost_usd: 0, model: "m" });
    await waitFor(() => expect((screen.getByRole("button", { name: "Read the client's reports with Sustentra's AI" }) as HTMLButtonElement).disabled).toBe(false));
  });

  it.each([
    ["off", "Off: an administrator turns it on."],
    ["cap_reached", "Monthly limit reached."],
    ["no_documents", "No report documents yet."],
    ["not_configured", "Sustentra's AI is not set up for this workspace."],
    ["a_code_from_the_future", "Some other sentence."],
  ])("states the AI status with the server's sentence and disables the button: %s", async (code, reason) => {
    await open(vi.fn(), fixture({ enabled: false, reason_code: code, reason }));
    expect(screen.getByText(reason)).toBeTruthy();
    expect((screen.getByRole("button", { name: "Read the client's reports with Sustentra's AI" }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("enables the button when the AI is on", async () => {
    await open();
    expect((screen.getByRole("button", { name: "Read the client's reports with Sustentra's AI" }) as HTMLButtonElement).disabled).toBe(false);
    expect(aiStatusWords({ enabled: true, reason_code: null, reason: null })).toBeNull();
  });

  it("copes with a status or field kind it does not know", async () => {
    await open();
    expect(statusWord("frobnicated")).toBe("Status unknown");
    const weird = row("Brand new field");
    expect(within(weird).getByText("Status unknown")).toBeTruthy();
    // The row still offers Edit and Revert; the server decides what is allowed.
    expect(within(weird).getByRole("button", { name: "Add value: Brand new field" })).toBeTruthy();
    expect(menuItems(weird, "Brand new field")).toContain("Revert");
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
      expect(onOpenDocument).toHaveBeenCalledWith("d1", expect.objectContaining({ fieldId: expect.any(String) }));
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
      expect(within(row(LABEL)).getByText("Suggested by Sustentra's AI")).toBeTruthy();
      expect(screen.queryByRole("combobox", { name: "Add an item" })).toBeNull();
    });

    it("offers Accept only where there is a suggestion; an empty row shows Add value and no Reject", async () => {
      const d = withStates({ reporting_period: "not_detected" });
      (d.fields[1] as { decision: unknown }).decision = null;
      await open(vi.fn(), d);
      const empty = row("Reporting period");
      expect(within(empty).queryByRole("button", { name: /^Accept:/ })).toBeNull();
      expect(within(empty).getByRole("button", { name: "Add value: Reporting period" })).toBeTruthy();
      expect(menuItems(empty, "Reporting period")).not.toContain("Reject");
      expect(within(row("Consolidation approach")).getByRole("button", { name: /^Accept:/ })).toBeTruthy();
    });

    it("copes with a server that sends no state at all", async () => {
      await open();
      expect(screen.getByText("Consolidation approach")).toBeTruthy();
    });
  });
  describe("reporting period as two dates", () => {
    const edit = () => rowAction(row("Reporting period"), "Edit", "Reporting period");
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

describe("the Scopes covered row", () => {
  const SCOPES = "Scopes covered";
  const withScopes = (record: Record<string, unknown> = {}, displayState = "not_detected") => {
    const d = fixture() as { catalog: Record<string, unknown>[]; fields: Record<string, unknown>[] };
    d.catalog.push({
      group_label: "x",
      user_added: false,
      field_id: "scopes:covered",
      group: "boundary",
      label: SCOPES,
      kind: "multiselect",
      allowed: ["Scope 1", "Scope 2", "Scope 3", "Not stated"],
      required: true,
    });
    d.fields.push({ field_id: "scopes:covered", user_added: false, display_state: displayState, shown: true, suggestion: null, decision: null, history: [], ...record });
    return d;
  };
  const suggestion = {
    value: [
      { option: "Scope 1", wording: "Scope 1" },
      { option: "Scope 3", wording: "category 6, business air travel" },
    ],
    quote: "Scope 1 and Scope 2 emissions of Café Québec",
    document_id: "d1",
    file_name: "Plan.pdf",
    source_reference: { page_number: 3 },
    evidence: [
      { label: "Scope 1", quote: "Scope 1 emissions of Café Québec", document_id: "d1", file_name: "Plan.pdf", source_reference: { page_number: 3 } },
      { label: "Scope 3", quote: "Scope 3 is reported only for category 6", document_id: "d1", file_name: "Plan.pdf", source_reference: { page_number: 4 } },
    ],
    origin: "ai",
    model: "m",
    request_id: "r",
    suggested_at: "2026-11-01T10:00:00Z",
  };

  it("shows each suggested scope with the company's wording and its own quote", async () => {
    await open(vi.fn(), withScopes({ suggestion }, "has_value"));
    const r = row(SCOPES);
    expect(within(r).getByText("Scope 1 (Scope 1); Scope 3 (category 6, business air travel)")).toBeTruthy();
    expect(within(r).getByText("Scope 1 emissions of Café Québec")).toBeTruthy();
    expect(within(r).getByText("Scope 3 is reported only for category 6")).toBeTruthy();
    expect(within(r).getByRole("button", { name: "Plan.pdf, page 4" })).toBeTruthy();
  });

  it("reads Not detected when the document names no scope", async () => {
    await open(vi.fn(), withScopes());
    expect(within(row(SCOPES)).getByText("Not detected")).toBeTruthy();
  });

  it("Not stated stands alone: choosing it clears the scopes and choosing a scope clears it; it can't be a free option", async () => {
    await open(vi.fn(), withScopes());
    const r = row(SCOPES);
    rowAction(r, "Edit", `${SCOPES}`);
    fireEvent.click(screen.getByRole("checkbox", { name: `Scope 1: ${SCOPES}` }));
    fireEvent.click(screen.getByRole("checkbox", { name: `Scope 2: ${SCOPES}` }));
    fireEvent.click(screen.getByRole("checkbox", { name: `Not stated: ${SCOPES}` }));
    expect((screen.getByRole("checkbox", { name: `Scope 1: ${SCOPES}` }) as HTMLInputElement).checked).toBe(false);
    expect(screen.queryByLabelText(`Company's wording for Not stated: ${SCOPES}`)).toBeNull();
    fireEvent.click(screen.getByRole("checkbox", { name: `Scope 3: ${SCOPES}` }));
    expect((screen.getByRole("checkbox", { name: `Not stated: ${SCOPES}` }) as HTMLInputElement).checked).toBe(false);
    expect(screen.queryByLabelText(`Add another option: ${SCOPES}`)).toBeNull(); // no free additions on this field
  });

  it("refuses to save nothing, naming Not stated, and saves the chosen scopes", async () => {
    await open(vi.fn(), withScopes());
    const r = row(SCOPES);
    rowAction(r, "Edit", `${SCOPES}`);
    fireEvent.click(within(r).getByRole("button", { name: "Save" }));
    expect(within(r).getByRole("alert").textContent).toBe("Choose at least one option, or Not stated if the document does not say.");
    expect(calls()).toHaveLength(0);
    fireEvent.click(screen.getByRole("checkbox", { name: `Scope 2: ${SCOPES}` }));
    fireEvent.click(within(r).getByRole("button", { name: "Save" }));
    await waitFor(() =>
      expect(calls()).toContainEqual([`${BASE}/scopes%3Acovered/edit`, expect.objectContaining({ body: { value: [{ option: "Scope 2", wording: "" }] } })])
    );
  });
});

describe("a GWP set with no stated horizon and a use note", () => {
  const gwpFixture = () => {
    const d = fixture() as { catalog: Record<string, unknown>[]; fields: Record<string, unknown>[] };
    const def = d.catalog.find((c) => c.field_id === "gwp")!;
    def.allowed = { set: ["AR4", "AR5", "AR6"], horizon: ["100-year", "20-year", "500-year", "Not stated"] };
    def.parts = [
      { key: "set", label: "Set", kind: "enum" },
      { key: "horizon", label: "Horizon", kind: "enum" },
      { key: "applies_to", label: "Applies to", kind: "text" },
    ];
    const record = d.fields.find((f) => f.field_id === "gwp")!;
    record.decision = null;
    record.suggestion = {
      value: { set: "AR5", horizon: "Not stated", applies_to: "embed AR5 values" },
      quote: "Supplier factors (CEDA, DESNZ) embed AR5 values",
      document_id: "d1",
      file_name: "Plan.pdf",
      source_reference: { page_number: 5 },
      origin: "ai",
      model: "m",
      request_id: "r",
      suggested_at: "2026-11-01T10:00:00Z",
    };
    return d;
  };

  it("shows the set, a missing horizon as '100-year (assumed — not stated)' and the use note, beside the quote", async () => {
    await open(vi.fn(), gwpFixture());
    const gwp = row("GWP");
    expect(within(gwp).getByText("AR5 (IPCC Fifth Assessment)")).toBeTruthy();
    expect(within(gwp).getByText(/100-year \(assumed — not stated\)/)).toBeTruthy();
    expect(gwp.textContent).toContain("embed AR5 values");
    expect(within(gwp).getByText("Supplier factors (CEDA, DESNZ) embed AR5 values")).toBeTruthy();
  });

  it("offers Not stated as a horizon and sends the use note with the edit", async () => {
    await open(vi.fn(), gwpFixture());
    rowAction(row("GWP"), "Edit", "GWP");
    const horizon = screen.getByLabelText("GWP: Horizon") as HTMLSelectElement;
    expect(Array.from(horizon.options).map((o) => o.textContent)).toEqual(["Choose", "100-year", "20-year", "500-year", "Not stated"]);
    expect(horizon.value).toBe("Not stated");
    fireEvent.change(screen.getByLabelText("GWP: Applies to"), { target: { value: "Zürich 排放 factors" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() =>
      expect(calls()).toContainEqual([`${BASE}/gwp/edit`, expect.objectContaining({ body: { value: { set: "AR5", horizon: "Not stated", applies_to: "Zürich 排放 factors" } } })])
    );
  });
});

describe("a reporting period with an implied start", () => {
  const impliedFixture = (value: unknown, quote = "for the year ended December 31, 2024") => {
    const d = fixture() as { fields: Record<string, unknown>[] };
    const record = d.fields.find((f) => f.field_id === "reporting_period")!;
    record.decision = null;
    record.history = [];
    record.suggestion = {
      value,
      quote,
      document_id: "d1",
      file_name: "Assertion.pdf",
      source_reference: { page_number: 1 },
      origin: "ai",
      model: "m",
      request_id: "r",
      suggested_at: "2026-11-01T10:00:00Z",
    };
    return d;
  };

  it("says the start is implied and shows the derived calendar or fiscal choice beside the quote that holds the end date", async () => {
    await open(vi.fn(), impliedFixture({ start: "2024-01-01", end: "2024-12-31", start_implied: true, basis: "Calendar year" }));
    const period = row("Reporting period");
    expect(within(period).getByText("2024-01-01 implied to 2024-12-31, calendar year")).toBeTruthy();
    expect(within(period).getByText("for the year ended December 31, 2024")).toBeTruthy();
    cleanup();
    await open(vi.fn(), impliedFixture({ start: "2024-07-01", end: "2025-06-30", start_implied: true, basis: "Fiscal year" }, "fiscal year ended June 30, 2025"));
    expect(within(row("Reporting period")).getByText("2024-07-01 implied to 2025-06-30, fiscal year")).toBeTruthy();
  });

  it("shows a stated start without the word implied, and a period with no derived choice as the two dates", async () => {
    await open(vi.fn(), impliedFixture({ start: "2025-01-01", end: "2025-06-30", basis: "Not stated" }));
    expect(within(row("Reporting period")).getByText("2025-01-01 to 2025-06-30, not stated")).toBeTruthy();
    cleanup();
    await open(vi.fn(), impliedFixture({ start: "2025-01-01", end: "2025-12-31" }));
    expect(within(row("Reporting period")).getByText("2025-01-01 to 2025-12-31")).toBeTruthy();
  });

  it("flags both dates when the year came from the document's title, and shows both quotes", async () => {
    const d = impliedFixture({ start: "2023-01-01", end: "2023-12-31", start_implied: true, end_implied: true, implied_from: "calendar year, year from title", basis: "Calendar year" }, "calendar reporting year basis") as { fields: { field_id: string; suggestion: Record<string, unknown> }[] };
    const sug = d.fields.find((f) => f.field_id === "reporting_period")!.suggestion;
    sug.evidence = [
      { label: "Calendar year", quote: "calendar reporting year basis", document_id: "d1", file_name: "Statement.pdf", source_reference: { page_number: 1 } },
      { label: "Year from the title", quote: "2023 Statement of GHG Emissions", document_id: "d1", file_name: "Statement.pdf", source_reference: { page_number: 1 } },
    ];
    await open(vi.fn(), d);
    const period = row("Reporting period");
    expect(
      within(period).getByText("2023-01-01 implied (calendar year, year from title) to 2023-12-31 implied (calendar year, year from title), calendar year")
    ).toBeTruthy();
    expect(within(period).getByText("calendar reporting year basis")).toBeTruthy();
    expect(within(period).getByText("2023 Statement of GHG Emissions")).toBeTruthy();
  });

  it("edits as two dates only, so a typed start is never sent as implied", async () => {
    await open(vi.fn(), impliedFixture({ start: "2024-01-01", end: "2024-12-31", start_implied: true, basis: "Calendar year" }));
    const period = row("Reporting period");
    rowAction(period, "Edit", "Reporting period");
    fireEvent.change(within(period).getByLabelText("Start date: Reporting period"), { target: { value: "2024-02-01" } });
    fireEvent.click(within(period).getByRole("button", { name: "Save" }));
    await waitFor(() =>
      expect(calls()).toContainEqual([`${BASE}/reporting_period/edit`, expect.objectContaining({ body: { value: { start: "2024-02-01", end: "2024-12-31" } } })])
    );
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
    { key: "included", label: "Included", kind: "enum", allowed: ["Yes", "No"], optional: true },
    { key: "control_quoted", label: "Operational control (as quoted)", kind: "enum", allowed: ["Yes", "No"], optional: true, show_if_present: true },
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
    const entity = { name: "Café Québec Holdings Inc.", facilities: [], equity_share_pct: null, financial_control: null, included: "Yes" };
    await open(vi.fn(), withBoundary(SENTENCE, entity));
    expect(within(row("Entities and facilities in the boundary")).queryByText("Boundary sentence only")).toBeNull();
  });

  it("labels each percentage of an entity, shows a missing one as absent, and keeps the Yes / No", async () => {
    const entity = { name: "Café Québec Holdings Inc.", facilities: ["Kent"], equity_share_pct: 51, financial_control: null, included: "Yes" };
    await open(vi.fn(), withBoundary(null, entity));
    const r = row("Entity row");
    expect(within(r).getByDisplayValue("Café Québec Holdings Inc.")).toBeTruthy();
    expect(r.textContent).toContain("1 facility");
    expect(within(r).getByText("51%")).toBeTruthy();
    expect(within(r).getByText("Yes")).toBeTruthy();
    const none = { name: "Zürich Büro AG", facilities: [], equity_share_pct: null, financial_control: null, included: "No" };
    cleanup();
    await open(vi.fn(), withBoundary(null, none));
    expect(within(row("Entity row")).getByDisplayValue("Zürich Büro AG")).toBeTruthy();
    expect(within(row("Entity row")).getByText("No")).toBeTruthy(); // a missing equity share reads as a dash, not 0%
    expect(row("Entity row").textContent).not.toContain("%");
  });

  it("shows an entity whose Yes / No is not stated without one, and lets the reviewer leave it as Not stated", async () => {
    const entity = { name: "Zürich Büro AG", facilities: [], equity_share_pct: 51, financial_control: null, included: null };
    await open(vi.fn(), withBoundary(null, entity));
    const r = row("Entity row");
    expect(within(r).getByDisplayValue("Zürich Büro AG")).toBeTruthy();
    expect(within(r).getByText("51%")).toBeTruthy();
    rowAction(r, "Edit", "Entity row");
    const control = screen.getByLabelText("Entity row: Included") as HTMLSelectElement;
    expect(Array.from(control.options).map((o) => o.textContent)).toEqual(["Not stated", "Yes", "No"]);
    expect(control.value).toBe("");
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() =>
      expect(calls()).toContainEqual([
        `${BASE}/entity%3Aabc123/edit`,
        expect.objectContaining({ body: { value: { name: "Zürich Büro AG", facilities: [], equity_share_pct: 51, financial_control: null, included: null } } }),
      ])
    );
    cleanup();
    await open(vi.fn(), withBoundary(null, entity));
    rowAction(row("Entity row"), "Edit", "Entity row");
    fireEvent.change(screen.getByLabelText("Entity row: Included"), { target: { value: "No" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(calls().some(([, o]) => JSON.stringify(o).includes('"included":"No"'))).toBe(true));
  });

  it("labels the per-entity Yes / No 'Included' and shows operational control separately, only when it was quoted", async () => {
    const quoted = { name: "Stockton Cold Storage JV", facilities: [], equity_share_pct: 50, financial_control: null, included: "Yes", control_quoted: "No" };
    await open(vi.fn(), withBoundary(null, quoted));
    const r = row("Entity row");
    expect((within(r).getByLabelText("Name: Entity row") as HTMLInputElement).value).toBe("Stockton Cold Storage JV");
    expect(r.textContent).toContain("50%");
    expect(r.textContent).toContain("operational control (as quoted): No");
    rowAction(r, "Edit", "Entity row");
    expect(screen.queryByLabelText("Entity row: Operational control")).toBeNull(); // the old label is gone
    const asQuoted = screen.getByLabelText("Entity row: Operational control (as quoted)") as HTMLSelectElement;
    expect(asQuoted.value).toBe("No");
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() =>
      expect(calls()).toContainEqual([
        `${BASE}/entity%3Aabc123/edit`,
        expect.objectContaining({ body: { value: { name: "Stockton Cold Storage JV", facilities: [], equity_share_pct: 50, financial_control: null, included: "Yes", control_quoted: "No" } } }),
      ])
    );
    cleanup();
    const plain = { name: "Zürich Büro AG", facilities: [], equity_share_pct: null, financial_control: null, included: "Yes" };
    await open(vi.fn(), withBoundary(null, plain));
    rowAction(row("Entity row"), "Edit", "Entity row");
    expect(screen.queryByLabelText("Entity row: Operational control (as quoted)")).toBeNull(); // not quoted: not shown
    expect(screen.getByLabelText("Entity row: Included")).toBeTruthy();
  });

  it("never reads an entity saved before Included had its own key as 'Included: No'", async () => {
    const legacy = { name: "Städtische Werke 纸", facilities: [], equity_share_pct: 50, financial_control: null, operational_control: "No" };
    await open(vi.fn(), withBoundary(null, legacy));
    const text = row("Entity row").textContent ?? "";
    expect(text).toContain("operational control (as quoted): No");
    expect(text).not.toContain("included: No");
  });

  it("says in words why an exclusion sentence was not kept as an entity or the boundary sentence", () => {
    expect(dropReasonWords("not_an_inclusion")).toMatch(/left out/);
    expect(dropReasonWords("not_a_boundary_sentence")).toMatch(/boundary covers/);
  });

  it("lets the reviewer correct the name and leave both percentages blank, sending null for each", async () => {
    const entity = { name: "Café Québec Holdings", facilities: [], equity_share_pct: null, financial_control: null, included: "Yes" };
    await open(vi.fn(), withBoundary(null, entity));
    const r = row("Entity row");
    rowAction(r, "Edit", "Entity row");
    expect((screen.getByLabelText("Entity row: Equity share (%, if stated)") as HTMLInputElement).value).toBe("");
    fireEvent.change(screen.getByLabelText("Entity row: Entity name"), { target: { value: "Café Québec Holdings, Inc." } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() =>
      expect(calls()).toContainEqual([
        `${BASE}/entity%3Aabc123/edit`,
        expect.objectContaining({
          body: { value: { name: "Café Québec Holdings, Inc.", facilities: [], equity_share_pct: null, financial_control: null, included: "Yes" } },
        }),
      ])
    );
  });
});


describe("Assign to… on a methodology row", () => {
  it("opens the window for that row, with the row's name", async () => {
    mock.data = fixture();
    render(
      <AssignTaskProvider orgId="org-1" engagementId="e1">
        <BackendMethodologyReview engagementId="e1" onOpenDocument={vi.fn()} onActivity={vi.fn()} />
      </AssignTaskProvider>,
    );
    await screen.findByText("Consolidation approach");
    rowAction(row("Consolidation approach"), "Assign to…", "Consolidation approach");
    const dialog = await screen.findByRole("dialog", { name: "Assign to…" });
    expect(dialog).toHaveTextContent("Methodology row");
    expect(dialog).toHaveTextContent("Consolidation approach");
    expect(screen.getByLabelText("Task")).toHaveValue("Review methodology: Consolidation approach");
  });

  it("is not offered where assigning is not available", async () => {
    await open();
    expect(screen.queryByRole("button", { name: /^Assign to…/ })).toBeNull();
  });
});

describe("Mark for client follow-up", () => {
  const engagement = { reportingPeriod: { start: "2025-01-01", end: "2025-12-31" }, signedInLogin: "ada@acme.test", signedInName: "Ada Admin", engagementTeam: [] } as unknown as EngagementConfig;
  const ask = (over: Partial<Ask> & { fieldKey?: string; origin?: Ask["source"]["origin"] } = {}): Ask => ({
    id: "ASK-METH-consolidation_approach",
    type: "clarify",
    whatIsNeeded: "x",
    source: { origin: over.origin ?? "methodology_row", fieldKey: over.fieldKey ?? "consolidation_approach", itemLabel: "Consolidation approach", facilityName: null, period: "FY 2025" },
    raisedByName: "Ada Admin",
    raisedByLogin: "ada@acme.test",
    raisedAt: "2026-11-20T15:04:05.000Z",
    state: over.state ?? "not_yet_sent",
    requestNumber: null,
    lineNumber: null,
    history: [],
  });
  const mount = async (asks: Ask[], onSaveAsk = vi.fn(() => Promise.resolve({})), data: unknown = fixture()) => {
    mock.data = data;
    const onOpenRequests = vi.fn();
    render(<BackendMethodologyReview engagementId="e1" onOpenDocument={vi.fn()} followUp={{ engagement, asks, onSaveAsk, onOpenRequests, serverRecordsActor: true }} />);
    await screen.findByText("Consolidation approach");
    return { onSaveAsk, onOpenRequests };
  };

  it("offers the action on a row, opens the same Add to requests window and raises a methodology request", async () => {
    const { onSaveAsk } = await mount([]);
    const r = row("Consolidation approach");
    rowAction(r, "Mark for client follow-up", "Consolidation approach");
    const dialog = screen.getByRole("dialog");
    expect(within(dialog).getByRole("heading", { name: "Add to requests" })).toBeTruthy();
    expect(within(dialog).getByText("Consolidation approach")).toBeTruthy(); // the Item line
    fireEvent.click(within(dialog).getByRole("button", { name: /^Add to requests$/ }));
    await waitFor(() => expect(onSaveAsk).toHaveBeenCalledTimes(1));
    const draft = (onSaveAsk.mock.calls[0] as unknown as [AskDraft])[0];
    expect(draft).toMatchObject({ origin: "methodology_row", fieldKey: "consolidation_approach", itemLabel: "Consolidation approach", type: "clarify", period: "FY 2025" });
    expect(draft.whatIsNeeded).toContain("Operational Control"); // what the row holds now
    await waitFor(() => expect(screen.getByRole("status").textContent).toMatch(/added to requests, not sent yet/));
  });

  it("shows a 'Requested · <date>' chip instead of the button once the row has an open request, and links to the requests", async () => {
    const { onSaveAsk, onOpenRequests } = await mount([ask()]);
    const r = row("Consolidation approach");
    expect(within(r).getByText("Requested · Nov 20, 2026")).toBeTruthy();
    expect(menuItems(r, "Consolidation approach")).not.toContain("Mark for client follow-up"); // so it cannot be raised twice
    fireEvent.click(within(r).getByRole("button", { name: "View in requests: Consolidation approach" }));
    expect(onOpenRequests).toHaveBeenCalledTimes(1);
    expect(onSaveAsk).not.toHaveBeenCalled();
    cleanup();
    await mount([ask({ state: "requested" })]);
    expect(within(row("Consolidation approach")).getByText(/^Requested · /)).toBeTruthy();
  });

  it("offers the action again when the earlier request is closed, and ignores other rows' and other pages' requests", async () => {
    await mount([ask({ state: "resolved" })]);
    expect(menuItems(row("Consolidation approach"), "Consolidation approach")).toContain("Mark for client follow-up");
    cleanup();
    await mount([ask({ state: "withdrawn" }), ask({ fieldKey: "reporting_period" }), ask({ origin: "data_point" })]);
    expect(menuItems(row("Consolidation approach"), "Consolidation approach")).toContain("Mark for client follow-up");
    expect(within(row("Reporting period")).getByText(/^Requested · /)).toBeTruthy(); // the period row's own request
  });

  it("keeps the window open with the server's sentence when the request fails, and sends one request per click", async () => {
    const onSaveAsk = vi.fn(() => Promise.reject(new Error("The request could not be saved. Try again.")));
    await mount([], onSaveAsk);
    rowAction(row("Consolidation approach"), "Mark for client follow-up", "Consolidation approach");
    const dialog = screen.getByRole("dialog");
    fireEvent.click(within(dialog).getByRole("button", { name: /^Add to requests$/ }));
    await waitFor(() => expect(within(screen.getByRole("dialog")).getByText(/could not be saved/)).toBeTruthy());
    expect(onSaveAsk).toHaveBeenCalledTimes(1);
    expect(screen.queryByText(/Requested ·/)).toBeNull();
  });

  it("reads a hostile or non-ASCII row label and value as plain text", async () => {
    const d = fixture() as { catalog: Record<string, unknown>[]; fields: Record<string, unknown>[] };
    const hostile = `Zürich 排放 <img src=x onerror=alert(1)> "quoted" & more`;
    d.catalog.find((c) => c.field_id === "exclusion:boundary")!.label = hostile;
    const r = d.fields.find((f) => f.field_id === "exclusion:boundary")!;
    r.decision = { status: "edited", value: "Käserei <b>bold</b> 燃料", by, at: "2026-11-02T10:00:00Z" };
    const { onSaveAsk } = await mount([], vi.fn(() => Promise.resolve({})), d);
    rowAction(row(hostile), "Mark for client follow-up", `${hostile}`);
    expect(document.querySelector("img")).toBeNull(); // nothing was parsed as markup
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: /^Add to requests$/ }));
    await waitFor(() => expect(onSaveAsk).toHaveBeenCalled());
    const draft = (onSaveAsk.mock.calls[0] as unknown as [AskDraft])[0];
    expect(draft.itemLabel).toBe(hostile);
    expect(draft.whatIsNeeded).toContain("Käserei <b>bold</b> 燃料");
  });

  it("shows no action where the page cannot raise requests", async () => {
    await open();
    expect(screen.queryByRole("menuitem", { name: /Mark for client follow-up/ })).toBeNull();
  });
});

describe("row declutter: quote, source link, filter and accept all", () => {
  type Rec = { field_id: string; suggestion: unknown };
  const twoSuggestions = () => {
    const d = fixture() as { fields: Rec[] };
    const sug = (value: string, quote: string, ref: unknown) => ({ value, quote, document_id: "d1", file_name: "GHG report.pdf", source_reference: ref, origin: "ai", model: "m", request_id: "r", suggested_at: "2026-11-01T10:00:00Z" });
    d.fields.find((f) => f.field_id === "exclusion:boundary")!.suggestion = sug("Stockton JV", "Stockton cold storage joint venture is excluded.", { page_number: 5 });
    return d;
  };

  it("shows the value, then the quote, then a small p. N link that opens the same document", async () => {
    const d = twoSuggestions();
    const { onOpenDocument } = await open(vi.fn(), d);
    const r = row("Excluded from boundary");
    const link = within(r).getByRole("button", { name: "GHG report.pdf, page 5" });
    expect(link.textContent).toBe("p. 5");
    fireEvent.click(link);
    expect(onOpenDocument).toHaveBeenCalledWith("d1", { fieldId: "exclusion:boundary", entry: null, page: 5 });
    const text = r.textContent ?? "";
    expect(text.indexOf("Stockton JV")).toBeLessThan(text.indexOf("Stockton cold storage joint venture"));
    expect(within(r).queryByText("Not decided yet")).toBeNull();
  });

  it("clamps a long quote to two lines and expands it on request", async () => {
    const sh = vi.spyOn(HTMLElement.prototype, "scrollHeight", "get").mockReturnValue(60);
    const ch = vi.spyOn(HTMLElement.prototype, "clientHeight", "get").mockReturnValue(30);
    try {
      await open(vi.fn(), twoSuggestions());
      const r = row("Excluded from boundary");
      const quote = r.querySelector("q") as HTMLElement;
      expect(quote.className).toContain("is-clamped");
      fireEvent.click(within(r.querySelector(".s1-mb-quote-wrap") as HTMLElement).getByRole("button", { name: "Show more" }));
      expect(quote.className).not.toContain("is-clamped");
      expect(within(r.querySelector(".s1-mb-quote-wrap") as HTMLElement).getByRole("button", { name: "Show less" })).toBeTruthy();
    } finally {
      sh.mockRestore();
      ch.mockRestore();
    }
  });

  it("filters to the rows that need review", async () => {
    await open(vi.fn(), twoSuggestions());
    expect(screen.getByText("Reporting period")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Needs review" }));
    expect(screen.queryByText("Reporting period")).toBeNull();
    expect(screen.getByText("Consolidation approach")).toBeTruthy();
    expect(screen.getByText("Excluded from boundary")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "All" }));
    expect(screen.getByText("Reporting period")).toBeTruthy();
  });

  it("accepts every suggestion in a section only after a confirm that says how many", async () => {
    await open(vi.fn(), twoSuggestions());
    fireEvent.click(screen.getByRole("button", { name: "Accept all suggestions in this section" }));
    const dialog = screen.getByRole("alertdialog", { name: /Accept all suggestions in/ });
    expect(dialog.textContent).toMatch(/Accept 2 suggestions in/);
    expect(calls()).toHaveLength(0);
    fireEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
    expect(calls()).toHaveLength(0);
    fireEvent.click(screen.getByRole("button", { name: "Accept all suggestions in this section" }));
    fireEvent.click(screen.getByRole("button", { name: "Accept 2" }));
    await waitFor(() => expect(calls().map(([p]) => p)).toEqual([`${BASE}/consolidation_approach/accept`, `${BASE}/exclusion%3Aboundary/accept`]));
  });
});

describe("the two cards", () => {
  it("sets the groups under Inventory Boundary and Methods, and folds a section from its header", async () => {
    await open();
    const h2 = screen.getAllByRole("heading", { level: 2 }).map((h) => h.textContent);
    expect(h2).toEqual(expect.arrayContaining(["Inventory Boundary", "Methods"]));
    const methods = screen.getByRole("heading", { name: "Methods" }).closest("section") as HTMLElement;
    expect(within(methods).getByRole("heading", { name: "GWP factors source" })).toBeTruthy();
    expect(within(methods).queryByRole("heading", { name: "Organizational boundary" })).toBeNull();
    const toggle = screen.getByRole("button", { name: "Organizational boundary" });
    expect(toggle.getAttribute("aria-expanded")).toBe("true");
    fireEvent.click(toggle);
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
    expect(screen.queryByText("Reporting period")).toBeNull();
  });
});

describe("the summary of the read and the tables", () => {
  const sug = (value: unknown) => ({ value, quote: "A quote that is long enough.", document_id: "d1", file_name: "GHG report.pdf", source_reference: { page_number: 4 }, origin: "ai", model: "claude-x", request_id: "r", suggested_at: "2026-11-01T10:00:00Z" });
  const def = { group_label: "x", user_added: false };
  const rec = (id: string, extra: Record<string, unknown>) => ({ field_id: id, user_added: false, suggestion: null, decision: null, history: [], ...extra });
  function summaryFixture() {
    return {
      ai: { enabled: true, reason_code: null, reason: null },
      groups: [
        { group: "boundary", label: "Organizational boundary" },
        { group: "gases", label: "Gases covered" },
        { group: "scope1", label: "Scope 1 emission categories" },
        { group: "gwp", label: "GWP factors source" },
      ],
      row_groups: [],
      catalog: [
        { ...def, field_id: "consolidation_approach", group: "boundary", label: "Consolidation approach", kind: "enum", allowed: ["Operational Control"] },
        { ...def, field_id: "reporting_period", group: "boundary", label: "Reporting period", kind: "date_range" },
        { ...def, field_id: "gas:co2", group: "gases", label: "Gas: CO2", kind: "enum", allowed: ["Included"] },
        { ...def, field_id: "gas:n2o", group: "gases", label: "Gas: N2O", kind: "enum", allowed: ["Included"] },
        { ...def, field_id: "category:scope1:stationary", group: "scope1", label: "Scope 1 Stationary Combustion", kind: "enum", allowed: ["Yes", "No"] },
        { ...def, field_id: "category:scope1:mobile", group: "scope1", label: "Scope 1 Mobile Combustion", kind: "enum", allowed: ["Yes", "No"] },
        { ...def, field_id: "gwp", group: "gwp", label: "GWP factors source", kind: "gwp", allowed: { set: ["AR5"], horizon: ["100-year"] } },
      ],
      fields: [
        rec("consolidation_approach", { suggestion: sug("Operational Control") }),
        rec("reporting_period", { display_state: "not_detected" }),
        rec("gas:co2", { suggestion: sug("Included") }),
        rec("gas:n2o", { display_state: "not_detected" }),
        rec("category:scope1:stationary", { suggestion: sug("Yes") }),
        rec("category:scope1:mobile", { display_state: "not_detected" }),
        rec("gwp", { suggestion: sug({ set: "AR5", horizon: null }) }),
      ],
    };
  }
  beforeEach(() => window.localStorage.clear());

  it("summarises only what the suggestions hold, and lists what was not found as chips", async () => {
    await open(vi.fn(), summaryFixture());
    const s = screen.getByRole("region", { name: "Summary of the read" });
    expect(s.textContent).toContain("Summary of GHG report.pdf · read by Sustentra's AI · Nov 1, 2026");
    expect(s.textContent).toContain("Boundary: Operational Control. Reporting period: not found.");
    expect(s.textContent).toContain("Gases: CO₂ included; N₂O not found.");
    expect(s.textContent).toContain("Scope 1: stationary combustion.");
    expect(s.textContent).toContain("GWP: AR5 (horizon not stated).");
    expect(s.textContent).toContain("3 items:");
    for (const name of ["Reporting period", "N₂O", "Mobile Combustion"]) expect(within(s).getByRole("button", { name })).toBeTruthy();
    expect(document.body.textContent).not.toMatch(/Claude|claude/);
  });

  it("uses one count for the header and the summary: suggestions waiting for review", async () => {
    await open(vi.fn(), summaryFixture());
    expect(screen.getByText("4 suggested, waiting for review")).toBeTruthy();
    expect(screen.getByRole("region", { name: "Summary of the read" }).textContent).toContain("4 values suggested, waiting for review");
  });

  it("remembers per engagement that the summary is collapsed, and works when storage is blocked", async () => {
    await open(vi.fn(), summaryFixture());
    fireEvent.click(screen.getByRole("button", { name: "Hide summary" }));
    expect(window.localStorage.getItem("s1.methodologySummary.collapsed.e1")).toBe("1");
    expect(screen.queryByText("What it found")).toBeNull();
    cleanup();
    await open(vi.fn(), summaryFixture());
    expect(screen.getByRole("button", { name: "Show summary" })).toBeTruthy();
    cleanup();
    window.localStorage.clear();
    const get = vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    const set = vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    try {
      await open(vi.fn(), summaryFixture());
      fireEvent.click(screen.getByRole("button", { name: "Hide summary" }));
      expect(screen.getByRole("button", { name: "Show summary" })).toBeTruthy();
    } finally {
      get.mockRestore();
      set.mockRestore();
    }
  });

  it("draws each section as a table: left-aligned header row, one body per field, gases by chemical name", async () => {
    await open(vi.fn(), summaryFixture());
    const gases = screen.getByRole("heading", { name: "Gases covered" }).closest(".s1-mr-group") as HTMLElement;
    const table = within(gases).getByRole("table");
    expect(within(table).getAllByRole("columnheader").map((h) => h.textContent)).toEqual(["Gas", "Value", "Source", "Actions"]  /* no Status column while no row has a status */);
    expect(within(table).getByRole("rowheader", { name: "CO₂" })).toBeTruthy();
    expect(within(table).getByRole("rowheader", { name: "N₂O" })).toBeTruthy();
    const scope1 = screen.getByRole("heading", { name: "Scope 1 emission categories" }).closest(".s1-mr-group") as HTMLElement;
    expect(within(within(scope1).getByRole("table")).getAllByRole("columnheader").map((h) => h.textContent)).toEqual(["Category", "Included", "Source", "Actions"]);
  });
});

describe("the matrix, entity and factor tables and the Add buttons in their headers", () => {
  const sug = (value: unknown) => ({ value, quote: "A quote that is long enough.", document_id: "d1", file_name: "GHG report.pdf", source_reference: { page_number: 4 }, origin: "ai", model: "m", request_id: "r", suggested_at: "2026-11-01T10:00:00Z" });
  const d0 = { group_label: "x", user_added: false };
  const rec = (id: string, extra: Record<string, unknown> = {}) => ({ field_id: id, user_added: false, suggestion: null, decision: null, history: [], ...extra });
  const full = () => ({
    ai: { enabled: true, reason_code: null, reason: null },
    groups: [
      { group: "boundary", label: "Organizational boundary" },
      { group: "scope2", label: "Scope 2 emission categories" },
      { group: "exclusions", label: "Exclusions" },
      { group: "factors", label: "Emission factors source" },
      { group: "gwp", label: "GWP factors source" },
    ],
    row_groups: ["entities", "factor:scope1", "factor:scope2", "gwp"],
    catalog: [
      { ...d0, field_id: "reporting_period", group: "boundary", label: "Reporting period", kind: "date_range" },
      { ...d0, field_id: "consolidation_approach", group: "boundary", label: "Consolidation approach", kind: "enum", allowed: ["Operational Control"] },
      { ...d0, field_id: "boundary:acquisitions", group: "boundary", label: "Acquisitions and divestitures", kind: "text" },
      { ...d0, field_id: "exclusion:boundary", group: "exclusions", label: "Excluded from organizational boundary", kind: "text" },
      { ...d0, field_id: "exclusion:inventory", group: "exclusions", label: "Excluded from this inventory", kind: "text" },
      ...["electricity", "heating", "steam", "cooling"].flatMap((k) => [
        { ...d0, field_id: `category:location:${k}`, group: "scope2", label: `Location-based Purchased ${k[0].toUpperCase()}${k.slice(1)}`, kind: "enum", allowed: ["Yes", "No"] },
        { ...d0, field_id: `category:market:${k}`, group: "scope2", label: `Market-based Purchased ${k[0].toUpperCase()}${k.slice(1)}`, kind: "enum", allowed: ["Yes", "No"] },
      ]),
      { ...d0, field_id: "scope2:instruments", group: "scope2", label: "Scope 2 instrument types (market-based)", kind: "multiselect", allowed: ["PPA or VPPA"] },
      { ...d0, field_id: "entity:e1", group: "boundary", label: "Entity", kind: "entity", user_added: true },
      { ...d0, field_id: "entity:e2", group: "boundary", label: "Entity", kind: "entity", user_added: true },
      { ...d0, field_id: "factor:scope1:f1", group: "factors", label: "Scope 1 emission factor source", kind: "factor", user_added: true },
      { ...d0, field_id: "gwp", group: "gwp", label: "GWP factors source", kind: "gwp", allowed: { set: ["AR5"], horizon: ["100-year"] }, allowed_labels: { set: { AR5: "IPCC Fifth Assessment Report (AR5)" } } },
    ],
    fields: [
      rec("reporting_period"),
      rec("consolidation_approach"),
      rec("boundary:acquisitions"),
      rec("exclusion:boundary"),
      rec("exclusion:inventory"),
      ...["electricity", "heating", "steam", "cooling"].flatMap((k) => [
        rec(`category:location:${k}`, k === "electricity" ? { suggestion: sug("Yes") } : {}),
        rec(`category:market:${k}`),
      ]),
      rec("scope2:instruments"),
      rec("entity:e1", { suggestion: sug({ name: "Cascade Provisions Co.", facilities: ["Kent", "Tualatin"], equity_share_pct: 100, included: "Yes" }) }),
      rec("entity:e2"),
      rec("factor:scope1:f1", { suggestion: sug({ database: "EPA GHG Emission Factors Hub", edition: "2025" }) }),
      rec("gwp", { suggestion: sug({ set: "AR5", horizon: null }) }),
    ],
  });

  it("puts the boundary exclusion with the boundary, after the entities and before the other exclusions", async () => {
    await open(vi.fn(), full());
    const boundary = screen.getByRole("button", { name: "Organizational boundary" }).closest(".s1-mr-group") as HTMLElement;
    expect(within(boundary).getByText("Excluded from organizational boundary")).toBeTruthy();
    const text = boundary.textContent ?? "";
    expect(text.indexOf("Entities")).toBeLessThan(text.indexOf("Excluded from organizational boundary"));
    expect(text.indexOf("Excluded from organizational boundary")).toBeLessThan(text.indexOf("Acquisitions and divestitures"));
    const exclusions = screen.getByRole("button", { name: "Exclusions" }).closest(".s1-mr-group") as HTMLElement;
    expect(within(exclusions).queryByText("Excluded from organizational boundary")).toBeNull();
    expect(within(exclusions).getByText("Excluded from this inventory")).toBeTruthy();
  });

  it("draws Scope 2 as a matrix: electricity, steam, heating, cooling by location-based and market-based; instruments follow", async () => {
    await open(vi.fn(), full());
    const scope2 = screen.getByRole("button", { name: "Scope 2 emission categories" }).closest(".s1-mr-group") as HTMLElement;
    const tables = within(scope2).getAllByRole("table");
    expect(within(tables[0]).getAllByRole("columnheader").map((h) => h.textContent)).toEqual(["Category", "Location-based", "Market-based"]);
    expect(within(tables[0]).getAllByRole("rowheader").map((h) => h.textContent)).toEqual(["Purchased Electricity", "Purchased Steam", "Purchased Heating", "Purchased Cooling"]);
    expect(within(tables[0]).getByRole("button", { name: "Accept: Location-based Purchased Electricity" })).toBeTruthy();
    expect(within(tables[1]).getByText("Scope 2 instrument types (market-based)")).toBeTruthy(); // right after the matrix
  });

  it("draws entities as Name | Included | Equity % with the Add button in the header, and labels an empty row", async () => {
    await open(vi.fn(), full());
    const block = screen.getByText("Entities").closest(".s1-mb-block") as HTMLElement;
    expect(within(block).getAllByRole("columnheader").map((h) => h.textContent)).toEqual(["Name", "Included", "Equity %", "Source", "Review · 0 of 2"]);
    const e1 = within(block).getByDisplayValue("Cascade Provisions Co.").closest("tbody") as HTMLElement;
    expect(e1.textContent).toContain("2 facilities");
    expect(within(e1).getByText("100%")).toBeTruthy();
    const names = within(block).getAllByLabelText(/^Name:/) as HTMLInputElement[];
    expect(names.map((n) => n.value)).toEqual(["Cascade Provisions Co.", ""]);
    expect(names[1].placeholder).toBe("New entity"); // never an unlabelled empty row
    fireEvent.click(within(block.querySelector(".s1-mb-subhead") as HTMLElement).getByRole("button", { name: "Add entity" }));
    await waitFor(() => expect(calls()).toContainEqual([`${BASE}/rows`, expect.objectContaining({ body: { group: "entities" } })]));
  });

  it("draws emission factor sources as Database | Edition, Scope 1 and Scope 2 apart, each with its Add button; no Identified by or Flag", async () => {
    await open(vi.fn(), full());
    const factors = screen.getByRole("button", { name: "Emission factors source" }).closest(".s1-mr-group") as HTMLElement;
    const heads = within(factors).getAllByRole("columnheader").map((h) => h.textContent);
    expect(heads.slice(0, 4)).toEqual(["Database", "Edition", "Source", "Actions"]);
    expect(heads).not.toContain("Identified by");
    expect(heads).not.toContain("Flag");
    expect(within(factors).getByText("EPA GHG Emission Factors Hub")).toBeTruthy();
    expect(within(factors).getByText("2025")).toBeTruthy();
    expect(within(factors).getAllByRole("button", { name: /^Add (Scope [12] factor row)$/ })).toHaveLength(2);
    expect(screen.getAllByRole("button", { name: "Add GWP set" })).toHaveLength(1);
  });

  it("shows the GWP set and a missing horizon as 100-year, assumed", async () => {
    await open(vi.fn(), full());
    const gwp = screen.getByRole("button", { name: "GWP factors source" }).closest(".s1-mr-group") as HTMLElement;
    expect(within(gwp).getAllByRole("columnheader").map((h) => h.textContent).slice(0, 4)).toEqual(["GWP set", "Time horizon", "Source", "Actions"]);
    expect(within(gwp).getByText("IPCC Fifth Assessment Report (AR5)")).toBeTruthy();
    expect(within(gwp).getByText("100-year (assumed — not stated)")).toBeTruthy();
  });
});

describe("the Status column", () => {
  it("shows only in a table where some row is accepted, edited or rejected, with the chip", async () => {
    await open();
    const boundary = screen.getByRole("button", { name: "Organizational boundary" }).closest(".s1-mr-group") as HTMLElement;
    expect(within(boundary).getAllByRole("columnheader").map((h) => h.textContent)).toContain("Status");
    expect(within(row("Reporting period")).getByText("Edited")).toBeTruthy();
  });

  it("gives the long-text expand control an accessible name", async () => {
    await open();
    for (const b of document.querySelectorAll(".s1-mb-expand")) expect(b.getAttribute("aria-label")).toMatch(/Show (more|less)/);
  });
});

describe("inline selects: the answer is chosen in the row, no free text", () => {
  const sug = (value: unknown) => ({ value, quote: "A quote that is long enough.", document_id: "d1", file_name: "GHG report.pdf", source_reference: { page_number: 4 }, origin: "ai", model: "m", request_id: "r", suggested_at: "2026-11-01T10:00:00Z" });
  const d0 = { group_label: "x", user_added: false };
  const rec = (id: string, extra: Record<string, unknown> = {}) => ({ field_id: id, user_added: false, suggestion: null, decision: null, history: [], ...extra });
  const data = () => ({
    ai: { enabled: true, reason_code: null, reason: null },
    groups: [
      { group: "boundary", label: "Organizational boundary" },
      { group: "gases", label: "Gases covered" },
      { group: "scope1", label: "Scope 1 emission categories" },
    ],
    row_groups: ["entities"],
    catalog: [
      { ...d0, field_id: "consolidation_approach", group: "boundary", label: "Consolidation approach", kind: "enum", allowed: ["Equity Share", "Financial Control", "Operational Control"] },
      { ...d0, field_id: "entity:e1", group: "boundary", label: "Entity", kind: "entity", user_added: true },
      { ...d0, field_id: "gas:co2", group: "gases", label: "Gas: CO2", kind: "enum", allowed: ["Included", "Declared absent", "Not mentioned"] },
      { ...d0, field_id: "gas:n2o", group: "gases", label: "Gas: N2O", kind: "enum", allowed: ["Included", "Declared absent", "Not mentioned"] },
      { ...d0, field_id: "category:scope1:mobile", group: "scope1", label: "Scope 1 Mobile Combustion", kind: "enum", allowed: ["Yes", "No", "Not detected"] },
    ],
    fields: [
      rec("consolidation_approach", { suggestion: sug("Operational Control") }),
      rec("entity:e1", { suggestion: sug({ name: "Cascade Provisions Co.", facilities: ["Kent"], equity_share_pct: 100, financial_control: null, included: "Yes" }) }),
      rec("gas:co2", { suggestion: sug("Included") }),
      rec("gas:n2o", { display_state: "not_detected" }),
      rec("category:scope1:mobile", { display_state: "not_detected" }),
    ],
  });
  const select = (label: string) => screen.getByRole("combobox", { name: `Choose: ${label}` }) as HTMLSelectElement;

  it("shows the suggestion as the selected value with its marker; Accept records it, picking another value is an Edit", async () => {
    await open(vi.fn(), data());
    const approach = select("Consolidation approach");
    expect(approach.value).toBe("Operational Control");
    expect(within(row("Consolidation approach")).getByText("Suggested by Sustentra's AI")).toBeTruthy();
    expect(Array.from(approach.options).map((o) => o.textContent)).toEqual(["Equity Share", "Financial Control", "Operational Control"]);
    fireEvent.change(approach, { target: { value: "Equity Share" } });
    await waitFor(() => expect(calls()).toContainEqual([`${BASE}/consolidation_approach/edit`, expect.objectContaining({ body: { value: "Equity Share" } })]));
    cleanup();
    vi.mocked(api).mockClear();
    await open(vi.fn(), data());
    fireEvent.click(screen.getByRole("button", { name: "Accept: Consolidation approach" }));
    await waitFor(() => expect(calls()).toContainEqual([`${BASE}/consolidation_approach/accept`, expect.objectContaining({ body: {} })]));
  });

  it("leaves a Not detected row undecided until a value is picked, and records the pick as an edit", async () => {
    await open(vi.fn(), data());
    const mobile = select("Scope 1 Mobile Combustion");
    expect(mobile.value).toBe("");
    expect(mobile.selectedOptions[0].textContent).toBe("Not detected");
    expect(calls()).toHaveLength(0);
    fireEvent.change(mobile, { target: { value: "Yes" } });
    await waitFor(() => expect(calls()).toContainEqual([`${BASE}/category%3Ascope1%3Amobile/edit`, expect.objectContaining({ body: { value: "Yes" } })]));
  });

  it("reads a gas nobody mentions as Not mentioned, and chooses Included / Declared absent / Not mentioned", async () => {
    await open(vi.fn(), data());
    const n2o = select("Gas: N2O");
    expect(n2o.selectedOptions[0].textContent).toBe("Not mentioned");
    expect(Array.from(n2o.options).map((o) => o.textContent)).toEqual(["Not mentioned", "Included", "Declared absent"]);
    fireEvent.change(n2o, { target: { value: "Declared absent" } });
    await waitFor(() => expect(calls()).toContainEqual([`${BASE}/gas%3An2o/edit`, expect.objectContaining({ body: { value: "Declared absent" } })]));
    expect(select("Gas: CO2").value).toBe("Included"); // the suggestion, awaiting Accept
  });

  it("is keyboard accessible: a native select with a name, reachable and not disabled, with the row's ⋯ menu beside it", async () => {
    await open(vi.fn(), data());
    const approach = select("Consolidation approach");
    approach.focus();
    expect(document.activeElement).toBe(approach);
    expect(approach.disabled).toBe(false);
    expect(within(row("Consolidation approach")).getByRole("button", { name: "More actions: Consolidation approach" })).toBeTruthy();
  });

  it("changes an entity's Included with a Yes / No / blank select and its name inline, sending the whole entity", async () => {
    await open(vi.fn(), data());
    const r = row("Entity");
    const included = within(r).getByLabelText("Included: Entity") as HTMLSelectElement;
    expect(Array.from(included.options).map((o) => o.textContent)).toEqual(["Not stated", "Yes", "No"]);
    fireEvent.change(included, { target: { value: "No" } });
    const whole = { name: "Cascade Provisions Co.", facilities: ["Kent"], equity_share_pct: 100, financial_control: null, included: "No" };
    await waitFor(() => expect(calls()).toContainEqual([`${BASE}/entity%3Ae1/edit`, expect.objectContaining({ body: { value: whole } })]));
    vi.mocked(api).mockClear();
    const name = within(r).getByLabelText("Name: Entity") as HTMLInputElement;
    fireEvent.change(name, { target: { value: "Cascade Provisions Inc." } });
    fireEvent.blur(name);
    await waitFor(() => expect(calls()).toContainEqual([`${BASE}/entity%3Ae1/edit`, expect.objectContaining({ body: { value: { ...whole, name: "Cascade Provisions Inc.", included: "Yes" } } })]));
  });

  it("shows Review · N of M in the entities header", async () => {
    await open(vi.fn(), data());
    expect(screen.getByRole("columnheader", { name: "Review · 0 of 1" })).toBeTruthy();
  });
});
