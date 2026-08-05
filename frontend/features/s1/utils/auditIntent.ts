export type AuditIntentAction =
  | "accept_detected_type"
  | "change_type"
  | "assign_facility"
  | "assign_period"
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

export function createAuditIntent(intent: AuditIntent): AuditIntent {
  return intent;
}

export function createBulkAuditIntents(
  items: Array<{ documentId: string; oldValue?: AuditIntent["oldValue"]; newValue?: AuditIntent["newValue"] }>,
  action: AuditIntentAction
): AuditIntent[] {
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
): [AuditIntent, AuditIntent] {
  return [
    createAuditIntent({ ...base, action: "correct_value_machine" }),
    createAuditIntent({
      ...base,
      action: "correct_value_human",
      newValue: correctedValue,
    }),
  ];
}
