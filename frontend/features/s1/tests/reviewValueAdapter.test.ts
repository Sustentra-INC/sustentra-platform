import { describe, expect, it } from "vitest";

import { encodeReviewCandidateToken } from "../adapters/fieldAdapter";
import { reviewValuesFromFields } from "../adapters/reviewValueAdapter";
import type { EvidenceItem, ExtractedField } from "../types";

function field(name: string, value: string | null, extra: Partial<ExtractedField> = {}): ExtractedField {
  return {
    documentId: "DOC-1",
    canonicalTypeId: "CT-S1-MOBFUEL",
    fieldKey: `candidate:${name}:${value}`,
    reviewToken: encodeReviewCandidateToken({
      candidate_id: `${name}:${value}`, evidence_id: "EV-1", document_id: "DOC-1", field_name: name,
      display_label: name, normalized_value: value, unit: null,
    }),
    fieldLabel: name,
    value,
    unit: null,
    valueProperties: [],
    fieldState: value === null ? "missing_requestable" : "populated",
    snippet: null,
    snippetContext: null,
    location: null,
    reviewStatus: "unreviewed",
    correctedValue: null,
    valueOrigin: "extracted",
    ...extra,
  };
}

const DOC = { documentId: "DOC-1", filename: "fleet.pdf", format: "pdf", uploadedAt: "2026-10-12T20:00:00Z",
  detectedType: "Mobile fuel consumption record" } as unknown as EvidenceItem;

describe("extracted fields as review cards", () => {
  it("spans a fuel statement's transaction dates when it has no billing period", () => {
    const cards = reviewValuesFromFields(
      [field("transaction_date", "2024-03-05"), field("transaction_date", "2024-03-02"), field("activity_quantity", "42.31")],
      [DOC]
    );
    expect(cards[0].period).toBe("2024-03-02 to 2024-03-05");
  });

  it("shows who reviewed a value and when, and keeps the machine original on a correction", () => {
    const [card] = reviewValuesFromFields(
      [field("activity_quantity", "42.31", {
        unit: "gal", reviewStatus: "corrected", correctedValue: "42.40", correctedUnit: "gal",
        reviewedBy: "claire@sustentra.com", reviewedAt: "2026-10-12T22:00:00Z",
      })],
      [DOC]
    );
    expect(card.value).toBe("42.40");
    expect(card.originalValue).toBe("42.31");
    expect(card.reviewState).toBe("corrected");
    expect(card.record[1]).toMatchObject({ actor: "claire@sustentra.com", at: "2026-10-12T22:00:00Z" });
  });

  it("dates the system read from the read, not from the upload", () => {
    // The same file name and bytes, uploaded on 12 Oct and read on 15 Oct: the card says 15 Oct.
    const [read] = reviewValuesFromFields([field("activity_quantity", "42.31", { readAt: "2026-10-15T09:30:00Z" })], [DOC]);
    expect(read.record[0]).toMatchObject({ kind: "machine", at: "2026-10-15T09:30:00Z" });
    // With no read time from the server (demo data), the upload time stands in.
    const [unknown] = reviewValuesFromFields([field("activity_quantity", "42.31")], [DOC]);
    expect(unknown.record[0].at).toBe("2026-10-12T20:00:00Z");
  });

  it("gives each document its own read time when two documents hold the same values", () => {
    const other = { ...DOC, documentId: "DOC-2", uploadedAt: "2026-10-15T08:00:00Z" } as EvidenceItem;
    const cards = reviewValuesFromFields(
      [
        field("activity_quantity", "42.31", { readAt: "2026-10-12T20:01:00Z" }),
        field("activity_quantity", "42.31", { documentId: "DOC-2", fieldKey: "candidate:other", readAt: "2026-10-15T08:01:00Z" }),
      ],
      [DOC, other]
    );
    expect(cards.map((c) => [c.documentId, c.record[0].at])).toEqual([
      ["DOC-1", "2026-10-12T20:01:00Z"],
      ["DOC-2", "2026-10-15T08:01:00Z"],
    ]);
  });

  it("gives the reviewer a card for a key value that was not found, and none for others", () => {
    const cards = reviewValuesFromFields([field("activity_quantity", null), field("supplier_name", null)], [DOC]);
    expect(cards.map((c) => [c.whatItIs, c.missing])).toEqual([["activity_quantity", true]]);
    expect(cards[0].record[0].action).toBe("did not find this on the document");
  });

  it("never gives two cards the same id", () => {
    const cards = reviewValuesFromFields([field("account_number", "A"), field("account_number", "A")], [DOC]);
    expect(new Set(cards.map((c) => c.id)).size).toBe(2);
  });
});
