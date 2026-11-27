/* @vitest-environment jsdom */
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import "@testing-library/jest-dom/vitest";

import { encodeReviewCandidateToken } from "../adapters/fieldAdapter";
import { reviewValuesFromFields } from "../adapters/reviewValueAdapter";
import type { EvidenceTree } from "../api/evidenceTree";
import { placementOfDocuments } from "../api/evidenceTree";
import { ExtractionReview } from "../components/ExtractionReview";
import { engagementConfig } from "../fixtures/engagementConfig";
import type { EvidenceItem, ExtractedField } from "../types";

/** Block 1 is decided by where a document sits, never by its type: a stationary bill moved there is reference only. */
function field(name: string, value: string): ExtractedField {
  return {
    documentId: "BILL-1",
    canonicalTypeId: "CT-S1-FUELQTY",
    fieldKey: `candidate:${name}`,
    reviewToken: encodeReviewCandidateToken({
      candidate_id: name, evidence_id: "EV-1", document_id: "BILL-1", field_name: name, display_label: name,
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
const BILL = { documentId: "BILL-1", filename: "gas_jan.pdf", format: "pdf", uploadedAt: "2026-10-20T09:00:00Z",
  detectedType: "Stationary fuel consumption record", processingState: "extracted" } as unknown as EvidenceItem;
const values = () => reviewValuesFromFields([field("activity_quantity", "182.4"), field("fuel_type", "Natural gas")], [BILL]);

function review(inSummaryBlock?: boolean) {
  return (
    <ExtractionReview
      engagement={engagementConfig}
      values={values()}
      onValuesChange={vi.fn()}
      initialDocumentId="BILL-1"
      initialDocumentName="gas_jan.pdf"
      typeItem={BILL}
      inSummaryBlock={inSummaryBlock}
      onSaveAsk={vi.fn()}
      onBack={vi.fn()}
      onOpenMethodology={vi.fn()}
    />
  );
}

afterEach(cleanup);

describe("a document placed in Block 1", () => {
  it("opens document-only with the summary note, and offers no values to accept", () => {
    const { container } = render(review(true));
    expect(screen.getByText(/Company-prepared summary document\./)).toBeInTheDocument();
    expect(container.querySelector(".s1-xr-card")).toBeNull();
    expect(screen.queryByRole("button", { name: /Accept/ })).toBeNull();
  });

  it("is a bill like any other when it sits in Block 3 (values to review, no summary note)", () => {
    const { container } = render(review(false));
    expect(screen.queryByText(/Company-prepared summary document\./)).toBeNull();
    expect(container.querySelectorAll(".s1-xr-card").length).toBeGreaterThan(0);
  });
});

describe("where a document sits, read from the tree", () => {
  const row = (document_id: string) => ({ document_id }) as never;
  const tree = {
    blocks: {
      summary: [row("BILL-1")],
      unassigned: [row("U-1")],
      supporting: { scopes: [{ categories: [{ level2s: [{ lines: [{ documents: [row("B-2")] }] }] }] }], unassigned: [row("S-1")] },
    },
  } as unknown as EvidenceTree;

  it("names Block 1, Block 2 and Block 3 documents, by placement alone", () => {
    const where = placementOfDocuments(tree);
    expect(where.get("BILL-1")).toBe("summary");
    expect(where.get("U-1")).toBe("unassigned");
    expect(where.get("B-2")).toBe("supporting");
    expect(where.get("S-1")).toBe("supporting");
  });
});
