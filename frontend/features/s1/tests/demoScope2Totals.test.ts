import { describe, expect, it } from "vitest";

import type { Recalculation } from "../api/recalculation";
import { demoApi } from "../demo-backend";
import { manufacturerEvidence } from "../fixtures/evidence/manufacturerEvidence";
import { manufacturerValues } from "../fixtures/extraction/manufacturerValues";
import { reportedTotal, scope2LocationWorkbookRows, verificationLines } from "../fixtures/verification/resultsDataset";

const sumOf = (box: string, activity?: string) =>
  verificationLines
    .filter((l) => l.box === box && (activity === undefined || l.activity === activity))
    .flatMap((l) => l.facilities ?? [])
    .reduce((s, f) => s + (f.reported ?? 0), 0);

describe("the demo's reported Scope 2 is its workbook's own sum (C9)", () => {
  it("on the recalculation, the workbook's extracted totals and its rows", async () => {
    const recalc = await demoApi<Recalculation>("/engagements/ENG-CASCADE-2025/recalculation");
    const reported = (key: string) => recalc.comparisons.find((c) => c.key === key)!.reported!;
    for (const box of ["scope2_location", "scope2_market"]) {
      expect(reported(`${box}_total`)).toBeCloseTo(sumOf(box), 9);
      expect(reportedTotal(box as "scope2_location")).toBeCloseTo(sumOf(box), 9);
    }
    expect(reported("purchased_electricity_total")).toBeCloseTo(sumOf("scope2_location", "Electricity"), 9);
    // Kent Cannery's steam: 15,800 Mlb from the neighbouring CHP plant at the company's 1,000 Btu/lb, EPA Table 7
    const steam = 15_800 * (66.33 / 1000 + (1.25 / 1e6) * 28 + (0.125 / 1e6) * 265);
    expect(reported("purchased_steam_total")).toBeCloseTo(steam, 9);
    expect(sumOf("scope2_location", "Steam")).toBeCloseTo(1049.090375, 9);
    // the workbook document's totals are the same figures, and its rows add up to them
    const workbook = (what: string) => Number(manufacturerValues.find((v) => v.documentId === "DOC-WORKBOOK" && v.whatItIs === what)!.value.replace(/,/g, ""));
    expect(workbook("Total Scope 2, location-based (client calc)")).toBe(Math.round(sumOf("scope2_location")));
    expect(workbook("Total Scope 2, market-based (client calc)")).toBe(Math.round(sumOf("scope2_market")));
    const rows = scope2LocationWorkbookRows();
    expect(rows.map((r) => r[2])).toEqual(["Electricity", "Electricity", "Electricity", "Steam", "Heating"]);
    expect(rows.reduce((s, r) => s + Number(r[6].replace(/,/g, "")), 0)).toBeCloseTo(sumOf("scope2_location"), -1);
  });

  it("has one set of Kent steam documents, the CHP statements, on Evidence and in the workbook's working", () => {
    const files = verificationLines.flatMap((l) => (l.facilities ?? []).flatMap((f) => f.steps.flatMap((s) => [s.reported?.source, s.recomputed?.source])))
      .flatMap((src) => (src?.kind === "records" ? src.items.map((d) => d.filename) : []));
    const steam = files.filter((f) => /steam/.test(f));
    expect(steam).toHaveLength(24); // twelve statements, cited by the location- and the market-based line
    expect(steam.every((f) => /^kent_chp_steam_[a-z]{3}_2025\.pdf$/.test(f))).toBe(true);
    const onEvidence = new Set(manufacturerEvidence.map((d) => d.filename));
    expect(steam.every((f) => onEvidence.has(f))).toBe(true);
    expect([...onEvidence].filter((f) => /steam/.test(f) && !f.startsWith("kent_chp_steam_"))).toEqual([]);
  });
});
