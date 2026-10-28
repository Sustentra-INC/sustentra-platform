/* @vitest-environment jsdom */
import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "../../../lib/api";
import {
  isActiveRun,
  listProcessingRuns,
  READ_FAILED_ON_OUR_SIDE,
  readFailureMessage,
  requestRead,
  type ProcessingRunView,
} from "../api/processingRuns";
import { HALT_REASONS } from "../constants/copy";
import { ERROR_MAX_MS, HIDDEN_MS, useProcessingRuns } from "../hooks/useProcessingRuns";

const fetchMock = vi.fn();

function json(status: number, body: unknown) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
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

const queued = run();
const inProgress = run({ status: "in_progress", started_at: "2026-10-28T10:00:01Z" });
const completed = run({
  status: "completed",
  evidence_id: "EV-1",
  started_at: "2026-10-28T10:00:01Z",
  completed_at: "2026-10-28T10:00:09Z",
});

function listOf(...items: ProcessingRunView[]) {
  return json(200, { engagement_id: "ENG-1", items });
}

beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe("processing runs client", () => {
  it("asks for a read with an empty body, or with the type the reviewer chose", async () => {
    fetchMock.mockImplementation(async () => json(202, queued));

    await requestRead("DOC-1");
    await requestRead("DOC-1", "CT-S1-FUELQTY");

    const [first, second] = fetchMock.mock.calls as Array<[string, RequestInit]>;
    expect(first[0]).toBe("/api/v1/documents/DOC-1/processing-runs");
    expect(first[1].method).toBe("POST");
    expect(first[1].body).toBe("{}");
    expect(second[0]).toBe("/api/v1/documents/DOC-1/processing-runs");
    expect(second[1].body).toBe('{"canonical_type_id_override":"CT-S1-FUELQTY"}');
  });

  it("resolves a queued run from a 202, and a finished run from a 200", async () => {
    fetchMock.mockResolvedValueOnce(json(202, queued)).mockResolvedValueOnce(json(200, completed));

    await expect(requestRead("DOC-1")).resolves.toEqual(queued);
    await expect(requestRead("DOC-1")).resolves.toEqual(completed);
  });

  it("lists the engagement's runs", async () => {
    fetchMock.mockResolvedValueOnce(listOf(queued, run({ run_id: "RUN-2", document_id: "DOC-2" })));

    const items = await listProcessingRuns("ENG-1");

    expect(String(fetchMock.mock.calls[0][0])).toBe("/api/v1/engagements/ENG-1/processing-runs");
    expect(items.map((item) => item.run_id)).toEqual(["RUN-1", "RUN-2"]);
  });

  it("tells queued and in-progress runs from finished ones", () => {
    expect(isActiveRun(queued)).toBe(true);
    expect(isActiveRun(inProgress)).toBe(true);
    expect(isActiveRun(completed)).toBe(false);
    expect(isActiveRun(run({ status: "failed" }))).toBe(false);
  });

  it("words a failed run the way a failed read has always been worded", () => {
    expect(readFailureMessage({ error: "Unreadable document: no text" })).toBe(HALT_REASONS.unreadable);
    expect(readFailureMessage({ error: null })).toBe(READ_FAILED_ON_OUR_SIDE);
    const timedOut = "Reading stopped before it finished. Try again later, or upload a smaller file.";
    expect(readFailureMessage({ error: timedOut })).toBe(timedOut);
  });
});

describe("useProcessingRuns", () => {
  let fetchedAt: number[];
  let started: number;
  const onFinished = vi.fn();
  const onError = vi.fn<(error: unknown) => boolean>();

  /** Answer the nth fetch (0 is the first) with `reply(n)`. */
  function serve(reply: (n: number) => Response | Promise<Response>) {
    fetchMock.mockImplementation(async () => {
      fetchedAt.push(Date.now() - started);
      return reply(fetchedAt.length - 1);
    });
  }

  async function advance(ms: number) {
    await act(async () => {
      await vi.advanceTimersByTimeAsync(ms);
    });
  }

  function mount(props: { enabled?: boolean; engagementId?: string } = {}) {
    return renderHook(
      (p: { enabled: boolean; engagementId: string }) =>
        useProcessingRuns({ ...p, onFinished, onError }),
      { initialProps: { enabled: true, engagementId: "ENG-1", ...props } }
    );
  }

  beforeEach(() => {
    vi.useFakeTimers();
    fetchedAt = [];
    started = Date.now();
    onFinished.mockReset();
    onError.mockReset();
    onError.mockReturnValue(false);
  });

  it("does nothing while disabled, or without an engagement", async () => {
    serve(() => listOf());
    const disabled = mount({ enabled: false });
    const noEngagement = mount({ engagementId: "" });

    await advance(10_000);

    expect(fetchMock).not.toHaveBeenCalled();
    expect(vi.getTimerCount()).toBe(0);
    expect(disabled.result.current.runs).toEqual({});
    expect(disabled.result.current.readingIds).toEqual([]);
    act(() => noEngagement.result.current.track(queued));
    expect(noEngagement.result.current.runs).toEqual({});
    expect(vi.getTimerCount()).toBe(0);
  });

  it("fetches once, and reports nothing, when the run had already finished", async () => {
    serve(() => listOf(completed));
    const { result } = mount();

    await advance(0);
    expect(result.current.runs["DOC-1"]).toEqual(completed);
    expect(result.current.readingIds).toEqual([]);

    await advance(10_000);
    expect(fetchedAt).toEqual([0]);
    expect(onFinished).not.toHaveBeenCalled();
  });

  it("picks up a run still going after a reload, and reports it when it finishes", async () => {
    serve((n) => listOf(n === 0 ? inProgress : completed));
    const { result } = mount();

    await advance(0);
    expect(result.current.readingIds).toEqual(["DOC-1"]);
    expect(onFinished).not.toHaveBeenCalled();

    await advance(2000);
    expect(onFinished).toHaveBeenCalledTimes(1);
    expect(onFinished).toHaveBeenCalledWith([completed]);
    expect(result.current.readingIds).toEqual([]);
    await advance(10_000);
    expect(fetchedAt).toEqual([0, 2000]);
  });

  it("follows a tracked run every 2 s until it finishes, then stops", async () => {
    serve((n) => listOf(...[[], [inProgress], [completed]][n]));
    const { result } = mount();
    await advance(0);

    act(() => result.current.track(queued));
    expect(result.current.readingIds).toEqual(["DOC-1"]);
    await advance(2000);
    expect(result.current.runs["DOC-1"].status).toBe("in_progress");
    expect(onFinished).not.toHaveBeenCalled();
    await advance(2000);

    expect(fetchedAt).toEqual([0, 2000, 4000]);
    expect(onFinished).toHaveBeenCalledTimes(1);
    expect(onFinished).toHaveBeenCalledWith([completed]);
    expect(result.current.readingIds).toEqual([]);
    await advance(10_000);
    expect(fetchedAt).toHaveLength(3);
  });

  it("batches the runs that finish in one poll", async () => {
    const other = run({ run_id: "RUN-2", document_id: "DOC-2" });
    const otherDone = { ...other, status: "failed" as const, error: "Unreadable document: no text" };
    serve((n) => (n === 0 ? listOf() : listOf(completed, otherDone)));
    const { result } = mount();
    await advance(0);
    act(() => {
      result.current.track(queued);
      result.current.track(other);
    });

    await advance(2000);

    expect(onFinished).toHaveBeenCalledTimes(1);
    expect(onFinished.mock.calls[0][0]).toEqual([completed, otherDone]);
  });

  it("polls every 5 s once a run has been active for a minute", async () => {
    serve((n) => listOf(...(n === 0 ? [] : [inProgress])));
    const { result } = mount();
    await advance(0);
    act(() => result.current.track(queued));

    await advance(70_000);

    const fast = Array.from({ length: 31 }, (_, i) => i * 2000); // 0, 2 s, ... 60 s
    expect(fetchedAt).toEqual([...fast, 65_000, 70_000]);
  });

  it("goes back to fast polling when a new run is tracked", async () => {
    serve(() => listOf(inProgress));
    const { result } = mount();
    await advance(61_000);
    expect(fetchedAt.slice(-2)).toEqual([58_000, 60_000]); // the next one is due at 65 s

    act(() => result.current.track(run({ run_id: "RUN-2", document_id: "DOC-2" })));
    await advance(4000);

    expect(fetchedAt.slice(-2)).toEqual([63_000, 65_000]);
  });

  it("reports a finished run only once", async () => {
    serve((n) => listOf(...(n === 0 ? [] : [completed])));
    const { result } = mount();
    await advance(0);
    act(() => result.current.track(queued));
    await advance(2000);
    expect(onFinished).toHaveBeenCalledTimes(1);

    // A late answer to the request that queued this run is tracked after the poll saw it finish.
    act(() => result.current.track(queued));
    await advance(2000);

    expect(fetchedAt).toEqual([0, 2000, 4000]);
    expect(result.current.runs["DOC-1"]).toEqual(completed);
    expect(onFinished).toHaveBeenCalledTimes(1);
  });

  it("waits at least 15 s while the tab is hidden, and polls at once when it shows again", async () => {
    let visibility: DocumentVisibilityState = "hidden";
    Object.defineProperty(document, "visibilityState", { configurable: true, get: () => visibility });
    try {
      serve(() => listOf(inProgress));
      const { result } = mount();
      await advance(0);
      act(() => result.current.track(queued));

      await advance(HIDDEN_MS - 1);
      expect(fetchedAt).toEqual([0]);
      await advance(1);
      expect(fetchedAt).toEqual([0, HIDDEN_MS]);

      await advance(5000);
      visibility = "visible";
      act(() => {
        document.dispatchEvent(new Event("visibilitychange"));
      });
      await advance(0);
      expect(fetchedAt).toEqual([0, HIDDEN_MS, HIDDEN_MS + 5000]);
      await advance(2000);
      expect(fetchedAt.at(-1)).toBe(HIDDEN_MS + 7000);
    } finally {
      delete (document as unknown as Record<string, unknown>).visibilityState;
    }
  });

  it("never lets two fetches overlap", async () => {
    let release: (response: Response) => void = () => {};
    serve((n) => (n === 0 ? listOf() : new Promise<Response>((resolve) => (release = resolve))));
    const { result } = mount();
    await advance(0);
    act(() => result.current.track(queued));

    await advance(30_000);
    expect(fetchedAt).toEqual([0, 2000]);

    release(listOf(completed));
    await advance(0);
    expect(onFinished).toHaveBeenCalledWith([completed]);
  });

  it("retries a failed poll after 4 s, then 8 s, and a success starts the delay over", async () => {
    serve((n) => (n === 0 || n === 3 ? listOf(inProgress) : json(500, { detail: "Server error." })));
    mount();

    await advance(30_000);

    // 0 ok, 2 s fails -> +4 s fails -> +8 s ok -> +2 s fails (back to 4 s) -> ...
    expect(fetchedAt.slice(0, 6)).toEqual([0, 2000, 6000, 14_000, 16_000, 20_000]);
    expect(onError).toHaveBeenCalled();
    expect(onError.mock.calls[0][0]).toBeInstanceOf(ApiError);
  });

  it("never waits longer than 30 s to retry", async () => {
    serve((n) => (n === 0 ? listOf(inProgress) : json(500, { detail: "Server error." })));
    mount();

    await advance(200_000);

    const gaps = fetchedAt.slice(1).map((at, i) => at - fetchedAt[i]);
    expect(gaps.slice(0, 5)).toEqual([2000, 4000, 8000, 16_000, ERROR_MAX_MS]);
    expect(Math.max(...gaps)).toBe(ERROR_MAX_MS);
  });

  it("stops polling when the session ended", async () => {
    onError.mockReturnValue(true);
    serve((n) => (n === 0 ? listOf(inProgress) : json(401, { detail: "Not authenticated." })));
    const { result } = mount();

    await advance(60_000);

    expect(fetchedAt).toEqual([0, 2000]);
    expect(onError).toHaveBeenCalledTimes(1);
    expect(onError.mock.calls[0][0]).toMatchObject({ status: 401 });
    act(() => result.current.track(queued));
    await advance(60_000);
    expect(fetchedAt).toHaveLength(2);
  });

  it("drops a response that comes back after the engagement changed", async () => {
    let release: (response: Response) => void = () => {};
    serve((n) => {
      if (n === 0) return listOf();
      if (n === 1) return new Promise<Response>((resolve) => (release = resolve));
      return json(200, { engagement_id: "ENG-2", items: [] });
    });
    const { result, rerender } = mount();
    await advance(0);
    act(() => result.current.track(queued));
    await advance(2000); // the poll for ENG-1 is now in flight
    expect(fetchedAt).toEqual([0, 2000]);

    rerender({ enabled: true, engagementId: "ENG-2" });
    await advance(0);
    expect(String(fetchMock.mock.calls[2][0])).toBe("/api/v1/engagements/ENG-2/processing-runs");
    release(listOf(completed));
    await advance(10_000);

    expect(onFinished).not.toHaveBeenCalled();
    expect(result.current.runs).toEqual({});
    expect(fetchedAt).toHaveLength(3);
  });

  it("starts from nothing when the engagement changes", async () => {
    serve((n) => (n === 0 ? listOf(completed) : json(200, { engagement_id: "ENG-2", items: [] })));
    const { result, rerender } = mount();
    await advance(0);
    expect(Object.keys(result.current.runs)).toEqual(["DOC-1"]);

    rerender({ enabled: true, engagementId: "ENG-2" });

    expect(result.current.runs).toEqual({});
    await advance(0);
    expect(fetchedAt).toHaveLength(2);
    expect(result.current.runs).toEqual({});
  });

  it("ignores runs of another engagement", async () => {
    const foreign = run({ run_id: "RUN-9", document_id: "DOC-9", engagement_id: "ENG-2" });
    serve(() => listOf(foreign, completed));
    const { result } = mount();
    await advance(0);

    act(() => result.current.track(foreign));

    expect(Object.keys(result.current.runs)).toEqual(["DOC-1"]);
    await advance(10_000);
    expect(fetchedAt).toEqual([0]);
  });

  it("keeps a run tracked while a fetch was in flight", async () => {
    // The fetch was asked before the read was requested, so it still shows the old run.
    const previous = run({ run_id: "RUN-0", status: "completed" });
    const rerun = run({ run_id: "RUN-2" });
    let release: (response: Response) => void = () => {};
    serve((n) => {
      if (n === 0) return listOf(previous, run({ run_id: "RUN-3", document_id: "DOC-2" }));
      if (n === 1) return new Promise<Response>((resolve) => (release = resolve));
      return listOf(rerun);
    });
    const { result } = mount();
    await advance(0);
    await advance(2000); // DOC-2 is queued, so the poll runs and is now in flight
    act(() => result.current.track(rerun));

    release(listOf(previous, run({ run_id: "RUN-3", document_id: "DOC-2" })));
    await advance(0);

    expect(result.current.runs["DOC-1"]).toEqual(rerun);
    expect(onFinished).not.toHaveBeenCalled();
    await advance(2000);
    expect(result.current.runs["DOC-1"]).toEqual(rerun);
    expect(fetchedAt).toHaveLength(3);
  });

  it("stops its timers when it unmounts", async () => {
    serve(() => listOf(inProgress));
    const { unmount } = mount();
    await advance(0);
    expect(vi.getTimerCount()).toBe(1);

    unmount();

    expect(vi.getTimerCount()).toBe(0);
    await advance(30_000);
    expect(fetchedAt).toEqual([0]);
  });
});
