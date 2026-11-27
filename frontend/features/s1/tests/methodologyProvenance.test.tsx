/* @vitest-environment jsdom */
import "@testing-library/jest-dom/vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

// Methodology review rows say who read or decided them. The suggestion's origin says whether it was the AI or the rules;
// a value the client stated is never "Accepted by" a person. MVP-237's "Read in part" and conflict texts stay beside the label.

const mock = vi.hoisted(() => ({ data: null as unknown }));
vi.mock("../../../lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../../../lib/api")>()),
  api: vi.fn(() => Promise.resolve(mock.data)),
}));

import { BackendMethodologyReview, methodologyActivityFrom } from "../components/BackendMethodologyReview";

afterEach(cleanup);

const NOTE = "Read in part: pages 8–12 not read because this month's limit on Sustentra's AI and scans is reached.";
const done = { state: "done", file_names: ["GHG report.pdf"], reason: null, not_read: [{ document_id: "d1", file_name: "GHG report.pdf", truncated: true, not_read: "pages 8–12", note: NOTE }] };

type Rec = Record<string, unknown>;

function review(opts: { suggestion?: Rec | null; decision?: Rec | null; history?: Rec[]; autoRead?: unknown } = {}): Rec {
  const suggestion =
    opts.suggestion === null
      ? null
      : {
          value: "Operational Control",
          quote: "We use the operational control approach.",
          document_id: "d1",
          file_name: "GHG report.pdf",
          source_reference: { page_number: 4 },
          origin: "ai",
          model: "m",
          request_id: "r",
          suggested_at: "2026-11-01T10:00:00Z",
          ...opts.suggestion,
        };
  return {
    ai: { enabled: true, reason_code: null, reason: null },
    auto_read: opts.autoRead ?? null,
    groups: [{ group: "boundary", label: "Organizational boundary" }],
    row_groups: [],
    catalog: [{ field_id: "consolidation_approach", group: "boundary", group_label: "x", user_added: false, label: "Consolidation approach", kind: "enum", allowed: ["Equity Share", "Financial Control", "Operational Control"] }],
    fields: [{ field_id: "consolidation_approach", user_added: false, suggestion, decision: opts.decision ?? null, history: opts.history ?? [] }],
  };
}

const decision = (status: string, login: string, name: string) => ({ status, value: "Operational Control", by: { name, login }, at: "2026-11-02T10:00:00Z" });

async function show(data: Rec) {
  mock.data = data;
  render(<BackendMethodologyReview engagementId="e1" onOpenDocument={vi.fn()} />);
  await screen.findByText("Consolidation approach");
}

describe("Methodology review rows", () => {
  it("a pending AI suggestion reads Read by AI", async () => {
    await show(review());
    expect(screen.getByText("Read by AI")).toBeInTheDocument();
    expect(screen.queryByText(/Accepted by/)).toBeNull();
  });

  it("a pending rules suggestion reads Read by system rules, not Read by AI", async () => {
    await show(review({ suggestion: { origin: "rules" } }));
    expect(screen.getByText("Read by system rules")).toBeInTheDocument();
    expect(screen.queryByText("Read by AI")).toBeNull();
  });

  it("a suggestion of an unknown origin carries no label", async () => {
    await show(review({ suggestion: { origin: "something else" } }));
    expect(document.querySelectorAll("[data-provenance]")).toHaveLength(0);
  });

  it("a value the client stated reads Stated by client with its report page, never Accepted by the client", async () => {
    await show(review({ decision: decision("accepted", "company", "Cascade Provisions Co. (stated in report)") }));
    expect(screen.getByText(/^Stated by client · report p\. 4$/)).toBeInTheDocument();
    expect(screen.queryByText(/Cascade Provisions/)).toBeNull();
    expect(screen.queryByText(/Accepted by/)).toBeNull();
  });

  it("a person's decision reads their name, and a missing or Reviewer name reads a reviewer", async () => {
    await show(review({ decision: decision("accepted", "mosei", "M. Osei") }));
    expect(screen.getByText(/^Accepted by M\. Osei/)).toBeInTheDocument();
    cleanup();
    await show(review({ decision: decision("edited", "x", "Reviewer") }));
    expect(screen.getByText(/^Corrected by a reviewer/)).toBeInTheDocument();
  });

  it("keeps MVP-237's Read in part and conflict texts beside the label", async () => {
    await show(review({ autoRead: done, suggestion: { conflicting: true, conflict_note: "Part 2 says Yes (p. 4); part 7 says No (p. 31)" } }));
    expect(await screen.findByTestId("mr-read-in-part")).toHaveTextContent(NOTE);
    expect(screen.getByTestId("mr-conflict").textContent).toBe("The documents disagree: Part 2 says Yes (p. 4); part 7 says No (p. 31). Check both before you accept.");
    expect(screen.getByText("Read by AI")).toBeInTheDocument();
  });
});

describe("methodologyActivityFrom", () => {
  const data = (suggestion: Rec | null, history: Rec[]) =>
    review({ suggestion, history }) as unknown as Parameters<typeof methodologyActivityFrom>[0];
  const adapted = (r: Rec) => ({
    catalog: [{ fieldId: "f", label: "Approach" }],
    fields: [{ fieldId: "f", history: r.history, suggestion: r.suggestion }],
  }) as unknown as Parameters<typeof methodologyActivityFrom>[0];

  it("maps accept, edit and reject to a person's action, and leaves reverts and row changes unlabelled", () => {
    const history = ["accept", "edit", "reject", "revert", "add_row", "remove_row", "frobnicate"].map((action) => ({ at: "2026-11-02T10:00:00Z", by: { name: "M. Osei", login: "m" }, action }));
    const log = methodologyActivityFrom(adapted({ history, suggestion: null }));
    expect(log.map((e) => e.action)).toEqual(["accepted", "corrected", "rejected", undefined, undefined, undefined, undefined]);
    expect(log.slice(3).every((e) => e.source === undefined)).toBe(true);
  });

  it("a suggestion is Read by AI or system rules by its origin, and never a person's act", () => {
    for (const [origin, source] of [["ai", "ai"], ["rules", "system"], ["other", undefined]] as const) {
      const [entry] = methodologyActivityFrom(adapted({ history: [], suggestion: { origin, suggested_at: "2026-11-01T10:00:00Z" } }));
      expect(entry.source).toBe(source);
      expect(entry.action).toBeUndefined();
    }
    expect(data).toBeTypeOf("function");
  });
});
