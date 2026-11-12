import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { mapBackendCandidateToExtractedField, type BackendExtractionCandidateLike } from "../adapters/fieldAdapter";
import { reviewValuesFromFields } from "../adapters/reviewValueAdapter";
import { AiValueNote } from "../components/AiValueNote";
import { STATE_ROLE_BY_PAIR } from "../constants/stateIndicators";
import type { EvidenceItem } from "../types";

const candidate = (over: Partial<BackendExtractionCandidateLike>): BackendExtractionCandidateLike => ({
  candidate_id: "candidate::EV-1::DOC-1::account_number",
  evidence_id: "EV-1",
  document_id: "DOC-1",
  field_name: "account_number",
  display_label: "Account number",
  raw_value: "5521-8890",
  normalized_value: "5521-8890",
  unit: null,
  confidence: 0.6,
  validation_flags: [],
  source_reference: { text_snippet: "Account Number 5521-8890", page_number: 2 },
  ...over,
});

const pdf = { documentId: "DOC-1", filename: "bill.pdf", format: "pdf" } as unknown as EvidenceItem;
const cardOf = (c: BackendExtractionCandidateLike) =>
  reviewValuesFromFields([mapBackendCandidateToExtractedField(c, "CT-S2-ELEC")], [pdf])[0];

describe("Claude's readings on the review cards", () => {
  it("maps the three flags and never pre-accepts a suggested value", () => {
    for (const flag of ["ai_suggested", "ai_disagrees", "ai_conflict"] as const) {
      const field = mapBackendCandidateToExtractedField(candidate({ validation_flags: [flag] }), "CT-S2-ELEC");
      expect(field.valueProperties).toContain(flag);
      expect(field.reviewStatus).toBe("unreviewed");
      expect(STATE_ROLE_BY_PAIR.valueProperty?.[flag]).toBe("open");
    }
    const card = cardOf(candidate({ validation_flags: ["ai_suggested"] }));
    expect(card.reviewState).toBe("to_review"); // needs review
    expect(card.ai).toEqual({ suggested: true });
    expect(card.record[0].actor).toBe("Claude");
  });

  it("shows the Suggested by Claude chip with the verified snippet and its page", () => {
    const html = renderToStaticMarkup(<AiValueNote value={cardOf(candidate({ validation_flags: ["ai_suggested"] }))} />);
    expect(html).toContain("Suggested by Claude");
    expect(html).toContain("Account Number 5521-8890");
    expect(html).toContain("page 2");
  });

  it("says Claude read two different values when the suggestion has a conflict", () => {
    const html = renderToStaticMarkup(
      <AiValueNote value={cardOf(candidate({ validation_flags: ["ai_suggested", "ai_conflict"] }))} />
    );
    expect(html).toContain("Suggested by Claude");
    expect(html).toContain("Claude read two different values here");
  });

  it("shows Claude's value and quote where the rules read another value, and keeps the rules' value", () => {
    const card = cardOf(
      candidate({
        field_name: "supplier_name",
        normalized_value: "Acme Energy",
        validation_flags: ["ai_disagrees"],
        ai_alternative: {
          value: "Meridian Power & Light",
          unit: null,
          source_reference: { text_snippet: "Supplier Meridian Power & Light", page_number: 1 },
        },
      })
    );
    expect(card.value).toBe("Acme Energy");
    const html = renderToStaticMarkup(<AiValueNote value={card} />);
    expect(html).toContain("Claude read a different value here");
    expect(html).toContain("Meridian Power &amp; Light");
    expect(html).toContain("Supplier Meridian Power &amp; Light");
    expect(html).toContain("page 1");
    expect(html).not.toContain("Suggested by Claude");
  });

  it("names no page for a workbook or CSV reading", () => {
    const card = { ...cardOf(candidate({ validation_flags: ["ai_suggested"] })), sourceKind: "spreadsheet" as const };
    expect(renderToStaticMarkup(<AiValueNote value={card} />)).not.toContain("· page");
  });

  it("shows nothing for a value Claude did not touch, or once the reviewer has accepted it", () => {
    expect(renderToStaticMarkup(<AiValueNote value={cardOf(candidate({}))} />)).toBe("");
    const accepted = { ...cardOf(candidate({ validation_flags: ["ai_suggested"] })), reviewState: "accepted" as const };
    expect(renderToStaticMarkup(<AiValueNote value={accepted} />)).toBe("");
  });
});
