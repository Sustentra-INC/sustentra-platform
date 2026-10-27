/* @vitest-environment jsdom */
import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("../../../lib/api", () => ({
  // A one-page PDF, or a text file of one line for the content view.
  api: vi.fn((path: string) =>
    Promise.resolve(path.endsWith("/content") ? { kind: "lines", truncated: false, lines: ["Total kWh Used: 182,400 kWh"] } : { pages: 1 })
  ),
  apiPath: (path: string) => `/api/v1${path}`,
}));

import { withRequestsFromAsks } from "../adapters/reviewValueAdapter";
import { BackendPageView } from "../components/BackendPageView";
import { DocumentContentView } from "../components/DocumentContentView";
import { manufacturerValues } from "../fixtures/extraction/manufacturerValues";
import type { Ask } from "../types/requests";
import type { PageMark, ReviewValue } from "../types/review";
import { engagementActivity } from "../utils/engagementActivity";
import { readablePeriod } from "../utils/formatPeriod";

/** Follow-ups from the final review of the Extraction review parity work. */

describe("the activity log: a request's outcome on a card", () => {
  // The demo's electricity card: one reading, two values (location- and market-based).
  const card = manufacturerValues.filter((v) => v.documentId === "DOC-tualatin-elec-jan");
  const at = (minute: number) => `2026-10-22T08:${String(minute).padStart(2, "0")}:00.000Z`;

  function closedRequest(state: "resolved" | "withdrawn"): { values: ReviewValue[]; ask: Ask } {
    const ask: Ask = {
      id: "ASK-1",
      type: "clarify",
      whatIsNeeded: "Please confirm the reading.",
      source: { origin: "review_value", documentId: card[0].documentId, fieldKey: card[0].id, itemLabel: "Electricity consumed · tualatin_electric_jan_2025.pdf", facilityName: "Tualatin Plant", period: "Jan 2025" },
      raisedByName: "M. Osei",
      raisedByLogin: "mosei",
      raisedAt: at(0),
      state,
      requestNumber: 1,
      lineNumber: 1,
      withdrawReason: state === "withdrawn" ? "found on the next bill" : null,
      history: [
        { kind: "raised", actorName: "M. Osei", actorLogin: "mosei", at: at(0) },
        { kind: "sent", actorName: "M. Osei", actorLogin: "mosei", at: at(1) },
        { kind: state, actorName: "M. Osei", actorLogin: "mosei", at: at(2) },
      ],
    };
    // As the review screen leaves them: both values point at the ask they were added to.
    const added = { kind: "human" as const, actor: "M. Osei", at: at(0), action: "added to requests", askId: ask.id };
    const values = card.map((v) => ({ ...v, reviewState: "requested" as const, record: [...v.record, added] }));
    return { values: withRequestsFromAsks(values, [ask]), ask };
  }

  for (const state of ["resolved", "withdrawn"] as const) {
    it(`logs a ${state} request once, as the request's event, not as a review`, () => {
      const { values, ask } = closedRequest(state);
      // Both values of the card carry the outcome line ...
      expect(values.map((v) => v.record.filter((r) => r.outcomeOf === ask.id).length)).toEqual([1, 1]);
      const log = engagementActivity({ evidence: [], values, asks: [ask], findings: [] });
      // ... and the log has it once, from the request's history.
      expect(log.filter((e) => e.what.startsWith(`${state} a request`))).toHaveLength(1);
      expect(log.filter((e) => e.kind === "review" && /Request( \d+)? (resolved|withdrawn)/.test(e.what))).toEqual([]);
      // Adding the card to requests is still the reviewer's own line, once per value as before.
      expect(log.filter((e) => e.kind === "review" && e.what.startsWith("added to requests"))).toHaveLength(2);
    });
  }
});

describe("a stored period that is not a real date range", () => {
  it("comes back as it was stored", () => {
    for (const stored of ["2025-13-01 to 2025-13-28", "2025-02-01 to 2025-13-31", "2025-02-30 to 2025-03-02", "2025-02-30 to ?", "? to 2025-00-10"]) {
      expect(readablePeriod(stored)).toBe(stored);
      expect(readablePeriod(stored)).not.toContain("undefined");
    }
    // Real ranges are still read as a person reads them.
    expect(readablePeriod("2025-02-01 to 2025-02-28")).toBe("Feb 2025");
    expect(readablePeriod("2024-02-29 to 2024-03-02")).toBe("29 Feb – 02 Mar 2024");
  });
});

describe("scrolling to the selected value", () => {
  const scroll = vi.fn();
  function motion(reduce: boolean) {
    scroll.mockClear();
    Element.prototype.scrollIntoView = scroll;
    window.matchMedia = vi.fn((query: string) => ({ matches: reduce && query.includes("reduce") })) as unknown as typeof window.matchMedia;
  }
  afterEach(() => {
    delete (window as { matchMedia?: unknown }).matchMedia;
  });

  const MARK: PageMark = {
    id: "kwh", span: { page: 1, x: 0.1, y: 0.4, w: 0.3, h: 0.02 }, anchor: { kind: "line", line: 1 }, rawText: "182,400",
    label: "Electricity consumed: 182,400 kWh", reviewState: "to_review",
  };

  for (const [reduce, behavior] of [[true, "auto"], [false, "smooth"]] as const) {
    it(`jumps on a page${reduce ? " at once under reduced motion" : " smoothly otherwise"}`, async () => {
      motion(reduce);
      render(<BackendPageView documentId="DOC" span={MARK.span!} marks={[MARK]} onPickMark={vi.fn()} />);
      fireEvent.load(await screen.findByRole("img"));
      expect(scroll).toHaveBeenCalledWith(expect.objectContaining({ behavior }));
    });

    it(`jumps in a file${reduce ? " at once under reduced motion" : " smoothly otherwise"}`, async () => {
      motion(reduce);
      render(<DocumentContentView documentId="DOC" marks={[MARK]} selectedId="kwh" />);
      await screen.findByRole("button", { name: /^Select Electricity consumed/ });
      expect(scroll).toHaveBeenCalledWith(expect.objectContaining({ behavior }));
    });
  }
});
