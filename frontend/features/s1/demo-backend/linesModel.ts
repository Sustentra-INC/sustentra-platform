/**
 * The demo's calculation lines and the records on them, built from the fixture documents
 * (`fixtures/evidence/manufacturerEvidence.ts`) and extracted values (`fixtures/extraction/
 * manufacturerValues.ts`). Evidence tree, supporting schedule and recalculation all read this one
 * model, so a line key, a documentId and a quantity are the same on every screen. Pure functions:
 * a fresh model per call, no randomness.
 *
 * Ports the backend's rules (`backend/app/services/calculation_lines.py`): line keys, default
 * placement, the reviewer's moves, and the month coverage.
 */
import { GAS_METERS } from "../fixtures/ai/claudeReadings";
import { engagementConfig } from "../fixtures/engagementConfig";
import { PROPANE_BY_DOC, fleetQuarter } from "../fixtures/extraction/demoQuantities";
import { documentReview } from "../fixtures/extraction/reviewDecisions";
import { manufacturerEvidence } from "../fixtures/evidence/manufacturerEvidence";
import { manufacturerValues } from "../fixtures/extraction/manufacturerValues";
import type { EngagementConfig, FacilityOption } from "../types/engagement";
import type { EvidenceLineSetting } from "../api/evidenceTree";
import type { EvidenceItem } from "../types/evidence";
import { demoDecisions, demoEngagement } from "./state";

export const BLOCK_SUMMARY = "block:summary";
export const BLOCK_UNASSIGNED = "block:unassigned";
export const SUPPORTING_UNASSIGNED = "supporting:unassigned";
const FIXED = new Set([BLOCK_SUMMARY, BLOCK_UNASSIGNED, SUPPORTING_UNASSIGNED]);

export const SCOPES: [string, string][] = [["s1", "Scope 1"], ["s2", "Scope 2"], ["biogenic", "Biogenic"]];
export const CATEGORIES: [string, string, string][] = [
  ["stationary", "Stationary combustion", "s1"],
  ["mobile", "Mobile combustion", "s1"],
  ["fugitive", "Fugitive emissions", "s1"],
  ["process", "Process emissions", "s1"],
  ["purchased_energy", "Purchased energy", "s2"],
  ["contractual", "Contractual instruments", "s2"],
  ["biogenic", "Biogenic CO₂", "biogenic"],
];
const CATEGORY_SCOPE = Object.fromEntries(CATEGORIES.map(([k, , s]) => [k, s]));

export function slug(text: string): string {
  return text.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 60).replace(/-+$/g, "") || "none";
}

export interface ModelLine {
  key: string;
  scope: string;
  category: string;
  level2: string;
  level2_label: string;
  anchor_kind: "facility" | "vehicle_group" | "company";
  anchor_id: string;
  label: string;
  facility_id: string | null;
  created_by_user: boolean;
}

export function lineKey(scope: string, category: string, level2: string, anchorKind: string, anchorId: string): string {
  return `${scope}:${category}:${slug(level2)}:${anchorKind === "company" ? "company" : slug(anchorId)}`;
}

export function makeLine(category: string, level2: string, level2Label: string, kind: ModelLine["anchor_kind"], anchorId: string, label: string, byUser: boolean): ModelLine {
  const scope = CATEGORY_SCOPE[category];
  const anchor = kind === "company" ? "company" : anchorId;
  return {
    key: lineKey(scope, category, level2, kind, anchorId), scope, category, level2: slug(level2), level2_label: level2Label,
    anchor_kind: kind, anchor_id: anchor, label, facility_id: kind === "facility" ? anchorId : null, created_by_user: byUser,
  };
}

/* ------------------------------------ setup ------------------------------------ */

export interface VehicleGroupAnchor { anchor_id: string; label: string; fuel: string }
export const DEFAULT_VEHICLE_GROUP = { fuel: "Diesel Fuel", vehicle_type: "Medium- and Heavy-Duty Vehicles", factor_fuel_type: "Diesel", on_road: true, model_year: 2018, distance: 3_047_850, distance_unit: "mi" as const, label: "Diesel trucks" };

export function engagementNow(): EngagementConfig {
  return demoEngagement() ?? engagementConfig;
}

/* ------------------------------------ records ------------------------------------ */

export type RecordKind = "gas" | "electricity" | "fleet" | "propane" | "refrigerant" | "other";

export interface ModelRecord {
  documentId: string;
  fileName: string;
  kind: RecordKind;
  /** The Setup facility the document belongs to. */
  facilityId: string | null;
  defaultTarget: string;
  start: string | null;
  end: string | null;
  quantity: number | null;
  unit: string | null;
  /** Mobile statements: the distance the vehicles drove. */
  distance: number | null;
  /** A reviewer accepted (or corrected) the quantity. */
  accepted: boolean;
  decision: "accepted" | "edited" | "not_reviewed" | "awaiting_other_fields";
  reviewer: string | null;
  reviewedAt: string | null;
  candidateId: string | null;
  page: number;
  /** Labels of the record's other fields still open (the quantity does not count meanwhile). */
  waiting: string[];
  /** Backend field names of the same (the recalculation's awaiting_review). */
  waitingFields: string[];
  values: number;
  acceptedValues: number;
  issues: number;
  account: string | null;
  meter: string | null;
  address: string | null;
  processingStatus: string;
  detectedType: string | null;
  matchedBy: string;
  /** Kinds of quality note the record carries. */
  flags: string[];
}

export interface SetAside { document_id: string; file_name: string; reason: string }

const FAC_CODE: Record<string, string> = { "facility-tualatin": "tualatin", "facility-kent": "kent", "facility-modesto": "modesto" };
const GAS_ACCOUNT: Record<string, string> = { tualatin: "WG-30418-2", kent: "GRG-77120", modesto: "SGP-5521-09" };
const ELEC_ACCOUNT: Record<string, string> = { tualatin: "TVP-88213", kent: "GRP-40977", modesto: "SGP-5521-10" };
const ELEC_METER: Record<string, string> = { tualatin: "E-31877", kent: "E-55604", modesto: "E-90412" };
const PROPANE_ACCOUNT: Record<string, string> = { kent: "KP-2031", modesto: "VP-6630", tualatin: "CP-1189" };

/**
 * What the fixtures cannot say. Whether a document is accepted, by whom and when comes from its
 * fixture values (`fixtures/extraction/reviewDecisions.ts`); a withdrawn document and a billing
 * cycle across the year come from the Evidence row. What is left here: the backend's name for an
 * open field.
 */
const FIELD_NAME: Record<string, string> = { "Fuel type": "fuel_type" };
const fieldName = (label: string) => FIELD_NAME[label] ?? label.toLowerCase().replace(/[^a-z0-9]+/g, "_");

const SUMMARY_TYPES = new Set(["Inventory workbook", "Organizational boundary statement", "Inventory methodology statement", "Facility list", "Emission factor source list", "Prior-year inventory or report"]);

function parseNumber(text: string): number | null {
  const n = Number(text.replace(/[, ]/g, ""));
  return Number.isFinite(n) ? n : null;
}

function addDays(iso: string, n: number): string {
  const d = new Date(`${iso}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + n);
  return d.toISOString().slice(0, 10);
}
export function daysBetween(start: string, end: string): number {
  return Math.round((Date.parse(`${end}T00:00:00Z`) - Date.parse(`${start}T00:00:00Z`)) / 86_400_000) + 1;
}

interface Built { records: ModelRecord[]; setAside: SetAside[] }

function valuesByDocument() {
  const byDoc = new Map<string, typeof manufacturerValues>();
  for (const v of manufacturerValues) byDoc.set(v.documentId, [...(byDoc.get(v.documentId) ?? []), v]);
  return byDoc;
}

export function buildRecords(facilities: FacilityOption[]): Built {
  const byDoc = valuesByDocument();
  const decisions = demoDecisions();
  const records: ModelRecord[] = [];
  const setAside: SetAside[] = [];
  const address = (id: string | null) => facilities.find((f) => f.facilityId === id)?.address ?? null;
  const facName = (id: string | null) => facilities.find((f) => f.facilityId === id)?.name ?? null;

  const docs = manufacturerEvidence.filter((d: EvidenceItem) => d.evidenceClass === "main");
  const fileOf = new Map(docs.map((d) => [d.documentId, d.filename]));
  for (const doc of docs) {
    const decision = decisions.get(doc.documentId);
    if (doc.disposition === "withdrawn" || decision?.disposition === "withdrawn") {
      // The Evidence row's note is the reason the reviewer gave.
      const why = doc.disposition === "withdrawn" && doc.note ? `: ${doc.note}` : ".";
      setAside.push({ document_id: doc.documentId, file_name: doc.filename, reason: `Withdrawn by the reviewer${why}` });
      continue;
    }
    const rel = doc.relationships.find((r) => r.kind === "superseded_by");
    if (rel) {
      setAside.push({ document_id: doc.documentId, file_name: doc.filename, reason: `Superseded by ${fileOf.get(rel.otherDocumentId) ?? rel.otherDocumentId}.` });
      continue;
    }
    if (doc.documentId === "DOC-DUPE-B") {
      setAside.push({ document_id: doc.documentId, file_name: doc.filename, reason: `Duplicate of ${fileOf.get("DOC-DUPE-A")}.` });
      continue;
    }

    const type = doc.detectedType;
    const facilityId = doc.facilityId ?? null;
    const code = facilityId ? FAC_CODE[facilityId] ?? slug(facName(facilityId) ?? "") : "";
    let kind: RecordKind = "other";
    let target = SUPPORTING_UNASSIGNED;
    let unit: string | null = null;
    if (type === null) target = BLOCK_UNASSIGNED;
    else if (SUMMARY_TYPES.has(type)) target = BLOCK_SUMMARY;
    else if (type === "Natural gas bill" && facilityId) { kind = "gas"; unit = "therms"; target = lineKey("s1", "stationary", "natural-gas", "facility", facilityId); }
    else if (type === "Electricity bill" && facilityId) { kind = "electricity"; unit = "kWh"; target = lineKey("s2", "purchased_energy", "electricity", "facility", facilityId); }
    else if (type === "Fleet fuel statement") { kind = "fleet"; unit = "gal"; target = lineKey("s1", "mobile", "diesel-fuel", "vehicle_group", "vg-diesel-trucks"); }
    else if (type === "Other fuel invoice" && facilityId) { kind = "propane"; unit = "gal"; target = lineKey("s1", "stationary", "propane", "facility", facilityId); }
    else if (type?.startsWith("Refrigerant") && facilityId) { kind = "refrigerant"; unit = "kg"; target = lineKey("s1", "fugitive", "r-404a", "facility", facilityId); }
    else if (type === "Renewable energy certificate or retirement statement" || type === "Power purchase agreement or supplier contract") target = lineKey("s2", "contractual", "renewable-energy-certificates", "company", "company");
    else if (type === "Supplier-specific factor documentation") target = lineKey("s2", "contractual", "supplier-specific-factors", "company", "company");

    const own = byDoc.get(doc.documentId) ?? [];
    const read = own.find((v) => /consumed|added on service/i.test(v.whatItIs) && (v.scope !== "scope2_market"));
    let quantity: number | null = read ? parseNumber(read.value) : null;
    let distance: number | null = null;
    const start = doc.periodStart ?? null;
    let end = doc.periodEnd ?? null;
    if (kind === "fleet" && facilityId && start) {
      const q = Math.ceil(Number(start.slice(5, 7)) / 3);
      ({ gal: quantity, mi: distance } = fleetQuarter(code, q));
      end = `${start.slice(0, 4)}-${["", "03-31", "06-30", "09-30", "12-31"][q]}`;
    }
    if (kind === "propane") quantity = PROPANE_BY_DOC[doc.filename] ?? null;

    const calc = kind !== "other";
    // The review decision is the fixture values' own: accepted, by whom, when, and what is still open.
    const review = documentReview(own);
    const accepted = calc && quantity !== null && doc.processingState !== "blocked" && review.done;
    const waiting = accepted ? review.open : [];
    const waitingFields = accepted ? waiting.map(fieldName) : kind !== "other" && doc.processingState !== "blocked" && quantity !== null ? ["activity_quantity"] : [];
    const edited = review.edited;
    const fields = doc.fieldsExtracted;
    const accountMap = kind === "gas" ? GAS_ACCOUNT : kind === "electricity" ? ELEC_ACCOUNT : kind === "propane" ? PROPANE_ACCOUNT : null;
    const utility = kind === "gas" || kind === "electricity";
    records.push({
      documentId: doc.documentId, fileName: doc.filename, kind, facilityId, defaultTarget: target, start, end, quantity, unit, distance,
      accepted: accepted && waiting.length === 0, decision: waiting.length ? "awaiting_other_fields" : accepted ? (edited ? "edited" : "accepted") : "not_reviewed",
      reviewer: accepted ? review.reviewer : null,
      reviewedAt: accepted ? review.at : null,
      candidateId: read?.id ?? null, page: read?.page ?? 1,
      waiting, waitingFields,
      values: fields, acceptedValues: accepted ? fields : 0, issues: doc.filename === "modesto_refrigerant_service.pdf" ? 1 : 0,
      account: accountMap && facilityId ? accountMap[code] ?? null : null,
      meter: utility && facilityId && doc.documentId !== "DOC-PARTIAL" ? (kind === "gas" ? GAS_METERS[facilityId] : ELEC_METER[code]) ?? null : null,
      address: utility ? address(facilityId) : null,
      processingStatus: doc.processingState, detectedType: type,
      matchedBy: doc.documentId === "DOC-PARTIAL" ? "Service address in Setup" : "Facility name in Setup",
      flags: [],
    });
  }
  return { records, setAside };
}

/* ------------------------------------ lines and placement ------------------------------------ */

export interface Slot { target: string; flags: string[] }

export interface Model {
  facilities: FacilityOption[];
  period: { start: string | null; end: string | null };
  vehicleGroups: VehicleGroupAnchor[];
  lines: ModelLine[];
  /** Every record with where it is filed now (default placement, then the reviewer's moves). */
  records: ModelRecord[];
  slots: Map<string, Slot[]>;
  setAside: SetAside[];
}

function userLine(entry: EvidenceLineSetting): ModelLine | null {
  if (!entry.category || !CATEGORY_SCOPE[entry.category] || !entry.level2_label || !entry.label || !entry.anchor_kind) return null;
  const anchorId = entry.anchor_kind === "company" ? "company" : entry.anchor_id;
  if (!anchorId) return null;
  return makeLine(entry.category, entry.level2 ?? entry.level2_label, entry.level2_label, entry.anchor_kind, anchorId, entry.label, true);
}

function applyMoves(slots: Slot[], moves: { from: string; to: string }[] | undefined, known: Set<string>): Slot[] {
  const effective = (s: Slot) => (FIXED.has(s.target) || known.has(s.target) ? s.target : SUPPORTING_UNASSIGNED);
  let out = slots.map((s) => ({ ...s, flags: [...s.flags] }));
  for (const move of moves ?? []) {
    if (!move.from || !move.to || move.from === move.to) continue;
    const moving = out.filter((s) => s.target === move.from || effective(s) === move.from);
    if (!moving.length) continue;
    const stay = out.filter((s) => !moving.includes(s));
    const existing = stay.find((s) => s.target === move.to || effective(s) === move.to);
    out = existing ? stay : [...stay, { target: move.to, flags: [] }];
  }
  return out;
}

export function buildModel(): Model {
  const engagement = engagementNow();
  const facilities = engagement.facilities;
  const { records, setAside } = buildRecords(facilities);
  const decisions = demoDecisions();
  const groups = (engagement.recalculation?.vehicle_groups ?? [DEFAULT_VEHICLE_GROUP]).map((g, i, all) => {
    const label = g.label ?? `${g.vehicle_type} (${g.factor_fuel_type})`;
    const base = `vg-${slug(label)}`;
    const n = all.slice(0, i).filter((o) => `vg-${slug(o.label ?? `${o.vehicle_type} (${o.factor_fuel_type})`)}` === base).length;
    return { anchor_id: n ? `${base}-${n + 1}` : base, label, fuel: g.fuel };
  });

  // The system lines: one per facility for each level 2 that has a record, one per vehicle group for a mobile fuel.
  const system = new Map<string, ModelLine>();
  const levels = new Map<string, { category: string; level2: string; label: string; kind: ModelLine["anchor_kind"] }>();
  const LABEL: Record<string, string> = { "natural-gas": "Natural gas", electricity: "Electricity", propane: "Propane", "r-404a": "R-404A", "diesel-fuel": "Diesel Fuel" };
  for (const r of records) {
    const parts = r.defaultTarget.split(":");
    if (parts.length !== 4 || parts[3] === "company") continue;
    levels.set(`${parts[1]}:${parts[2]}`, { category: parts[1], level2: parts[2], label: LABEL[parts[2]] ?? parts[2], kind: parts[1] === "mobile" ? "vehicle_group" : "facility" });
  }
  for (const lv of levels.values()) {
    if (lv.kind === "facility") {
      for (const f of facilities) {
        const line = makeLine(lv.category, lv.level2, lv.label, "facility", f.facilityId, f.name, false);
        system.set(line.key, line);
      }
    } else {
      for (const g of groups.filter((x) => x.fuel.toLowerCase() === lv.label.toLowerCase())) {
        const line = makeLine(lv.category, lv.level2, lv.label, "vehicle_group", g.anchor_id, `${lv.label}, ${g.label}`, false);
        // The label a vehicle group line carries is the group's, as the recalculation names it.
        system.set(line.key, { ...line, label: g.label });
      }
    }
  }
  // Contractual lines (company anchor): the documents that carry them.
  const company: [string, string][] = [["renewable-energy-certificates", "Renewable energy certificates"], ["supplier-specific-factors", "Supplier-specific factors"]];
  for (const [level2, label] of company) {
    if (records.some((r) => r.defaultTarget === lineKey("s2", "contractual", level2, "company", "company"))) {
      const line = makeLine("contractual", level2, label, "company", "company", "Company", false);
      system.set(line.key, line);
    }
  }
  const created = (engagement.evidenceLines ?? []).map(userLine).filter((l): l is ModelLine => l !== null);
  const merged = new Map<string, ModelLine>();
  for (const l of [...created, ...system.values()]) merged.set(l.key, l);
  const order = new Map(CATEGORIES.map(([k], i) => [k, i]));
  const lines = [...merged.values()].sort((a, b) => (order.get(a.category)! - order.get(b.category)!) || a.level2_label.toLowerCase().localeCompare(b.level2_label.toLowerCase()) || a.label.toLowerCase().localeCompare(b.label.toLowerCase()) || a.key.localeCompare(b.key));
  const known = new Set(lines.map((l) => l.key));

  const slots = new Map<string, Slot[]>();
  for (const r of records) {
    const moved = applyMoves([{ target: r.defaultTarget, flags: [] }], decisions.get(r.documentId)?.placements, known);
    const resolved = moved.map((s) => (FIXED.has(s.target) || known.has(s.target) ? s : { target: SUPPORTING_UNASSIGNED, flags: [...s.flags, "unknown_line"] }));
    const merged2 = new Map<string, Slot>();
    for (const s of resolved) {
      const into = merged2.get(s.target) ?? { target: s.target, flags: [] };
      into.flags = [...new Set([...into.flags, ...s.flags])].sort();
      merged2.set(s.target, into);
    }
    slots.set(r.documentId, [...merged2.values()]);
  }
  return {
    facilities, period: { start: engagement.reportingPeriod?.start ?? null, end: engagement.reportingPeriod?.end ?? null },
    vehicleGroups: groups, lines, records, slots, setAside,
  };
}

export function recordsOn(model: Model, lineKeyValue: string): ModelRecord[] {
  return model.records.filter((r) => model.slots.get(r.documentId)?.some((s) => s.target === lineKeyValue));
}

/* ------------------------------------ coverage ------------------------------------ */

export type Coverage = { month: string; status: "counted" | "counted_in_part" | "not_reviewed" | "no_document"; quantity: number | null; unit: string | null; document_ids: string[]; flags: string[]; waiting_on: string[] };

/** The backend's `month_coverage`: a value's quantity spreads evenly over its service period's days. */
export function monthCoverage(period: { start: string | null; end: string | null }, records: ModelRecord[]): Coverage[] {
  if (!period.start || !period.end) return [];
  const dated = records
    .map((r) => ({ r, start: r.start ?? r.end, end: r.end ?? r.start }))
    .filter((d): d is { r: ModelRecord; start: string; end: string } => Boolean(d.start && d.end && d.start <= d.end));
  const unit = dated.find((d) => d.r.accepted && d.r.quantity !== null)?.r.unit ?? null;
  const out: Coverage[] = [];
  let year = Number(period.start.slice(0, 4));
  let month = Number(period.start.slice(5, 7));
  const lastY = Number(period.end.slice(0, 4));
  const lastM = Number(period.end.slice(5, 7));
  while (year < lastY || (year === lastY && month <= lastM)) {
    const first = `${year}-${String(month).padStart(2, "0")}-01`;
    const next = month === 12 ? `${year + 1}-01-01` : `${year}-${String(month + 1).padStart(2, "0")}-01`;
    const lastDay = addDays(next, -1);
    const from = first < period.start ? period.start : first;
    const to = lastDay > period.end ? period.end : lastDay;
    const all = daysBetween(from, to);
    let counted = 0;
    let present = 0;
    let quantity = 0;
    let hasQuantity = false;
    const documents: string[] = [];
    const waiting: string[] = [];
    // Days are counted per record; records that overlap each other count the days once in the real service,
    // and the demo's records do not overlap.
    for (const d of dated) {
      const a = d.start > from ? d.start : from;
      const b = d.end < to ? d.end : to;
      if (a > b) continue;
      const overlap = daysBetween(a, b);
      present += overlap;
      for (const w of d.r.waiting) if (!waiting.includes(w)) waiting.push(w);
      if (!documents.includes(d.r.documentId)) documents.push(d.r.documentId);
      if (d.r.accepted) {
        counted += overlap;
        if (d.r.quantity !== null) { quantity += (d.r.quantity * overlap) / daysBetween(d.start, d.end); hasQuantity = true; }
      }
    }
    const status = counted >= all ? "counted" : counted > 0 ? "counted_in_part" : present > 0 ? "not_reviewed" : "no_document";
    out.push({ month: `${year}-${String(month).padStart(2, "0")}`, status, quantity: counted && hasQuantity ? Math.round(quantity * 10_000) / 10_000 : null, unit: counted && hasQuantity ? unit : null, document_ids: documents, flags: [], waiting_on: waiting });
    [year, month] = month === 12 ? [year + 1, 1] : [year, month + 1];
  }
  return out;
}

/** The share of a record's service period that falls in the reporting period (a bill crossing the year is prorated). */
export function shareInPeriod(r: ModelRecord, period: { start: string | null; end: string | null }): number {
  if (!r.start || !r.end || !period.start || !period.end) return 1;
  const a = r.start > period.start ? r.start : period.start;
  const b = r.end < period.end ? r.end : period.end;
  if (a > b) return 0;
  return daysBetween(a, b) / daysBetween(r.start, r.end);
}
