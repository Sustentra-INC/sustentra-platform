import { api } from "../../../lib/api";
import type { DocumentDecision } from "../types";
import { saveWorkpaperItem } from "./workpaper";

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
}

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
  categories: TreeCategory[];
}

export interface EvidenceTree {
  blocks: {
    summary: TreeDocRow[];
    unassigned: TreeDocRow[];
    supporting: { scopes: TreeScope[]; unassigned: TreeDocRow[] };
  };
  facilities: { facility_id: string; name: string; address?: string }[];
  lines: CalculationLine[];
  /** Withdrawn, duplicate or superseded documents: filed nowhere. */
  set_aside: { document_id: string; file_name: string; reason: string }[];
}

export type CoverageStatus = "counted" | "counted_in_part" | "not_reviewed" | "no_document";

export interface LineSchedule {
  line: CalculationLine;
  reporting_period: { start: string | null; end: string | null } | string | null;
  coverage: { month: string; status: CoverageStatus; quantity: number | null; unit: string | null; document_ids: string[] }[];
  identifiers: { label: string; value: string; documents_with: number; documents_total: number }[];
  values: ScheduleValue[];
  history: { at: string; text: string }[];
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
}

/** One move of one placement, applied in order to the document's default placements. */
export interface Placement {
  from: string;
  to: string;
}

export const BLOCK_SUMMARY = "block:summary";
export const BLOCK_UNASSIGNED = "block:unassigned";
export const SUPPORTING_UNASSIGNED = "supporting:unassigned";

export function getEvidenceTree(engagementId: string): Promise<EvidenceTree> {
  return api<EvidenceTree>(`/engagements/${encodeURIComponent(engagementId)}/evidence-tree`);
}

export function getLineSchedule(engagementId: string, lineKey: string): Promise<LineSchedule> {
  return api<LineSchedule>(
    `/engagements/${encodeURIComponent(engagementId)}/calculation-lines/${encodeURIComponent(lineKey)}/schedule`
  );
}

/** Lowercase letters, digits and hyphens: the slug the line key is built from. */
export function slug(text: string): string {
  return text
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
}

/** Whether a saved `evidenceLines` entry is the line the tree shows (by key, else by its parts). */
export function isSameLine(entry: EvidenceLineSetting, line: CalculationLine): boolean {
  if (entry.key) return entry.key === line.key;
  return entry.category === line.category && slug(entry.level2_label) === line.level2 && entry.anchor_id === line.anchor_id;
}

/**
 * The document's saved decision with one more placement move. The workpaper item is replaced as
 * a whole, so every other key (facility, disposition, relationships, notes…) is carried over.
 */
export function withPlacement(decision: DocumentDecision | undefined, documentId: string, move: Placement): DocumentDecision {
  return { ...(decision ?? {}), documentId, placements: [...(decision?.placements ?? []), move] };
}

/** Saves a placement move on the document's workpaper item; returns the payload that was saved. */
export async function saveDocumentPlacement(
  engagementId: string,
  decision: DocumentDecision | undefined,
  documentId: string,
  move: Placement
): Promise<DocumentDecision> {
  const next = withPlacement(decision, documentId, move);
  await saveWorkpaperItem(engagementId, "document", documentId, next);
  return next;
}
