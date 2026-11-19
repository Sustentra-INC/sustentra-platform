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
  /** The record's own index in the document (null for a single record), as the backend numbers it. */
  recordIndex?: number | null;
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

const PLACEMENT_FIELDS = new Set(["facility_name", "service_address", "account_number", "meter_number"]);

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

const REVIEWED_STATUSES = new Set(["accepted", "corrected", "keyed_by_reviewer"]);
const isReviewed = (field: ExtractedField) => REVIEWED_STATUSES.has(field.reviewStatus);

/**
 * The value of one field of one record that may decide where a bill is placed. The backend's ``_one_field`` and
 * ``for_placement``, exactly: with several readings of the field, the reviewed one counts (two reviewed with
 * different values leave nothing), otherwise the last reading stands. Then a value a reviewer rejected or asked
 * more evidence on, and one only Claude read, give nothing; a reviewed value or one the rules read is used.
 */
export function placementValue(readings: ExtractedField[]): string | null {
  if (!readings.length) return null;
  let field: ExtractedField | null;
  if (readings.length === 1) field = readings[0];
  else {
    const reviewed = readings.filter(isReviewed);
    if (!reviewed.length) field = readings[readings.length - 1];
    else {
      const same = (f: ExtractedField) =>
        (f.correctedValue ?? f.value) === (reviewed[0].correctedValue ?? reviewed[0].value) &&
        (f.correctedUnit ?? f.unit) === (reviewed[0].correctedUnit ?? reviewed[0].unit);
      field = reviewed.every(same) ? reviewed[reviewed.length - 1] : null;
    }
  }
  if (!field || field.placementBlocked) return null;
  if (isReviewed(field)) return field.correctedValue ?? field.value ?? null;
  return field.valueProperties.includes("ai_suggested") ? null : field.value ?? null;
}

export function documentFacts(fields: ExtractedField[]): Map<string, DocumentFacts> {
  const facts = new Map<string, DocumentFacts & { dates: string[] }>();
  // document -> record -> field name -> every reading of it, in the order given
  const readings = new Map<string, Map<string, Map<string, ExtractedField[]>>>();
  for (const field of fields) {
    const name = fieldName(field);
    if (name && PLACEMENT_FIELDS.has(name)) {
      const records = readings.get(field.documentId) ?? new Map<string, Map<string, ExtractedField[]>>();
      readings.set(field.documentId, records);
      const key = String(field.recordIndex ?? "");
      const named = records.get(key) ?? new Map<string, ExtractedField[]>();
      records.set(key, named);
      named.set(name, [...(named.get(name) ?? []), field]);
    }
    const value = field.correctedValue ?? field.value;
    if (!value) continue;
    const entry = facts.get(field.documentId) ?? {
      facilityName: null, address: null, periodStart: null, periodEnd: null, dates: [], facilityNames: [],
      addresses: [],
    };
    switch (name) {
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
    const records: RecordFacts[] = [];
    for (const [key, named] of readings.get(documentId) ?? []) {
      const rec: RecordFacts = {
        recordIndex: key === "" ? null : Number(key),
        name: placementValue(named.get("facility_name") ?? []),
        address: placementValue(named.get("service_address") ?? []),
        account: placementValue(named.get("account_number") ?? []),
        meter: placementValue(named.get("meter_number") ?? []),
      };
      if (rec.name || rec.address || rec.account || rec.meter) records.push(rec);
    }
    records.sort((x, y) => (x.recordIndex ?? -1) - (y.recordIndex ?? -1));
    const doc: DocumentFacts = {
      ...rest,
      facilityName: records.find((r) => r.name)?.name ?? null,
      address: records.find((r) => r.address)?.address ?? null,
      accountNumber: records.find((r) => r.account)?.account ?? null,
      meterNumber: records.find((r) => r.meter)?.meter ?? null,
      facilityNames: [...new Set(records.flatMap((r) => (r.name ? [r.name] : [])))],
      addresses: [...new Set(records.flatMap((r) => (r.address ? [r.address] : [])))],
      periodStart: sorted[0] ?? null,
      periodEnd: sorted.at(-1) ?? null,
    };
    out.set(documentId, records.length ? { ...doc, records } : doc);
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
