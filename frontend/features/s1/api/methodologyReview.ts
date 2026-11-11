import { api } from "../../../lib/api";

/**
 * Methodology review in the backend (docs/api_contract.md, "Methodology review"). One record
 * per decision field; the catalog, with the allowed values and the editors of each value,
 * comes from the API, so nothing here lists a field or a vocabulary. Who decided and when
 * is recorded by the server: no body below carries a name, a login or a time.
 */

export type MethodologyValue = string | number | boolean | null | string[] | { [key: string]: MethodologyValue };

export interface FieldPart {
  key: string;
  label: string;
  kind: "text" | "list" | "percent" | "enum" | string;
  allowed?: string[];
}

export interface CatalogField {
  fieldId: string;
  group: string;
  groupLabel: string;
  label: string;
  kind: "text" | "enum" | "entity" | "factor" | "gwp" | string;
  /** An enum's values; for gwp `{set, horizon}`; for an entity `{operational_control}`. */
  allowed?: string[] | Record<string, string[]>;
  /** Display names of allowed values, e.g. `{set: {AR5: "..."}}` for gwp. */
  allowedLabels?: Record<string, Record<string, string>>;
  /** The value's editors (entity, factor, gwp), so a blank row can be drawn. */
  parts?: FieldPart[];
  userAdded: boolean;
}

export interface MethodologySuggestion {
  value: MethodologyValue;
  quote: string;
  document_id: string;
  file_name: string;
  source_reference: string | null;
  origin: string;
  model: string;
  request_id: string;
  suggested_at: string;
}

export interface MethodologyDecision {
  status: "pending" | "accepted" | "edited" | "rejected" | string;
  /** null when rejected. */
  value: MethodologyValue;
  reason?: string | null;
  by: { name: string; login: string };
  at: string;
}

export interface MethodologyRecord {
  fieldId: string;
  /** Only rows the reviewer added can be removed. */
  userAdded: boolean;
  suggestion: MethodologySuggestion | null;
  decision: MethodologyDecision | null;
  history: {
    at: string;
    by: { name: string; login: string };
    action: "accept" | "edit" | "reject" | "revert" | "add_row" | "remove_row" | string;
    to?: unknown;
  }[];
}

export type AiReasonCode = "off" | "not_configured" | "cap_reached" | "no_documents" | "not_built";

export interface AiStatus {
  enabled: boolean;
  /** null when Claude can be asked; a code this screen does not know still shows `reason`. */
  reason_code: AiReasonCode | string | null;
  /** The sentence to show. */
  reason: string | null;
  provider?: string | null;
  model?: string | null;
  month_spend_usd?: number | null;
  cap_usd?: number | null;
}

export interface MethodologyReviewData {
  fields: MethodologyRecord[];
  catalog: CatalogField[];
  groups: { group: string; label: string }[];
  rowGroups: string[];
  ai: AiStatus;
}

export interface PrefillResult {
  suggested: number;
  dropped: Record<string, number>;
  kept_reviewer_decision: number;
  documents_read: { document_id: string; file_name: string; truncated: boolean }[];
  cost_usd: number;
  model: string;
}

const base = (engagementId: string) => `/engagements/${encodeURIComponent(engagementId)}/methodology-review`;
const field = (engagementId: string, fieldId: string) => `${base(engagementId)}/${encodeURIComponent(fieldId)}`;

type WireRecord = { field_id: string; user_added?: boolean } & Omit<MethodologyRecord, "fieldId" | "userAdded">;
type WireDef = { field_id: string; group_label: string; allowed_labels?: CatalogField["allowedLabels"]; user_added?: boolean } & Omit<
  CatalogField,
  "fieldId" | "groupLabel" | "allowedLabels" | "userAdded"
>;

function readRecord({ field_id, user_added, ...rest }: WireRecord): MethodologyRecord {
  return { ...rest, fieldId: field_id, userAdded: Boolean(user_added) };
}

function readDef({ field_id, group_label, allowed_labels, user_added, ...rest }: WireDef): CatalogField {
  return { ...rest, fieldId: field_id, groupLabel: group_label, allowedLabels: allowed_labels, userAdded: Boolean(user_added) };
}

/** The server names a field `field_id`; the screen reads it as `fieldId`, the methodology review's own id (not an extraction field). */
export async function getMethodologyReview(engagementId: string): Promise<MethodologyReviewData> {
  const wire = await api<{ fields: WireRecord[]; catalog: WireDef[]; groups: { group: string; label: string }[]; row_groups: string[]; ai: AiStatus }>(
    base(engagementId)
  );
  return { ai: wire.ai, groups: wire.groups, rowGroups: wire.row_groups, catalog: wire.catalog.map(readDef), fields: wire.fields.map(readRecord) };
}

export const acceptField = (engagementId: string, fieldId: string) =>
  api<unknown>(`${field(engagementId, fieldId)}/accept`, { method: "POST", body: {} });

export const editField = (engagementId: string, fieldId: string, value: MethodologyValue) =>
  api<unknown>(`${field(engagementId, fieldId)}/edit`, { method: "POST", body: { value } });

export const rejectField = (engagementId: string, fieldId: string, reason: string) =>
  api<unknown>(`${field(engagementId, fieldId)}/reject`, { method: "POST", body: { reason } });

export const revertField = (engagementId: string, fieldId: string) =>
  api<unknown>(`${field(engagementId, fieldId)}/revert`, { method: "POST", body: {} });

/** `group` is one of the GET's `row_groups`. */
export const addRow = (engagementId: string, group: string) =>
  api<unknown>(`${base(engagementId)}/rows`, { method: "POST", body: { group } });

export const removeRow = (engagementId: string, fieldId: string) =>
  api<unknown>(field(engagementId, fieldId), { method: "DELETE" });

export const prefillMethodology = (engagementId: string) =>
  api<PrefillResult>(`${base(engagementId)}/prefill`, { method: "POST", body: {} });
