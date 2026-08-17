import { describe, expect, it } from "vitest";

import type { Finding, RequestRecord, Requirement } from "../types";
import {
  countActiveFindings,
  preserveDraftAfterSendFailure,
  rerecordExamination,
  reviseNote,
  rollbackAssignment,
  withdrawFinding,
  withdrawRequest,
} from "../utils/lifecycle";

describe("S2 object lifecycle helpers", () => {
  it("retains prior examination entries when re-recording", () => {
    const first = rerecordExamination([], { requirementId: "REQ-1", note: "first" });
    const second = rerecordExamination(first, { requirementId: "REQ-1", note: "second" });

    expect(second).toHaveLength(2);
    expect(second.map((entry) => entry.version)).toEqual([1, 2]);
  });

  it("versions note revisions", () => {
    const first = reviseNote([], "REQ-1", "first note");
    const second = reviseNote(first, "REQ-1", "revised note");

    expect(second).toHaveLength(2);
    expect(second[1].version).toBe(2);
  });

  it("withdraws findings without deleting the row and drops them from counts", () => {
    const findings: Finding[] = [
      finding("F-1", "raised"),
      finding("F-2", "raised"),
    ];
    const withdrawn = withdrawFinding(findings, "F-1");

    expect(withdrawn).toHaveLength(2);
    expect(withdrawn[0].state).toBe("withdrawn");
    expect(countActiveFindings(withdrawn)).toBe(1);
  });

  it("withdraws requests without deleting the record", () => {
    const requests: RequestRecord[] = [request("REQ-1", "sent")];
    const withdrawn = withdrawRequest(requests, "REQ-1");

    expect(withdrawn).toHaveLength(1);
    expect(withdrawn[0].state).toBe("withdrawn");
  });

  it("preserves drafted request state after send failure", () => {
    expect(preserveDraftAfterSendFailure(request("REQ-1", "sent")).state).toBe("drafted");
  });

  it("rolls back optimistic assignment failures", () => {
    const previous: Pick<Requirement, "assignedTo"> = { assignedTo: "user-old" };
    const current: Pick<Requirement, "assignedTo"> = { assignedTo: "user-new" };

    expect(rollbackAssignment(current, previous).assignedTo).toBe("user-old");
  });
});

function finding(id: string, state: Finding["state"]): Finding {
  return {
    id,
    type: "misstatement",
    lineId: "LN-1",
    fieldId: "S1-STC-010",
    summary: "Quantity differs from source",
    state,
    raisedBy: "C. Yang",
    raisedAt: "2026-08-14T00:00:00Z",
  };
}

function request(id: string, state: RequestRecord["state"]): RequestRecord {
  return {
    id,
    state,
    asks: [],
    itemsCovered: 1,
    itemsSatisfied: 0,
  };
}

