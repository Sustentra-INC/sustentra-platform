import type { EvidenceItem, FacilityOption } from "../types";
import { formatPeriod } from "./formatPeriod";

/** Where a document sits, in words: its facility's name, or why it has none. */
export function documentFacilityLabel(item: Pick<EvidenceItem, "facilityName" | "facilityState">): string {
  if (item.facilityName) return item.facilityName;
  if (item.facilityState === "multiple") return "multiple facilities";
  if (item.facilityState === "not_facility_scoped") return "entity-level";
  return "not yet known";
}

export interface SearchDocument {
  id: string;
  fileName: string;
  /** The type as the Evidence screen shows it. */
  type: string;
  facility: string;
  /** "September 2025", "Q1 2025"; empty when the period is not known. */
  period: string;
  /** The facilities this document counts under (Evidence's facility filter rule). */
  facilityIds: string[];
  /** Lowercased text the search looks in besides the file name. */
  other: string;
}

export interface SearchFacility {
  id: string;
  name: string;
  /** Documents under this facility, counted as the Evidence screen counts them. */
  documents: number;
}

export interface SearchIndex {
  documents: SearchDocument[];
  facilities: SearchFacility[];
}

/** The documents and facilities the app has loaded, ready to search. */
export function buildSearchIndex(evidence: EvidenceItem[], facilities: FacilityOption[]): SearchIndex {
  const documents = evidence.map((item): SearchDocument => {
    const period = item.periodStart && item.periodEnd ? formatPeriod(item.periodStart, item.periodEnd) : "";
    const facility = documentFacilityLabel(item);
    // Withdrawn files stay findable by name but count under no facility, as on the Evidence screen.
    const facilityIds =
      item.disposition !== "active"
        ? []
        : item.facilityState === "resolved" && item.facilityId
          ? [item.facilityId]
          : item.facilityState === "multiple"
            ? (item.facilityIds ?? [])
            : [];
    return {
      id: item.documentId,
      fileName: item.filename,
      type: item.detectedType ?? "Type unresolved",
      facility,
      period,
      facilityIds,
      other: [item.detectedType, facility, period, item.periodStart, item.periodEnd].filter(Boolean).join(" ").toLowerCase(),
    };
  });
  const counts = new Map<string, number>();
  for (const doc of documents) for (const id of doc.facilityIds) counts.set(id, (counts.get(id) ?? 0) + 1);
  return {
    documents,
    facilities: facilities.map((f) => ({ id: f.facilityId, name: f.name, documents: counts.get(f.facilityId) ?? 0 })),
  };
}

/** The typed words, lowercased. Every one must appear for a match, in any order. */
export function queryWords(query: string): string[] {
  return query.toLowerCase().split(/\s+/).filter(Boolean);
}

/** 0: the label starts with the query; 1: the label has every word; 2: the words are spread over
 *  the label and the other fields; null: no match. */
function rank(label: string, other: string, query: string): 0 | 1 | 2 | null {
  const words = queryWords(query);
  const name = label.toLowerCase();
  if (!words.length) return 1;
  if (!words.every((w) => name.includes(w) || other.includes(w))) return null;
  if (name.startsWith(words.join(" "))) return 0;
  return words.every((w) => name.includes(w)) ? 1 : 2;
}

function ranked<T>(items: T[], label: (item: T) => string, other: (item: T) => string, query: string): T[] {
  return items
    .map((item) => ({ item, rank: rank(label(item), other(item), query) }))
    .filter((r): r is { item: T; rank: 0 | 1 | 2 } => r.rank !== null)
    .sort((a, b) => a.rank - b.rank || label(a.item).localeCompare(label(b.item), undefined, { sensitivity: "base" }))
    .map((r) => r.item);
}

/** Documents matching the query, best first; only one facility's when `facilityId` is given. */
export function findDocuments(index: SearchIndex, query: string, facilityId?: string | null): SearchDocument[] {
  const pool = facilityId ? index.documents.filter((d) => d.facilityIds.includes(facilityId)) : index.documents;
  return ranked(pool, (d) => d.fileName, (d) => d.other, query);
}

/** Facilities whose name has every typed word, best first. */
export function findFacilities(index: SearchIndex, query: string): SearchFacility[] {
  return ranked(index.facilities, (f) => f.name, () => "", query);
}
