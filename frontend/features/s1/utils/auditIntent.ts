export type AuditIntentAction =
  | "accept_detected_type"
  | "change_type"
  | "assign_facility"
  | "assign_period"
  | "withdraw_document"
  | "reinstate_document"
  | "set_type"
  | "set_facility"
  | "add_note"
  | "mark_duplicate"
  | "mark_supersedes"
  | "answers_request"
  | "accept_value"
  | "correct_value_machine"
  | "correct_value_human"
  | "enter_value"
  | "re_extract";

export interface AuditIntent {
  action: AuditIntentAction;
  /** The document the change is on. */
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

/**
 * Who a session-only entry is attributed to: the signed-in person, set by the app once it knows them.
 * Until then it is "You", never a made-up name. (Evidence line and placement changes are not session
 * entries: the server records them with the person who made them.)
 */
let sessionActor = { id: "session-user", name: "You" };

export function setAuditActor(actor: { id: string; name: string }): void {
  sessionActor = { id: actor.id || "session-user", name: actor.name.trim() || "You" };
}

export function recordAuditEntry(intent: AuditIntent): SessionAuditEntry {
  return {
    ...intent,
    entryId: `session-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
    actor: { ...sessionActor, actorType: "reviewer" },
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
