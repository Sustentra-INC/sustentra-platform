export interface AuditActor {
  id: string;
  name: string;
  actorType: "preparer" | "reviewer" | "client" | "system";
}

export interface AuditEntry {
  entryId: string;
  documentId: string;
  fieldKey: string | null;
  action: string;
  oldValue: string | number | boolean | null;
  newValue: string | number | boolean | null;
  actor: AuditActor;
  timestamp: string;
  persistence: "intent_only" | "saved";
}
