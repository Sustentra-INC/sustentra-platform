import { describe, expect, it } from "vitest";

import { sixDocumentEvidence } from "../fixtures/evidence/sixDocuments";
import { selectableEvidenceIds, workspaceNeeds } from "../utils/workspaceState";

describe("workspace state helpers", () => {
  it("excludes withdrawn documents from needs-you counts", () => {
    const base = workspaceNeeds(sixDocumentEvidence);
    const withdrawn = sixDocumentEvidence.map((item) =>
      item.documentId === "DOC-0004" ? { ...item, disposition: "withdrawn" as const } : item
    );

    expect(workspaceNeeds(withdrawn)).toEqual({
      ...base,
      facility: base.facility - 1,
      period: base.period - 1,
      blocked: base.blocked - 1,
    });
  });

  it("excludes withdrawn documents from bulk selection ids", () => {
    const withdrawn = sixDocumentEvidence.map((item) =>
      item.documentId === "DOC-0005" ? { ...item, disposition: "withdrawn" as const } : item
    );

    expect(selectableEvidenceIds(withdrawn)).not.toContain("DOC-0005");
    expect(selectableEvidenceIds(withdrawn)).toHaveLength(sixDocumentEvidence.length - 1);
  });
});
