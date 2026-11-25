import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { mapBackendDocumentToEvidenceItem } from "../adapters/evidenceAdapter";
import { workspaceNeeds } from "../utils/workspaceState";
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
    expect(html).toContain("Type suggested by Sustentra&#x27;s AI, please confirm");
    expect(html).toContain("Refrigerant charge log");
    expect(html).not.toMatch(/CT-/);
  });

  it("says in words that Claude disagreed, and leaves the type as the rules set it", () => {
    const item = mapBackendDocumentToEvidenceItem(document, {
      canonical_type_id: "CT-S2-ELEC",
      canonical_type_source: "classifier",
      ai_routing: { ...routing, used: false, disagrees: true },
    });
    expect(item.typeReviewBand).toBe("needs_review");
    expect(item.typeReviewReason).toBe("Type to check");
    const html = renderToStaticMarkup(<AiTypeNote item={item} />);
    expect(html).toContain("Type to check");
    expect(html).toContain("The rules chose Purchased electricity record");
    expect(html).toContain("The type was not changed");
    expect(html).toContain("page 1");
    expect(html).toContain("Refrigerant service record");
    expect(html).not.toMatch(/CT-/);
  });

  it("shows nothing for a document Claude did not read", () => {
    const item = mapBackendDocumentToEvidenceItem(document, { canonical_type_id: "CT-S2-ELEC" });
    expect(item.aiType).toBeUndefined();
    expect(renderToStaticMarkup(<AiTypeNote item={item} />)).toBe("");
  });

  const disagreeing = (extra: object = {}, summary: object = {}) =>
    mapBackendDocumentToEvidenceItem(document, {
      canonical_type_id: "CT-S2-ELEC",
      canonical_type_source: "classifier",
      ai_routing: { ...routing, used: false, disagrees: true, ...extra },
      ...summary,
    });

  it("clears the mark once a person confirmed or changed the type", () => {
    const item = disagreeing();
    expect(renderToStaticMarkup(<AiTypeNote item={{ ...item, typeConfirmed: true }} />)).toBe("");
  });

  it("does not mark a document the rules and Sustentra's AI agree on, or an old run with no ai_routing block", () => {
    expect(mapBackendDocumentToEvidenceItem(document, { canonical_type_id: "CT-S2-ELEC", ai_routing: { ...routing, used: false, disagrees: false } }).typeReviewBand).toBe("auto_accepted");
    const old = mapBackendDocumentToEvidenceItem(document, { canonical_type_id: "CT-S2-ELEC", canonical_type_source: "classifier" });
    expect(old.typeReviewBand).toBe("auto_accepted");
    expect(renderToStaticMarkup(<AiTypeNote item={old} />)).toBe("");
  });

  it("names an unknown type id in words and never shows the id", () => {
    const html = renderToStaticMarkup(<AiTypeNote item={disagreeing({ canonical_type_id: "CT-NOT-A-TYPE" })} />);
    expect(html).toContain("Unmapped document type");
    expect(html).not.toMatch(/CT-/);
  });

  it("renders a markup quote as text and cuts a very long one", () => {
    const html = renderToStaticMarkup(<AiTypeNote item={disagreeing({ quote: `<img src=x onerror=alert(1)>${"x".repeat(5000)}` })} />);
    expect(html).not.toContain("<img");
    expect(html).toContain("&lt;img");
    expect(html.length).toBeLessThan(1500);
  });

  it("keeps a missing quote or page from breaking the note", () => {
    const html = renderToStaticMarkup(<AiTypeNote item={disagreeing({ quote: "", page_number: null })} />);
    expect(html).toContain("Type to check");
    expect(html).not.toContain("“”");
  });

  it("never says Claude or a model id", () => {
    const html = renderToStaticMarkup(<AiTypeNote item={disagreeing()} />);
    expect(html).not.toMatch(/Claude|sonnet|opus|haiku/i);
  });

  it("counts a type to check as needing a person until it is confirmed", () => {
    const item = disagreeing();
    expect(workspaceNeeds([item]).type).toBe(1);
    expect(workspaceNeeds([{ ...item, typeConfirmed: true, typeReviewBand: null }]).type).toBe(0);
  });
});
