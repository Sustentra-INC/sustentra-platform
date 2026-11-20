import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

import type { BackendExtractionCandidateLike } from "../adapters/fieldAdapter";
import { fieldsFromExtraction, type BackendReviewDecision } from "../api/s1Backend";
import type { DocumentDecision, EvidenceItem, FacilityOption } from "../types";
import { applyDocumentView, documentFacts, placeRecord } from "../utils/documentView";

/**
 * Where a bill is placed, over the cases the backend tests read too
 * (backend/tests/fixtures/facility_placement_cases.json; the backend side is
 * test_facility_placement_cases.py). The screen must put every record of every case where the backend does.
 * The fields go through the same mapping the screen uses for what the API returns (``fieldsFromExtraction``),
 * so a rejected value is blocked by that mapping, not by hand, and records are looked up by record_index.
 */
type Status = "rule" | "ai_only" | "accepted" | "rejected" | "needs_more_evidence";
type Reading = [string, Status];
interface Case {
  id: string;
  company?: string | null;
  decision?: { facilityId: string };
  type?: string;
  record_indexes?: number[];
  records: Record<string, Reading | Reading[]>[];
  /** Claude's facility suggestion stored with the extraction result (a suggestion, never a placement). */
  suggestion?: { facility_id: string; quote: string; source: "file_name" | "line"; page_number?: number | null };
  expect: { facility: (string | null)[]; note: (string | null)[]; reason?: string; suggestion?: string | null };
}
const shared = JSON.parse(
  readFileSync(resolve(process.cwd(), "../backend/tests/fixtures/facility_placement_cases.json"), "utf-8")
) as { company: string; facilities: FacilityOption[]; cases: Case[] };

const readingsOf = (raw: Reading | Reading[]): Reading[] => (Array.isArray(raw[0]) ? (raw as Reading[]) : [raw as Reading]);

/** The backend's items and reviews for a case, then the screen's fields from them. */
function fieldsOf(c: Case) {
  const multi = c.records.length > 1;
  const indexes = c.record_indexes ?? c.records.map((_, i) => i + 1);
  const items: BackendExtractionCandidateLike[] = [];
  const reviews: BackendReviewDecision[] = [];
  c.records.forEach((record, i) => {
    for (const [name, raw] of Object.entries(record)) {
      readingsOf(raw).forEach(([value, status], reading) => {
        const candidate_id = `D1:${indexes[i]}:${name}:${reading}`;
        items.push({
          candidate_id, document_id: "D1", field_name: name, display_label: name, normalized_value: value,
          unit: null, record_index: multi ? indexes[i] : null,
          validation_flags: status === "ai_only" || status === "accepted" ? ["ai_suggested"] : [],
        });
        if (status === "accepted" || status === "rejected" || status === "needs_more_evidence") {
          reviews.push({ candidate_id, field_name: name, decision: status, reviewed_value: status === "accepted" ? value : null });
        }
      });
    }
  });
  return fieldsFromExtraction({ items, created_at: null } as never, reviews, "CT-S1-FUELQTY");
}

describe("the Evidence screen places a bill where the backend does (shared cases)", () => {
  for (const c of shared.cases) {
    it(c.id, () => {
      const company = "company" in c ? c.company : shared.company;
      const multi = c.records.length > 1;
      const indexes = c.record_indexes ?? c.records.map((_, i) => i + 1);
      const facts = documentFacts(fieldsOf(c)).get("D1");
      const item = {
        documentId: "D1", filename: "D1.pdf", facilityState: "unresolved", facilityId: null, facilityName: null, disposition: "active", relationships: [],
        ...(c.suggestion ? { facilitySuggestion: { facilityId: c.suggestion.facility_id, quote: c.suggestion.quote, where: "the file name" } } : {}),
      } as unknown as EvidenceItem;
      const decisions: Record<string, DocumentDecision> = c.decision ? { D1: { documentId: "D1", facilityId: c.decision.facilityId } } : {};
      const [row] = applyDocumentView([item], new Map(facts ? [["D1", facts]] : []), decisions, shared.facilities, company);
      // Claude's suggestion is shown only while the bill awaits a decision: the Evidence screen and the backend tree agree
      expect(row.facilitySuggestion?.facilityId ?? null).toBe(c.expect.suggestion ?? null);

      if (c.decision) {
        expect(row.facilityId).toBe(c.decision.facilityId); // the reviewer's choice comes first
        return;
      }
      // A record whose every value is blocked (rejected, or only Claude read it) has nothing left to read.
      const nothing = { name: null, address: null, account: null, meter: null };
      const placements = indexes.map((index) => {
        const rec = facts?.records?.find((r) => r.recordIndex === (multi ? index : null));
        return placeRecord(rec ?? nothing, shared.facilities, company);
      });
      expect(placements.map((p) => p.facility?.facilityId ?? null)).toEqual(c.expect.facility);
      placements.forEach((p, i) => {
        const want = c.expect.note[i];
        if (want === null) expect(p.note).toBeNull();
        else expect(p.note).toContain(want);
      });
      if (c.expect.reason && !placements[0].facility) {
        // the recalculation's reason for a record it cannot place
        expect(placements[0].ambiguous ? "identifier_on_two_facilities" : "no_facility_match").toBe(c.expect.reason);
      }
      // The row on the Evidence screen: one facility, several ("multiple"), or none.
      const placed = [...new Set(c.expect.facility.filter((f): f is string => f !== null))];
      if (placed.length === 0) expect(row.facilityId ?? null).toBeNull();
      else if (placed.length === 1) expect(row.facilityId).toBe(placed[0]);
      else expect([row.facilityState, [...(row.facilityIds ?? [])].sort()]).toEqual(["multiple", [...placed].sort()]);
    });
  }
});
