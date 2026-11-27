/* @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

import type { BackendDocumentLike } from "../adapters/evidenceAdapter";
import type { EvidenceTree } from "../api/evidenceTree";
import { S1WorkpaperApp } from "../pages/S1WorkpaperApp";
import { viewToSearch } from "../utils/viewHistory";

/**
 * Whether a document is in Block 1 decides whether its review screen offers values: the app reads where each
 * document sits from the Evidence tree first. Until that is known the screen waits; if it cannot be read the
 * screen says so, with Retry. The document's type is never the answer.
 */

const USER = { email: "m.osei@example.com", firstName: "Mary", role: "org_member" as const, orgSlug: "acme" };
const ENGAGEMENT_ROW = {
  id: "ENG-1", org_id: "ORG-1", name: "FY2025 inventory", client_name: "Acme Foods",
  reporting_period_start: "2025-01-01", reporting_period_end: "2025-12-31", status: "active",
  settings: { facilities: [{ facilityId: "FAC-KC01", name: "Kent" }] },
  created_at: "2026-10-01T00:00:00Z", updated_at: "2026-10-01T00:00:00Z",
};
// A summary-type document (a workbook) that a reviewer moved onto a calculation line in Block 3.
const DOC: BackendDocumentLike = {
  document_id: "WB", evidence_id: "EV-1", file_name: "GHG workbook.xlsx", mime_type: "application/vnd.ms-excel",
  uploaded_by: USER.email, uploaded_at: "2026-10-28T10:00:00Z", processing_status: "completed",
} as BackendDocumentLike;
const counts = (documents: number) => ({ documents, values: 0, accepted: 0, to_review: 0, issues: 0, pct_accepted: 0 });
const row = (placement_from: string) => ({
  document_id: "WB", file_name: "GHG workbook.xlsx", period_start: null, period_end: null, facility_id: null,
  facility_name: null, processing_status: "completed", detected_type: "Inventory workbook", also_in: [], values: 1,
  accepted: 0, flags: [], value_family: null, placement_from,
});
const LINE = {
  key: "s1:stationary:natural-gas:fac-kc01", scope: "s1", category: "stationary", level2: "natural-gas",
  level2_label: "Natural gas", anchor_kind: "facility", anchor_id: "FAC-KC01", label: "Kent", facility_id: "FAC-KC01",
  created_by_user: false, family: "stationary", read_as_id: null, read_as: null,
};
function tree(inBlock: "summary" | "line"): EvidenceTree {
  return {
    blocks: {
      summary: inBlock === "summary" ? [row("block:summary")] : [], summary_counts: counts(inBlock === "summary" ? 1 : 0),
      unassigned: [], unassigned_counts: counts(0),
      supporting: {
        scopes: [{ scope: "s1", label: "Scope 1", counts: counts(1), categories: [{ category: "stationary", label: "Stationary combustion", counts: counts(1), level2s: [{
          level2: "natural-gas", label: "Natural gas", counts: counts(1),
          lines: [{ line: LINE, counts: counts(1), documents: inBlock === "line" ? [row(LINE.key)] : [] }] }] }] }],
        unassigned: [],
      },
    },
    facilities: [{ facility_id: "FAC-KC01", name: "Kent" }], lines: [LINE], set_aside: [],
  } as unknown as EvidenceTree;
}

const server: { tree: "pending" | "error" | "summary" | "line"; treeCalls: number } = { tree: "line", treeCalls: 0 };
const json = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
  const path = String(input).replace(/^\/api\/v1/, "");
  if (path === "/auth/me") return json(200, { email: USER.email, role: USER.role });
  if (path === "/engagements") return json(200, { items: [ENGAGEMENT_ROW] });
  if (path === "/engagements/ENG-1/documents") return json(200, { items: [DOC] });
  if (path === "/engagements/ENG-1/processing-runs") return json(200, { engagement_id: "ENG-1", items: [] });
  if (path.startsWith("/engagements/ENG-1/workpaper-items")) return json(200, { items: [] });
  if (path.startsWith("/engagements/ENG-1/evidence-activity")) return json(200, { items: [], next_cursor: null });
  if (path.startsWith("/engagements/ENG-1/evidence-tree")) {
    server.treeCalls += 1;
    if (server.tree === "pending") return new Promise<Response>(() => undefined);
    if (server.tree === "error") return json(500, { detail: "The evidence service is not answering." });
    return json(200, tree(server.tree));
  }
  if (path === "/pipeline/evidence/EV-1/latest-run") {
    return json(200, { evidence_id: "EV-1", document_id: "WB", canonical_type_id: "CT-GHG-WORKBOOK", target_count: 1, candidate_count: 1, found_candidate_count: 1, status: "completed" });
  }
  if (path === "/documents/WB/extraction-result/latest") {
    return json(200, {
      evidence_id: "EV-1", document_id: "WB", canonical_type_id: "CT-GHG-WORKBOOK", candidate_count: 1,
      items: [{ candidate_id: "c1", evidence_id: "EV-1", document_id: "WB", field_name: "reported_total", display_label: "Reported total", normalized_value: 500, unit: "t", source_reference: { page_number: 1 } }],
    });
  }
  if (path === "/documents/WB/reviews") return json(200, []);
  return json(404, { detail: "Not found." });
});

beforeEach(() => {
  vi.stubGlobal("fetch", fetchMock);
  fetchMock.mockClear();
  server.tree = "line";
  server.treeCalls = 0;
  window.matchMedia = ((q: string) => ({ matches: false, media: q, addEventListener() {}, removeEventListener() {} })) as unknown as typeof window.matchMedia;
  Element.prototype.scrollTo = (() => {}) as unknown as typeof Element.prototype.scrollTo;
  window.history.replaceState(null, "", `/?${viewToSearch({ name: "extraction", documentId: "WB", mode: "snippet", nodeKey: "N" })}`);
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  window.localStorage.clear();
});

describe("a document's review screen waits for where it sits", () => {
  it("shows a loading state, and no values to accept, while the placements are pending", async () => {
    server.tree = "pending";
    const { container } = render(<S1WorkpaperApp user={USER} />);
    expect(await screen.findByRole("status", { name: "Loading document" })).toBeInTheDocument();
    expect(container.querySelector(".s1-xr-card")).toBeNull();
    expect(screen.queryByText(/Company-prepared summary document\./)).toBeNull();
  });

  it("says so when the placements cannot be read, with Retry that loads them", async () => {
    server.tree = "error";
    const { container } = render(<S1WorkpaperApp user={USER} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("The evidence service is not answering.");
    expect(container.querySelector(".s1-xr-card")).toBeNull();
    server.tree = "line";
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    await waitFor(() => expect(container.querySelectorAll(".s1-xr-card").length).toBeGreaterThan(0));
  });

  it("shows a summary-type document's values once the tree places it in Block 3", async () => {
    server.tree = "line";
    const { container } = render(<S1WorkpaperApp user={USER} />);
    await waitFor(() => expect(container.querySelectorAll(".s1-xr-card").length).toBeGreaterThan(0));
    expect(screen.queryByText(/Company-prepared summary document\./)).toBeNull();
  });

  it("offers no values for the same document when the tree places it in Block 1", async () => {
    server.tree = "summary";
    const { container } = render(<S1WorkpaperApp user={USER} />);
    await waitFor(() => expect(fetchMock.mock.calls.some(([p]) => String(p).includes("/evidence-tree"))).toBe(true));
    await waitFor(() => expect(screen.queryByRole("status", { name: "Loading document" })).toBeNull());
    // the reference-document screen, not the values review: nothing to accept
    expect(container.querySelector(".s1-xr-card")).toBeNull();
    expect(screen.queryByRole("button", { name: /Accept/ })).toBeNull();
  });
});
