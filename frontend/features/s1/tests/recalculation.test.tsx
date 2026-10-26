/* @vitest-environment jsdom */
import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import {
  coverageFromRecalculation,
  documentsBasis,
  leftOutMessage,
  recalculationMateriality,
  recalculationRows,
  type RecalcCategory,
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

  describe("names only the documents with reviewed values", () => {
    const pending = (document_id: string) => ({
      document_id, record: `${document_id}.pdf`, canonical_type_id: "CT-S2-ELEC", fields: ["activity_quantity"],
    });
    // As on staging: 4 documents read, 1 accepted, 3 still awaiting review (one with two records waiting).
    const staging: Recalculation = {
      ...RESULT,
      documents_considered: 4,
      documents_reviewed: 1,
      awaiting_review: [pending("SCAN-1"), pending("SCAN-2"), pending("DIESEL-CSV"), pending("DIESEL-CSV")],
    };

    it("counts reviewed documents and says how many more await review", () => {
      const note = recalculationMateriality(staging).note;
      expect(note).toContain("from 1 document with reviewed values (3 more awaiting review), at AR5 GWPs.");
      expect(note).not.toContain("4 document");
    });

    it("uses the plural, and names documents held by a question about their values", () => {
      expect(documentsBasis({ ...staging, documents_considered: 5, documents_reviewed: 2 }))
        .toBe("2 documents with reviewed values (3 more awaiting review)");
      expect(documentsBasis({ ...staging, documents_considered: 6, documents_reviewed: 2 }))
        .toBe("2 documents with reviewed values (3 more awaiting review, 1 more needing an input)");
      expect(documentsBasis({ ...staging, documents_considered: 3, documents_reviewed: 0 }))
        .toBe("0 documents with reviewed values (3 awaiting review)");
      expect(documentsBasis({ ...staging, documents_considered: 1, documents_reviewed: 1, awaiting_review: [] }))
        .toBe("1 document with reviewed values");
    });

    it("keeps the old wording for results without documents_reviewed", () => {
      expect(RESULT.documents_reviewed).toBeUndefined();
      expect(recalculationMateriality(RESULT).note).toContain("from 4 document(s) with reviewed values, at AR5 GWPs.");
    });
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
      refrigerant_gwps: {},
      steam_heat_content: {},
      vehicle_groups: [],
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
    expect(rules["COV-S1-FUGITIVE"].status).toBe("not_applicable");
    expect(rules["COV-S1-MOBILE"].status).toBe("not_applicable");
  });

  it("says when records were left out for being outside the reporting period", () => {
    const outside: Recalculation = {
      ...RESULT,
      excluded: [{ document_id: "MF-01", record: "MF-01.pdf (record 1)", canonical_type_id: "CT-S1-MOBFUEL", period: "2024-03-02" }],
    };
    const rules = Object.fromEntries(coverageFromRecalculation(outside).map((r) => [r.ruleId, r]));
    expect(rules["COV-PERIOD"].reason).toContain("MF-01.pdf (record 1) (2024-03-02)");
    expect(rules["COV-S1-MOBILE"].reason).toContain("1 outside the reporting period");
    const mobileRow = byKey(recalculationRows(outside)).mobile_combustion_total;
    expect(mobileRow.recomputeReason).toBe("its records are left out (see why)");
  });

  it("says which documents the reviewer left out and why", () => {
    const decided: Recalculation = {
      ...RESULT,
      excluded: [
        { document_id: "GAS-1", record: "gas.pdf", canonical_type_id: "CT-S1-MOBFUEL", period: "", reason: "withdrawn" },
        { document_id: "FUEL-2", record: "fuel.pdf (record 1)", canonical_type_id: "CT-S1-MOBFUEL", period: "2024-03-02",
          reason: "outside_reporting_period" },
      ],
    };
    const rules = Object.fromEntries(coverageFromRecalculation(decided).map((r) => [r.ruleId, r]));
    expect(rules["COV-DECISIONS"].reason).toBe("gas.pdf (withdrawn by the reviewer).");
    expect(rules["COV-S1-MOBILE"].reason).toContain("1 withdrawn by the reviewer, 1 outside the reporting period");
    expect(rules["COV-PERIOD"].reason).not.toContain("gas.pdf");
  });
});

describe("refrigerants (simplified material balance)", () => {
  const LB_T = 0.45359237 / 1000;
  const mass = 5.5 * LB_T;
  const fugitive: RecalcCategory = {
    category: "fugitive_refrigerants",
    lines: [{
      key: "R-410A",
      equations: { "R-410A": "(P_N - C_N) + P_S + (C_D - R_D)" },
      mass_t: { "R-410A": mass },
      steps: [
        { label: "R-410A emitted", formula: "(P_N - C_N) + P_S + (C_D - R_D)", result: 5.5, result_unit: "lb",
          inputs: {
            "P_N (charged into new equipment)": { value: 21, unit: "lb", source: "2 reviewed record(s)" },
            "C_N (full charge of new equipment)": { value: 20, unit: "lb", source: "2 reviewed record(s)" },
            "P_S (added when servicing)": { value: 4.5, unit: "lb", source: "2 reviewed record(s)" },
          } },
        { label: "R-410A emitted in metric tons", formula: "lb to metric tons", result: mass, result_unit: "t",
          inputs: { mass: { value: 5.5, unit: "lb", source: null } } },
        { label: "R-410A in CO2e", formula: "mass x GWP", result: mass * 1924, result_unit: "t CO2e",
          inputs: { mass: { value: mass, unit: "t", source: null },
            GWP: { value: 1924, unit: "", source: "EPA GHG Emission Factors Hub 2025, Table 12, row 575 (IPCC AR5)" } } },
      ],
      flags: [],
      biogenic_co2_t: 0,
    }],
    total_mass_t: { "R-410A": mass },
    total_co2e_t: { "R-410A": mass * 1924 },
    total_co2e: mass * 1924,
    gwp: { "R-410A": { value: 1924, source: "EPA GHG Emission Factors Hub 2025, Table 12, row 575 (IPCC AR5)" } },
    biogenic_co2_t: 0,
    steps: [],
    flags: [],
    details: { inputs: [{ fuel: "R-410A", unit: "lb", quantity: 5.5, documents: [
      { document_id: "LOG", record: "log.pdf (record 2)", quantity: 4.5, unit: "lb", service_type: "service" },
      { document_id: "LOG", record: "log.pdf (record 4)", quantity: 21, unit: "lb", service_type: "installation" },
    ] }] },
    gwp_set: "AR5",
  };
  const withRefrigerants: Recalculation = {
    ...RESULT,
    categories: { ...RESULT.categories, fugitive_refrigerants: fugitive },
    comparisons: [...RESULT.comparisons, {
      key: "fugitive_total", data_point: "Direct emissions from fugitive sources", workbook_row: 45, unit: "t CO2e",
      reported: null, recalculated: mass * 1924, difference: null, difference_pct: null, status: "not_reported",
      inputs_incomplete: false,
    }],
    excluded: [{ document_id: "LOG", record: "log.pdf (record 5)", canonical_type_id: "CT-S1-REFRSVC",
      period: "2025-10-02", reason: "montreal_protocol_gas", gas: "HCFC-22" }],
  };

  it("shows every material-balance term with the records it came from", () => {
    const row = byKey(recalculationRows(withRefrigerants)).fugitive_total;
    expect(row.recomputed).toBe("4.80");
    const working = row.working!;
    expect(working.formula).toContain("(P_N − C_N) + P_S + (C_D − R_D)");
    expect(working.inputs.map((i) => i.label)).toEqual([
      "R-410A · P_N (charged into new equipment)",
      "R-410A · C_N (full charge of new equipment)",
      "R-410A · P_S (added when servicing)",
    ]);
    expect(working.inputs[0].source).toBe("log.pdf (record 4)"); // P_N: the installation
    expect(working.inputs[2].source).toBe("log.pdf (record 2)"); // P_S: the service
    expect(working.factors).toEqual([{ label: "GWP R-410A (AR5)", value: "1924",
      source: "EPA GHG Emission Factors Hub 2025, Table 12, row 575 (IPCC AR5)" }]);
    expect(working.references[0]).toBe("EPA GHG Emission Factors Hub 2025, Table 12");
  });

  it("explains an HCFC left out of Scope 1 and covers the category", () => {
    expect(leftOutMessage(withRefrigerants.excluded![0])).toContain("HCFC-22 is a CFC or HCFC");
    const rules = Object.fromEntries(coverageFromRecalculation(withRefrigerants).map((r) => [r.ruleId, r]));
    expect(rules["COV-S1-FUGITIVE"].status).toBe("inputs_present");
    expect(rules["COV-S1-FUGITIVE"].reason).toContain("R-410A from 2 reviewed record(s)");
    expect(rules["COV-S1-FUGITIVE"].reason).toContain("(HCFC-22) are listed but not counted");
    expect(rules["COV-DECISIONS"]).toBeUndefined();
  });

  it("asks for a GWP the EPA Hub does not have and saves it", () => {
    const onSave = vi.fn();
    const result: Recalculation = {
      ...RESULT,
      needs_input: [{ kind: "refrigerant_gwp", key: "R-454B",
        message: "No AR5 GWP for R-454B in the EPA GHG Emission Factors Hub (Tables 11-12)." }],
    };
    render(<RecalculationInputs result={result} reference={REFERENCE} settings={{}} saving={false} error={null}
      onSave={onSave} />);
    const field = screen.getByText("R-454B").closest("label")!;
    fireEvent.change(within(field).getByRole("textbox"), { target: { value: "466" } });
    fireEvent.click(screen.getByRole("button", { name: "Save and recalculate" }));
    expect(onSave).toHaveBeenCalledWith(expect.objectContaining({ refrigerant_gwps: { "R-454B": 466 } }));
  });
});

describe("vehicle groups (mobile CH4 and N2O)", () => {
  const mobileLine = { ...RESULT.categories.purchased_electricity_location_based!.lines[0], key: "Diesel Fuel" };
  const withMobile: Recalculation = {
    ...RESULT,
    categories: {
      ...RESULT.categories,
      mobile_combustion: { ...RESULT.categories.purchased_electricity_location_based!, category: "mobile_combustion",
        lines: [mobileLine], flags: ["ch4_n2o_need_vehicle_groups"] },
    },
  };
  const reference: RecalculationReference = {
    ...REFERENCE,
    vehicle_types: [
      { vehicle_type: "Medium- and Heavy-Duty Vehicles", fuel_type: "Diesel", on_road: true, by_model_year: true,
        first_model_year: 1960, last_model_year: 2022 },
      { vehicle_type: "Industrial/Commercial Equipment", fuel_type: "Diesel", on_road: false, by_model_year: false,
        first_model_year: null, last_model_year: null },
    ],
  };

  it("adds an on-road group with model year and distance, and saves it", () => {
    const onSave = vi.fn();
    render(<RecalculationInputs result={withMobile} reference={reference} settings={{}} saving={false} error={null}
      onSave={onSave} />);
    fireEvent.click(screen.getByRole("button", { name: /Recalculation inputs/ }));
    fireEvent.click(screen.getByRole("button", { name: "Add vehicle group" }));
    const group = screen.getByRole("group", { name: "Vehicle group 1" });
    fireEvent.change(within(group).getByLabelText("Vehicle type (EPA)"), {
      target: { value: "Medium- and Heavy-Duty Vehicles" } });
    expect((within(group).getByLabelText("EPA fuel for CH₄ and N₂O") as HTMLSelectElement).value).toBe("Diesel");
    const save = screen.getByRole("button", { name: "Save and recalculate" }) as HTMLButtonElement;
    expect(save.disabled).toBe(true); // no distance yet
    fireEvent.change(within(group).getByLabelText("Model year"), { target: { value: "2018" } });
    fireEvent.change(within(group).getByLabelText("Distance driven"), { target: { value: "10000" } });
    fireEvent.change(within(group).getByLabelText("Group"), { target: { value: "4 heavy trucks" } });
    expect(save.disabled).toBe(false);
    fireEvent.click(save);
    expect(onSave).toHaveBeenCalledWith(expect.objectContaining({
      vehicle_groups: [{ fuel: "Diesel Fuel", vehicle_type: "Medium- and Heavy-Duty Vehicles",
        factor_fuel_type: "Diesel", on_road: true, label: "4 heavy trucks", distance: 10000, distance_unit: "mi",
        model_year: 2018 }],
    }));
  });

  it("does not send a model year left behind when the vehicle type no longer uses one", () => {
    const onSave = vi.fn();
    const typesWithCng = { ...reference, vehicle_types: [...reference.vehicle_types!, { vehicle_type: "Buses",
      fuel_type: "CNG", on_road: true, by_model_year: false, first_model_year: null, last_model_year: null }] };
    render(<RecalculationInputs result={withMobile} reference={typesWithCng} settings={{}} saving={false} error={null}
      onSave={onSave} />);
    fireEvent.click(screen.getByRole("button", { name: /Recalculation inputs/ }));
    fireEvent.click(screen.getByRole("button", { name: "Add vehicle group" }));
    const group = screen.getByRole("group", { name: "Vehicle group 1" });
    fireEvent.change(within(group).getByLabelText("Vehicle type (EPA)"), {
      target: { value: "Medium- and Heavy-Duty Vehicles" } });
    fireEvent.change(within(group).getByLabelText("Model year"), { target: { value: "201" } });
    fireEvent.change(within(group).getByLabelText("Distance driven"), { target: { value: "100" } });
    const save = screen.getByRole("button", { name: "Save and recalculate" }) as HTMLButtonElement;
    expect(save.disabled).toBe(true); // "201" is not a year
    fireEvent.change(within(group).getByLabelText("Vehicle type (EPA)"), { target: { value: "Buses" } });
    expect(save.disabled).toBe(false);
    fireEvent.click(save);
    expect(onSave.mock.calls[0][0].vehicle_groups[0]).not.toHaveProperty("model_year");
  });

  it("lets a lone non-road group leave the fuel blank", () => {
    const onSave = vi.fn();
    render(<RecalculationInputs result={withMobile} reference={reference} settings={{ vehicle_groups: [
      { fuel: "Diesel Fuel", vehicle_type: "Industrial/Commercial Equipment", factor_fuel_type: "Diesel",
        on_road: false }] }} saving={false} error={null} onSave={onSave} />);
    fireEvent.click(screen.getByRole("button", { name: /Recalculation inputs/ }));
    fireEvent.click(screen.getByRole("button", { name: "Save and recalculate" }));
    expect(onSave).toHaveBeenCalledWith(expect.objectContaining({
      vehicle_groups: [{ fuel: "Diesel Fuel", vehicle_type: "Industrial/Commercial Equipment",
        factor_fuel_type: "Diesel", on_road: false }],
    }));
  });
});


describe("purchased steam billed by weight", () => {
  it("asks for the steam's heat content and saves it per facility", () => {
    const onSave = vi.fn();
    const result: Recalculation = {
      ...RESULT,
      needs_input: [{ kind: "steam_heat_content", key: "Facility C", category: "purchased_steam",
        message: "Facility C: steam is billed by weight (klb). Enter its heat content in Btu per lb." }],
    };
    render(<RecalculationInputs result={result} reference={REFERENCE} settings={{}} saving={false} error={null} onSave={onSave} />);
    const field = screen.getByText("Facility C", { selector: "legend ~ label span" }).closest("label")!;
    expect(within(field).getByText(/needed/)).toBeTruthy();
    fireEvent.change(within(field).getByRole("textbox"), { target: { value: "90" } });
    expect((screen.getByRole("button", { name: "Save and recalculate" }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.change(within(field).getByRole("textbox"), { target: { value: "1,194" } }); // as suppliers write it
    fireEvent.click(screen.getByRole("button", { name: "Save and recalculate" }));
    expect(onSave.mock.calls[0][0].steam_heat_content).toEqual({ "Facility C": 1194 });
  });

  it("says purchased cooling is listed, not calculated", () => {
    const message = leftOutMessage({ record: "COOL-JUL.pdf", period: "2025-07-01 to 2025-07-31",
      reason: "purchased_cooling_not_calculated" });
    expect(message).toMatch(/^COOL-JUL\.pdf: purchased cooling \(chilled water\) is not calculated yet/);
  });
});
