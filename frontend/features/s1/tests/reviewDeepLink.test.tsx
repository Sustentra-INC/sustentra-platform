/* @vitest-environment jsdom */
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import "@testing-library/jest-dom/vitest";

import { encodeReviewCandidateToken } from "../adapters/fieldAdapter";
import { reviewValuesFromFields } from "../adapters/reviewValueAdapter";
import { ExtractionReview } from "../components/ExtractionReview";
import { engagementConfig } from "../fixtures/engagementConfig";
import { manufacturerValues } from "../fixtures/extraction/manufacturerValues";
import { S1WorkpaperApp } from "../pages/S1WorkpaperApp";
import type { EvidenceItem, ExtractedField } from "../types";
import type { ReviewValue } from "../types/review";
import { viewToSearch } from "../utils/viewHistory";

function field(name: string, value: string): ExtractedField {
  return {
    documentId: "DOC-1",
    canonicalTypeId: "CT-S2-ELEC",
    fieldKey: `candidate:${name}`,
    reviewToken: encodeReviewCandidateToken({
      candidate_id: name, evidence_id: "EV-1", document_id: "DOC-1", field_name: name, display_label: name,
      normalized_value: value, unit: null,
    }),
    fieldLabel: name,
    value,
    unit: null,
    valueProperties: [],
    fieldState: "populated",
    snippet: null,
    snippetContext: null,
    location: null,
    reviewStatus: "unreviewed",
    correctedValue: null,
    valueOrigin: "extracted",
  };
}
const DOC = { documentId: "DOC-1", filename: "kent_electric_feb.pdf", format: "pdf", uploadedAt: "2026-10-20T09:00:00Z",
  detectedType: "Electricity bill" } as unknown as EvidenceItem;
const values = () => reviewValuesFromFields([field("activity_quantity", "182.4"), field("account_number", "ACC-77")], [DOC]);

function review(vs: ReviewValue[], extra: { valueId?: string; docId?: string } = {}) {
  return (
    <ExtractionReview
      engagement={engagementConfig}
      values={vs}
      onValuesChange={vi.fn()}
      initialDocumentId={extra.docId ?? "DOC-1"}
      initialDocumentName="kent_electric_feb.pdf"
      initialValueId={extra.valueId ?? "candidate:activity_quantity"}
      initialNodeKey="N"
      onSaveAsk={vi.fn()}
      onBack={vi.fn()}
    />
  );
}
const grid = (c: HTMLElement) => c.querySelector(".s1-xr-grid")!.textContent;

afterEach(cleanup);

describe("a review link opened before the workspace has loaded", () => {
  it("shows the same document, value and node once the values arrive", () => {
    const mounted = render(review(values()));
    const expected = grid(mounted.container);
    const selectedNode = mounted.container.querySelector(".s1-xr-node.is-on")?.textContent;
    mounted.unmount();

    const late = render(review([])); // reload: nothing loaded yet
    late.rerender(review(values())); // data arrives after mount
    expect(grid(late.container)).toBe(expected);
    expect(late.container.querySelector(".s1-xr-node.is-on")?.textContent).toBe(selectedNode);
    expect(screen.queryByText("Select a value to open its source.")).toBeNull();
    expect(late.container.querySelectorAll(".s1-xr-card").length).toBeGreaterThan(0);
  });

  it("selects the document's first value when the linked value is gone", () => {
    const { container, rerender } = render(review([], { valueId: "candidate:gone" }));
    rerender(review(values(), { valueId: "candidate:gone" }));
    expect(container.querySelectorAll(".s1-xr-card").length).toBeGreaterThan(0);
    expect(screen.queryByText("Select a value to open its source.")).toBeNull();
  });

  it("says so, plainly, when the document has no values", () => {
    const { rerender } = render(review([], { docId: "DOC-EMPTY" }));
    rerender(review(values(), { docId: "DOC-EMPTY" }));
    expect(screen.getByText(/No values were read from/)).toBeInTheDocument();
  });
});

describe("the real app in fixture mode", () => {
  it("opens a generated review URL on the same document and value", () => {
    vi.stubEnv("NEXT_PUBLIC_S1_DATA_MODE", "fixture");
    // jsdom lacks these; the demo document uses them to scroll to the selected value.
    window.matchMedia = ((q: string) => ({ matches: false, media: q, addEventListener() {}, removeEventListener() {} })) as unknown as typeof window.matchMedia;
    Element.prototype.scrollTo = (() => {}) as unknown as typeof Element.prototype.scrollTo;
    window.localStorage.setItem("sustentra-demo-signedin", "1");
    const value = manufacturerValues[0];
    window.history.replaceState(
      null, "",
      `/?${viewToSearch({ name: "extraction", documentId: value.documentId, mode: "snippet", valueId: value.id, nodeKey: "N" })}`
    );
    const { container } = render(<S1WorkpaperApp />);
    expect(container.querySelectorAll(".s1-xr-card").length).toBeGreaterThan(0);
    expect(screen.queryByText("Select a value to open its source.")).toBeNull();
    vi.unstubAllEnvs();
  });
});
