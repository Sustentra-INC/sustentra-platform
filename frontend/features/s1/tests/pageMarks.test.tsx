/* @vitest-environment jsdom */
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeAll, describe, expect, it, vi } from "vitest";

vi.mock("../../../lib/api", () => ({
  api: vi.fn().mockResolvedValue({ pages: 2, kind: "pdf" }),
  apiPath: (path: string) => `/api/v1${path}`,
}));

import { BackendPageView } from "../components/BackendPageView";
import { ExtractionReview } from "../components/ExtractionReview";
import { engagementConfig } from "../fixtures/engagementConfig";
import type { PageMark, ReviewValue } from "../types/review";

beforeAll(() => {
  Element.prototype.scrollIntoView = () => {}; // jsdom has no layout
});

const span = (page: number, x: number, y: number) => ({ page, x, y, w: 0.2, h: 0.02 });

const MARKS: PageMark[] = [
  { id: "kwh", span: span(1, 0.1, 0.4), label: "Activity quantity: 700,000 kWh", reviewState: "to_review" },
  { id: "start", span: span(1, 0.1, 0.3), label: "Service period start: 2025-01-01", reviewState: "accepted" },
  { id: "page2", span: span(2, 0.1, 0.5), label: "Account number: HVP-1001", reviewState: "to_review" },
  { id: "unit", span: span(1, 0.1, 0.4), label: "Activity unit: kWh", reviewState: "to_review" }, // same line
];

describe("document to value", () => {
  it("draws a box for every value on the page and picks the one clicked", async () => {
    const onPickMark = vi.fn();
    render(<BackendPageView documentId="DOC" span={MARKS[1].span} marks={MARKS} onPickMark={onPickMark} />);
    const boxes = await screen.findAllByRole("button", { name: /^Select / });
    expect(boxes.map((b) => b.getAttribute("aria-label"))).toEqual([
      // One box for one line; the name says each value's state, not the colour alone.
      "Select Activity quantity: 700,000 kWh, to review · Activity unit: kWh, to review",
      "Select Service period start: 2025-01-01, accepted",
    ]); // the page-2 value is not drawn on page 1
    fireEvent.click(boxes[0]);
    expect(onPickMark).toHaveBeenCalledWith(MARKS[0]);
  });

  it("selects the value's card when its box is clicked, cycling through values that share a box", () => {
    const value = (id: string, whatItIs: string, v: string, x: number): ReviewValue => ({
      id, documentId: "DOC", filename: "bill.pdf", documentType: "Purchased electricity record", facilityId: null,
      notYetKnown: true, period: "2025-01-01 to 2025-06-30", whatItIs, scope: "scope2_location", value: v, unit: "",
      reviewState: "to_review", record: [], sourceKind: "pdf", page: 1, pageCount: 1, span: span(1, x, 0.4),
      reviewToken: id,
    });
    const values = [
      value("quantity", "Activity quantity", "700,000", 0.1),
      value("unit", "Activity unit", "kWh", 0.1), // same line, same box
      value("account", "Account number", "HVP-1001", 0.6),
    ];
    render(
      <ExtractionReview
        engagement={engagementConfig}
        values={values}
        onValuesChange={() => {}}
        initialDocumentId="DOC"
        onSaveAsk={() => {}}
        onBack={() => {}}
        renderPage={(_doc, _span, onPickBox, marks) => (
          <div>
            {(marks ?? []).map((m) => (
              <button key={m.id} type="button" aria-label={`box ${m.id}`} onClick={() => m.span && onPickBox?.(m.span, m.id)} />
            ))}
          </div>
        )}
      />
    );
    const selected = () => document.querySelector(".s1-xr-card.is-sel")?.textContent ?? "";
    fireEvent.click(screen.getByRole("button", { name: "box account" }));
    expect(selected()).toContain("HVP-1001");
    fireEvent.click(screen.getByRole("button", { name: "box quantity" }));
    expect(selected()).toContain("700,000");
    fireEvent.click(screen.getByRole("button", { name: "box quantity" })); // same box again: the next value on it
    expect(selected()).toContain("kWh");
  });
});
