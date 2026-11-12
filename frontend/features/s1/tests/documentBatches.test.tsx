/* @vitest-environment jsdom */
import "@testing-library/jest-dom/vitest";
import { act, fireEvent, render, renderHook, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { BATCH_POLL_MS, type BatchDocument, type BatchView } from "../api/documentBatches";
import { BATCH_STATUS, BatchProgress } from "../components/BatchProgress";
import { UploadDialog } from "../components/UploadDialog";
import { useBatchProgress } from "../hooks/useBatchProgress";
import { findBlockedUiTerms } from "../utils/copyCompliance";

const fetchMock = vi.fn();

function doc(overrides: Partial<BatchDocument> = {}): BatchDocument {
  return {
    document_id: "DOC-1",
    file_name: "march-bill.pdf",
    status: "done",
    chunks: null,
    canonical_type_id: "CT-S1-FUELQTY",
    halt_reason: null,
    records_found: 4,
    ...overrides,
  };
}

function batch(items: BatchDocument[], overrides: Partial<BatchView> = {}): BatchView {
  const totals = { queued: 0, reading: 0, done: 0, partial: 0, failed: 0 };
  for (const item of items) totals[item.status] += 1;
  return {
    batch_id: "B1",
    engagement_id: "ENG-1",
    label: null,
    items,
    totals,
    complete: totals.queued + totals.reading === 0,
    ...overrides,
  };
}

function reply(view: BatchView) {
  return new Response(JSON.stringify(view), { status: 200, headers: { "Content-Type": "application/json" } });
}

beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe("batch progress table", () => {
  const mixed = batch([
    doc(),
    doc({ document_id: "DOC-2", file_name: "scan.pdf", status: "failed", canonical_type_id: null, records_found: 0,
          halt_reason: "Unreadable document." }),
    doc({ document_id: "DOC-3", file_name: "big.pdf", status: "reading", records_found: 0, canonical_type_id: null,
          chunks: { total: 8, completed: 3, failed: 1, failed_pages: [[11, 20]] } }),
    doc({ document_id: "DOC-4", file_name: "later.pdf", status: "queued", records_found: 0, canonical_type_id: null }),
    doc({ document_id: "DOC-5", file_name: "long.pdf", status: "partial", records_found: 2,
          halt_reason: "Pages 11-20 could not be read." }),
  ]);

  it("shows each file's status, type, records, reason and chunk progress, and the totals", () => {
    render(<BatchProgress batch={mixed} onOpenDocument={vi.fn()} />);
    const rows = screen.getAllByRole("row").slice(1);
    expect(rows).toHaveLength(5);
    expect(within(rows[0]).getByText("Done")).toBeInTheDocument();
    expect(within(rows[0]).getByText("Stationary fuel consumption record")).toBeInTheDocument();
    expect(within(rows[0]).getByText("4")).toBeInTheDocument();
    expect(within(rows[1]).getByText("Couldn't read")).toBeInTheDocument();
    expect(within(rows[1]).getByText("Unreadable document.")).toBeInTheDocument();
    expect(within(rows[2]).getByText("Reading")).toBeInTheDocument();
    expect(within(rows[2]).getByText("3 of 8 parts read, 1 failed")).toBeInTheDocument();
    expect(within(rows[3]).getByText("Waiting")).toBeInTheDocument();
    expect(within(rows[4]).getByText("Partly read")).toBeInTheDocument();
    expect(within(rows[4]).getByText("Pages 11-20 could not be read.")).toBeInTheDocument();
    expect(screen.getByText("1 waiting · 1 reading · 1 done · 1 partly read · 1 couldn't read")).toBeInTheDocument();
  });

  it("links a read file to its extraction review, and not a file still waiting or reading", () => {
    const open = vi.fn();
    render(<BatchProgress batch={mixed} onOpenDocument={open} />);
    fireEvent.click(screen.getByRole("button", { name: "march-bill.pdf" }));
    fireEvent.click(screen.getByRole("button", { name: "scan.pdf" }));
    expect(open.mock.calls).toEqual([["DOC-1"], ["DOC-2"]]);
    expect(screen.queryByRole("button", { name: "big.pdf" })).toBeNull();
    expect(screen.queryByRole("button", { name: "later.pdf" })).toBeNull();
  });

  it("uses words the copy rules allow", () => {
    const words = Object.values(BATCH_STATUS).map((s) => s.label).join(" ");
    expect(findBlockedUiTerms(words)).toEqual([]);
    render(<BatchProgress batch={mixed} onOpenDocument={vi.fn()} />);
    expect(findBlockedUiTerms(document.body.textContent ?? "")).toEqual([]);
  });

  it("appears in the upload dialog only for a batch with files", () => {
    const props = { onClose: vi.fn(), onUploadFiles: vi.fn(), batch: [], tasks: [], onOpenWorkspace: vi.fn() };
    const { rerender } = render(<UploadDialog {...props} batchProgress={batch([])} onOpenDocument={vi.fn()} />);
    expect(screen.queryByText("Reading this batch")).toBeNull();
    rerender(<UploadDialog {...props} batchProgress={mixed} onOpenDocument={vi.fn()} />);
    expect(screen.getByText("Reading this batch")).toBeInTheDocument();
  });
});

describe("batch polling", () => {
  const running = batch([doc({ status: "reading" })]);
  const finished = batch([doc()]);

  async function flush() {
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
  }

  it("polls every 3 s while anything is running and stops once the batch is complete", async () => {
    vi.useFakeTimers();
    fetchMock.mockImplementation(async () => reply(fetchMock.mock.calls.length < 3 ? running : finished));
    const { result } = renderHook(() =>
      useBatchProgress({ enabled: true, engagementId: "ENG-1", batchId: "B1", uploading: false })
    );
    await flush();
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0][0]).toContain("/engagements/ENG-1/document-batches/B1");
    expect(result.current?.complete).toBe(false);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(BATCH_POLL_MS);
    });
    expect(fetchMock).toHaveBeenCalledTimes(2);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(BATCH_POLL_MS);
    });
    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect(result.current?.complete).toBe(true);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(BATCH_POLL_MS * 5);
    });
    expect(fetchMock).toHaveBeenCalledTimes(3); // no more asking
  });

  it("keeps polling a complete batch while files are still being uploaded", async () => {
    vi.useFakeTimers();
    fetchMock.mockImplementation(async () => reply(finished));
    renderHook(() => useBatchProgress({ enabled: true, engagementId: "ENG-1", batchId: "B1", uploading: true }));
    await flush();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(BATCH_POLL_MS * 2);
    });
    expect(fetchMock.mock.calls.length).toBeGreaterThanOrEqual(3);
  });

  it("fetches nothing without a batch or outside backend mode", async () => {
    vi.useFakeTimers();
    renderHook(() => useBatchProgress({ enabled: true, engagementId: "ENG-1", batchId: null, uploading: false }));
    renderHook(() => useBatchProgress({ enabled: false, engagementId: "ENG-1", batchId: "B1", uploading: false }));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(BATCH_POLL_MS * 3);
    });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("stops when the session has ended", async () => {
    vi.useFakeTimers();
    fetchMock.mockImplementation(async () => new Response("{}", { status: 401 }));
    const onError = vi.fn(() => true);
    renderHook(() => useBatchProgress({ enabled: true, engagementId: "ENG-1", batchId: "B1", uploading: false, onError }));
    await flush();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(BATCH_POLL_MS * 3);
    });
    expect(onError).toHaveBeenCalledTimes(1);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});
