export type AuditIntentAction =
  | "accept_detected_type"
  | "change_type"
  | "assign_facility"
  | "assign_period"
  | "withdraw_document"
  | "reinstate_document"
  | "accept_value"
  | "correct_value_machine"
  | "correct_value_human"
  | "enter_value"
  | "re_extract";

export interface AuditIntent {
  action: AuditIntentAction;
  documentId: string;
  fieldKey?: string;
  oldValue?: string | number | boolean | null;
  newValue?: string | number | boolean | null;
}

export interface SessionAuditEntry extends AuditIntent {
  entryId: string;
  actor: {
    id: string;
    name: string;
    actorType: "preparer" | "reviewer" | "client" | "system";
  };
  timestamp: string;
  persistence: "intent_only" | "saved";
}

export function recordAuditEntry(intent: AuditIntent): SessionAuditEntry {
  return {
    ...intent,
    entryId: `session-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
    actor: { id: "session-reviewer", name: "C. Yang", actorType: "reviewer" },
    timestamp: new Date().toISOString(),
    persistence: "intent_only",
  };
}

export function createAuditIntent(intent: AuditIntent): SessionAuditEntry {
  return recordAuditEntry(intent);
}

export function createBulkAuditIntents(
  items: Array<{ documentId: string; oldValue?: AuditIntent["oldValue"]; newValue?: AuditIntent["newValue"] }>,
  action: AuditIntentAction
): SessionAuditEntry[] {
  return items.map((item) =>
    createAuditIntent({
      action,
      documentId: item.documentId,
      oldValue: item.oldValue ?? null,
      newValue: item.newValue ?? null,
    })
  );
}

export function createCorrectionAuditIntents(
  base: Omit<AuditIntent, "action" | "newValue">,
  correctedValue: string | number | boolean | null
): [SessionAuditEntry, SessionAuditEntry] {
  return [
    createAuditIntent({ ...base, action: "correct_value_machine" }),
    createAuditIntent({
      ...base,
      action: "correct_value_human",
      newValue: correctedValue,
    }),
  ];
}
