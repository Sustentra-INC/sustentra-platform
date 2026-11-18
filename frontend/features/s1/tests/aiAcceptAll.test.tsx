/* @vitest-environment jsdom */
import { describe, expect, it, vi } from "vitest";
import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen } from "@testing-library/react";

import { mapBackendCandidateToExtractedField, type BackendExtractionCandidateLike } from "../adapters/fieldAdapter";
import { reviewValuesFromFields } from "../adapters/reviewValueAdapter";
import { ExtractionReview } from "../components/ExtractionReview";
import { engagementConfig } from "../fixtures/engagementConfig";
import type { EvidenceItem } from "../types";
import type { ReviewValue } from "../types/review";

const DOC = {
  documentId: "DOC-1",
  filename: "bill.pdf",
  format: "pdf",
  uploadedAt: "2026-10-20T09:00:00Z",
  detectedType: "Electricity bill",
} as unknown as EvidenceItem;

const candidate = (name: string, value: string, flags: string[] = [], id = name): BackendExtractionCandidateLike => ({
  candidate_id: id,
  evidence_id: "EV-1",
  document_id: "DOC-1",
  field_name: name,
  display_label: name,
  normalized_value: value,
  unit: null,
  validation_flags: flags,
  source_reference: { text_snippet: `${name} ${value}`, page_number: 1 },
});

function review(candidates: BackendExtractionCandidateLike[]) {
  const values = reviewValuesFromFields(
    candidates.map((c) => mapBackendCandidateToExtractedField(c, "CT-S2-ELEC")),
    [DOC]
  );
  const onValuesChange = vi.fn();
  render(
    <ExtractionReview
      engagement={engagementConfig}
      values={values}
      onValuesChange={onValuesChange}
      initialDocumentId="DOC-1"
      onSaveAsk={vi.fn()}
      onBack={vi.fn()}
    />
  );
  return { values, onValuesChange };
}

describe("Accept all and Claude's readings", () => {
  it("skips a suggested value and both sides of a conflict, and says how many it skipped", () => {
    const { values, onValuesChange } = review([
      candidate("account_number", "5521-8890"),
      candidate("supplier_name", "Meridian"),
      candidate("meter_number", "MTR-1", ["ai_suggested"]),
      candidate("activity_quantity", "12400", ["ai_suggested", "ai_conflict"], "q1"),
      candidate("activity_quantity", "13100", ["ai_suggested", "ai_conflict"], "q2"),
    ]);
    expect(screen.getByRole("button", { name: "Accept all 2" })).toBeInTheDocument();
    expect(screen.getByText("3 suggested by Claude need individual review")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Accept all 2" }));
    const next = (onValuesChange.mock.calls[0][0] as (cur: ReviewValue[]) => ReviewValue[])(values);
    const states = Object.fromEntries(next.map((v) => [v.reviewToken ? v.whatItIs + v.value : v.id, v.reviewState]));
    expect(states).toEqual({
      "account_number5521-8890": "accepted",
      "supplier_nameMeridian": "accepted",
      "meter_numberMTR-1": "to_review",
      "activity_quantity12400": "to_review",
      "activity_quantity13100": "to_review",
    });
  });

  it("offers no Accept all when only Claude's readings are left, but still says so", () => {
    review([candidate("account_number", "5521-8890", ["ai_suggested"]), candidate("meter_number", "MTR-1", ["ai_suggested"])]);
    expect(screen.queryByRole("button", { name: /Accept all/ })).toBeNull();
    expect(screen.getByText("2 suggested by Claude need individual review")).toBeInTheDocument();
  });
});
