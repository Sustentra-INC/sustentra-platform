/* @vitest-environment jsdom */
import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import {
  coverageFromRecalculation,
  recalculationMateriality,
  recalculationRows,
  type Recalculation,
  type RecalculationReference,
} from "../api/recalculation";
import { RecalculationInputs } from "../components/RecalculationInputs";
import workbookExample from "./fixtures/recalculationWorkbookExample.json";

/*
 * The fixture is the backend's own response for Claire's GHG Required Data workbook
 * example (Facility A 1,200 MWh in NYUP, Facility B 800 MWh in RFCE, 600 MWh of
 * certificates) plus 28,100 MMBtu of natural gas, with reported Scope 1 = 1,400,
 * Scope 2 location = 348.14 and market = 243.70 t CO2e.
 */
const RESULT = workbookExample as unknown as Recalculation;

const REFERENCE: RecalculationReference = {
  dataset: "EPA GHG Emission Factors Hub 2025",
  gwp_sets: ["AR5", "AR6"],
  default_gwp_set: "AR5",
  egrid_subregions: [
    { egrid_subregion: "NYUP", name: "NPCC Upstate NY" },
    { egrid_subregion: "RFCE", name: "RFC East" },
  ],
  stationary_fuels: ["Natural Gas", "Distillate Fuel Oil No. 2"],
  mobile_fuels: ["Diesel Fuel"],
  reported_data_points: [
    { key: "scope1_total", label: "Scope 1 (Total)", workbook_row: 22, unit: "t CO2e" },
    { key: "scope2_location_total", label: "Scope 2 (Total), location-based", workbook_row: 29, unit: "t CO2e" },
  ],
};

const byKey = (rows: ReturnType<typeof recalculationRows>) =>
  Object.fromEntries(rows.map((row) => [row.methodologyFieldId, row]));

describe("recalculation → verification rows", () => {
  const rows = byKey(recalculationRows(RESULT));

  it("matches Claire's worked example within tolerance", () => {
    const location = rows.scope2_location_total;
    expect(location.layer).toBe("scope2");
    expect(location.scopeBasis).toBe("location");
    expect(location.reportedValue).toBe("348.14");
    expect(location.recomputed).toBe("348.15");
    expect(location.checkOutcome).toBe("held");
    expect(rows.scope2_market_total.recomputed).toBe("243.70");
    expect(rows.scope2_market_total.scopeBasis).toBe("market");
    expect(rows.scope2_market_total.checkOutcome).toBe("held");
  });

  it("flags a reported Scope 1 total outside the 5% tolerance", () => {
    const scope1 = rows.scope1_total;
    expect(scope1.recomputed).toBe("1,492.52");
    expect(scope1.delta).toBe("+6.61%");
    expect(rows.scope2_location_total.delta).toBe("+0.00%");
    expect(scope1.checkOutcome).toBe("exception");
    expect(scope1.checkReason).toContain("±5%");
  });

  it("never invents a reported value or a number for paths not built", () => {
    expect(rows.scope1_co2.reportedValue).toBe("");
    expect(rows.scope1_co2.checkOutcome).toBe("could_not_check");
    expect(rows.scope1_sf6.recomputed).toBeNull();
    expect(rows.scope1_sf6.checkOutcome).toBe("out_of_scope");
    expect(rows.mobile_combustion_total.recomputed).toBeNull();
    expect(rows.mobile_combustion_total.checkOutcome).toBe("could_not_check");
  });

  it("shows the working with EPA factors, sources and the workbook row", () => {
    const working = rows.scope2_location_total.working!;
    expect(working.inputs.map((i) => `${i.label}: ${i.value}`)).toEqual(["Facility A: 1,200 MWh", "Facility B: 800 MWh"]);
    expect(working.inputs[0].source).toBe("BILL-A1.pdf · BILL-A2.pdf");
    expect(working.factors).toContainEqual({
      label: "Facility A · CO2 (electricity) · EF (NYUP)",
      value: "240.99 lb per MWh",
      source: "EPA GHG Emission Factors Hub 2025, Table 6, row 353",
    });
    expect(working.factors?.some((f) => f.label === "GWP CH4 (AR5)" && f.value === "28")).toBe(true);
    expect(working.references).toContain("GHG Required Data workbook, row 29 (Scope 2 (Total), location-based)");
    expect(working.result).toContain("within tolerance");

    const gas = rows.stationary_combustion_total.working!;
    expect(gas.inputs[0]).toMatchObject({ label: "Natural Gas", value: "28,100 mmBtu", source: "GAS-1.pdf" });
    expect(gas.note).toContain("matched to the EPA fuel automatically");
  });

  it("sums materiality over the headline totals only", () => {
    const figures = recalculationMateriality(RESULT);
    expect(figures.total).toBeCloseTo(1400 + 348.14, 6);
    expect(figures.tolerancePct).toBe(5);
    expect(figures.uncorrected).toBeCloseTo(92.51745, 4);
    expect(figures.misstatement).toBeCloseTo(92.51745 + 0.00798, 4);
  });

  it("cannot check anything while inputs are missing", () => {
    const incomplete: Recalculation = {
      ...RESULT,
      comparisons: RESULT.comparisons.map((c) => ({ ...c, inputs_incomplete: c.status !== "not_recalculated" })),
      needs_input: [{ kind: "grid_region", key: "Facility C", message: "Choose the eGRID subregion for Facility C." }],
    };
    const row = byKey(recalculationRows(incomplete)).scope2_location_total;
    expect(row.checkOutcome).toBe("could_not_check");
    expect(recalculationMateriality(incomplete).note).toContain("1 item(s) still need");
  });
});

describe("recalculation inputs panel", () => {
  it("asks for a missing grid region and saves the choices", () => {
    const onSave = vi.fn();
    const result: Recalculation = {
      ...RESULT,
      needs_input: [
        { kind: "grid_region", key: "Facility C", message: "Choose the eGRID subregion for Facility C (Albany, NY).",
          options: ["NYUP", "RFCE"] },
      ],
    };
    render(
      <RecalculationInputs
        result={result}
        reference={REFERENCE}
        settings={{ grid_regions: { "Facility A": "NYUP" }, reported: { scope1_total: 1400 } }}
        saving={false}
        error={null}
        onSave={onSave}
      />
    );
    expect(screen.getByText("1 needed")).toBeTruthy();
    const facilityC = screen.getByText("Facility C").closest("label")!;
    fireEvent.change(within(facilityC).getByRole("combobox"), { target: { value: "NYUP" } });
    fireEvent.change(screen.getByDisplayValue("1400"), { target: { value: "1450.5" } });
    fireEvent.click(screen.getByRole("button", { name: "Save and recalculate" }));
    expect(onSave).toHaveBeenCalledWith({
      grid_regions: { "Facility A": "NYUP", "Facility C": "NYUP" },
      reported: { scope1_total: 1450.5 },
      certificates: [],
    });
  });

  it("will not save a reported value that is not a number", () => {
    render(
      <RecalculationInputs result={RESULT} reference={REFERENCE} settings={{}} saving={false} error={null} onSave={vi.fn()} />
    );
    fireEvent.click(screen.getByRole("button", { name: /Recalculation inputs/ }));
    const row = screen.getByText(/Scope 1 \(Total\)/).closest("label")!;
    fireEvent.change(within(row).getByRole("textbox"), { target: { value: "about 1400" } });
    expect((screen.getByRole("button", { name: "Save and recalculate" }) as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText(/Reported values must be numbers/)).toBeTruthy();
  });
});


describe("materiality and coverage when inputs are partial", () => {
  const withoutScope1Reported: Recalculation = {
    ...RESULT,
    comparisons: RESULT.comparisons.map((c) =>
      c.key === "scope1_total" ? { ...c, reported: null, difference: null, difference_pct: null, status: "not_reported" } : c
    ),
  };

  it("uses the recalculated total where a reported total is missing, and says so", () => {
    const figures = recalculationMateriality(withoutScope1Reported);
    expect(figures.total).toBeCloseTo(1492.51745 + 348.14, 4);
    expect(figures.totalBasis).toContain("recalculated otherwise");
  });

  it("lists what is present, missing and out of scope from the recalculation itself", () => {
    const rules = Object.fromEntries(coverageFromRecalculation(withoutScope1Reported).map((r) => [r.ruleId, r]));
    expect(rules["COV-S2-LOCATION"].status).toBe("inputs_present");
    expect(rules["COV-S2-MARKET"].reason).toBe("600.00 of 2,000.00 MWh covered by certificates.".replace(/\.00/g, ""));
    expect(rules["COV-REPORTED"].status).toBe("inputs_missing");
    expect(rules["COV-REPORTED"].reason).toContain("Scope 1 (Total)");
    expect(rules["COV-FUGITIVE"].status).toBe("out_of_scope");
    expect(rules["COV-S1-MOBILE"].status).toBe("not_applicable");
  });

  it("says when records were left out for being outside the reporting period", () => {
    const outside: Recalculation = {
      ...RESULT,
      excluded: [{ document_id: "MF-01", record: "MF-01.pdf (record 1)", canonical_type_id: "CT-S1-MOBFUEL", period: "2024-03-02" }],
    };
    const rules = Object.fromEntries(coverageFromRecalculation(outside).map((r) => [r.ruleId, r]));
    expect(rules["COV-PERIOD"].reason).toContain("MF-01.pdf (record 1) (2024-03-02)");
    expect(rules["COV-S1-MOBILE"].reason).toContain("outside the reporting period");
    const mobileRow = byKey(recalculationRows(outside)).mobile_combustion_total;
    expect(mobileRow.recomputeReason).toBe("records are outside the reporting period");
  });
});
