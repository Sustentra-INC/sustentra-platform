import { api } from "../../../lib/api";

/**
 * Methodology review in the backend (docs/api_contract.md, "Methodology review"). One record
 * per decision field; the catalog, with the allowed values and the editors of each value,
 * comes from the API, so nothing here lists a field or a vocabulary. Who decided and when
 * is recorded by the server: no body below carries a name, a login or a time.
 */

export type MethodologyValue = string | number | boolean | null | string[] | MethodologyValue[] | { [key: string]: MethodologyValue };

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
  /** "Must appear" (true or missing) rows are always on the page; false rows show only once they have a value or were added. */
  required?: boolean;
  /** A multi-select that also takes options of the reviewer's own. */
  free?: boolean;
  /** A short note shown beside the value ("Boundary sentence only"). */
  value_note?: string;
}

export interface MethodologySourceReference {
  page_number?: number | null;
  sheet_name?: string | null;
  cell_or_range?: string | null;
  text_snippet?: string | null;
  [key: string]: unknown;
}

/** The plain location shown after the file name: "page 4", "Sheet1, B12", or "" when unknown. */
export function sourceLocation(ref: MethodologySuggestion["source_reference"] | undefined): string {
  if (typeof ref === "string") return ref.trim();
  if (!ref || typeof ref !== "object") return "";
  const sheet = typeof ref.sheet_name === "string" ? ref.sheet_name.trim() : "";
  const cell = typeof ref.cell_or_range === "string" ? ref.cell_or_range.trim() : "";
  if (sheet || cell) return [sheet, cell].filter(Boolean).join(", ");
  const page = ref.page_number;
  return typeof page === "number" && Number.isInteger(page) && page > 0 ? `page ${page}` : "";
}

/** The quote behind one entry or option of a list suggestion. */
export interface MethodologyEvidence {
  label: string;
  quote: string;
  document_id: string;
  file_name: string;
  source_reference?: MethodologySourceReference | string | null;
  /** True when this quote was cut at 1,000 characters. */
  quote_truncated?: boolean;
}

export interface MethodologySuggestion {
  value: MethodologyValue;
  quote: string;
  document_id: string;
  file_name: string;
  /** An object from the backend; an older record may hold a plain string. */
  source_reference: MethodologySourceReference | string | null;
  /** A list suggestion (entries, options): one quote per entry, in the value's order. */
  evidence?: MethodologyEvidence[];
  /** Entries left out because their quotes did not fit the record (the first ones are kept). */
  entries_omitted?: number;
  /** True when the stored quote was cut at 1,000 characters (it was verified whole). */
  quote_truncated?: boolean;
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
  /** What an empty row reads: not checked yet (no Claude run), not detected (a run found nothing), or it has a value. */
  displayState?: "not_checked" | "not_detected" | "has_value" | string;
  /** Why a conditional row is on the page although its condition is not met (a sentence from the server). */
  shownNote?: string | null;
  /** False for an optional row that is hidden until it has a value or the reviewer adds it. */
  shown?: boolean;
  suggestion: MethodologySuggestion | null;
  decision: MethodologyDecision | null;
  history: {
    at: string;
    by: { name: string; login: string };
    action: "accept" | "edit" | "reject" | "revert" | "add_row" | "remove_row" | string;
    to?: unknown;
  }[];
}

export type AiReasonCode = "off" | "not_configured" | "cap_reached" | "no_documents";

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

type WireRecord = { field_id: string; user_added?: boolean; display_state?: string; shown_note?: string | null } & Omit<
  MethodologyRecord,
  "fieldId" | "userAdded" | "displayState" | "shownNote"
>;
type WireDef = { field_id: string; group_label: string; allowed_labels?: CatalogField["allowedLabels"]; user_added?: boolean } & Omit<
  CatalogField,
  "fieldId" | "groupLabel" | "allowedLabels" | "userAdded"
>;

function readRecord({ field_id, user_added, display_state, shown_note, ...rest }: WireRecord): MethodologyRecord {
  return { ...rest, fieldId: field_id, userAdded: Boolean(user_added), displayState: display_state, shownNote: shown_note ?? null };
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

/** "Add an item": show a hidden optional row, ready for a value. The server remembers it. */
export const revealField = (engagementId: string, fieldId: string) =>
  api<unknown>(`${field(engagementId, fieldId)}/reveal`, { method: "POST", body: {} });

export const prefillMethodology = (engagementId: string) =>
  api<PrefillResult>(`${base(engagementId)}/prefill`, { method: "POST", body: {} });
