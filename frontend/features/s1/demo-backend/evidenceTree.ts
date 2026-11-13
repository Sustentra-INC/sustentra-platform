/**
 * Demo backend: the Evidence tree, a line's supporting schedule and the document placement save.
 * Shapes are those of `features/s1/api/evidenceTree.ts` (the backend's evidence_tree_service);
 * the data is the demo line model (`linesModel.ts`), built from the fixture documents.
 */
import type {
  CalculationLine, CoverageStatus, EvidenceTree, IdentifierGroup, LineSchedule, ScheduleRow, ScheduleValue, TreeCounts, TreeDocRow, TreeLevel2,
} from "../api/evidenceTree";
import type { WorkpaperItem } from "../api/workpaper";
import type { DocumentDecision } from "../types/evidence";
import {
  BLOCK_SUMMARY, BLOCK_UNASSIGNED, CATEGORIES, SCOPES, SUPPORTING_UNASSIGNED, buildModel, daysBetween, monthCoverage, recordsOn,
  type Model, type ModelLine, type ModelRecord,
} from "./linesModel";
import { demoError } from "./index";
import { saveDemoDecision } from "./state";
import type { DemoRoute } from "./types";

const CATEGORY_SCOPE = Object.fromEntries(CATEGORIES.map(([k, , s]) => [k, s]));

function lineOf(line: ModelLine): CalculationLine {
  return { ...line };
}

function counts(parts: ModelRecord[]): TreeCounts {
  const seen = new Map<string, ModelRecord>();
  for (const r of parts) seen.set(r.documentId, r);
  let values = 0, accepted = 0, issues = 0;
  for (const r of seen.values()) { values += r.values; accepted += r.acceptedValues; issues += r.issues; }
  return {
    documents: seen.size, values, accepted, to_review: Math.max(0, values - accepted - issues), issues,
    pct_accepted: values ? Math.round((1000 * accepted) / values) / 10 : 0,
  };
}

function periodOf(r: ModelRecord): { start: string | null; end: string | null } {
  return { start: r.start, end: r.end };
}

export function buildTree(facilityId: string | null): EvidenceTree {
  const model = buildModel();
  const byKey = new Map(model.lines.map((l) => [l.key, l]));
  const facilityName = new Map(model.facilities.map((f) => [f.facilityId, f.name]));
  const shown = model.lines.filter((l) => !facilityId || l.facility_id === facilityId);

  const rows = new Map<string, { row: TreeDocRow; record: ModelRecord }[]>();
  for (const record of model.records) {
    const slots = model.slots.get(record.documentId) ?? [];
    for (const slot of slots) {
      const line = byKey.get(slot.target);
      const fid = line ? line.facility_id : record.facilityId;
      const p = periodOf(record);
      const row: TreeDocRow = {
        document_id: record.documentId, file_name: record.fileName, period_start: p.start, period_end: p.end,
        facility_id: fid, facility_name: fid ? facilityName.get(fid) ?? null : null,
        processing_status: record.processingStatus, detected_type: record.detectedType,
        also_in: slots.filter((s) => s.target !== slot.target && byKey.has(s.target)).map((s) => s.target),
        values: record.values, accepted: record.acceptedValues, flags: [...slot.flags], placement_from: slot.target,
      };
      if (facilityId && row.facility_id !== facilityId) continue;
      rows.set(slot.target, [...(rows.get(slot.target) ?? []), { row, record }]);
    }
  }
  const documents = (target: string) =>
    (rows.get(target) ?? []).map((e) => e.row).sort((a, b) => (a.period_start ?? "9999").localeCompare(b.period_start ?? "9999") || a.file_name.localeCompare(b.file_name));
  const countsOf = (targets: string[]) => counts(targets.flatMap((t) => (rows.get(t) ?? []).map((e) => e.record)));

  const scopes = SCOPES.map(([scope, label]) => {
    const categories = CATEGORIES.filter(([, , owner]) => owner === scope).map(([category, clabel]) => {
      const inCategory = shown.filter((l) => l.category === category);
      const level2s = new Map<string, TreeLevel2>();
      for (const line of inCategory) {
        const level2 = level2s.get(line.level2) ?? { level2: line.level2, label: line.level2_label, counts: counts([]), lines: [] };
        level2.lines.push({ line: lineOf(line), counts: countsOf([line.key]), documents: documents(line.key) });
        level2s.set(line.level2, level2);
      }
      for (const level2 of level2s.values()) level2.counts = countsOf(level2.lines.map((e) => e.line.key));
      return { category, label: clabel, counts: countsOf(inCategory.map((l) => l.key)), level2s: [...level2s.values()] };
    });
    return { scope, label, categories, counts: countsOf(shown.filter((l) => CATEGORY_SCOPE[l.category] === scope).map((l) => l.key)) };
  });

  return {
    blocks: {
      summary: documents(BLOCK_SUMMARY), summary_counts: countsOf([BLOCK_SUMMARY]),
      unassigned: documents(BLOCK_UNASSIGNED), unassigned_counts: countsOf([BLOCK_UNASSIGNED]),
      supporting: { scopes, unassigned: documents(SUPPORTING_UNASSIGNED), unassigned_counts: countsOf([SUPPORTING_UNASSIGNED]) },
    },
    facilities: model.facilities.map((f) => ({ facility_id: f.facilityId, name: f.name, address: f.address })),
    lines: shown.map(lineOf),
    vehicle_groups: model.vehicleGroups,
    anchors_for_contractual: "company",
    set_aside: model.setAside.map((s) => ({ ...s })),
  };
}

/* ------------------------------------ schedule ------------------------------------ */

const NOTES: Record<string, string> = { stationary: "fuel quantity combusted", biogenic: "fuel quantity combusted", mobile: "fuel use quantity", fugitive: "refrigerant quantity added or recovered" };

function dateLabel(r: ModelRecord): string {
  return r.kind === "fleet" ? "Statement period" : r.kind === "propane" ? "Delivery date" : r.kind === "refrigerant" ? "Service date" : "Service period";
}

function groupsOf(model: Model, on: ModelRecord[]): IdentifierGroup[] {
  const defs: [string, (r: ModelRecord) => string | null][] = [
    ["Facility", (r) => (r.facilityId ? model.facilities.find((f) => f.facilityId === r.facilityId)?.name ?? null : null)],
    ["Service address", (r) => r.address],
    ["Account number", (r) => r.account],
    ["Meter number", (r) => r.meter],
  ];
  return defs.map(([label, get]) => {
    const groups = new Map<string, { document_id: string; file_name: string; matched_by?: string }[]>();
    for (const r of on) {
      const value = get(r);
      if (!value) continue;
      groups.set(value, [...(groups.get(value) ?? []), { document_id: r.documentId, file_name: r.fileName, ...(label === "Facility" ? { matched_by: r.matchedBy } : {}) }]);
    }
    const withValue = new Set([...groups.values()].flat().map((d) => d.document_id));
    const group: IdentifierGroup = {
      label,
      values: [...groups.entries()].sort(([a], [b]) => a.localeCompare(b)).map(([value, documents]) => ({ value, documents: documents.sort((a, b) => a.file_name.localeCompare(b.file_name)) })),
      not_found: on.filter((r) => !withValue.has(r.documentId)).map((r) => ({ document_id: r.documentId, file_name: r.fileName })),
      documents_with: withValue.size, documents_total: on.length,
    };
    if (label === "Facility") group.matched_by = [...new Set([...groups.values()].flat().map((d) => d.matched_by as string))].sort();
    return group;
  });
}

function money(n: number): string {
  return n.toLocaleString("en-US", { maximumFractionDigits: 4 });
}

export function buildSchedule(lineKey: string): LineSchedule | null {
  const model = buildModel();
  const line = model.lines.find((l) => l.key === lineKey);
  if (!line) return null;
  const on = recordsOn(model, lineKey).sort((a, b) => (a.start ?? "9999").localeCompare(b.start ?? "9999") || a.fileName.localeCompare(b.fileName));
  const quantified = on.filter((r) => r.quantity !== null);
  const rows: ScheduleRow[] = [];
  const values: ScheduleValue[] = [];
  const history: { at: string; text: string }[] = [];
  const hasDistance = quantified.some((r) => r.distance !== null);
  for (const r of on) {
    const days = r.start && r.end && r.end >= r.start ? daysBetween(r.start, r.end) : null;
    const label = dateLabel(r);
    rows.push({
      record_key: `${r.documentId}:0`, record_index: 0, accepted: r.accepted, decision: r.decision,
      waiting_on: [...r.waiting], rejected_fields: [],
      date: { start: r.start, end: r.end, days, label },
      activity_quantity: { value: r.quantity, unit: r.quantity === null ? null : r.unit },
      cells: r.distance !== null ? { distance: { value: r.distance, unit: "mi" } } : {},
      saved_by: r.accepted && r.reviewer ? { name: r.reviewer, at: r.reviewedAt } : null,
      document_id: r.documentId, file_name: r.fileName, page: r.quantity === null ? null : r.page, candidate_id: r.candidateId,
    });
    if (r.quantity === null) continue;
    values.push({
      service_period_start: r.start ?? "", service_period_end: r.end ?? "", days: days ?? 0, quantity: r.quantity, unit: r.unit ?? "",
      document_id: r.documentId, file_name: r.fileName, page: r.page, candidate_id: r.candidateId,
      decided_by: r.accepted ? r.reviewer : null, decided_at: r.accepted ? r.reviewedAt : null, decision: r.decision,
    });
    if (r.accepted && r.reviewer && r.reviewedAt) {
      history.push({ at: r.reviewedAt, text: `${r.reviewer} ${r.decision === "edited" ? "edited" : "accepted"} ${money(r.quantity)} ${r.unit} from ${r.fileName}, page ${r.page}` });
    }
  }
  if (values.length) history.push({ at: "2025-09-10T08:00:00Z", text: `System extracted ${values.length} ${values.length === 1 ? "value" : "values"} from ${on.length} ${on.length === 1 ? "document" : "documents"}` });
  history.sort((a, b) => b.at.localeCompare(a.at));

  const columns = [{ key: "date", label: "Date", unit_in_cells: true }, { key: "activity_quantity", label: "Activity quantity", unit_in_cells: true }];
  if (hasDistance) columns.push({ key: "distance", label: "Distance", unit_in_cells: true });
  const calculated = ["stationary", "mobile", "purchased_energy"].includes(line.category) && on.some((r) => r.accepted && r.quantity !== null);
  const what = line.category === "purchased_energy" ? "electricity quantity purchased" : NOTES[line.category];
  const identifiers = groupsOf(model, on).flatMap((g) => g.values.map((v) => ({ label: g.label, value: v.value, documents_with: v.documents.length, documents_total: on.length })));

  return {
    line: lineOf(line), calculated,
    reporting_period: { start: model.period.start, end: model.period.end },
    coverage: monthCoverage(model.period, on).map((m) => ({ ...m, status: m.status as CoverageStatus })),
    identifiers, identifier_groups: groupsOf(model, on),
    values, rows, columns, activity_quantity_note: what ? `Activity quantity: ${what}` : null, history,
  };
}

/* ------------------------------------ routes ------------------------------------ */

export const evidenceTreeRoutes: DemoRoute[] = [
  { method: "GET", path: /^\/engagements\/(?<id>[^/]+)\/evidence-tree$/, handle: ({ query }) => buildTree(query.get("facility_id")) },
  {
    method: "GET",
    path: /^\/engagements\/(?<id>[^/]+)\/calculation-lines\/(?<key>[^/]+)\/schedule$/,
    handle: ({ params }) => buildSchedule(params.key) ?? demoError(404, "This engagement has no such calculation line."),
  },
  {
    method: "PUT",
    path: /^\/engagements\/(?<id>[^/]+)\/workpaper-items\/document\/(?<key>[^/]+)$/,
    handle: ({ params, body }): WorkpaperItem => {
      const payload = ((body as { payload?: Record<string, unknown> } | null)?.payload ?? {}) as Record<string, unknown>;
      const documentId = typeof payload.documentId === "string" ? payload.documentId : params.key;
      const decision = { ...payload, documentId } as unknown as DocumentDecision;
      saveDemoDecision(decision);
      return { kind: "document", item_key: params.key, payload: { ...payload, documentId }, created_at: "2026-01-20T10:00:00Z", updated_at: "2026-01-20T10:00:00Z" };
    },
  },
];
