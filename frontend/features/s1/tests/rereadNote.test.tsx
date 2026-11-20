import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { mapBackendCandidateToExtractedField, type BackendExtractionCandidateLike } from "../adapters/fieldAdapter";
import { reviewValuesFromFields } from "../adapters/reviewValueAdapter";
import { RereadNote } from "../components/RereadNote";
import { historySentence, rowFlag } from "../components/SupportingSchedule";
import type { ScheduleHistoryEntry, ScheduleRow } from "../api/evidenceTree";
import type { EvidenceItem } from "../types";

const candidate = (over: Partial<BackendExtractionCandidateLike>): BackendExtractionCandidateLike => ({
  candidate_id: "candidate::EV-1::DOC-1::activity_quantity::r2",
  evidence_id: "EV-1",
  document_id: "DOC-1",
  field_name: "activity_quantity",
  display_label: "Activity quantity (record 2 · Müller Käserei – Zürich)",
  raw_value: "135,63 MWh",
  normalized_value: 135.63,
  unit: "MWh",
  validation_flags: [],
  source_reference: { text_snippet: "Verbrauch 135,63 MWh", page_number: 1 },
  ...over,
});

const pdf = { documentId: "DOC-1", filename: "Rechnung.pdf", format: "pdf" } as unknown as EvidenceItem;
const cardOf = (c: BackendExtractionCandidateLike) =>
  reviewValuesFromFields([mapBackendCandidateToExtractedField(c, "CT-S2-ELEC")], [pdf])[0];

describe("a re-read leaves an earlier decision on a changed value", () => {
  it("shows Review it again on the card, from the API flag", () => {
    const card = cardOf(candidate({ review_reread_changed: true }));
    expect(card.reviewState).toBe("to_review");
    expect(card.rereadChanged).toBe(true);
    const html = renderToStaticMarkup(<RereadNote value={card} />);
    expect(html).toContain("The document was re-read and this value changed. Review it again.");
    expect(html).toContain("s1-muted");
  });

  it("says nothing when the document was not re-read", () => {
    const card = cardOf(candidate({}));
    expect(card.rereadChanged).toBeUndefined();
    expect(renderToStaticMarkup(<RereadNote value={card} />)).toBe("");
  });

  it("says the extracted value changed when a correction carried over", () => {
    const card = cardOf(candidate({ validation_flags: ["extracted_value_changed_since_review"] }));
    expect(card.valueChangedSinceReview).toBe(true);
    expect(renderToStaticMarkup(<RereadNote value={card} />)).toContain("the extracted value changed");
  });

  it("does not show Review it again once the value is reviewed", () => {
    const html = renderToStaticMarkup(
      <RereadNote value={{ rereadChanged: true, reviewState: "accepted" }} />
    );
    expect(html).toBe("");
  });
});

describe("the schedule after a re-read", () => {
  const row = (over: Record<string, unknown>) =>
    ({ record_key: "BILL-1:2", accepted: false, decision: "not_reviewed", ...over }) as unknown as ScheduleRow;

  it("flags a row whose sibling field was rejected as not counted, and nothing on an unreviewed row (those are hidden)", () => {
    expect(rowFlag(row({ decision: "awaiting_other_fields", rejected_fields: ["Fuel type"] }))).toBe("Not counted — Fuel type rejected");
    expect(rowFlag(row({}))).toBeNull();
  });

  it("says when a correction carried over a changed value, and marks a voided decision in the history", () => {
    expect(rowFlag(row({ decision: "edited", accepted: true, value_changed_since_review: true }))).toBe(
      "Edited · Value changed since review"
    );
    const entry = {
      action: "accepted", actor_name: "K. Müller", at: null, field: "Menge", value: "58,92", unit: "MWh",
      file_name: "Rechnung – Zürich.pdf", page: 1, superseded_by_reread: true,
    } as unknown as ScheduleHistoryEntry;
    expect(historySentence(entry)).toContain("no longer applies: the document was re-read");
    expect(historySentence({ ...entry, superseded_by_reread: undefined })).not.toContain("no longer applies");
  });
});
