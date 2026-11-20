/* @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import "@testing-library/jest-dom/vitest";
import { act, fireEvent, render, screen, within } from "@testing-library/react";

import type { BackendDocumentLike } from "../adapters/evidenceAdapter";
import type { ProcessingRunView } from "../api/processingRuns";
import type { CalculationLine, EvidenceTree, TreeDocRow } from "../api/evidenceTree";
import { S1WorkpaperApp } from "../pages/S1WorkpaperApp";

/**
 * Moving a summary or workbook document (or any document of another type) onto a calculation line asks the
 * extraction queue to read it again as that line's type. The move is saved first, so a failed read leaves the
 * document where it was put, with the error on its row.
 */

const USER = { email: "m.osei@example.com", firstName: "Mary", role: "org_member" as const, orgSlug: "acme" };
const ENGAGEMENT_ROW = {
  id: "ENG-1", org_id: "ORG-1", name: "FY2025 inventory", client_name: "Acme Foods",
  reporting_period_start: "2025-01-01", reporting_period_end: "2025-12-31", status: "active",
  settings: { facilities: [{ facilityId: "FAC-KC01", name: "Kent" }] },
  created_at: "2026-10-01T00:00:00Z", updated_at: "2026-10-01T00:00:00Z",
};
const WORKBOOK_DOC: BackendDocumentLike = {
  document_id: "WB", file_name: "GHG workbook 工作簿.xlsx", mime_type: "application/vnd.ms-excel",
  uploaded_by: USER.email, uploaded_at: "2026-10-28T10:00:00Z", processing_status: "completed",
};

const KENT: CalculationLine = {
  key: "s1:stationary:natural-gas:fac-kc01", scope: "s1", category: "stationary", level2: "natural-gas",
  level2_label: "Natural gas", anchor_kind: "facility", anchor_id: "FAC-KC01", label: "Kent", facility_id: "FAC-KC01",
  created_by_user: false, family: "stationary", read_as_id: "CT-S1-FUELQTY", read_as: "Stationary fuel consumption record",
};
const counts = (documents: number) => ({ documents, values: 0, accepted: 0, to_review: 0, issues: 0, pct_accepted: 0 });
const row = (over: Partial<TreeDocRow> = {}): TreeDocRow => ({
  document_id: "WB", file_name: "GHG workbook 工作簿.xlsx", period_start: null, period_end: null, facility_id: null,
  facility_name: null, processing_status: "completed", detected_type: "Inventory workbook", also_in: [], values: 0,
  accepted: 0, flags: [], value_family: null, placement_from: "block:summary", ...over,
});

/** What the server's tree says: the workbook in Block 1, or (after the move) on the Kent line. */
function treeWith(placed: boolean): EvidenceTree {
  const onLine = row({ placement_from: KENT.key, detected_type: "Stationary fuel consumption record", values: 4 });
  return {
    blocks: {
      summary: placed ? [] : [row()], summary_counts: counts(placed ? 0 : 1), unassigned: [], unassigned_counts: counts(0),
      supporting: {
        scopes: [{ scope: "s1", label: "Scope 1", counts: counts(placed ? 1 : 0), categories: [{
          category: "stationary", label: "Stationary combustion", counts: counts(placed ? 1 : 0), level2s: [{
            level2: "natural-gas", label: "Natural gas", counts: counts(placed ? 1 : 0),
            lines: [{ line: KENT, counts: counts(placed ? 1 : 0), documents: placed ? [onLine] : [] }] }] }] }],
        unassigned: [],
      },
    },
    facilities: [{ facility_id: "FAC-KC01", name: "Kent" }], lines: [KENT], set_aside: [],
  };
}

const server: {
  placed: boolean;
  readRequest: () => Response;
  runs: ProcessingRunView[];
  requests: { key: string; body: unknown }[];
} = { placed: false, readRequest: () => json(500, {}), runs: [], requests: [] };

function json(status: number, body: unknown) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

const queuedRun = (over: Partial<ProcessingRunView> = {}): ProcessingRunView => ({
  run_id: "RUN-1", document_id: "WB", engagement_id: "ENG-1", evidence_id: null, status: "queued", started_at: null,
  completed_at: null, pipeline_version: "t", error: null, ...over,
});

const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
  const path = String(input).replace(/^\/api\/v1/, "");
  const method = init?.method ?? "GET";
  server.requests.push({ key: `${method} ${path}`, body: init?.body ? JSON.parse(String(init.body)) : undefined });
  if (path === "/auth/me") return json(200, { email: USER.email, role: USER.role });
  if (path === "/engagements") return json(200, { items: [ENGAGEMENT_ROW] });
  if (path === "/engagements/ENG-1/documents") return json(200, { items: [WORKBOOK_DOC] });
  if (path === "/engagements/ENG-1/processing-runs") return json(200, { engagement_id: "ENG-1", items: server.runs });
  if (path.startsWith("/engagements/ENG-1/workpaper-items")) return json(200, method === "PUT" ? {} : { items: [] });
  if (path.startsWith("/engagements/ENG-1/evidence-tree")) return json(200, treeWith(server.placed));
  if (path.startsWith("/engagements/ENG-1/evidence-activity")) return json(200, { items: [], next_cursor: null });
  if (path === "/engagements/ENG-1/documents/WB/placements" && method === "POST") {
    server.placed = true;
    return json(200, {
      document_id: "WB", payload: { documentId: "WB", placements: [{ from: "*", to: KENT.key }] },
      reread: { canonical_type_id: "CT-S1-FUELQTY", type_name: "Stationary fuel consumption record" },
    });
  }
  if (path === "/engagements/ENG-1/documents/WB/reread-state" && method === "POST") return json(200, { document_id: "WB", payload: {} });
  if (path === "/documents/WB/processing-runs" && method === "POST") return server.readRequest();
  return json(404, { detail: "Not found." });
});

async function settle() {
  for (let i = 0; i < 10; i += 1) {
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
  }
}

/** The reviewer moves the workbook onto the Kent line, through the dialog. */
async function moveWorkbookOntoKent() {
  render(<S1WorkpaperApp user={USER} />);
  await settle();
  fireEvent.click(document.querySelector(`.s1-side__item[title="Evidence"]`) as HTMLElement);
  await settle();
  fireEvent.click(screen.getByRole("button", { name: "Expand all" }));
  fireEvent.click(screen.getByRole("button", { name: "Actions for GHG workbook 工作簿.xlsx" }));
  fireEvent.click(screen.getByRole("menuitem", { name: "Move to…" }));
  const dialog = screen.getByRole("dialog");
  fireEvent.change(within(dialog).getByLabelText("Move to"), { target: { value: KENT.key } });
  expect(dialog).toHaveTextContent("The document will be read again as Stationary fuel consumption record.");
  expect(dialog).toHaveTextContent("start unreviewed");
  expect(dialog).toHaveTextContent("the earlier reading stays in the record");
  fireEvent.click(within(dialog).getByRole("button", { name: "Move" }));
  fireEvent.click(within(dialog).getByRole("button", { name: "Confirm move" }));
  await settle();
}

describe("a move onto a line of another type asks for a read as that type", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.stubGlobal("fetch", fetchMock);
    fetchMock.mockClear();
    server.placed = false;
    server.runs = [];
    server.requests = [];
    server.readRequest = () => json(500, { detail: "Not set up." });
  });
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.unstubAllEnvs();
    vi.useRealTimers();
    window.localStorage.clear();
  });

  it("saves the move, then queues the read with the line's type, and shows Re-reading as <type>… until it ends", async () => {
    server.readRequest = () => {
      server.runs = [queuedRun()];
      return json(202, queuedRun());
    };
    await moveWorkbookOntoKent();
    const read = server.requests.find((r) => r.key === "POST /documents/WB/processing-runs");
    expect(read?.body).toEqual({ canonical_type_id_override: "CT-S1-FUELQTY" });
    const order = server.requests.map((r) => r.key);
    expect(order.indexOf("POST /engagements/ENG-1/documents/WB/placements")).toBeLessThan(order.indexOf("POST /documents/WB/processing-runs"));
    expect(screen.getByText("Re-reading as Stationary fuel consumption record…")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "GHG workbook 工作簿.xlsx" })).toBeInTheDocument();
  });

  it("when the read fails, the document stays visible on the line with the error, and Try again asks once more", async () => {
    server.readRequest = () => json(422, { detail: "The file could not be read." });
    await moveWorkbookOntoKent();
    const failure = screen.getByText(/Couldn't re-read as Stationary fuel consumption record\./);
    expect(failure.closest("[role=alert]")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "GHG workbook 工作簿.xlsx" })).toBeInTheDocument(); // still on the page
    // the failure is kept on the server, with the reason, so it survives a reload
    const kept = server.requests.filter((r) => r.key === "POST /engagements/ENG-1/documents/WB/reread-state");
    expect(kept.map((r) => (r.body as { state: string }).state)).toEqual(["pending", "failed"]);
    expect((kept[1].body as { error: string }).error).toContain("could not be read");
    const reads = () => server.requests.filter((r) => r.key === "POST /documents/WB/processing-runs").length;
    expect(reads()).toBe(1);
    server.readRequest = () => json(200, queuedRun({ status: "completed" }));
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    await settle();
    expect(reads()).toBe(2);
    expect(screen.queryByText(/Couldn't re-read as/)).toBeNull();
  });
});
