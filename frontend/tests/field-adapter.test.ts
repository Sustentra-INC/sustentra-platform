import { describe, it, expect } from "vitest";

import { mapBackendCandidateToExtractedField } from "../features/s1/adapters/fieldAdapter";

const base = {
  candidate_id: "candidate::EV-1::DOC-1::activity_quantity::r2",
  evidence_id: "EV-1",
  document_id: "DOC-1",
  field_name: "activity_quantity",
  display_label: "Activity quantity (record 2 · PR-A1174 · 2024-01-30 to 2024-02-28)",
  raw_value: "748",
  normalized_value: 748,
  unit: "ccf",
  confidence: 0.88,
  validation_flags: [],
};

describe("mapBackendCandidateToExtractedField", () => {
  it("maps the contract bounding box {x, y, width, height} to the page region", () => {
    const field = mapBackendCandidateToExtractedField(
      {
        ...base,
        source_reference: {
          page_number: 1,
          text_snippet: "Meter # ... Usage | PR-A1174 ... 748 CCF",
          bounding_box: { x: 0.62, y: 0.31, width: 0.05, height: 0.015 },
        },
      },
      "CT-S1-FUELQTY",
    );
    expect(field.location).toEqual({ kind: "page", page: 1, region: { x: 0.62, y: 0.31, w: 0.05, h: 0.015 } });
    expect(field.fieldLabel).toContain("record 2");
    expect(field.value).toBe("748");
  });

  it("still accepts legacy w/h boxes", () => {
    const field = mapBackendCandidateToExtractedField(
      {
        ...base,
        source_reference: {
          page_number: 2,
          bounding_box: { x: 0.1, y: 0.2, w: 0.3, h: 0.04 },
        },
      },
      "CT-S1-FUELQTY",
    );
    expect(field.location).toEqual({ kind: "page", page: 2, region: { x: 0.1, y: 0.2, w: 0.3, h: 0.04 } });
  });
});
