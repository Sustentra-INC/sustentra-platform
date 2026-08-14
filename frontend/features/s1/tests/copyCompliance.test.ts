import { describe, expect, it } from "vitest";

import { EXACT_COPY } from "../constants/copy";
import { HALT_REASONS } from "../constants/copy";
import { mapBackendDocumentToEvidenceItem, mapHaltReason } from "../adapters/evidenceAdapter";
import { sixDocumentEvidence } from "../fixtures/evidence/sixDocuments";
import { findBlockedUiTerms } from "../utils/copyCompliance";

describe("copy compliance", () => {
  it("keeps fixture-visible S1 copy free of blocked UI terms", () => {
    const visibleFixtureText = [
      ...Object.values(EXACT_COPY),
      ...sixDocumentEvidence.flatMap((item) => [
        item.filename,
        item.detectedType,
        item.typeReviewReason,
        item.facilityName,
        item.haltReason,
        item.reviewArea,
        item.note,
      ]),
    ]
      .filter((value): value is string => typeof value === "string")
      .join(" ");

    expect(findBlockedUiTerms(visibleFixtureText)).toEqual([]);
  });

  it("blocks raw percentage copy and completed-state language", () => {
    expect(findBlockedUiTerms("This is 85% complete.")).toEqual(["complete", "numeric percentage"]);
    expect(findBlockedUiTerms("Completeness renders here.")).toEqual([]);
  });

  it("maps backend halt details to exact halt reasons only", () => {
    const rendered = [
      mapHaltReason({ noExtractionTargets: true, details: ["Parser stage returned failed status."] }),
      mapHaltReason({
        noExtractionTargets: false,
        details: ["No confident canonical_type_id available; target planning skipped."],
      }),
      mapHaltReason({ noExtractionTargets: false, details: ["OCR failed upstream."] }),
    ];

    expect(rendered).toEqual([
      HALT_REASONS.noTemplate,
      HALT_REASONS.pipeline,
      HALT_REASONS.ocrFailed,
    ]);
    const allowedReasons = new Set<string>(Object.values(HALT_REASONS));
    expect(rendered.every((value) => allowedReasons.has(value))).toBe(true);
  });

  it("does not render raw canonical type IDs as detected type names", () => {
    const item = mapBackendDocumentToEvidenceItem(
      {
        document_id: "document::ENG-S1-2025::type-test",
        file_name: "gas-bill.pdf",
        uploaded_by: "local_reviewer",
        uploaded_at: "2026-08-14T00:00:00Z",
        processing_status: "completed",
        evidence_id: "evidence::ENG-S1-2025::type-test",
      },
      {
        canonical_type_id: "CT-S1-FUELQTY",
        target_count: 1,
        candidate_count: 1,
        found_candidate_count: 1,
        status: "completed",
      }
    );

    expect(item.detectedType).toBe("Stationary fuel consumption record");
    expect(item.detectedType).not.toMatch(/^CT-/);
  });
});
