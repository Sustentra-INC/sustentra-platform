/* @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import "@testing-library/jest-dom/vitest";
import { act, fireEvent, render, screen } from "@testing-library/react";

import type { BackendDocumentLike } from "../adapters/evidenceAdapter";
import type { ProcessingRunView } from "../api/processingRuns";
import { UploadInterruptedError, uploadDocumentWithProgress } from "../api/s1Backend";
import { S1WorkpaperApp } from "../pages/S1WorkpaperApp";

// The upload goes over XMLHttpRequest, which jsdom cannot serve; everything else is the real client.
vi.mock("../api/s1Backend", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../api/s1Backend")>()),
  uploadDocumentWithProgress: vi.fn(),
}));

function run(overrides: Partial<ProcessingRunView> = {}): ProcessingRunView {
  return {
    run_id: "RUN-1",
    engagement_id: "ENG-1",
    document_id: "DOC-1",
    status: "completed",
    ...overrides,
  } as ProcessingRunView;
}

const USER = { email: "m.osei@example.com", firstName: "Mary", role: "org_member" as const, orgSlug: "acme" };

const ENGAGEMENT_ROW = {
  id: "ENG-1",
  org_id: "ORG-1",
  name: "FY2025 inventory",
  client_name: "Acme Foods",
  reporting_period_start: "2025-01-01",
  reporting_period_end: "2025-12-31",
  status: "active",
  settings: {},
  created_at: "2026-10-01T00:00:00Z",
  updated_at: "2026-10-01T00:00:00Z",
};

const STORED: BackendDocumentLike = {
  document_id: "DOC-1",
  file_name: "sc-08.pdf",
  mime_type: "application/pdf",
  uploaded_by: "m.osei@example.com",
  uploaded_at: "2026-10-28T10:00:00Z",
  processing_status: "not_started",
};

/** What the API would answer, as the test sets it up. */
const server: {
  documents: BackendDocumentLike[];
  runs: ProcessingRunView[];
  /** The answer to POST /documents/{id}/processing-runs (a read asked for in the request). */
  readRequest: (documentId: string) => Response;
  requests: string[];
} = { documents: [], runs: [], readRequest: () => json(500, { detail: "Not set up." }), requests: [] };

function json(status: number, body: unknown) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
  const path = String(input).replace(/^\/api\/v1/, "");
  server.requests.push(`${init?.method ?? "GET"} ${path}`);
  if (path === "/auth/me") return json(200, { email: USER.email, role: USER.role });
  if (path === "/engagements") return json(200, { items: [ENGAGEMENT_ROW] });
  if (path === "/engagements/ENG-1/documents") return json(200, { items: server.documents });
  if (path === "/engagements/ENG-1/processing-runs") return json(200, { engagement_id: "ENG-1", items: server.runs });
  if (path === "/engagements/ENG-1/workpaper-items") return json(200, { items: [] });
  if (path.startsWith("/engagements/ENG-1/workpaper-items/") && init?.method === "PUT") return json(200, {});
  const readOf = path.match(/^\/documents\/([^/]+)\/processing-runs$/);
  if (readOf && init?.method === "POST") return server.readRequest(readOf[1]);
  return json(404, { detail: "Not found." });
});

async function settle() {
  for (let i = 0; i < 8; i += 1) {
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
  }
}

async function advance(ms: number) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
  await settle();
}

async function openEvidence() {
  render(<S1WorkpaperApp user={USER} />);
  await settle();
  fireEvent.click(sidebarItem("Evidence"));
  await settle();
  // These tests are about the table by document type (the tree has its own tests).
  fireEvent.click(screen.getByRole("button", { name: "By document type" }));
  await settle();
}

/** The sidebar's destinations (the page has other buttons with the same words). */
function sidebarItem(title: string): HTMLElement {
  return document.querySelector(`.s1-side__item[title="${title}"]`) as HTMLElement;
}

/** Opens the upload dialog and puts a file in it. */
async function uploadFiles(...names: string[]) {
  fireEvent.click(sidebarItem("Upload"));
  const input = document.querySelector<HTMLInputElement>('input[type="file"]');
  const files = names.map((name) => new File(["x"], name, { type: "application/pdf" }));
  fireEvent.change(input as HTMLInputElement, { target: { files } });
  await settle();
}


const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const mockUpload = vi.mocked(uploadDocumentWithProgress);

function pick(...names: string[]) {
  const input = document.querySelector<HTMLInputElement>('input[type="file"]');
  const files = names.map((name) => new File(["x"], name, { type: "application/pdf" }));
  fireEvent.change(input as HTMLInputElement, { target: { files } });
}

describe("S1WorkpaperApp: many files, safely", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.stubGlobal("fetch", fetchMock);
    fetchMock.mockClear();
    server.documents = [];
    server.runs = [];
    server.requests = [];
    server.readRequest = () => json(200, run());
    mockUpload.mockReset();
  });
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.useRealTimers();
    window.localStorage.clear();
  });

  it("sends the same upload id on a retry of the same file, so one document is stored", async () => {
    await openEvidence();
    const stored = new Map<string, BackendDocumentLike>();
    const seen: string[] = [];
    mockUpload.mockImplementation(async (_e, _f, _p, _b, clientId) => {
      seen.push(String(clientId));
      if (!stored.has(String(clientId))) stored.set(String(clientId), STORED); // the server stores it...
      if (seen.length === 1) throw new UploadInterruptedError(); // ...but the answer is lost
      return stored.get(String(clientId))!;
    });
    server.documents = [STORED];
    await uploadFiles("sc-08.pdf");
    await advance(1500); // the pause before the retry
    expect(seen).toHaveLength(2);
    expect(seen[0]).toMatch(UUID);
    expect(seen[1]).toBe(seen[0]);
    expect(stored.size).toBe(1);
    expect(document.querySelectorAll(".s1-upq__row")).toHaveLength(1);
    expect(screen.getByText("1 of 1 file uploaded and read")).toBeInTheDocument();
  });

  it("a second pick while one is uploading is refused with a plain line, not mixed in", async () => {
    await openEvidence();
    let release: (doc: BackendDocumentLike) => void = () => undefined;
    mockUpload.mockImplementationOnce(() => new Promise((resolve) => (release = resolve)));
    await uploadFiles("first.pdf");
    pick("second.pdf");
    await settle();
    expect(screen.getByText(/Another upload is still running/)).toBeInTheDocument();
    expect(mockUpload).toHaveBeenCalledTimes(1);
    expect(document.querySelectorAll(".s1-upq__row")).toHaveLength(1);
    expect(screen.getByText("first.pdf")).toBeInTheDocument();

    server.documents = [STORED];
    await act(async () => release(STORED));
    await settle();
    mockUpload.mockResolvedValueOnce({ ...STORED, document_id: "DOC-2", file_name: "second.pdf" });
    pick("second.pdf"); // once it is over, a new pick is taken
    await settle();
    expect(mockUpload).toHaveBeenCalledTimes(2);
    expect(screen.queryByText(/Another upload is still running/)).toBeNull();
  });

  it("asks before the tab is closed while files are going up, and stops asking after", async () => {
    await openEvidence();
    let release: (doc: BackendDocumentLike) => void = () => undefined;
    mockUpload.mockImplementationOnce(() => new Promise((resolve) => (release = resolve)));
    await uploadFiles("first.pdf");
    const during = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(during);
    expect(during.defaultPrevented).toBe(true);
    server.documents = [STORED];
    await act(async () => release(STORED));
    await settle();
    const after = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(after);
    expect(after.defaultPrevented).toBe(false);
  });

  it("stops sending when the app is left", async () => {
    await openEvidence();
    const view = document.body;
    let release: (doc: BackendDocumentLike) => void = () => undefined;
    mockUpload.mockImplementationOnce(() => new Promise((resolve) => (release = resolve)));
    await uploadFiles("first.pdf", "second.pdf");
    expect(view).toBeTruthy();
    // Unmounting (navigating away) aborts the run: the second file is never sent.
    const { cleanup } = await import("@testing-library/react");
    cleanup();
    await act(async () => release(STORED));
    await settle();
    expect(mockUpload).toHaveBeenCalledTimes(1);
  });
});
