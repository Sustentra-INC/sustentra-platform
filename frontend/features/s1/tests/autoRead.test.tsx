/* @vitest-environment jsdom */
import "@testing-library/jest-dom/vitest";
import { act, cleanup, render, renderHook, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mock = vi.hoisted(() => ({ review: [] as unknown[], status: [] as unknown[] }));
vi.mock("../../../lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../../../lib/api")>()),
  api: vi.fn((path: string) => {
    const queue = path.endsWith("/auto-read") ? mock.status : mock.review;
    return Promise.resolve(queue.length > 1 ? queue.shift() : queue[0]);
  }),
}));

import { BackendMethodologyReview } from "../components/BackendMethodologyReview";
import { useAutoRead } from "../hooks/useAutoRead";
import { withAutoRead } from "../utils/readingState";
import type { EvidenceItem } from "../types";

const def = { group_label: "x", user_added: false };
function review(autoRead: unknown, pending = false): Record<string, unknown> {
  return {
    ai: { enabled: true, reason_code: null, reason: null },
    auto_read: autoRead,
    groups: [{ group: "boundary", label: "Organizational boundary" }],
    row_groups: [],
    catalog: [{ ...def, field_id: "consolidation_approach", group: "boundary", label: "Consolidation approach", kind: "text" }],
    fields: [
      {
        field_id: "consolidation_approach",
        user_added: false,
        suggestion: pending ? { value: "Operational Control", quote: "q", document_id: "D1", file_name: "ghg.pdf", origin: "ai", at: "2026-11-02T10:00:00Z" } : null,
        decision: null,
        history: [],
      },
    ],
  };
}

const reading = { state: "reading", file_names: ["ghg.pdf"], reason: null };

beforeEach(() => {
  mock.review = [];
  mock.status = [];
});
afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

describe("Methodology review while Sustentra's AI reads by itself", () => {
  it("says it is reading the file, keeps the button, then shows the suggestions when the read finishes", async () => {
    mock.review = [review(reading), review(null, true)];
    render(<BackendMethodologyReview engagementId="e1" onOpenDocument={vi.fn()} />);
    expect(await screen.findByText("Sustentra's AI is reading ghg.pdf…")).toBeInTheDocument();
    const button = screen.getByRole("button", { name: "Read the client's reports with Sustentra's AI" });
    expect(button).toBeDisabled(); // the busy lock: a manual read would be refused now
    expect(screen.getByText("0 suggested, waiting for review")).toBeInTheDocument();

    // the page polls the review endpoint (every 3 s) and the finished read's suggestions appear
    await waitFor(() => expect(screen.queryByText("Sustentra's AI is reading ghg.pdf…")).toBeNull(), { timeout: 6000 });
    expect(await screen.findByText(/Sustentra's AI read ghg\.pdf\. 1 suggested, waiting for your review/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Read the client's reports with Sustentra's AI" })).toBeEnabled(); // manual re-reads stay
  }, 15000);

  it("says it will read shortly while the batch is still arriving", async () => {
    mock.review = [review({ state: "waiting", file_names: ["a.xlsx", "b.pdf", "c.docx"], reason: null })];
    render(<BackendMethodologyReview engagementId="e1" onOpenDocument={vi.fn()} />);
    expect(await screen.findByText("Sustentra's AI will read a.xlsx, b.pdf and 1 more shortly…")).toBeInTheDocument();
  });

  it("says why it did not read", async () => {
    mock.review = [review({ state: "skipped", file_names: ["ghg.pdf"], reason: "This month's limit on suggestions has been reached." })];
    render(<BackendMethodologyReview engagementId="e1" onOpenDocument={vi.fn()} />);
    expect(await screen.findByText(/Not read automatically: This month's limit/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Read the client's reports with Sustentra's AI" })).toBeEnabled();
  });

  it("shows nothing extra when no automatic read is going on", async () => {
    mock.review = [review(null)];
    render(<BackendMethodologyReview engagementId="e1" onOpenDocument={vi.fn()} />);
    await screen.findByText("Consolidation approach");
    expect(screen.queryByText(/Sustentra's AI (is reading|will read|read )/)).toBeNull();
  });
});

function item(documentId: string, filename: string, extra: Partial<EvidenceItem> = {}): EvidenceItem {
  return { documentId, filename, disposition: "active", processingState: "extracted", ...extra } as EvidenceItem;
}

describe("Evidence rows of a summary document being read", () => {
  const rows = [item("D1", "ghg.pdf"), item("D2", "bill.pdf"), item("D3", "old.pdf", { disposition: "withdrawn" })];

  it("marks the files being read, and only those", () => {
    const out = withAutoRead(rows, { state: "reading", file_names: ["ghg.pdf", "old.pdf"], reason: null });
    expect(out.map((r) => r.reading)).toEqual(["in_progress", undefined, undefined]);
  });

  it("marks them while the read waits for the rest of the batch too", () => {
    expect(withAutoRead(rows, { state: "waiting", file_names: ["ghg.pdf"], reason: null })[0].reading).toBe("in_progress");
  });

  it("changes nothing when no read is going on", () => {
    expect(withAutoRead(rows, null)).toBe(rows);
    expect(withAutoRead(rows, { state: "skipped", file_names: ["ghg.pdf"], reason: "x" })).toBe(rows);
  });
});

describe("useAutoRead", () => {
  it("polls every 3 s while a read is going on and stops when it is over", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    mock.status = [{ auto_read: reading }, { auto_read: reading }, { auto_read: null }, { auto_read: null }, { auto_read: null }, { auto_read: null }];
    const { result } = renderHook(() => useAutoRead({ enabled: true, engagementId: "e1", nudge: 0 }));
    await waitFor(() => expect(result.current?.state).toBe("reading"));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(3100);
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(3100);
    });
    await waitFor(() => expect(result.current).toBeNull());
  });

  it("fetches nothing when disabled", () => {
    mock.status = [{ auto_read: reading }];
    const { result } = renderHook(() => useAutoRead({ enabled: false, engagementId: "e1", nudge: 0 }));
    expect(result.current).toBeNull();
  });
});
