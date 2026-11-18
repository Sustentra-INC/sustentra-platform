import { describe, expect, it } from "vitest";

import { decodeReviewCandidateToken, encodeReviewCandidateToken } from "../adapters/fieldAdapter";

describe("review candidate token", () => {
  it("round-trips values outside Latin-1 instead of throwing (Evidence failed to load on 'CO₂')", () => {
    const candidate = {
      candidate_id: "c1",
      evidence_id: "e1",
      document_id: "d1",
      field_name: "fuel_type",
      display_label: "Fuel type – stationary",
      raw_value: "Natural gas (CO₂e) 32°F “metered”",
      normalized_value: "natural gas",
      unit: "therms",
    };
    const token = encodeReviewCandidateToken(candidate);
    const decoded = decodeReviewCandidateToken(token);
    expect(decoded?.raw_value).toBe("Natural gas (CO₂e) 32°F “metered”");
    expect(decoded?.display_label).toBe("Fuel type – stationary");
  });

  it("still reads a plain ASCII token", () => {
    const token = encodeReviewCandidateToken({
      candidate_id: "c2",
      evidence_id: "e2",
      document_id: "d2",
      field_name: "activity_quantity",
      display_label: "Activity quantity",
      raw_value: "6692",
      normalized_value: 6692,
      unit: "CCF",
    });
    expect(decodeReviewCandidateToken(token)?.normalized_value).toBe(6692);
  });
});
