import { describe, expect, it } from "vitest";

import type { EvidenceActivityItem } from "../api/evidenceTree";
import { engagementActivity } from "../utils/engagementActivity";

const base = { evidence: [], values: [], asks: [], findings: [] };
const event = (over: Partial<EvidenceActivityItem>): EvidenceActivityItem => ({
  id: "1", event_type: "evidence_line_created", at: "2025-11-04T12:00:00Z", actor_name: "Jane Park", ...over,
});

describe("the Activity log shows what the server recorded on the Evidence page", () => {
  it("writes one plain sentence per event, with the person who made it", () => {
    const log = engagementActivity({
      ...base,
      evidenceEvents: [
        event({ event_type: "evidence_line_created", label: "Propane at Kent", level2_label: "Propane" }),
        event({ id: "2", at: "2025-11-04T12:01:00Z", event_type: "evidence_line_renamed", old_label: "Propane at Kent", new_label: "燃料 tank" }),
        event({ id: "3", at: "2025-11-04T12:02:00Z", event_type: "evidence_line_deleted", label: "燃料 tank", documents_moved: 3 }),
        event({ id: "4", at: "2025-11-04T12:03:00Z", event_type: "evidence_line_deleted", label: "x", documents_moved: 1 }),
        event({ id: "5", at: "2025-11-04T12:04:00Z", event_type: "evidence_document_moved", document_id: "D1", from_label: "Natural gas · Kent", to_label: "Unassigned supporting evidence", actor_name: null }),
      ],
    });
    expect(log.map((e) => e.what)).toEqual([
      "moved a document from Natural gas · Kent to Unassigned supporting evidence",
      "deleted the line x, moving 1 document to Unassigned supporting evidence",
      "deleted the line 燃料 tank, moving 3 documents to Unassigned supporting evidence",
      "renamed the line Propane at Kent to 燃料 tank",
      "added the line Propane · Propane at Kent",
    ]);
    expect(log[4].who).toBe("Jane Park");
    expect(log[0].who).toBe("A team member");
    expect(log.every((e) => e.kind === "document")).toBe(true);
  });

  it("names the file a document move concerns when the page knows it", () => {
    const log = engagementActivity({
      ...base,
      evidence: [{ documentId: "D1", filename: "feb-bill.pdf", uploadedAt: "2025-01-01T00:00:00Z", uploadedBy: { name: "Ana" } }] as never,
      evidenceEvents: [event({ event_type: "evidence_document_moved", document_id: "D1", from_label: "A", to_label: "B" })],
    });
    expect(log.find((e) => e.what.startsWith("moved"))?.what).toBe("moved feb-bill.pdf from A to B");
  });

  it("words the folder events", () => {
    const log = engagementActivity({
      ...base,
      evidenceEvents: [
        event({ event_type: "evidence_folder_created", folder_name: "Données 排放" }),
        event({ id: "2", at: "2025-11-04T12:01:00Z", event_type: "evidence_folder_renamed", old_label: "Données 排放", new_label: "Archive" }),
        event({ id: "3", at: "2025-11-04T12:02:00Z", event_type: "evidence_document_folder_set", document_id: "D1", from_label: "Archive", to_label: "Summary documents and workbook" }),
        event({ id: "4", at: "2025-11-04T12:03:00Z", event_type: "evidence_folder_deleted", folder_name: "Archive", documents_moved: 2 }),
      ],
    });
    expect(log.map((e) => e.what)).toEqual([
      "deleted the folder Archive, moving 2 documents to the top of Summary documents and workbook",
      "moved a document from Archive to Summary documents and workbook",
      "renamed the folder Données 排放 to Archive",
      "added the folder Données 排放",
    ]);
  });
});
