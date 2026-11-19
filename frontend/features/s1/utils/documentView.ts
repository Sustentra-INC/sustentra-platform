import { decodeReviewCandidateToken } from "../adapters/fieldAdapter";
import type { DocumentDecision, EvidenceItem, ExtractedField, FacilityOption } from "../types";
import { matchFacility, matchFacilityState } from "./facilityMatch";
import { matchByIdentifier } from "./facilityNumbers";

/** The backend's document types a reviewer can set (backend mode), and their ids. */
export const BACKEND_TYPE_IDS: Record<string, string> = {
  "Stationary fuel consumption record": "CT-S1-FUELQTY",
  "Mobile fuel consumption record": "CT-S1-MOBFUEL",
  "Refrigerant service record": "CT-S1-REFRSVC",
  "Purchased electricity record": "CT-S2-ELEC",
  "Purchased steam, heat or cooling record": "CT-S2-THERMAL",
};

/** What one record of a document says about where it belongs (only values placement may read). */
export interface RecordFacts {
  name: string | null;
  address: string | null;
  account: string | null;
  meter: string | null;
}

/** What a document's own extracted values say about it. */
export interface DocumentFacts {
  facilityName: string | null;
  address: string | null;
  /** The account and meter number the bill gives (provisional step, see utils/facilityNumbers.ts). */
  accountNumber?: string | null;
  meterNumber?: string | null;
  /** The same, record by record (a bill can hold several). When absent, the fields above stand for one record. */
  records?: RecordFacts[];
  periodStart: string | null;
  periodEnd: string | null;
  /** Every facility name and address the document's records give (a log can cover several sites). */
  facilityNames?: string[];
  addresses?: string[];
}

function fieldName(field: ExtractedField): string | null {
  const candidate = field.reviewToken ? decodeReviewCandidateToken(field.reviewToken) : null;
  return typeof candidate?.field_name === "string" ? candidate.field_name : null;
}

/**
 * A value the backend would read to place a bill (record.for_placement): reviewed, or read by the rules, but not
 * one only Claude read and nobody accepted, and not one a reviewer rejected or asked for more evidence on.
 */
function countsForPlacement(field: ExtractedField): boolean {
  if (field.placementBlocked) return false;
  return field.reviewStatus !== "unreviewed" || !field.valueProperties.includes("ai_suggested");
}

export interface RecordPlacement {
  facility: FacilityOption | null;
  how: string | null;
  /** Why nothing was placed when the account or meter number had something to say; null otherwise. */
  note: string | null;
  ambiguous: boolean;
}

const usable = (text: string | null | undefined) => /[\p{L}\p{N}]/u.test((text ?? "").normalize("NFKC"));

/**
 * The one place a record's Setup facility is decided on the screen (the backend's place_on_facility, without the
 * reviewer's choice, which the caller applies first): the facility name, then the service address, then, only
 * when the bill gives no name and no address at all, the account or meter number. A bill whose name or address
 * matched nothing is never placed by its number: it gets a note that asks for a choice.
 */
export function placeRecord(rec: RecordFacts, facilities: FacilityOption[], company?: string | null): RecordPlacement {
  const none: RecordPlacement = { facility: null, how: null, note: null, ambiguous: false };
  const state = matchFacilityState(rec.name, rec.address, facilities, company);
  if (state.facility) {
    const byName = matchFacility(rec.name, null, facilities, company) === state.facility;
    return { ...none, facility: state.facility, how: byName ? "Facility name in Setup" : "Service address in Setup" };
  }
  if (state.ambiguous) return none; // a name or address that points at several facilities: no number settles it
  const byNumber = matchByIdentifier(rec.account, rec.meter, facilities);
  if (byNumber.ambiguous) return { ...none, note: `${byNumber.ambiguous}. Choose the facility.`, ambiguous: true };
  if (!byNumber.facility) return none;
  const given = usable(rec.address) ? (["address", rec.address] as const) : usable(rec.name) ? (["facility name", rec.name] as const) : null;
  if (!given) return { ...none, facility: byNumber.facility, how: byNumber.reason };
  const shown = (given[1] ?? "").split(/\s+/).filter(Boolean).join(" ");
  return { ...none, note: `${byNumber.what} is listed on ${byNumber.facility.name}, but this bill's ${given[0]} (${shown}) is not in Setup. Choose the facility.` };
}

/** The record facts of a document's facts: its records, or the document-level fields standing for one record. */
function recordsOf(fact: DocumentFacts): RecordFacts[] {
  if (fact.records?.length) return fact.records;
  const records: RecordFacts[] = [
    { name: fact.facilityName, address: fact.address, account: fact.accountNumber ?? null, meter: fact.meterNumber ?? null },
  ];
  for (const name of fact.facilityNames ?? []) records.push({ name, address: null, account: null, meter: null });
  for (const address of fact.addresses ?? []) records.push({ name: null, address, account: null, meter: null });
  return records;
}

export function documentFacts(fields: ExtractedField[]): Map<string, DocumentFacts> {
  const facts = new Map<string, DocumentFacts & { dates: string[] }>();
  const byRecord = new Map<string, Map<string, RecordFacts>>();
  const recordOf = (field: ExtractedField): RecordFacts => {
    const records = byRecord.get(field.documentId) ?? new Map<string, RecordFacts>();
    byRecord.set(field.documentId, records);
    const key = String(field.recordIndex ?? "");
    const record = records.get(key) ?? { name: null, address: null, account: null, meter: null };
    records.set(key, record);
    return record;
  };
  for (const field of fields) {
    const value = field.correctedValue ?? field.value;
    if (!value) continue;
    const entry = facts.get(field.documentId) ?? {
      facilityName: null, address: null, periodStart: null, periodEnd: null, dates: [], facilityNames: [],
      addresses: [],
    };
    switch (fieldName(field)) {
      // Placement reads the same source as the backend's best(): a reviewed value or one the rules read,
      // never one only Claude read. That holds for the name, the address and the account and meter numbers.
      case "facility_name":
        if (!countsForPlacement(field)) break;
        recordOf(field).name ??= value;
        entry.facilityName ??= value;
        if (!entry.facilityNames!.includes(value)) entry.facilityNames!.push(value);
        break;
      case "service_address":
        if (!countsForPlacement(field)) break;
        recordOf(field).address ??= value;
        entry.address ??= value;
        if (!entry.addresses!.includes(value)) entry.addresses!.push(value);
        break;
      case "account_number":
        if (!countsForPlacement(field)) break;
        recordOf(field).account ??= value;
        entry.accountNumber ??= value;
        break;
      case "meter_number":
        if (!countsForPlacement(field)) break;
        recordOf(field).meter ??= value;
        entry.meterNumber ??= value;
        break;
      case "service_period_start":
      case "transaction_date":
      case "service_date":
        entry.dates.push(value);
        break;
      case "service_period_end":
        entry.dates.push(value);
        break;
    }
    facts.set(field.documentId, entry);
  }
  const out = new Map<string, DocumentFacts>();
  facts.forEach(({ dates, ...rest }, documentId) => {
    const sorted = [...dates].sort();
    const records = [...(byRecord.get(documentId)?.values() ?? [])].filter((r) => r.name || r.address || r.account || r.meter);
    out.set(documentId, { ...rest, ...(records.length ? { records } : {}), periodStart: sorted[0] ?? null, periodEnd: sorted.at(-1) ?? null });
  });
  return out;
}

/**
 * Each document as the screens show it: the machine's view, with the facility it
 * matches in Setup (or the reviewer's choice), its period, and the reviewer's
 * decisions (withdrawn, notes, duplicate/supersedes, type) laid over it.
 */
export function applyDocumentView(
  items: EvidenceItem[],
  facts: Map<string, DocumentFacts>,
  decisions: Record<string, DocumentDecision>,
  facilities: FacilityOption[],
  company?: string | null
): EvidenceItem[] {
  return items.map((item) => {
    const fact = facts.get(item.documentId);
    const decision = decisions[item.documentId];
    const chosen = decision?.facilityId ? facilities.find((f) => f.facilityId === decision.facilityId) : undefined;
    const matched = chosen ? [] : matchedFacilities(fact, facilities, company);
    const next: EvidenceItem = { ...item };
    if (chosen || matched.length === 1) {
      const facility = chosen ?? matched[0];
      next.facilityState = "resolved";
      next.facilityId = facility.facilityId;
      next.facilityName = facility.name;
      next.facilitySource = chosen ? "reviewer" : "matched";
    } else if (matched.length > 1) {
      // A log or statement whose records name several Setup facilities.
      next.facilityState = "multiple";
      next.facilityCount = matched.length;
      next.facilityIds = matched.map((f) => f.facilityId);
    }
    if (fact?.periodStart && item.periodState === "unresolved") {
      next.periodState = "resolved";
      next.periodStart = fact.periodStart;
      next.periodEnd = fact.periodEnd ?? fact.periodStart;
    }
    if (decision) {
      if (decision.disposition) next.disposition = decision.disposition;
      if (decision.notes) next.notes = decision.notes;
      if (decision.note !== undefined) next.note = decision.note;
      if (decision.relationships) next.relationships = decision.relationships;
      if (decision.detectedType) next.detectedType = decision.detectedType;
      if (decision.detectedType || decision.typeConfirmed) {
        next.typeConfirmed = true;
        next.typeReviewBand = null;
        next.typeReviewReason = null;
      }
    }
    return next;
  });
}

/** The Setup facilities a document's records match (each record by the one rule, ``placeRecord``), each once. */
function matchedFacilities(fact: DocumentFacts | undefined, facilities: FacilityOption[], company?: string | null): FacilityOption[] {
  if (!fact) return [];
  const found = recordsOf(fact)
    .map((rec) => placeRecord(rec, facilities, company).facility)
    .filter((f): f is FacilityOption => f !== null);
  return found.filter((f, i) => found.findIndex((g) => g.facilityId === f.facilityId) === i);
}

/** The reviewer's edits between two views of a document, as a decision (or null if none). */
export function decisionFromEdit(before: EvidenceItem, after: EvidenceItem, prior?: DocumentDecision): DocumentDecision | null {
  const decision: DocumentDecision = { ...(prior ?? {}), documentId: after.documentId };
  let changed = false;
  if (after.facilityId !== before.facilityId && after.facilityState === "resolved") {
    decision.facilityId = after.facilityId;
    changed = true;
  }
  if (after.disposition !== before.disposition) {
    decision.disposition = after.disposition;
    changed = true;
  }
  if (after.note !== before.note || after.notes !== before.notes) {
    decision.note = after.note;
    decision.notes = after.notes;
    changed = true;
  }
  if (after.relationships !== before.relationships) {
    decision.relationships = after.relationships;
    changed = true;
  }
  if (after.detectedType !== before.detectedType) {
    decision.detectedType = after.detectedType;
    changed = true;
  }
  if (after.typeConfirmed && !before.typeConfirmed) {
    decision.typeConfirmed = true;
    changed = true;
  }
  return changed ? decision : null;
}

/** Facilities named on bills that match no Setup facility yet (one entry per name). */
export function unmatchedFacilities(
  facts: Map<string, DocumentFacts>,
  facilities: FacilityOption[],
  company?: string | null
): { name: string; address: string | null }[] {
  const seen = new Map<string, { name: string; address: string | null }>();
  facts.forEach((fact) => {
    const name = fact.facilityName ?? fact.address;
    if (!name || matchFacility(fact.facilityName, fact.address, facilities, company)) return;
    const key = name.trim().toLowerCase();
    if (!seen.has(key)) seen.set(key, { name: name.trim(), address: fact.address });
  });
  return [...seen.values()];
}
