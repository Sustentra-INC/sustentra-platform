import { describe, expect, it } from "vitest";

import type { EvidenceItem, FacilityOption } from "../types";
import { applyDocumentView, decisionFromEdit, unmatchedFacilities, type DocumentFacts } from "../utils/documentView";
import { matchFacility } from "../utils/facilityMatch";

const FACILITIES: FacilityOption[] = [
  { facilityId: "F1", name: "Albany Plant", address: "15 State Street", gridRegion: "NYUP" },
  { facilityId: "F2", name: "Facility B" },
];

const item = (documentId: string): EvidenceItem =>
  ({
    documentId, filename: `${documentId}.pdf`, facilityState: "unresolved", facilityId: null, facilityName: null,
    periodState: "unresolved", periodStart: null, periodEnd: null, disposition: "active", relationships: [],
    detectedType: "Purchased electricity record", note: null,
  }) as unknown as EvidenceItem;

const facts = new Map<string, DocumentFacts>([
  ["A", { facilityName: "HVP Account 1001", address: "15 State Street, Albany, NY", periodStart: "2025-01-01", periodEnd: "2025-06-30" }],
  ["B", { facilityName: "FACILITY B", address: null, periodStart: null, periodEnd: null }],
  ["C", { facilityName: "Harborview Cold Storage", address: "210 Dock Street, Erie, PA", periodStart: null, periodEnd: null }],
]);

describe("facility matching (same rules as the backend)", () => {
  it("matches by name or street address, never on a guess", () => {
    expect(matchFacility("facility b", null, FACILITIES)?.facilityId).toBe("F2");
    expect(matchFacility("Someone", "15 State Street, Albany", FACILITIES)?.facilityId).toBe("F1");
    expect(matchFacility("Albany", "Albany", FACILITIES)).toBeNull();
  });
});

describe("documents as the screens show them", () => {
  it("places bills under their Setup facility, with their period", () => {
    const [a, b, c] = applyDocumentView([item("A"), item("B"), item("C")], facts, {}, FACILITIES);
    expect([a.facilityName, a.periodStart, a.periodEnd]).toEqual(["Albany Plant", "2025-01-01", "2025-06-30"]);
    expect(b.facilityId).toBe("F2");
    expect(c.facilityState).toBe("unresolved");
  });

  it("lets the reviewer's saved decisions win", () => {
    const [c] = applyDocumentView([item("C")], facts, { C: { documentId: "C", facilityId: "F2", disposition: "withdrawn" } }, FACILITIES);
    expect([c.facilityName, c.disposition, c.facilitySource]).toEqual(["Facility B", "withdrawn", "reviewer"]);
    const [a] = applyDocumentView([item("A")], facts, {}, FACILITIES);
    expect(a.facilitySource).toBe("matched");
  });

  it("shows a log whose records name several facilities as multiple facilities", () => {
    const log = new Map<string, DocumentFacts>([["L", {
      facilityName: "Albany Plant", address: null, periodStart: null, periodEnd: null,
      facilityNames: ["Albany Plant", "Facility B", "Somewhere Else"], addresses: [],
    }]]);
    const [l] = applyDocumentView([item("L")], log, {}, FACILITIES);
    expect([l.facilityState, l.facilityCount, l.facilityIds]).toEqual(["multiple", 2, ["F1", "F2"]]);
  });

  it("turns an edit into a decision, and ignores no-op updates", () => {
    const before = item("A");
    expect(decisionFromEdit(before, { ...before })).toBeNull();
    const decision = decisionFromEdit(before, { ...before, disposition: "withdrawn" });
    expect(decision).toEqual({ documentId: "A", disposition: "withdrawn" });
  });

  it("keeps a type the reviewer chose or confirmed as confirmed, across a reload", () => {
    const guessed = { ...item("A"), typeReviewBand: "needs_review", typeReviewReason: "low confidence" } as EvidenceItem;
    // Confirming the type already shown records a decision even though the type did not change.
    const confirmed = decisionFromEdit(guessed, { ...guessed, typeConfirmed: true });
    expect(confirmed).toEqual({ documentId: "A", typeConfirmed: true });
    const [shown] = applyDocumentView([guessed], new Map(), { A: confirmed! }, FACILITIES);
    expect([shown.typeConfirmed, shown.typeReviewBand, shown.detectedType]).toEqual([true, null, "Purchased electricity record"]);
    // A type set to something else is confirmed too.
    const [changed] = applyDocumentView([guessed], new Map(), { A: { documentId: "A", detectedType: "Stationary fuel consumption record" } }, FACILITIES);
    expect([changed.typeConfirmed, changed.detectedType]).toEqual([true, "Stationary fuel consumption record"]);
    // Without a decision, the machine's guess stays unconfirmed.
    expect(applyDocumentView([guessed], new Map(), {}, FACILITIES)[0].typeConfirmed).toBeUndefined();
  });

  it("offers the facilities found on bills that match nothing yet", () => {
    expect(unmatchedFacilities(facts, FACILITIES)).toEqual([
      { name: "Harborview Cold Storage", address: "210 Dock Street, Erie, PA" },
    ]);
  });
});
