/* @vitest-environment jsdom */
import "@testing-library/jest-dom/vitest";
import { act, fireEvent, render, renderHook, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "../../../lib/api";
import { BATCH_POLL_MS, type BatchDocument, type BatchView } from "../api/documentBatches";
import { BATCH_STATUS, BatchProgress } from "../components/BatchProgress";
import { UploadDialog } from "../components/UploadDialog";
import { BATCH_LOAD_FAILED, BATCH_MAX_FAILURES, BATCH_NOT_CREATED, useBatchProgress } from "../hooks/useBatchProgress";
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
  const totals = { queued: 0, reading: 0, done: 0, partial: 0, failed: 0, not_started: 0 };
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

  it("shows a file no read was asked for as not started, with its sentence, a link, and no records", () => {
    const open = vi.fn();
    const idle = batch([doc({ document_id: "DOC-9", file_name: "idle.pdf", status: "not_started", canonical_type_id: null,
      records_found: 0, halt_reason: "Reading hasn't started for this file. Open it to start reading." })]);
    render(<BatchProgress batch={idle} onOpenDocument={open} />);
    const row = screen.getAllByRole("row")[1];
    expect(within(row).getByText("Not started")).toBeInTheDocument();
    expect(within(row).getByText("Reading hasn't started for this file. Open it to start reading.")).toBeInTheDocument();
    fireEvent.click(within(row).getByRole("button", { name: "idle.pdf" }));
    expect(open).toHaveBeenCalledWith("DOC-9");
    expect(screen.getByText("1 not started")).toBeInTheDocument();
    expect(findBlockedUiTerms(document.body.textContent ?? "")).toEqual([]);
  });

  it("says so when the batch could not be made or its progress could not be loaded", () => {
    const props = { onClose: vi.fn(), onUploadFiles: vi.fn(), batch: [], tasks: [], onOpenWorkspace: vi.fn() };
    const { rerender } = render(<UploadDialog {...props} batchNote={BATCH_NOT_CREATED} />);
    expect(screen.getByText("These files were uploaded without a batch.")).toBeInTheDocument();
    rerender(<UploadDialog {...props} batchNote={BATCH_LOAD_FAILED} />);
    expect(screen.getByText("Progress couldn't be loaded. Refresh to try again.")).toBeInTheDocument();
    expect(findBlockedUiTerms(`${BATCH_NOT_CREATED} ${BATCH_LOAD_FAILED}`)).toEqual([]);
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
    expect(result.current.view?.complete).toBe(false);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(BATCH_POLL_MS);
    });
    expect(fetchMock).toHaveBeenCalledTimes(2);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(BATCH_POLL_MS);
    });
    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect(result.current.view?.complete).toBe(true);

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

describe("batch polling failures", () => {
  const hook = (onError?: (e: unknown) => boolean) =>
    renderHook(() => useBatchProgress({ enabled: true, engagementId: "ENG-1", batchId: "B1", uploading: false, onError }));

  it("stops at once on a 4xx and says progress could not be loaded", async () => {
    vi.useFakeTimers();
    fetchMock.mockImplementation(async () => new Response(JSON.stringify({ detail: "Batch not found." }), { status: 404 }));
    const { result } = hook(() => false);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(BATCH_POLL_MS * 10);
    });
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(result.current.error).toBe(BATCH_LOAD_FAILED);
  });

  it("backs off 3 s then 6 s on server errors and stops at the third failure in a row", async () => {
    vi.useFakeTimers();
    fetchMock.mockImplementation(async () => new Response("{}", { status: 503 }));
    const { result } = hook();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(fetchMock).toHaveBeenCalledTimes(1);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(BATCH_POLL_MS - 1);
    });
    expect(fetchMock).toHaveBeenCalledTimes(1);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1);
    });
    expect(fetchMock).toHaveBeenCalledTimes(2);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(BATCH_POLL_MS * 2 - 1);
    });
    expect(fetchMock).toHaveBeenCalledTimes(2);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1);
    });
    expect(fetchMock).toHaveBeenCalledTimes(BATCH_MAX_FAILURES);
    expect(result.current.error).toBe(BATCH_LOAD_FAILED);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(BATCH_POLL_MS * 20);
    });
    expect(fetchMock).toHaveBeenCalledTimes(BATCH_MAX_FAILURES);
  });

  it("starts the count again after a poll that works, and keeps the last table when it gives up", async () => {
    vi.useFakeTimers();
    const running = batch([doc({ status: "reading" })]);
    const answers = [503, 503, "ok", 503, 503, 503];
    fetchMock.mockImplementation(async () => {
      const next = answers.shift();
      return next === "ok" ? reply(running) : new Response("{}", { status: Number(next ?? 503) });
    });
    const { result } = hook();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(BATCH_POLL_MS * 30);
    });
    expect(fetchMock).toHaveBeenCalledTimes(6);
    expect(result.current.error).toBe(BATCH_LOAD_FAILED);
    expect(result.current.view?.items).toHaveLength(1);
  });

  it("hands a failure the app handles (the session ended) to onError and stops", async () => {
    vi.useFakeTimers();
    fetchMock.mockImplementation(async () => new Response("{}", { status: 503 }));
    const onError = vi.fn(() => true);
    const { result } = hook(onError);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(BATCH_POLL_MS * 10);
    });
    expect(onError).toHaveBeenCalledTimes(1);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(result.current.error).toBeNull();
  });

  it("stops asking and ignores a late answer after unmount", async () => {
    vi.useFakeTimers();
    let release: (r: Response) => void = () => undefined;
    fetchMock.mockImplementationOnce(() => new Promise<Response>((resolve) => (release = resolve)));
    const { unmount, result } = hook();
    unmount();
    release(reply(batch([doc({ status: "reading" })])));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(BATCH_POLL_MS * 5);
    });
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(result.current.view).toBeNull();
  });

  it("is an ApiError that carries the status the hook reads", () => {
    expect(new ApiError(404, "x", null, null).status).toBe(404);
  });
});
