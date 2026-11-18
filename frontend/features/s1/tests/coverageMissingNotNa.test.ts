import { describe, expect, it } from "vitest";

import {
  coverageFromRecalculation,
  type ExcludedRecord,
  type RecalcComparison,
  type RecalcAwaitingReview,
  type Recalculation,
} from "../api/recalculation";

/** A new engagement: nothing read, nothing awaiting review, every source in scope. */
const BASE: Recalculation = {
  engagement_id: "ENG-X",
  gwp_set: "AR5",
  reporting_period: { start: "2026-01-01", end: "2026-12-31" },
  tolerance_pct: 5,
  categories: {
    stationary_combustion: null,
    mobile_combustion: null,
    purchased_electricity_location_based: null,
    purchased_electricity_market_based: null,
  },
  scope_totals: { scope1: null, scope2_location: null, scope2_market: null },
  comparisons: [],
  needs_input: [],
  awaiting_review: [],
  excluded: [],
  not_recalculated: [],
  documents_considered: 0,
};

const ids = {
  stationary: "COV-S1-STATIONARY",
  mobile: "COV-S1-MOBILE",
  electricity: "COV-S2-LOCATION",
  refrigerant: "COV-S1-FUGITIVE",
};

const rulesOf = (result: Recalculation) => Object.fromEntries(coverageFromRecalculation(result).map((r) => [r.ruleId, r]));

const notInScope = (...keys: string[]): RecalcComparison[] =>
  keys.map((key) => ({ key, data_point: key, status: "not_in_scope" }) as unknown as RecalcComparison);

const leftOut = (typeId: string, record: string, reason: ExcludedRecord["reason"]): ExcludedRecord => ({
  document_id: `doc-${record}`,
  record,
  canonical_type_id: typeId,
  period: "",
  reason,
});

describe("coverage: an in-scope source with no documents is missing, not 'not applicable'", () => {
  it("marks all four sources missing with no evidence and says so in plain words", () => {
    const rules = rulesOf(BASE);
    for (const id of Object.values(ids)) {
      expect(rules[id]).toMatchObject({ status: "inputs_missing", missingBecause: "no_evidence" });
    }
    expect(rules[ids.stationary].reason).toBe("No documents for stationary fuel yet.");
    expect(rules[ids.mobile].reason).toBe("No documents for vehicle fuel yet.");
    expect(rules[ids.electricity].reason).toBe("No documents for electricity yet.");
    expect(rules[ids.refrigerant].reason).toBe("No documents for refrigerant yet.");
  });

  it("is not applicable when Setup takes the data point out of scope", () => {
    const rules = rulesOf({ ...BASE, comparisons: notInScope("mobile_combustion_total", "fugitive_total") });
    expect(rules[ids.mobile]).toMatchObject({ status: "not_applicable" });
    expect(rules[ids.mobile].missingBecause).toBeUndefined();
    expect(rules[ids.mobile].reason).toContain("Setup");
    expect(rules[ids.refrigerant].status).toBe("not_applicable");
    // The sources still in scope stay missing.
    expect(rules[ids.stationary].status).toBe("inputs_missing");
    expect(rules[ids.electricity].status).toBe("inputs_missing");
  });

  it("is not applicable when the reviewer confirmed the company has none, and shows the reason", () => {
    const reason = "Keine Fahrzeuge: Müller Käserei – Zürich hat keine Flotte (社用車なし)";
    const result = {
      ...BASE,
      rollup: { categories: { mobile_combustion: { status: "confirmed_absent", absent_reason: reason } } },
    } as unknown as Recalculation;
    const rule = rulesOf(result)[ids.mobile];
    expect(rule.status).toBe("not_applicable");
    expect(rule.reason).toContain(reason);
    expect(rulesOf(result)[ids.stationary].status).toBe("inputs_missing");
  });

  it("every record left out is missing evidence, with the left-out reason (non-ASCII names)", () => {
    const result: Recalculation = {
      ...BASE,
      excluded: [
        leftOut("CT-S2-ELEC", "Strom März – Zürich.pdf", "withdrawn"),
        leftOut("CT-S2-ELEC", "電気 2026.pdf", "duplicate"),
        leftOut("CT-S1-FUELQTY", "Erdgas CO₂ 12 °F.pdf", "superseded"),
      ],
    };
    const rules = rulesOf(result);
    expect(rules[ids.electricity]).toMatchObject({ status: "inputs_missing", missingBecause: "no_evidence" });
    expect(rules[ids.electricity].reason).toContain("1 withdrawn by the reviewer");
    expect(rules[ids.electricity].reason).toContain("1 marked as a duplicate");
    expect(rules[ids.stationary]).toMatchObject({ status: "inputs_missing", missingBecause: "no_evidence" });
    expect(rules[ids.stationary].reason).toContain("1 superseded by a newer document");
  });

  it("a source with documents awaiting review is waiting, not missing", () => {
    const waiting: RecalcAwaitingReview = {
      document_id: "d1",
      record: "Rechnung März.pdf",
      canonical_type_id: "CT-S2-ELEC",
      fields: ["quantity"],
    };
    const rules = rulesOf({ ...BASE, awaiting_review: [waiting] });
    expect(rules[ids.electricity]).toMatchObject({ status: "inputs_missing", missingBecause: "awaiting_review" });
    expect(rules[ids.stationary].missingBecause).toBe("no_evidence");
  });

  it("the refrigerant note about CFCs and HCFCs is kept on the missing reason", () => {
    const result: Recalculation = {
      ...BASE,
      excluded: [{ ...leftOut("CT-S1-REFRSVC", "R-22 service", "montreal_protocol_gas"), gas: "R-22" }],
    };
    const rule = rulesOf(result)[ids.refrigerant];
    expect(rule.status).toBe("inputs_missing");
    expect(rule.reason).toContain("R-22");
  });
});
