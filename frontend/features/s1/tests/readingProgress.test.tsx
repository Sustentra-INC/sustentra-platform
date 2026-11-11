/* @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import "@testing-library/jest-dom/vitest";
import { act, fireEvent, render, screen, within } from "@testing-library/react";

import type { BackendDocumentLike } from "../adapters/evidenceAdapter";
import { READ_FAILED_ON_OUR_SIDE, type ProcessingRunView } from "../api/processingRuns";
import { uploadDocumentWithProgress } from "../api/s1Backend";
import { EvidenceWorkspace } from "../components/EvidenceWorkspace";
import { HALT_REASONS } from "../constants/copy";
import { engagementConfig } from "../fixtures/engagementConfig";
import { manufacturerEvidence } from "../fixtures/evidence/manufacturerEvidence";
import { S1WorkpaperApp } from "../pages/S1WorkpaperApp";
import type { EvidenceItem } from "../types";
import { RUN_MESSAGE_CODES, readAfterUpload, withReadingState } from "../utils/readingState";

// The upload goes over XMLHttpRequest, which jsdom cannot serve; everything else is the real client.
vi.mock("../api/s1Backend", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../api/s1Backend")>()),
  uploadDocumentWithProgress: vi.fn(),
}));

// Recorded from the Evidence screen as it was before "Reading…" existed: the text of every
// Status cell of manufacturerEvidence, in screen order (every type group opened), then each
// group's status mix. Fixture mode must keep showing exactly this.
const MANUFACTURER_STATUS_CELLS = [
  "Extracting", "Extracting", "ExtractedPeriod outside reporting year", "Extracted", "Extracted", "Extracted",
  "Extracted", "BlockedScan is unreadable · no extractable text on any page.",
  "ExtractedPeriod outside reporting year", "Extracted", "Extracted", "Extracted", "Extracted", "Extracted",
  "Extracted", "Extracted", "Extracted", "Extracted", "Extracted", "Extracted", "Extracted", "Extracted",
  "Extracted", "Extracted", "Extracted", "Extracted", "Extracted",
  "ExtractedDuplicate of tualatin_electric_july_copy.pdf",
  "ExtractedDuplicate of tualatin_electric_jul_2025.pdf", "Extracted", "Extracted",
  "ExtractedConflicts with modesto_meter_aug_photo.jpg", "Extracted", "Extracted", "Extracted", "Extracted",
  "Extracted", "Extracted", "Extracted", "Extracted", "Extracted", "Extracted", "Extracted", "Extracted",
  "Extracted", "Extracted", "Extracted", "Extracted", "Extracted", "Extracted", "Extracted", "Extracted",
  "Extracted", "Extracted", "Extracted", "ExtractedSuperseded by tualatin_gas_apr_2025_corrected.pdf",
  "ExtractedSupersedes tualatin_gas_apr_2025.pdf", "Extracted", "Extracted", "Extracted", "Extracted",
  "Extracted", "Extracted", "Extracted", "Extracted", "Extracted", "Extracted", "Extracted", "Extracted",
  "Extracted", "Extracted", "Partially extractedNot found: Service period end date", "Extracted", "Extracted",
  "Extracted", "Extracted", "Extracted", "Extracted", "Extracted", "Extracted", "Extracted", "Extracted",
  "Extracted", "Extracted", "Extracted", "Extracted", "Extracted", "Extracted", "Extracted", "Extracted",
  "Extracted", "Extracted", "Extracted", "Extracted", "Extracted", "Extracted", "Extracted", "Extracted",
  "Extracted", "Extracted", "Extracted", "Extracted", "Extracted", "Extracted", "Extracted", "Extracted",
  "Extracted", "Extracted", "Extracted", "Extracted", "Extracted", "Extracted", "Extracted", "Extracted",
  "Extracted", "Extracted", "Extracted", "Extracted", "Extracted", "Extracted", "Extracted", "Extracted",
  "Extracted", "Extracted", "ExtractedConflicts with modesto_electric_aug_2025.pdf", "Extracted", "Extracted",
  "Extracted", "Extracted", "Extracted", "Extracted", "Extracted", "Extracted", "Extracted", "Extracted",
  "Extracted", "Extracted", "Extracted", "Extracted", "Extracted", "Extracted", "Extracted", "Extracted",
  "Extracted", "Extracted", "Extracted", "Extracted",
];

const MANUFACTURER_GROUP_MIX = [
  "2 to review", "5 extracted", "1 blocked3 to review33 extracted", "3 to review34 extracted", "4 extracted",
  "12 extracted", "3 extracted", "1 to review36 extracted", "2 extracted", "3 extracted", "1 extracted",
  "2 extracted", "1 extracted", "1 extracted",
];

/** A document just uploaded: the row the workspace shows before its read has produced anything. */
function uploadedRow(overrides: Partial<EvidenceItem> = {}): EvidenceItem {
  return {
    documentId: "DOC-1",
    filename: "sc-08.pdf",
    format: "pdf",
    uploadedBy: { id: "m.osei", name: "m.osei", actorType: "preparer" },
    uploadedAt: "2026-10-28T10:00:00Z",
    evidenceClass: "main",
    disposition: "active",
    processingState: "not_ingested",
    haltReason: null,
    detectedType: null,
    typeReviewBand: null,
    typeReviewReason: null,
    facilityState: "unresolved",
    facilityId: null,
    facilityName: null,
    facilityCount: null,
    periodState: "unresolved",
    periodStart: null,
    periodEnd: null,
    fieldsExpected: 0,
    fieldsExpectedDisplay: null,
    fieldsExtracted: 0,
    documentProperties: [],
    relationships: [],
    reviewArea: null,
    note: null,
    ...overrides,
  };
}

function run(overrides: Partial<ProcessingRunView> = {}): ProcessingRunView {
  return {
    run_id: "RUN-1",
    document_id: "DOC-1",
    engagement_id: "ENG-1",
    evidence_id: null,
    status: "queued",
    started_at: null,
    completed_at: null,
    pipeline_version: "abc1234",
    error: null,
    ...overrides,
  };
}

const TIMED_OUT = "Reading stopped before it finished. Try again later, or upload a smaller file.";

describe("withReadingState", () => {
  const rows = [uploadedRow(), uploadedRow({ documentId: "DOC-2", filename: "other.pdf" })];

  it("marks a document whose run is waiting or being read", () => {
    const [queued] = withReadingState(rows, { "DOC-1": run({ status: "queued" }) });
    const [inProgress] = withReadingState(rows, { "DOC-1": run({ status: "in_progress" }) });

    expect(queued.reading).toBe("queued");
    expect(inProgress.reading).toBe("in_progress");
  });

  it("leaves the other documents as they were", () => {
    const view = withReadingState(rows, { "DOC-1": run() });

    expect(view[1]).toBe(rows[1]);
    expect(view[1].reading).toBeUndefined();
  });

  it("says why a blocked document stopped, in the run's own words", () => {
    const blocked = [uploadedRow({ processingState: "blocked", haltReason: HALT_REASONS.pipeline })];

    const [view] = withReadingState(blocked, {
      "DOC-1": run({ status: "failed", error_code: "timed_out", error: TIMED_OUT }),
    });

    expect(view.haltReason).toBe(TIMED_OUT);
    expect(view.reading).toBeUndefined();
  });

  it.each(RUN_MESSAGE_CODES)("uses the run's message for %s", (code) => {
    const blocked = [uploadedRow({ processingState: "blocked", haltReason: HALT_REASONS.pipeline })];

    const [view] = withReadingState(blocked, {
      "DOC-1": run({ status: "failed", error_code: code, error: `The words for ${code}.` }),
    });

    expect(view.haltReason).toBe(`The words for ${code}.`);
  });

  it("keeps the document's own reason when the run failed for another cause", () => {
    const blocked = [uploadedRow({ processingState: "blocked", haltReason: HALT_REASONS.unreadable })];

    const view = withReadingState(blocked, {
      "DOC-1": run({ status: "failed", error_code: "unreadable_document", error: "Unreadable document: no text" }),
    });

    expect(view[0]).toBe(blocked[0]);
    expect(view[0].haltReason).toBe(HALT_REASONS.unreadable);
  });

  it("only rewords a document that is blocked", () => {
    const extracted = [uploadedRow({ processingState: "extracted" })];

    const view = withReadingState(extracted, {
      "DOC-1": run({ status: "failed", error_code: "timed_out", error: TIMED_OUT }),
    });

    expect(view[0]).toBe(extracted[0]);
  });

  it("returns the same array when there are no runs, or none that change anything", () => {
    expect(withReadingState(rows, {})).toBe(rows);
    expect(withReadingState(rows, { "DOC-1": run({ status: "completed" }), "DOC-9": run({ document_id: "DOC-9" }) })).toBe(
      rows
    );
  });
});

describe("readAfterUpload", () => {
  const stored: BackendDocumentLike = {
    document_id: "DOC-1",
    file_name: "sc-08.pdf",
    uploaded_by: "m.osei",
    uploaded_at: "2026-10-28T10:00:00Z",
    processing_status: "not_started",
  };

  it("uses the run the upload came back with, and asks for nothing", async () => {
    const request = vi.fn();
    const queued = run();

    await expect(readAfterUpload({ ...stored, processing_run: queued }, request)).resolves.toEqual({
      kind: "reading",
      run: queued,
    });
    const going = run({ status: "in_progress" });
    await expect(readAfterUpload({ ...stored, processing_run: going }, request)).resolves.toEqual({
      kind: "reading",
      run: going,
    });
    expect(request).not.toHaveBeenCalled();
  });

  it("asks for the read when the upload came back without a run", async () => {
    const completed = run({ status: "completed", evidence_id: "EV-1" });
    const request = vi.fn().mockResolvedValue(completed);

    await expect(readAfterUpload(stored, request)).resolves.toEqual({ kind: "done", run: completed });
    expect(request).toHaveBeenCalledWith("DOC-1");
  });

  it("says a read that failed in the request could not be read", async () => {
    const failed = run({ status: "failed", error: "Unreadable document: no text on any page" });
    const request = vi.fn().mockResolvedValue(failed);

    await expect(readAfterUpload(stored, request)).resolves.toEqual({
      kind: "failed",
      reason: `Uploaded, but could not be read: ${HALT_REASONS.unreadable}`,
    });
  });

  it("falls back to the plain sentence when a failed run has no reason", async () => {
    const request = vi.fn().mockResolvedValue(run({ status: "failed", error: null }));

    await expect(readAfterUpload(stored, request)).resolves.toEqual({
      kind: "failed",
      reason: `Uploaded, but could not be read: ${READ_FAILED_ON_OUR_SIDE}`,
    });
  });

  it("lets a failed request reach the caller", async () => {
    const request = vi.fn().mockRejectedValue(new Error("Network down."));

    await expect(readAfterUpload(stored, request)).rejects.toThrow("Network down.");
  });
});

function renderWorkspace(evidence = manufacturerEvidence) {
  const view = render(
    <EvidenceWorkspace
      engagement={engagementConfig}
      evidence={evidence}
      asks={[]}
      onSaveAsk={vi.fn()}
      onEvidenceChange={vi.fn()}
      onOpenExtraction={vi.fn()}
      onOpenUpload={vi.fn()}
    />
  );
  // Groups open on a click; open them all so every row is on screen.
  for (const head of view.container.querySelectorAll(".s1-ws-gr__head")) fireEvent.click(head);
  return view;
}

const statusCell = (container: HTMLElement) => container.querySelector("tbody tr td:nth-child(4)");

describe("Evidence screen: a document being read", () => {
  it("says Reading… and that it is waiting when its run is queued", () => {
    const { container } = renderWorkspace([uploadedRow({ reading: "queued" })]);

    expect(within(statusCell(container) as HTMLElement).getByText("Reading…")).toBeInTheDocument();
    expect(screen.getByText("Waiting to be read")).toBeInTheDocument();
  });

  it("says only Reading… once the read has started", () => {
    const { container } = renderWorkspace([uploadedRow({ reading: "in_progress" })]);

    expect(statusCell(container)).toHaveTextContent(/^Reading…$/);
    expect(screen.queryByText("Waiting to be read")).toBeNull();
  });

  it("shows a blocked document that is read again as being read, not as blocked", () => {
    const again = uploadedRow({
      processingState: "blocked",
      haltReason: HALT_REASONS.unreadable,
      reading: "in_progress",
    });
    const { container } = renderWorkspace([again]);

    // The row: only Reading…, with none of the earlier failure.
    expect(statusCell(container)).toHaveTextContent(/^Reading…$/);
    expect(screen.queryByText(HALT_REASONS.unreadable)).toBeNull();
    // The group's mix and the header count it as being read, not as blocked.
    expect(container.querySelector(".s1-ws-gr__mix")).toHaveTextContent(/^1 extracting$/);
    expect(container.querySelector(".s1-ws-count--blocking")).toHaveTextContent(/^0Blocked$/);
  });

  it("keeps a blocked document that is not being read blocked, and leaves one being read out of the filter", () => {
    const stuck = uploadedRow({
      documentId: "DOC-1",
      filename: "stuck.pdf",
      processingState: "blocked",
      haltReason: HALT_REASONS.unreadable,
    });
    const again = uploadedRow({
      documentId: "DOC-2",
      filename: "again.pdf",
      processingState: "blocked",
      haltReason: HALT_REASONS.unreadable,
      reading: "queued",
    });
    const { container } = renderWorkspace([stuck, again]);

    expect(container.querySelector(".s1-ws-count--blocking")).toHaveTextContent(/^1Blocked$/);
    expect(container.querySelector(".s1-ws-gr__mix")).toHaveTextContent("1 blocked");
    expect(container.querySelector(".s1-ws-gr__mix")).toHaveTextContent("1 extracting");
    expect(screen.getAllByText(HALT_REASONS.unreadable)).toHaveLength(1); // stuck.pdf's, not again.pdf's

    fireEvent.click(container.querySelector(".s1-ws-count--blocking") as HTMLElement);

    const shown = [...container.querySelectorAll(".s1-doc-link")].map((link) => link.textContent);
    expect(shown).toEqual(["stuck.pdf"]);
  });

  it("does not count a document being read among those that need you", () => {
    const waiting = renderWorkspace([uploadedRow()]);
    expect(waiting.container.querySelector(".s1-ws-gr__mix")).toHaveTextContent("1 to review");
    waiting.unmount();

    const reading = renderWorkspace([uploadedRow({ reading: "queued" })]);
    expect(reading.container.querySelector(".s1-ws-gr__mix")).toHaveTextContent("1 extracting");
  });
});

describe("Evidence screen: fixture parity", () => {
  it("shows manufacturerEvidence exactly as before", () => {
    const { container } = renderWorkspace();

    const rows = [...container.querySelectorAll("tbody tr")];
    expect(rows.map((row) => row.querySelectorAll(":scope > td")[3]?.textContent)).toEqual(MANUFACTURER_STATUS_CELLS);
    expect([...container.querySelectorAll(".s1-ws-gr__mix")].map((mix) => mix.textContent)).toEqual(
      MANUFACTURER_GROUP_MIX
    );
  });
});

// --- the page: uploads that don't wait, and reads that finish later -----------------------------

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

/** The reviewer sets the type of the (only) document on screen, which reads it again as that type. */
async function setTypeOfOnlyDocument() {
  openGroups();
  fireEvent.change(screen.getByLabelText("Set document type"), {
    target: { value: "Stationary fuel consumption record" },
  });
  await settle();
}

function openGroups() {
  for (const head of document.querySelectorAll(".s1-ws-gr__head")) fireEvent.click(head);
}

describe("S1WorkpaperApp: reads in the background", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.stubGlobal("fetch", fetchMock);
    fetchMock.mockClear();
    server.documents = [];
    server.runs = [];
    server.requests = [];
    server.readRequest = () => json(500, { detail: "Not set up." });
    vi.mocked(uploadDocumentWithProgress).mockReset();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.unstubAllEnvs();
    vi.useRealTimers();
    window.localStorage.clear();
  });

  it("goes on to the next file at once, then shows the read finishing without a reload", async () => {
    await openEvidence();
    const queued = run();
    vi.mocked(uploadDocumentWithProgress).mockResolvedValue({ ...STORED, processing_run: queued });
    server.documents = [STORED];
    server.runs = [queued];

    await uploadFiles("sc-08.pdf");

    // The upload is over and no read was asked for: the run came back with the upload.
    expect(server.requests).not.toContain("POST /documents/DOC-1/processing-runs");
    openGroups();
    expect(screen.getByText("Waiting to be read")).toBeInTheDocument();
    const row = document.querySelector("tbody tr") as HTMLElement;
    expect(within(row).getByText("Reading…")).toBeInTheDocument();

    // The reader takes it; the page follows, then shows what the read produced.
    server.runs = [run({ status: "in_progress", started_at: "2026-10-28T10:00:05Z" })];
    await advance(2000);
    expect(screen.queryByText("Waiting to be read")).toBeNull();
    expect(within(document.querySelector("tbody tr") as HTMLElement).getByText("Reading…")).toBeInTheDocument();

    server.documents = [{ ...STORED, processing_status: "completed" }];
    server.runs = [run({ status: "completed", evidence_id: "EV-1", completed_at: "2026-10-28T10:00:09Z" })];
    await advance(2000);
    expect(within(document.querySelector("tbody tr") as HTMLElement).queryByText("Reading…")).toBeNull();
    expect(within(document.querySelector("tbody tr") as HTMLElement).getByText("Extracted")).toBeInTheDocument();
    expect(screen.queryByRole("status")).toBeNull();
  });

  it("shows a failed read's reason in the Evidence banner, and keeps it through the refresh", async () => {
    await openEvidence();
    const queued = run();
    vi.mocked(uploadDocumentWithProgress).mockResolvedValue({ ...STORED, processing_run: queued });
    server.documents = [STORED];
    server.runs = [queued];
    await uploadFiles("sc-08.pdf");

    server.documents = [{ ...STORED, processing_status: "failed" }];
    server.runs = [
      run({ status: "failed", error_code: "unreadable_document", error: "Unreadable document: no text on any page" }),
    ];
    await advance(2000);

    const banner = screen.getByRole("status");
    expect(banner).toHaveTextContent("Couldn't read 1 file");
    expect(banner).toHaveTextContent(`sc-08.pdf: Uploaded, but could not be read: ${HALT_REASONS.unreadable}`);
    // The dialog's row says so too.
    const dialogRow = screen.getByText("sc-08.pdf", { selector: ".s1-upq__name" }).closest("li") as HTMLElement;
    expect(within(dialogRow).getByText("Failed")).toBeInTheDocument();
    // The list was loaded again after the failure (once), and the banner is still there after it.
    await advance(10_000);
    expect(screen.getByRole("status")).toHaveTextContent("Couldn't read 1 file");
  });

  it("keeps the banner for a file that wasn't read when a later read finishes and the list loads again", async () => {
    await openEvidence();
    const second: BackendDocumentLike = { ...STORED, document_id: "DOC-2", file_name: "b.pdf" };
    const secondRun = run({ run_id: "RUN-2", document_id: "DOC-2" });
    const firstFailed = run({ status: "failed", error_code: "unreadable_document", error: "Unreadable document: no text" });
    // a.pdf is read in the request and fails; b.pdf is only queued.
    vi.mocked(uploadDocumentWithProgress)
      .mockResolvedValueOnce({ ...STORED, file_name: "a.pdf" })
      .mockResolvedValueOnce({ ...second, processing_run: secondRun });
    server.readRequest = () => json(200, firstFailed);
    server.documents = [{ ...STORED, file_name: "a.pdf", processing_status: "failed" }, second];
    server.runs = [firstFailed, secondRun];
    await uploadFiles("a.pdf", "b.pdf");
    expect(screen.getByRole("status")).toHaveTextContent(
      `a.pdf: Uploaded, but could not be read: ${HALT_REASONS.unreadable}`
    );

    server.documents = [
      { ...STORED, file_name: "a.pdf", processing_status: "failed" },
      { ...second, processing_status: "completed" },
    ];
    server.runs = [firstFailed, { ...secondRun, status: "completed", evidence_id: "EV-2" }];
    await advance(2000);

    // The list loaded again for b.pdf, which clears the banner; a.pdf's line is put back.
    expect(server.requests.filter((request) => request === "GET /engagements/ENG-1/documents")).toHaveLength(3);
    expect(screen.getByRole("status")).toHaveTextContent("Couldn't read 1 file");
    expect(screen.getByRole("status")).toHaveTextContent("a.pdf: Uploaded, but could not be read");
    expect(screen.getByRole("status")).not.toHaveTextContent("b.pdf");
  });

  it("shows Reading… after a reload while the read is still going", async () => {
    server.documents = [STORED];
    server.runs = [run({ status: "in_progress", started_at: "2026-10-28T10:00:05Z" })];

    await openEvidence();
    openGroups();

    const row = document.querySelector("tbody tr") as HTMLElement;
    expect(within(row).getByText("Reading…")).toBeInTheDocument();
    expect(within(row).queryByText("Waiting to be read")).toBeNull();
  });

  it("reads inline as before: the read is asked for, and an unreadable file shows its reason", async () => {
    await openEvidence();
    vi.mocked(uploadDocumentWithProgress).mockResolvedValue(STORED); // no run came back
    server.readRequest = () =>
      json(200, run({ status: "failed", error_code: "unreadable_document", error: "Unreadable document: no text" }));
    server.documents = [{ ...STORED, processing_status: "failed" }];

    await uploadFiles("sc-08.pdf");

    expect(server.requests).toContain("POST /documents/DOC-1/processing-runs");
    expect(screen.getByRole("status")).toHaveTextContent("Couldn't read 1 file");
    expect(screen.getByRole("status")).toHaveTextContent(
      `sc-08.pdf: Uploaded, but could not be read: ${HALT_REASONS.unreadable}`
    );
  });

  it("reads inline as before: a file that is read is done", async () => {
    await openEvidence();
    vi.mocked(uploadDocumentWithProgress).mockResolvedValue(STORED);
    server.readRequest = () => json(200, run({ status: "completed", evidence_id: "EV-1" }));
    server.documents = [{ ...STORED, processing_status: "completed" }];

    await uploadFiles("sc-08.pdf");

    expect(screen.queryByRole("status")).toBeNull();
    const dialogRow = screen.getByText("sc-08.pdf", { selector: ".s1-upq__name" }).closest("li") as HTMLElement;
    expect(within(dialogRow).getByText("Done")).toBeInTheDocument();
  });

  it("says a file was uploaded but could not be read when asking for the read fails", async () => {
    await openEvidence();
    vi.mocked(uploadDocumentWithProgress).mockResolvedValue(STORED);
    server.readRequest = () => json(409, { detail: "This document is being read as another type." });
    server.documents = [STORED];

    await uploadFiles("sc-08.pdf");

    expect(screen.getByRole("status")).toHaveTextContent(
      "sc-08.pdf: Uploaded, but could not be read: This document is being read as another type."
    );
  });

  it("reads a document again as the type the reviewer set, and says if that read fails later", async () => {
    server.documents = [STORED];
    await openEvidence();
    server.readRequest = () => json(202, run({ run_id: "RUN-2", status: "queued" }));

    await setTypeOfOnlyDocument();

    expect(server.requests).toContain("POST /documents/DOC-1/processing-runs");
    openGroups(); // the document moved to the group of the type it was set to
    expect(within(document.querySelector("tbody tr") as HTMLElement).getByText("Reading…")).toBeInTheDocument();
    expect(screen.queryByRole("status")).toBeNull();

    server.documents = [{ ...STORED, processing_status: "failed" }];
    server.runs = [run({ run_id: "RUN-2", status: "failed", error_code: "timed_out", error: TIMED_OUT })];
    await advance(2000);

    const banner = screen.getByRole("status");
    expect(banner).toHaveTextContent("Couldn't read the document as that type");
    expect(banner).toHaveTextContent(TIMED_OUT);
  });

  it("says so when a read as another type fails in the request, after loading the list again", async () => {
    server.documents = [STORED];
    await openEvidence();
    server.readRequest = () =>
      json(200, run({ run_id: "RUN-2", status: "failed", error_code: "unreadable_document", error: "Unreadable document: no text" }));

    await setTypeOfOnlyDocument();

    const banner = screen.getByRole("status");
    expect(banner).toHaveTextContent("Couldn't read the document as that type");
    expect(banner).toHaveTextContent(HALT_REASONS.unreadable);
  });

  it("shows the API's reason when it refuses to read the document as another type", async () => {
    server.documents = [STORED];
    await openEvidence();
    server.readRequest = () => json(409, { detail: "This document is already being read as another type." });

    await setTypeOfOnlyDocument();

    const banner = screen.getByRole("status");
    expect(banner).toHaveTextContent("Couldn't read the document as that type");
    expect(banner).toHaveTextContent("This document is already being read as another type.");
  });

  it("fixture mode asks the API for nothing and schedules no poll", async () => {
    vi.stubEnv("NEXT_PUBLIC_S1_DATA_MODE", "fixture");
    window.localStorage.setItem("sustentra-demo-signedin", "1");

    render(<S1WorkpaperApp />);
    await settle();
    await advance(60_000);

    expect(fetchMock).not.toHaveBeenCalled();
  });
});
