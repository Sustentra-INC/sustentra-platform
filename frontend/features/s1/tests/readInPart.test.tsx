/* @vitest-environment jsdom */
import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// MVP-237: a read by Sustentra's AI that stopped before the end of a document says so, with the pages and the reason,
// wherever it is shown; a document read as several types, a facility read naming several facilities and methodology
// parts that disagree are shown, never resolved silently.

const mock = vi.hoisted(() => ({ data: null as unknown, prefill: null as unknown, polls: [] as unknown[] }));
vi.mock("../../../lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../../../lib/api")>()),
  api: vi.fn((path: string, options?: { method?: string }) => {
    if (path.endsWith("/prefill")) return Promise.resolve(mock.prefill);
    if (options?.method) return Promise.resolve({});
    if (mock.polls.length) mock.data = mock.polls.shift();
    return Promise.resolve(mock.data);
  }),
}));

import { BackendMethodologyReview } from "../components/BackendMethodologyReview";
import { AiFacilityNote } from "../components/AiFacilityNote";
import { AiTypeNote } from "../components/AiTypeNote";
import { mapBackendDocumentToEvidenceItem } from "../adapters/evidenceAdapter";

afterEach(cleanup);
beforeEach(() => {
  mock.prefill = null;
  mock.polls = [];
});

const NOTE = "Read in part: pages 8–12 not read because this month's limit on Sustentra's AI and scans is reached.";

function review(autoRead: unknown = null, suggestion: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    ai: { enabled: true, reason_code: null, reason: null },
    auto_read: autoRead,
    groups: [{ group: "boundary", label: "Organizational boundary" }],
    row_groups: [],
    catalog: [
      { field_id: "consolidation_approach", group: "boundary", group_label: "x", user_added: false, label: "Consolidation approach",
        kind: "enum", allowed: ["Equity Share", "Financial Control", "Operational Control"] },
    ],
    fields: [
      {
        field_id: "consolidation_approach",
        user_added: false,
        suggestion: { value: "Operational Control", quote: "We use the operational control approach.", document_id: "d1",
                      file_name: "GHG report.pdf", source_reference: { page_number: 4 }, origin: "ai", model: "m", request_id: "r",
                      suggested_at: "2026-11-01T10:00:00Z", ...suggestion },
        decision: null,
        history: [],
      },
    ],
  };
}

const done = {
  state: "done",
  file_names: ["GHG report.pdf"],
  reason: null,
  not_read: [{ document_id: "d1", file_name: "GHG report.pdf", truncated: true, not_read: "pages 8–12", note: NOTE }],
};

describe("Methodology review: a read in part", () => {
  it("shows the finished read's 'Read in part' sentence with its reason, in the muted note style", async () => {
    mock.data = review(done);
    render(<BackendMethodologyReview engagementId="e1" onOpenDocument={vi.fn()} />);
    const note = await screen.findByTestId("mr-read-in-part");
    expect(note.textContent).toBe(`GHG report.pdf: ${NOTE}`);
    expect(note).toHaveClass("s1-mr-muted");
  });

  it("starts the read, shows it reading, and shows the read in part once the poll finds it done", async () => {
    mock.data = review(null);
    mock.prefill = { state: "started", auto_read: { state: "reading", file_names: ["GHG report.pdf"], reason: null } };
    render(<BackendMethodologyReview engagementId="e1" onOpenDocument={vi.fn()} />);
    await screen.findByText("Consolidation approach");
    mock.polls = [review({ state: "reading", file_names: ["GHG report.pdf"], reason: null }), review(done)];
    fireEvent.click(screen.getByRole("button", { name: "Read the client's reports with Sustentra's AI" }));
    fireEvent.click(screen.getByRole("button", { name: "Read the reports" }));
    expect(await screen.findByText("Sustentra's AI is reading GHG report.pdf…")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByTestId("mr-read-in-part").textContent).toContain(NOTE), { timeout: 8000 });
  }, 10000);

  it("says nothing about a part when every document was read whole", async () => {
    mock.data = review({ ...done, not_read: [] });
    render(<BackendMethodologyReview engagementId="e1" onOpenDocument={vi.fn()} />);
    await screen.findByText("Consolidation approach");
    expect(screen.queryByTestId("mr-read-in-part")).toBeNull();
  });

  it("shows parts that disagree on a suggestion, with both pages", async () => {
    mock.data = review(null, { conflicting: true, conflict_note: "Part 2 says Yes (p. 4); part 7 says No (p. 31)" });
    render(<BackendMethodologyReview engagementId="e1" onOpenDocument={vi.fn()} />);
    const note = await screen.findByTestId("mr-conflict");
    expect(note.textContent).toBe("The documents disagree: Part 2 says Yes (p. 4); part 7 says No (p. 31). Check both before you accept.");
  });
});

describe("The type-to-check row and the facility card", () => {
  const document = { document_id: "DOC-1", file_name: "bundle.pdf", uploaded_by: "u", uploaded_at: "2026-11-11T00:00:00Z",
                     processing_status: "completed", evidence_id: "EV-1" };

  it("shows the other types the document's parts read as, and what the type read did not reach", () => {
    const item = mapBackendDocumentToEvidenceItem(document, {
      canonical_type_id: "CT-S2-ELEC",
      canonical_type_source: "ai",
      ai_routing: { canonical_type_id: "CT-S2-ELEC", quote: "Electric Statement", page_number: 1, used: true,
                    other_types: ["CT-S1-REFRSVC"], read_in_part: "pages 6–20" },
    });
    render(<AiTypeNote item={item} />);
    expect(screen.getByTestId("ai-type-others").textContent).toMatch(/^Parts of this document read as .+: it may hold several documents\.$/);
    expect(screen.getByTestId("ai-type-others").textContent).not.toMatch(/CT-/);
    expect(screen.getByTestId("ai-type-read-in-part").textContent).toBe("Read in part: pages 6–20 not read.");
  });

  it("shows the facility read's 'Read in part' line and every facility it found", () => {
    render(
      <AiFacilityNote facilityName="Fresno Plant" quote="Fresno Plant" where="page 2" onPlace={() => {}} readInPart="pages 7–20"
        candidates={[{ facility_id: "fac-fr", quote: "Fresno Plant", page: 2 }, { facility_id: "fac-tac", quote: "Tacoma Distribution Center", page: 18 }]} />
    );
    expect(screen.getByTestId("ai-facility-read-in-part").textContent).toBe("Read in part: pages 7–20 not read.");
    expect(screen.getByTestId("ai-facility-candidates").textContent).toBe(
      "The document points at more than one facility: “Fresno Plant” · page 2; “Tacoma Distribution Center” · page 18. Choose the right one.");
  });

  it("takes both from the server's explanation on the Evidence tree", () => {
    render(
      <AiFacilityNote facilityName="Fresno Plant" quote="Fresno Plant" where="page 2" onPlace={() => {}}
        explanation={{ reason: null, reason_note: null, items: [], read_in_part: "pages 7–20" }} />
    );
    expect(screen.getByTestId("ai-facility-read-in-part").textContent).toBe("Read in part: pages 7–20 not read.");
    expect(screen.queryByTestId("ai-facility-candidates")).toBeNull();
  });
});
