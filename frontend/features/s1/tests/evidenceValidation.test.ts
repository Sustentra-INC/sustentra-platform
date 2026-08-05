import { describe, expect, it } from "vitest";

import { sixDocumentEvidence } from "../fixtures/evidence/sixDocuments";
import type { EvidenceItem } from "../types";
import { validateEvidenceItems } from "../utils/evidenceValidation";

describe("evidence validation", () => {
  it("accepts the six-document S1 fixture", () => {
    expect(validateEvidenceItems(sixDocumentEvidence)).toEqual([]);
  });

  it("fails blocked documents without halt reasons", () => {
    const invalid: EvidenceItem[] = sixDocumentEvidence.map((item) =>
      item.processingState === "blocked" ? { ...item, haltReason: null } : item
    );

    expect(validateEvidenceItems(invalid)).toContainEqual({
      documentId: "DOC-0004",
      rule: "blocked_reason_required",
    });
  });

  it("fails resolved facility or period states with blank display values", () => {
    const invalid: EvidenceItem[] = [
      { ...sixDocumentEvidence[0], facilityName: "" },
      { ...sixDocumentEvidence[1], periodStart: null },
    ];

    expect(validateEvidenceItems(invalid)).toEqual([
      { documentId: "DOC-0001", rule: "facility_never_blank" },
      { documentId: "DOC-0002", rule: "period_never_blank" },
    ]);
  });
});
