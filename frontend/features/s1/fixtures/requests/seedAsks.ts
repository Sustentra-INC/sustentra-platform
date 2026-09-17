import type { Ask } from "../../types/requests";

/**
 * Two asks already in flight, so the Add-to-requests cell shows its non-empty
 * states on first load: one requested (request 1, sent), one still not-yet-sent.
 */
export const seedAsks: Ask[] = [
  {
    id: "ASK-SEED-1",
    type: "replace_document",
    whatIsNeeded:
      "scan_0417.pdf · Modesto Bottling · Aug 2025: the scan is unreadable — please re-send a legible copy.",
    source: {
      origin: "workspace_document",
      documentId: "DOC-BLOCKED",
      itemLabel: "scan_0417.pdf",
      facilityName: "Modesto Bottling",
      period: "Aug 2025",
      arrival: "Uploaded",
    },
    raisedByName: "M. Osei",
    raisedByLogin: "mosei",
    raisedAt: "2025-09-14T16:20:00Z",
    state: "requested",
    requestNumber: 1,
    lineNumber: 1,
    resolution: null,
    withdrawReason: null,
    history: [
      { kind: "raised", actorName: "M. Osei", actorLogin: "mosei", at: "2025-09-14T16:20:00Z" },
      { kind: "sent", actorName: "M. Osei", actorLogin: "mosei", at: "2025-09-14T17:02:00Z", detail: "request 1" },
    ],
  },
  {
    id: "ASK-SEED-2",
    type: "replace_document",
    whatIsNeeded:
      "kent_gas_sep_2025.pdf · Kent Cannery · Sep 2025: the service period end date was not found — please confirm it.",
    source: {
      origin: "workspace_document",
      documentId: "DOC-PARTIAL",
      itemLabel: "kent_gas_sep_2025.pdf",
      facilityName: "Kent Cannery",
      period: "Sep 2025",
      arrival: "Uploaded",
    },
    raisedByName: "M. Osei",
    raisedByLogin: "mosei",
    raisedAt: "2025-09-15T09:40:00Z",
    state: "not_yet_sent",
    requestNumber: null,
    lineNumber: null,
    resolution: null,
    withdrawReason: null,
    history: [{ kind: "raised", actorName: "M. Osei", actorLogin: "mosei", at: "2025-09-15T09:40:00Z" }],
  },
];
