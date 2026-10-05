import { describe, expect, it } from "vitest";

import {
  createBulkAuditIntents,
  createCorrectionAuditIntents,
  createAuditIntent,
} from "../utils/auditIntent";

describe("audit intents", () => {
  it("creates one audit intent per bulk target", () => {
    const targets = Array.from({ length: 60 }, (_, index) => ({
      documentId: `DOC-${String(index + 1).padStart(4, "0")}`,
      newValue: "Electric utility bill",
    }));

    const intents = createBulkAuditIntents(targets, "accept_detected_type");

    expect(intents).toHaveLength(60);
    expect(new Set(intents.map((intent) => intent.documentId))).toHaveLength(60);
  });

  it("creates separate machine and human entries for corrections", () => {
    const intents = createCorrectionAuditIntents(
      {
        documentId: "DOC-0001",
        fieldKey: "field:DOC-0001::consumption_kwh",
        oldValue: "142,880",
      },
      "143,000"
    );

    expect(intents.map((intent) => intent.action)).toEqual([
      "correct_value_machine",
      "correct_value_human",
    ]);
    expect(intents[1].newValue).toBe("143,000");
  });

  it("records session audit entries through the audit boundary", () => {
    const entry = createAuditIntent({
      action: "withdraw_document",
      documentId: "DOC-0001",
      oldValue: "active",
      newValue: "withdrawn",
    });

    expect(entry.entryId).toMatch(/^session-/);
    expect(entry.actor.name).toBe("C. Yang");
    expect(entry.persistence).toBe("intent_only");
    expect(entry.timestamp).toBeTruthy();
  });
});
