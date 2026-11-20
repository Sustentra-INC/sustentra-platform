import { describe, expect, it } from "vitest";

import type { MethodologyRecord } from "../api/methodologyReview";
import { factsReadByDocument } from "../utils/methodologyFacts";

const record = (document_id: string | null, evidence: string[] = []): MethodologyRecord =>
  ({
    fieldId: "f",
    userAdded: false,
    suggestion: document_id
      ? { value: "Yes", quote: "q", document_id, file_name: "x", source_reference: null, evidence: evidence.map((d) => ({ label: "l", quote: "q", document_id: d, file_name: "x" })), origin: "ai", model: "m", request_id: "r", suggested_at: "t" }
      : null,
    decision: null,
    history: [],
  }) as MethodologyRecord;

describe("factsReadByDocument", () => {
  it("counts each field once per document it cites, as its source or through an entry", () => {
    const counts = factsReadByDocument({ fields: [record("A"), record("B", ["A", "A", "C"]), record(null)] });
    expect([...counts]).toEqual([["A", 2], ["B", 1], ["C", 1]]);
  });
  it("is empty when nothing was suggested", () => {
    expect(factsReadByDocument({ fields: [] }).size).toBe(0);
  });
});
