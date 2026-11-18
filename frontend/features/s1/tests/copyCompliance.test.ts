import { describe, expect, it } from "vitest";

import { EXACT_COPY } from "../constants/copy";
import { HALT_REASONS } from "../constants/copy";
import {
  haltReasonFromCode,
  mapBackendDocumentToEvidenceItem,
  mapHaltReason,
  resolveCanonicalTypeDisplayName,
  unreadPagesFromWarnings,
} from "../adapters/evidenceAdapter";
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

  const doc = {
    document_id: "document::ENG-S1-2025::big",
    file_name: "big.pdf",
    uploaded_by: "local_reviewer",
    uploaded_at: "2026-08-14T00:00:00Z",
    processing_status: "completed",
    evidence_id: "evidence::ENG-S1-2025::big",
  };

  it("says a document is too long instead of claiming it has no template", () => {
    const sentence = "This document has 501 pages, more than the 500 we read in one document. Split it.";
    const item = mapBackendDocumentToEvidenceItem(doc, {
      status: "partial",
      candidate_count: 0,
      target_count: 0,
      halt_reason: { code: "document_too_long", message: sentence },
    });

    expect(item.processingState).toBe("blocked");
    expect(item.haltReason).toBe(sentence);
    expect(item.haltReason).not.toBe(HALT_REASONS.noTemplate);
    expect(haltReasonFromCode("document_too_long")).toBe(HALT_REASONS.documentTooLong);
  });

  it("shows the page ranges a chunked read could not read, as the server wrote them", () => {
    const item = mapBackendDocumentToEvidenceItem(doc, {
      canonical_type_id: "CT-S1-FUELQTY",
      status: "partial",
      candidate_count: 3,
      target_count: 3,
      found_candidate_count: 3,
      warnings: ["pages_unread: Pages 11-20, 51 could not be read, so any values on them are missing."],
    });

    expect(item.processingState).toBe("extracted");
    expect(item.unreadPages).toBe("11-20, 51");
    expect(unreadPagesFromWarnings(["something else"])).toBeNull();
  });

  it("names Scope 2 electricity bills instead of calling them unmapped", () => {
    expect(resolveCanonicalTypeDisplayName({ canonical_type_id: "CT-S2-ELEC" })).toBe("Purchased electricity record");
  });
});
