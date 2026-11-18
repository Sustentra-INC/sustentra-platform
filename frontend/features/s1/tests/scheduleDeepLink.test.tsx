/* @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import "@testing-library/jest-dom/vitest";
import { act, cleanup, render, screen } from "@testing-library/react";

import type { BackendDocumentLike } from "../adapters/evidenceAdapter";
import { S1WorkpaperApp } from "../pages/S1WorkpaperApp";

/**
 * A reload or a shared link to a supporting schedule (or a review) opens it. The page waits for the
 * engagement and its documents, so the schedule is never asked for under a blank engagement id (which
 * the server answers 404, sending the reader to Evidence). Only a line the server says is missing
 * falls back to Evidence, with a plain notice.
 */

const USER = { email: "m.osei@example.com", firstName: "Mary", role: "org_member" as const, orgSlug: "acme" };

const ENGAGEMENT_ROW = {
  id: "ENG-1",
  org_id: "ORG-1",
  name: "FY2025 inventory",
  client_name: "Müller Käserei – Zürich",
  reporting_period_start: "2025-01-01",
  reporting_period_end: "2025-12-31",
  status: "active",
  settings: {},
  created_at: "2026-10-01T00:00:00Z",
  updated_at: "2026-10-01T00:00:00Z",
};

const DOC: BackendDocumentLike = {
  document_id: "DOC-1",
  file_name: "Rechnung März 電気.pdf",
  mime_type: "application/pdf",
  uploaded_by: "m.osei@example.com",
  uploaded_at: "2026-10-28T10:00:00Z",
  processing_status: "not_started",
};

const LINE_KEY = "s1:stationary:natural-gas:fac-zürich–電気";
const LINE_LABEL = "Erdgas Müller – Zürich 電気 (CO₂, °F)";

function schedule() {
  return {
    line: {
      key: LINE_KEY, scope: "scope1", category: "stationary", level2: "natural-gas", level2_label: "Natural gas",
      anchor_kind: "facility", anchor_id: "fac-1", label: LINE_LABEL, facility_id: "fac-1", created_by_user: false,
    },
    calculated: true,
    reporting_period: { start: "2025-01-01", end: "2025-12-31" },
    coverage: [], identifiers: [], values: [], history: [], rows: [], columns: [], identifier_groups: [],
  };
}

function json(status: number, body: unknown) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

/** Answers held back until the test releases them, so loading is observable. */
let releaseEngagements: () => void = () => {};
let releaseDocuments: () => void = () => {};
let engagementsGate: Promise<void>;
let documentsGate: Promise<void>;
let scheduleStatus = 200;
const requested: string[] = [];

const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
  const path = String(input).replace(/^\/api\/v1/, "");
  requested.push(path);
  if (path === "/auth/me") return json(200, { email: USER.email, role: USER.role });
  if (path === "/engagements") {
    await engagementsGate;
    return json(200, { items: [ENGAGEMENT_ROW] });
  }
  if (path === "/engagements/ENG-1/documents") {
    await documentsGate;
    return json(200, { items: [DOC] });
  }
  if (path.startsWith("/engagements/ENG-1/evidence-tree")) {
    return json(200, {
      blocks: { summary: [], unassigned: [], supporting: { scopes: [], unassigned: [] } },
      facilities: [], lines: [], set_aside: [],
    });
  }
  if (path === "/engagements/ENG-1/workpaper-items") return json(200, { items: [] });
  if (path === `/engagements/ENG-1/calculation-lines/${encodeURIComponent(LINE_KEY)}/schedule`) {
    return scheduleStatus === 200 ? json(200, schedule()) : json(scheduleStatus, { detail: "That line was not found." });
  }
  return json(404, { detail: "Not found." });
});

async function settle() {
  for (let i = 0; i < 8; i += 1) {
    await act(async () => {
      await Promise.resolve();
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
  }
}

const scheduleUrl = `/?view=schedule&e=ENG-1&line=${encodeURIComponent(LINE_KEY)}`;
const reviewUrl = "/?view=review&e=ENG-1&doc=DOC-1&value=candidate%3Aactivity_quantity";

beforeEach(() => {
  window.history.replaceState(null, "", "/");
  vi.stubGlobal("fetch", fetchMock);
  fetchMock.mockClear();
  requested.length = 0;
  scheduleStatus = 200;
  engagementsGate = new Promise<void>((resolve) => { releaseEngagements = resolve; });
  documentsGate = new Promise<void>((resolve) => { releaseDocuments = resolve; });
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  window.localStorage.clear();
});

describe("a schedule link opened cold", () => {
  it("waits for the workspace, then shows the schedule, never Evidence", async () => {
    window.history.replaceState(null, "", scheduleUrl);
    render(<S1WorkpaperApp user={USER} />);
    await settle();
    // Slow engagements answer: loading, no schedule request under a blank engagement, still on the schedule URL.
    expect(window.location.search).toContain("view=schedule");
    expect(requested.some((p) => p.includes("/calculation-lines/"))).toBe(false);
    expect(screen.queryByRole("heading", { name: "Evidence" })).toBeNull();

    releaseEngagements();
    await settle();
    // Slow documents answer: still loading, still on the schedule.
    expect(window.location.search).toContain("view=schedule");
    expect(screen.queryByRole("heading", { name: "Evidence" })).toBeNull();

    releaseDocuments();
    await settle();
    expect(window.location.search).toContain("view=schedule");
    expect(screen.queryByRole("heading", { name: "Evidence" })).toBeNull();
    expect(screen.queryByText("Couldn't open that schedule")).toBeNull();
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(LINE_LABEL);
    expect(requested.filter((p) => p.includes("//"))).toEqual([]);
  });

  it("a line the server says is missing falls back to Evidence with the notice", async () => {
    scheduleStatus = 404;
    window.history.replaceState(null, "", scheduleUrl);
    render(<S1WorkpaperApp user={USER} />);
    releaseEngagements();
    releaseDocuments();
    await settle();
    expect(window.location.search).toContain("view=evidence");
    expect(screen.getByText("Couldn't open that schedule")).toBeInTheDocument();
  });
});

describe("a review link opened cold", () => {
  it("lands on the document, not Evidence", async () => {
    window.history.replaceState(null, "", reviewUrl);
    render(<S1WorkpaperApp user={USER} />);
    await settle();
    expect(window.location.search).toContain("view=review");
    releaseEngagements();
    releaseDocuments();
    await settle();
    expect(window.location.search).toContain("view=review");
    expect(window.location.search).toContain("doc=DOC-1");
    expect(screen.queryByText("Couldn't open that document")).toBeNull();
  });
});
