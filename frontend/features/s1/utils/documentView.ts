import { decodeReviewCandidateToken } from "../adapters/fieldAdapter";
import type { DocumentDecision, EvidenceItem, ExtractedField, FacilityOption } from "../types";
import { matchFacility } from "./facilityMatch";

/** The backend's document types a reviewer can set (backend mode), and their ids. */
export const BACKEND_TYPE_IDS: Record<string, string> = {
  "Stationary fuel consumption record": "CT-S1-FUELQTY",
  "Mobile fuel consumption record": "CT-S1-MOBFUEL",
  "Purchased electricity record": "CT-S2-ELEC",
};

/** What a document's own extracted values say about it. */
export interface DocumentFacts {
  facilityName: string | null;
  address: string | null;
  periodStart: string | null;
  periodEnd: string | null;
}

function fieldName(field: ExtractedField): string | null {
  const candidate = field.reviewToken ? decodeReviewCandidateToken(field.reviewToken) : null;
  return typeof candidate?.field_name === "string" ? candidate.field_name : null;
}

export function documentFacts(fields: ExtractedField[]): Map<string, DocumentFacts> {
  const facts = new Map<string, DocumentFacts & { dates: string[] }>();
  for (const field of fields) {
    const value = field.correctedValue ?? field.value;
    if (!value) continue;
    const entry = facts.get(field.documentId) ?? {
      facilityName: null, address: null, periodStart: null, periodEnd: null, dates: [],
    };
    switch (fieldName(field)) {
      case "facility_name":
        entry.facilityName ??= value;
        break;
      case "service_address":
        entry.address ??= value;
        break;
      case "service_period_start":
      case "transaction_date":
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
    out.set(documentId, { ...rest, periodStart: sorted[0] ?? null, periodEnd: sorted.at(-1) ?? null });
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
  facilities: FacilityOption[]
): EvidenceItem[] {
  return items.map((item) => {
    const fact = facts.get(item.documentId);
    const decision = decisions[item.documentId];
    const chosen = decision?.facilityId ? facilities.find((f) => f.facilityId === decision.facilityId) : undefined;
    const facility = chosen ?? (fact ? matchFacility(fact.facilityName, fact.address, facilities) : null);
    const next: EvidenceItem = { ...item };
    if (facility) {
      next.facilityState = "resolved";
      next.facilityId = facility.facilityId;
      next.facilityName = facility.name;
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
    }
    return next;
  });
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
  return changed ? decision : null;
}

/** Facilities named on bills that match no Setup facility yet (one entry per name). */
export function unmatchedFacilities(
  facts: Map<string, DocumentFacts>,
  facilities: FacilityOption[]
): { name: string; address: string | null }[] {
  const seen = new Map<string, { name: string; address: string | null }>();
  facts.forEach((fact) => {
    const name = fact.facilityName ?? fact.address;
    if (!name || matchFacility(fact.facilityName, fact.address, facilities)) return;
    const key = name.trim().toLowerCase();
    if (!seen.has(key)) seen.set(key, { name: name.trim(), address: fact.address });
  });
  return [...seen.values()];
}
