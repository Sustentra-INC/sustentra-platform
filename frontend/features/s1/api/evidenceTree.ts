import { api } from "../../../lib/api";
import type { DocumentDecision } from "../types";

/**
 * The Evidence tree and the supporting schedule (backend routes of the calculation-lines work).
 * Every number on these screens is computed by the backend; the frontend only lays it out.
 * Shapes follow the API contract: GET /engagements/{id}/evidence-tree and
 * GET /engagements/{id}/calculation-lines/{line_key}/schedule.
 */

export type AnchorKind = "facility" | "vehicle_group" | "company";

export interface CalculationLine {
  key: string;
  scope: string;
  category: string;
  level2: string;
  level2_label: string;
  anchor_kind: AnchorKind;
  anchor_id: string;
  label: string;
  facility_id: string | null;
  created_by_user: boolean;
  /** Reviewer lines only, stamped by the server when the line was added. */
  created_by?: string | null;
  created_at?: string | null;
  /** The creator's name (their login when they have none); null when the user is unknown. */
  created_by_name?: string | null;
  /** The calculation this line feeds; null when none reads it (fugitive, process, steam…). */
  family?: CalculationFamily | null;
}

export type CalculationFamily = "stationary" | "mobile" | "electricity";

export interface TreeCounts {
  documents: number;
  values: number;
  accepted: number;
  to_review: number;
  issues: number;
  pct_accepted: number;
}

export interface TreeDocRow {
  document_id: string;
  file_name: string;
  period_start: string | null;
  period_end: string | null;
  facility_id: string | null;
  facility_name: string | null;
  processing_status: string;
  detected_type: string | null;
  /** Keys of the other calculation lines this document feeds. */
  also_in: string[];
  values: number;
  accepted: number;
  /** "unknown_line": it was moved to a line that no longer exists, so it sits in Unassigned. */
  flags: string[];
  /** The calculation this row's values feed; null when mixed or when none reads them. */
  value_family?: CalculationFamily | null;
  /** The placement this row stands for, sent as `from` when the row is moved (else the row's line key). */
  placement_from?: string;
}

export interface TreeLineNode {
  line: CalculationLine;
  counts: TreeCounts;
  documents: TreeDocRow[];
}

export interface TreeLevel2 {
  level2: string;
  label: string;
  counts: TreeCounts;
  lines: TreeLineNode[];
}

export interface TreeCategory {
  category: string;
  label: string;
  counts: TreeCounts;
  level2s: TreeLevel2[];
}

export interface TreeScope {
  scope: string;
  label: string;
  counts?: TreeCounts;
  categories: TreeCategory[];
}

export interface EvidenceTree {
  blocks: {
    summary: TreeDocRow[];
    summary_counts?: TreeCounts;
    unassigned: TreeDocRow[];
    unassigned_counts?: TreeCounts;
    supporting: { scopes: TreeScope[]; unassigned: TreeDocRow[]; unassigned_counts?: TreeCounts };
  };
  /** Vehicle groups from Setup: the anchors a mobile line can sit on. */
  vehicle_groups?: { anchor_id: string; label: string; fuel: string }[];
  /** The anchor id a contractual line uses (its anchor_kind is "company"). */
  anchors_for_contractual?: string;
  facilities: { facility_id: string; name: string; address?: string }[];
  lines: CalculationLine[];
  /** Withdrawn, duplicate or superseded documents: filed nowhere. */
  set_aside: { document_id: string; file_name: string; reason: string }[];
}

export type CoverageStatus = "counted" | "counted_in_part" | "not_reviewed" | "no_document";

export interface LineSchedule {
  line: CalculationLine;
  /** True when the recalculation has this line. Absent on an older server (then treated as true). */
  calculated?: boolean;
  reporting_period: { start: string | null; end: string | null };
  coverage: { month: string; status: CoverageStatus; quantity: number | null; unit: string | null; document_ids: string[]; flags?: string[]; waiting_on?: string[] }[];
  identifiers: { label: string; value: string; documents_with: number; documents_total: number }[];
  values: ScheduleValue[];
  /** Newest first, at most 200; `history_total` is the count before the cap. */
  history: ScheduleHistoryEntry[];
  history_total?: number;
  /** Schedule v2: one row per record, accepted or not. */
  rows: ScheduleRow[];
  /** The ordered column set; Date and Activity quantity first, then only the extras the line has. */
  columns: ScheduleColumn[];
  activity_quantity_note?: string | null;
  identifier_groups: IdentifierGroup[];
}

export type HistoryAction = "extracted" | "accepted" | "corrected" | "added" | "rejected" | "asked_for_more_evidence";

/** One thing that happened on the line. The page words the sentence; who, when, what and where are fields. */
export interface ScheduleHistoryEntry {
  action: HistoryAction;
  actor_name: string | null;
  at: string | null;
  field: string | null;
  value: string | null;
  unit: string | null;
  file_name: string | null;
  page: number | null;
  /** Values folded into this entry (a bulk accept), or the values extracted by the system entry. */
  count?: number;
  /** Documents the system entry extracted from. */
  documents?: number | null;
}

export interface ScheduleColumn {
  key: string;
  label: string;
  unit_in_cells: boolean;
}

/** Where a value was read: its candidate, and a page (PDF, image) or a sheet and cell (workbook, CSV). */
export interface ValueSource {
  candidate_id?: string | null;
  page?: number | null;
  sheet?: string | null;
  cell?: string | null;
}

export interface ScheduleCell extends ValueSource {
  value: string | number | null;
  unit?: string | null;
}

export interface ScheduleRow {
  record_key: string;
  record_index?: number;
  accepted: boolean;
  /** Absent on an older server; then `accepted` decides. */
  decision?: "not_reviewed" | "rejected" | "needs_more_evidence" | "accepted" | "edited" | "awaiting_other_fields";
  /** Labels of the record's other fields the recalculation still waits on (decision awaiting_other_fields). */
  waiting_on?: string[];
  /** Labels of other fields the reviewer rejected, so the record is not calculated. */
  rejected_fields?: string[];
  /** `days` is counted by the server; the page never works it out. */
  date: { start: string | null; end: string | null; days: number | null; label: string };
  activity_quantity: { value: number | string | null; unit: string | null } & ValueSource;
  cells: Record<string, ScheduleCell>;
  saved_by: { name: string; at: string | null } | null;
  document_id: string;
  file_name: string;
  page: number | null;
  candidate_id: string | null;
}

export interface IdentifierDocument {
  document_id: string;
  file_name: string;
  matched_by?: string;
  /** Claude read this value and no reviewer has decided it yet (identifiers only; they never feed a number). */
  read_by_claude?: boolean;
}

export interface IdentifierGroup {
  label: string;
  values: { value: string; documents: IdentifierDocument[] }[];
  not_found: IdentifierDocument[];
  documents_with: number;
  documents_total: number;
  /** Facility only: how the match was made. */
  matched_by?: string[];
}

export interface ScheduleValue {
  service_period_start: string;
  service_period_end: string;
  days: number;
  quantity: number;
  unit: string;
  document_id: string;
  file_name: string;
  page: number | null;
  candidate_id: string | null;
  decided_by: string | null;
  decided_at: string | null;
  decision: string | null;
}

/** One entry of the engagement setting `evidenceLines`: the lines a reviewer added. The server
 *  derives `key` and `level2` from the other parts, so a new line leaves them out. */
export interface EvidenceLineSetting {
  key?: string;
  scope?: string;
  category: string;
  level2?: string;
  level2_label: string;
  anchor_kind: AnchorKind;
  anchor_id: string;
  label: string;
  /** Set by the server and sent back unchanged; the server ignores what a client puts here. */
  created_by?: string;
  created_at?: string;
}

/** One move of one placement, applied in order to the document's default placements. */
export interface Placement {
  from: string;
  to: string;
}

export const BLOCK_SUMMARY = "block:summary";
export const BLOCK_UNASSIGNED = "block:unassigned";
export const SUPPORTING_UNASSIGNED = "supporting:unassigned";

/** The tree; with a facility, only what belongs to it, recounted by the server. */
export function getEvidenceTree(engagementId: string, facilityId?: string | null): Promise<EvidenceTree> {
  const query = facilityId ? `?facility_id=${encodeURIComponent(facilityId)}` : "";
  return api<EvidenceTree>(`/engagements/${encodeURIComponent(engagementId)}/evidence-tree${query}`);
}

export function getLineSchedule(engagementId: string, lineKey: string): Promise<LineSchedule> {
  return api<LineSchedule>(
    `/engagements/${encodeURIComponent(engagementId)}/calculation-lines/${encodeURIComponent(lineKey)}/schedule`
  );
}

/** Whether a saved `evidenceLines` entry is the line the tree shows. The server fills in every key. */
export function isSameLine(entry: EvidenceLineSetting, line: CalculationLine): boolean {
  return entry.key === line.key;
}

/** What to call a line: its label, with the fuel in front unless the label already names it. */
export function lineTitle(line: CalculationLine): string {
  return line.label.toLowerCase().includes(line.level2_label.toLowerCase()) ? line.label : `${line.level2_label} · ${line.label}`;
}

/** What a line action answers: the engagement's reviewer lines as they now stand (the client keeps
 *  them, so a later Setup save sends the same list), plus the line or the count the action concerns. */
export interface LineAnswer {
  evidenceLines: EvidenceLineSetting[];
  line?: EvidenceLineSetting;
  documents_moved?: number;
  /** A delete answers with the saved payload of every document it changed (the set-aside ones too). */
  documents?: Record<string, DocumentDecision>;
}

const lines = (engagementId: string) => `/engagements/${encodeURIComponent(engagementId)}/evidence-lines`;

/** Adds a line. The server builds its key and records who added it; 422 says what is wrong with it. */
export function createEvidenceLine(engagementId: string, entry: EvidenceLineSetting): Promise<LineAnswer> {
  const { key: _key, scope: _scope, level2: _level2, created_by: _by, created_at: _at, ...fields } = entry;
  void [_key, _scope, _level2, _by, _at];
  return api<LineAnswer>(lines(engagementId), { method: "POST", body: fields });
}

export function renameEvidenceLine(engagementId: string, lineKey: string, label: string): Promise<LineAnswer> {
  return api<LineAnswer>(`${lines(engagementId)}/${encodeURIComponent(lineKey)}`, { method: "PATCH", body: { label } });
}

/** Deletes a line; its documents move to Unassigned supporting evidence (the count comes back). */
export function deleteEvidenceLine(engagementId: string, lineKey: string): Promise<LineAnswer> {
  return api<LineAnswer>(`${lines(engagementId)}/${encodeURIComponent(lineKey)}`, { method: "DELETE" });
}

/** Moves one placement of a document. 409 when another tab moved it first. Answers the saved payload. */
export function moveEvidenceDocument(
  engagementId: string,
  documentId: string,
  move: Placement
): Promise<{ document_id: string; payload: DocumentDecision }> {
  return api(`/engagements/${encodeURIComponent(engagementId)}/documents/${encodeURIComponent(documentId)}/placements`, {
    method: "POST",
    body: move,
  });
}

/** One change recorded by the server on the Evidence page. */
export interface EvidenceActivityItem {
  id: string;
  event_type: "evidence_line_created" | "evidence_line_renamed" | "evidence_line_deleted" | "evidence_document_moved";
  at: string;
  actor_name: string | null;
  line_key?: string;
  label?: string;
  level2_label?: string;
  old_label?: string;
  new_label?: string;
  documents_moved?: number;
  document_id?: string;
  from_label?: string;
  to_label?: string;
}

/** One page (100 at most) of the Evidence changes on the engagement, newest first. `next_cursor` is null on the last. */
export function getEvidenceActivity(
  engagementId: string,
  cursor?: string | null
): Promise<{ items: EvidenceActivityItem[]; next_cursor: string | null }> {
  const query = cursor ? `?limit=100&cursor=${encodeURIComponent(cursor)}` : "?limit=100";
  return api(`/engagements/${encodeURIComponent(engagementId)}/evidence-activity${query}`);
}
