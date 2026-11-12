import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { mapBackendDocumentToEvidenceItem } from "../adapters/evidenceAdapter";
import { AiTypeNote } from "../components/AiTypeNote";

const document = {
  document_id: "DOC-1",
  file_name: "log.pdf",
  uploaded_by: "u",
  uploaded_at: "2026-11-11T00:00:00Z",
  processing_status: "completed",
  evidence_id: "EV-1",
};
const routing = { canonical_type_id: "CT-S1-REFRSVC", quote: "Refrigerant charge log", page_number: 1, used: true };

describe("Claude's type suggestion", () => {
  it("asks the reviewer to confirm a type Claude set, with its quote", () => {
    const item = mapBackendDocumentToEvidenceItem(document, {
      canonical_type_id: "CT-S1-REFRSVC",
      canonical_type_source: "ai",
      ai_routing: routing,
    });
    expect(item.typeReviewBand).toBe("needs_review");
    const html = renderToStaticMarkup(<AiTypeNote item={item} />);
    expect(html).toContain("Type suggested by Claude, please confirm");
    expect(html).toContain("Refrigerant charge log");
  });

  it("says in words that Claude disagreed, and leaves the type as the rules set it", () => {
    const item = mapBackendDocumentToEvidenceItem(document, {
      canonical_type_id: "CT-S2-ELEC",
      canonical_type_source: "classifier",
      ai_routing: { ...routing, used: false, disagrees: true },
    });
    expect(item.typeReviewBand).toBe("auto_accepted");
    expect(renderToStaticMarkup(<AiTypeNote item={item} />)).toContain("The type was not changed");
  });

  it("shows nothing for a document Claude did not read", () => {
    const item = mapBackendDocumentToEvidenceItem(document, { canonical_type_id: "CT-S2-ELEC" });
    expect(item.aiType).toBeUndefined();
    expect(renderToStaticMarkup(<AiTypeNote item={item} />)).toBe("");
  });
});
