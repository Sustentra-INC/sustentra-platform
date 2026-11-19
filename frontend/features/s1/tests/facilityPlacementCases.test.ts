import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

import { encodeReviewCandidateToken } from "../adapters/fieldAdapter";
import type { EvidenceItem, ExtractedField, FacilityOption } from "../types";
import { applyDocumentView, documentFacts, placeRecord } from "../utils/documentView";

/**
 * Where a bill is placed, over the cases the backend tests read too
 * (backend/tests/fixtures/facility_placement_cases.json; the backend side is
 * test_facility_placement_cases.py). The screen must put every record of every case where the backend does.
 */
type Status = "rule" | "ai_only" | "accepted" | "rejected" | "needs_more_evidence";
interface Case {
  id: string;
  records: Record<string, [string, Status]>[];
  expect: { facility: (string | null)[]; note: (string | null)[] };
}
const shared = JSON.parse(
  readFileSync(resolve(process.cwd(), "../backend/tests/fixtures/facility_placement_cases.json"), "utf-8")
) as { facilities: FacilityOption[]; cases: Case[] };

function field(name: string, value: string, status: Status, recordIndex: number | null): ExtractedField {
  return {
    documentId: "D1", canonicalTypeId: "CT-S1-FUELQTY", fieldKey: `${name}-${recordIndex}`, fieldLabel: name, value,
    unit: null, fieldState: "populated", snippet: null, snippetContext: null, location: null,
    valueProperties: status === "ai_only" || status === "accepted" ? ["ai_suggested"] : [],
    reviewStatus: status === "accepted" ? "accepted" : "unreviewed",
    ...(status === "rejected" || status === "needs_more_evidence" ? { placementBlocked: true } : {}),
    correctedValue: null, valueOrigin: "extracted", recordIndex,
    reviewToken: encodeReviewCandidateToken({
      candidate_id: `D1:${recordIndex}:${name}`, document_id: "D1", field_name: name, normalized_value: value,
    } as never),
  } as ExtractedField;
}

describe("the Evidence screen places a bill where the backend does (shared cases)", () => {
  for (const c of shared.cases) {
    it(c.id, () => {
      const multi = c.records.length > 1;
      const fields = c.records.flatMap((record, i) =>
        Object.entries(record).map(([name, [value, status]]) => field(name, value, status, multi ? i + 1 : null))
      );
      const facts = documentFacts(fields).get("D1")!;
      // A record whose every value is blocked (rejected, or only Claude read it) has nothing left to read.
      const nothing = { name: null, address: null, account: null, meter: null };
      const placements = c.records.map((_, i) => placeRecord(facts.records?.[i] ?? nothing, shared.facilities));
      expect(placements.map((p) => p.facility?.facilityId ?? null)).toEqual(c.expect.facility);
      placements.forEach((p, i) => {
        const want = c.expect.note[i];
        if (want === null) expect(p.note).toBeNull();
        else expect(p.note).toContain(want);
      });
      // The row on the Evidence screen: one facility, several ("multiple"), or none.
      const item = { documentId: "D1", filename: "D1.pdf", facilityState: "unresolved", facilityId: null, facilityName: null, disposition: "active", relationships: [] } as unknown as EvidenceItem;
      const [row] = applyDocumentView([item], new Map([["D1", facts]]), {}, shared.facilities);
      const placed = [...new Set(c.expect.facility.filter((f): f is string => f !== null))];
      if (placed.length === 0) expect(row.facilityId ?? null).toBeNull();
      else if (placed.length === 1) expect(row.facilityId).toBe(placed[0]);
      else expect([row.facilityState, row.facilityIds]).toEqual(["multiple", placed]);
    });
  }
});
