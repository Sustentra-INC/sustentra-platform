import { describe, expect, it } from "vitest";

import { findingDedupeKey } from "../utils/findingKey";
import { resolveId } from "../utils/resolveId";

describe("S2 identity boundaries", () => {
  it("resolves identifiers opaquely without parsing them", () => {
    expect(resolveId("field", "S1-STC-010")).toEqual({
      entity: "field",
      id: "S1-STC-010",
      label: "S1-STC-010",
    });
  });

  it("keys platform findings on field, type, and summary rather than volatile IDs", () => {
    expect(
      findingDedupeKey({
        fieldId: "S1-STC-010",
        type: "misstatement",
        summary: "Quantity differs from source",
      })
    ).toBe("S1-STC-010::misstatement::Quantity differs from source");
  });
});

