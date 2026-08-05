import { describe, expect, it } from "vitest";

import { EXACT_COPY } from "../constants/copy";
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
});
