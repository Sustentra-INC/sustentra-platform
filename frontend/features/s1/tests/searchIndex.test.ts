import { describe, expect, it } from "vitest";

import type { EvidenceItem, FacilityOption } from "../types";
import { buildSearchIndex, documentFacilityLabel, findDocuments, findFacilities, queryWords } from "../utils/searchIndex";

function doc(over: Partial<EvidenceItem> & { documentId: string; filename: string }): EvidenceItem {
  return {
    disposition: "active",
    detectedType: null,
    facilityState: "unresolved",
    facilityId: null,
    facilityName: null,
    periodStart: null,
    periodEnd: null,
    ...over,
  } as EvidenceItem;
}

const FACILITIES: FacilityOption[] = [
  { facilityId: "kent", name: "Kent Cannery" },
  { facilityId: "tual", name: "Tualatin Plant" },
  { facilityId: "hq", name: "Head office" },
];

const EVIDENCE = [
  doc({
    documentId: "1",
    filename: "tualatin_gas_dec_2025.pdf",
    detectedType: "Natural gas bill",
    facilityState: "resolved",
    facilityId: "tual",
    facilityName: "Tualatin Plant",
    periodStart: "2025-12-01",
    periodEnd: "2025-12-31",
  }),
  doc({
    documentId: "2",
    filename: "pge_electric_sep.pdf",
    detectedType: "Electricity bill",
    facilityState: "resolved",
    facilityId: "kent",
    facilityName: "Kent Cannery",
    periodStart: "2025-09-01",
    periodEnd: "2025-09-30",
  }),
  doc({ documentId: "3", filename: "kent_water.pdf", facilityState: "resolved", facilityId: "kent", facilityName: "Kent Cannery" }),
  doc({ documentId: "4", filename: "fleet.xlsx", facilityState: "multiple", facilityIds: ["kent", "tual"] }),
  doc({ documentId: "5", filename: "old_kent.pdf", disposition: "withdrawn", facilityState: "resolved", facilityId: "kent", facilityName: "Kent Cannery" }),
  doc({ documentId: "6", filename: "policy.pdf", facilityState: "not_facility_scoped" }),
];

const index = buildSearchIndex(EVIDENCE, FACILITIES);
const names = (q: string, facility?: string) => findDocuments(index, q, facility).map((d) => d.fileName);

describe("search index", () => {
  it("labels a document's facility the way the assistant does", () => {
    expect(documentFacilityLabel({ facilityName: "Kent Cannery", facilityState: "resolved" })).toBe("Kent Cannery");
    expect(documentFacilityLabel({ facilityName: null, facilityState: "multiple" })).toBe("multiple facilities");
    expect(documentFacilityLabel({ facilityName: null, facilityState: "not_facility_scoped" })).toBe("entity-level");
    expect(documentFacilityLabel({ facilityName: null, facilityState: "unresolved" })).toBe("not yet known");
  });

  it("describes each document with its type, facility and period as the screens show them", () => {
    const [gas] = index.documents;
    expect(gas).toMatchObject({ type: "Natural gas bill", facility: "Tualatin Plant", period: "December 2025" });
    expect(index.documents[2]).toMatchObject({ type: "Type unresolved", period: "" });
  });

  it("counts facility documents like the Evidence screen: active files, multi-facility files under each", () => {
    expect(index.facilities).toEqual([
      { id: "kent", name: "Kent Cannery", documents: 3 },
      { id: "tual", name: "Tualatin Plant", documents: 2 },
      { id: "hq", name: "Head office", documents: 0 },
    ]);
  });

  it("needs every word, in any order, across name, type, facility and period", () => {
    expect(queryWords("  Gas  DEC ")).toEqual(["gas", "dec"]);
    expect(names("gas dec")).toEqual(["tualatin_gas_dec_2025.pdf"]);
    expect(names("dec gas")).toEqual(["tualatin_gas_dec_2025.pdf"]);
    expect(names("electric")).toEqual(["pge_electric_sep.pdf"]);
    expect(names("2025-09")).toEqual(["pge_electric_sep.pdf"]);
    expect(names("september")).toEqual(["pge_electric_sep.pdf"]);
    expect(names("entity")).toEqual(["policy.pdf"]);
    expect(names("zzz")).toEqual([]);
  });

  it("ranks name starts, then name contains, then other fields, then A to Z", () => {
    // kent_water starts with it; old_kent has it inside; pge_electric only through its facility.
    expect(names("kent")).toEqual(["kent_water.pdf", "old_kent.pdf", "pge_electric_sep.pdf"]);
  });

  it("limits to one facility's documents, all of them on an empty query", () => {
    expect(names("", "kent")).toEqual(["fleet.xlsx", "kent_water.pdf", "pge_electric_sep.pdf"]);
    expect(names("water", "kent")).toEqual(["kent_water.pdf"]);
  });

  it("finds facilities by name only", () => {
    expect(findFacilities(index, "kent").map((f) => f.name)).toEqual(["Kent Cannery"]);
    expect(findFacilities(index, "plant tual").map((f) => f.name)).toEqual(["Tualatin Plant"]);
    expect(findFacilities(index, "electric")).toEqual([]);
  });
});
