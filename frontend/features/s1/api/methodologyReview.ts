import { api } from "../../../lib/api";

/**
 * Methodology review in the backend (GET and POST /engagements/{id}/methodology-review).
 * One record per decision field; the catalog, with the allowed values, comes from the
 * API, so nothing here lists a field or a vocabulary. Who decided and when is recorded
 * by the server: no body below carries a name, a login or a time.
 */

export type MethodologyValue = string | number | boolean | null | string[] | { [key: string]: MethodologyValue };

export interface CatalogField {
  fieldId: string;
  group: string;
  label: string;
  kind: string;
  /** An enum's values, or for a field of several parts the values of each part. */
  allowed?: string[] | Record<string, string[]>;
  userAdded?: boolean;
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
  status: string;
  value: MethodologyValue;
  reason?: string | null;
  by: { name: string; login: string };
  at: string;
}

export interface MethodologyRecord {
  fieldId: string;
  suggestion: MethodologySuggestion | null;
  decision: MethodologyDecision | null;
  history: { at: string; by: { name: string; login: string }; action: string; from?: unknown; to?: unknown }[];
}

export interface AiStatus {
  enabled: boolean;
  provider?: string | null;
  model?: string | null;
  month_spend_usd?: number | null;
  cap_usd?: number | null;
  reason_if_off?: string | null;
}

export interface MethodologyReviewData {
  fields: MethodologyRecord[];
  catalog: CatalogField[];
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

export type RowGroup = "entities" | "factor:scope1" | "factor:scope2";

const base = (engagementId: string) => `/engagements/${encodeURIComponent(engagementId)}/methodology-review`;
const field = (engagementId: string, fieldId: string) => `${base(engagementId)}/${encodeURIComponent(fieldId)}`;

type Wire<T> = Omit<T, "fieldId"> & { field_id: string };

/** The server names a field `field_id`; the screen reads it as `fieldId`, the methodology review's own id (not an extraction field). */
export async function getMethodologyReview(engagementId: string): Promise<MethodologyReviewData> {
  const wire = await api<{ fields: Wire<MethodologyRecord>[]; catalog: (Wire<CatalogField> & { user_added?: boolean })[]; ai: AiStatus }>(base(engagementId));
  const rename = <T extends { field_id: string }>({ field_id, ...rest }: T) => ({ ...rest, fieldId: field_id });
  return {
    ai: wire.ai,
    catalog: wire.catalog.map((c) => ({ ...rename(c), userAdded: c.user_added })) as unknown as CatalogField[],
    fields: wire.fields.map(rename) as unknown as MethodologyRecord[],
  };
}

export const acceptField = (engagementId: string, fieldId: string) =>
  api<unknown>(`${field(engagementId, fieldId)}/accept`, { method: "POST", body: {} });

export const editField = (engagementId: string, fieldId: string, value: MethodologyValue) =>
  api<unknown>(`${field(engagementId, fieldId)}/edit`, { method: "POST", body: { value } });

export const rejectField = (engagementId: string, fieldId: string, reason: string) =>
  api<unknown>(`${field(engagementId, fieldId)}/reject`, { method: "POST", body: { reason } });

export const revertField = (engagementId: string, fieldId: string) =>
  api<unknown>(`${field(engagementId, fieldId)}/revert`, { method: "POST", body: {} });

export const addRow = (engagementId: string, group: RowGroup) =>
  api<unknown>(`${base(engagementId)}/rows`, { method: "POST", body: { group } });

export const removeRow = (engagementId: string, fieldId: string) =>
  api<unknown>(field(engagementId, fieldId), { method: "DELETE" });

export const prefillMethodology = (engagementId: string) =>
  api<PrefillResult>(`${base(engagementId)}/prefill`, { method: "POST", body: {} });
