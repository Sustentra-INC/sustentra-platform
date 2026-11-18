/**
 * The demo's recalculation, step by step: the calculation lines (Step 1 activity, Step 2 unit,
 * Step 3 gases, Results, company side) and the category results the totals roll up from.
 * Every input is a reviewed record of the demo line model; every factor is the EPA GHG Emission
 * Factors Hub 2025 value the old demo already used. Mirrors the backend's response shapes
 * (`api/recalculation.ts`), computed the way `backend/app/services/recalculation_lines.py` does.
 */
import type {
  CalcGas, CalcLineGas, CalcLineResults, CalcLineStatus, CalcLineStep1Row, CalcLineStep2, CalcQuantity, CalculationLine, CategoryKey, ExcludedRecord,
  RecalcAwaitingReview, RecalcCategory, RecalcLine, RecalcStep, RollupSourceKey,
} from "../api/recalculation";
import type { RecalculationSettings } from "../types/engagement";
import { DEFAULT_VEHICLE_GROUP, buildModel, engagementNow, recordsOn, shareInPeriod, type Model, type ModelLine, type ModelRecord } from "./linesModel";

const HUB = "EPA GHG Emission Factors Hub 2025";
export const GASES: CalcGas[] = ["CO2", "CH4", "N2O"];
const LB_PER_T = 2204.62;

/* ------------------------------------ reference values ------------------------------------ */

const GWPS: Record<string, { CO2: number; CH4: number; N2O: number; r404a: number }> = {
  AR4: { CO2: 1, CH4: 25, N2O: 298, r404a: 3922 },
  AR5: { CO2: 1, CH4: 28, N2O: 265, r404a: 3943 },
  AR6: { CO2: 1, CH4: 27.9, N2O: 273, r404a: 4728 },
};
const GWP_ROW: Record<CalcGas, number> = { CO2: 524, CH4: 525, N2O: 526 };

/** eGRID2023 total-output factors (EPA Hub Table 6), lb per MWh. */
export const EGRID: Record<string, { name: string; row: number; CO2: number; CH4: number; N2O: number }> = {
  NWPP: { name: "WECC Northwest", row: 350, CO2: 631.705, CH4: 0.054, N2O: 0.008 },
  CAMX: { name: "WECC California", row: 342, CO2: 436.655, CH4: 0.025, N2O: 0.003 },
};
/** ZIP code to eGRID subregion, for the demo's three facilities. */
export const ZIP_SUBREGION: Record<string, string[]> = { "97062": ["NWPP"], "98032": ["NWPP"], "95354": ["CAMX"] };

const FUELS = {
  gas: { name: "Natural Gas", row: 38, co2: 53.06, ch4: 1.0, n2o: 0.1, toMmbtu: 0.1, fromUnit: "therms", conversionSource: `${HUB}, Table 1: 1 therm = 0.1 MMBtu` },
  propane: { name: "Propane", row: 72, co2: 62.87, ch4: 3.0, n2o: 0.6, toMmbtu: 0.091, fromUnit: "gal", conversionSource: `${HUB}, Table 1: heat content 0.091 MMBtu per gallon (HHV)` },
};
const DIESEL = { name: "Diesel Fuel", row: 107, co2: 10.21, ch4: 0.0095, n2o: 0.0431, chRow: 256 };

export function gwpOf(set: string) {
  return GWPS[set] ?? GWPS.AR5;
}
const gwpSource = (gas: CalcGas, set: string) => `${HUB}, Table 11, row ${GWP_ROW[gas]} (IPCC ${GWPS[set] ? set : "AR5"})`;
const round = (n: number, d = 6) => Math.round(n * 10 ** d) / 10 ** d;

/* ------------------------------------ inputs ------------------------------------ */

export interface Inputs {
  gwp_set: string;
  tolerance_pct: number;
  settings: RecalculationSettings;
  vehicleGroup: typeof DEFAULT_VEHICLE_GROUP;
  gridRegions: Record<string, string>;
  certificates: { label: string; mwh: number }[];
  shares: Record<string, number>;
}

export function inputsNow(): Inputs {
  const engagement = engagementNow();
  const settings = engagement.recalculation ?? {};
  const tolerance = Number.parseFloat(engagement.materialityThreshold ?? "5");
  return {
    gwp_set: settings.gwp_set ?? "AR5",
    tolerance_pct: Number.isFinite(tolerance) ? tolerance : 5,
    settings,
    vehicleGroup: { ...DEFAULT_VEHICLE_GROUP, ...(settings.vehicle_groups?.[0] ?? {}) } as typeof DEFAULT_VEHICLE_GROUP,
    gridRegions: settings.grid_regions ?? {},
    certificates: settings.certificates ?? [{ label: "Green power PPA retirement statement (cascade_ppa_greenpower.pdf)", mwh: 8000 }],
    shares: settings.consolidated_shares ?? {},
  };
}

/** What the client reported for each line before Setup changes it (the old demo's workbook): annual activity. */
export function defaultCompanyActivity(model: Model): Record<string, CalcQuantity> {
  const key = (category: string, level2: string, facility: string) => `${category === "purchased_energy" ? "s2" : "s1"}:${category}:${level2}:${facility}`;
  const out: Record<string, CalcQuantity> = {
    [key("stationary", "natural-gas", "facility-tualatin")]: { quantity: 800_000, unit: "therms" },
    [key("stationary", "natural-gas", "facility-kent")]: { quantity: 650_000, unit: "therms" },
    [key("stationary", "natural-gas", "facility-modesto")]: { quantity: 350_000, unit: "therms" },
    [key("stationary", "propane", "facility-modesto")]: { quantity: 8_000, unit: "gal" },
    [key("stationary", "propane", "facility-kent")]: { quantity: 6_000, unit: "gal" },
    [key("purchased_energy", "electricity", "facility-tualatin")]: { quantity: 9_000, unit: "MWh" },
    [key("purchased_energy", "electricity", "facility-kent")]: { quantity: 7_200, unit: "MWh" },
    [key("purchased_energy", "electricity", "facility-modesto")]: { quantity: 6_095, unit: "MWh" },
  };
  for (const g of model.vehicleGroups) out[`s1:mobile:diesel-fuel:${g.anchor_id}`] = { quantity: 448_900, unit: "gal" };
  return out;
}

/* ------------------------------------ the line calculation ------------------------------------ */

interface GasPlan { gas: CalcGas; activity: CalcQuantity; ef: { value: number; unit: string; source: string }; conv: number }

interface Plan {
  route: string;
  equations: Partial<Record<CalcGas, string>>;
  step2: (activity: CalcQuantity) => CalcLineStep2;
  gases: (step2: CalcLineStep2) => GasPlan[];
}

function planFor(line: ModelLine, inputs: Inputs, facilityRegion: string | null): Plan | null {
  if (line.category === "stationary" && (line.level2 === "natural-gas" || line.level2 === "propane")) {
    const f = line.level2 === "propane" ? FUELS.propane : FUELS.gas;
    return {
      route: "Energy content × per-MMBtu factor (Eq. 1)",
      equations: { CO2: "Eq. 1", CH4: "Eq. 8", N2O: "Eq. 8" },
      step2: (a) => {
        const result = round(a.quantity * f.toMmbtu, 6);
        return { from_unit: a.unit, to_unit: "MMBtu", factor: a.unit === "MMBtu" ? 1 : f.toMmbtu, source: a.unit === "MMBtu" ? null : f.conversionSource, result: { quantity: a.unit === "MMBtu" ? a.quantity : result, unit: "MMBtu" }, distance: null, implied_fuel_economy: null };
      },
      gases: (s2) => [
        { gas: "CO2", activity: s2.result, ef: { value: f.co2, unit: "kg CO₂/MMBtu", source: `${HUB}, Table 1, row ${f.row}` }, conv: 0.001 },
        { gas: "CH4", activity: s2.result, ef: { value: f.ch4, unit: "g CH₄/MMBtu", source: `${HUB}, Table 1, row ${f.row}` }, conv: 1e-6 },
        { gas: "N2O", activity: s2.result, ef: { value: f.n2o, unit: "g N₂O/MMBtu", source: `${HUB}, Table 1, row ${f.row}` }, conv: 1e-6 },
      ],
    };
  }
  if (line.category === "mobile") {
    const g = inputs.vehicleGroup;
    return {
      route: "Fuel × CO₂ factor (Eq. 1); distance × CH₄ and N₂O factors (Eq. 4, on-road)",
      equations: { CO2: "Eq. 1", CH4: "Eq. 4", N2O: "Eq. 4" },
      step2: (a) => {
        const distance = g.distance ?? 0;
        return {
          from_unit: a.unit, to_unit: "gal", factor: 1, source: null, result: { quantity: a.quantity, unit: "gal" },
          distance: distance ? { quantity: distance, unit: g.distance_unit ?? "mi", source: "Vehicle group distance entered under Recalculation inputs" } : null,
          implied_fuel_economy: distance && a.quantity ? { value: round(distance / a.quantity, 2), unit: "mi/gal", role: "reasonableness_check" } : null,
        };
      },
      gases: (s2) => [
        { gas: "CO2", activity: s2.result, ef: { value: DIESEL.co2, unit: "kg CO₂/gal", source: `${HUB}, Table 2, row ${DIESEL.row}` }, conv: 0.001 },
        ...(s2.distance
          ? ([
              { gas: "CH4", activity: { quantity: s2.distance.quantity, unit: s2.distance.unit }, ef: { value: DIESEL.ch4, unit: "g CH₄/mi", source: `${HUB}, Table 4, row ${DIESEL.chRow}` }, conv: 1e-6 },
              { gas: "N2O", activity: { quantity: s2.distance.quantity, unit: s2.distance.unit }, ef: { value: DIESEL.n2o, unit: "g N₂O/mi", source: `${HUB}, Table 4, row ${DIESEL.chRow}` }, conv: 1e-6 },
            ] as { gas: CalcGas; activity: CalcQuantity; ef: GasPlan["ef"]; conv: number }[])
          : []),
      ].map((p) => ({ ...p })) as GasPlan[],
    };
  }
  if (line.category === "purchased_energy" && line.level2 === "electricity" && facilityRegion && EGRID[facilityRegion]) {
    const region = EGRID[facilityRegion];
    return {
      route: "MWh × eGRID lb/MWh factor",
      equations: { CO2: "Eq. 5", CH4: "Eq. 5", N2O: "Eq. 5" },
      step2: (a) => ({ from_unit: a.unit, to_unit: "MWh", factor: a.unit === "MWh" ? 1 : 0.001, source: a.unit === "MWh" ? null : "Unit conversion: 1 MWh = 1,000 kWh", result: { quantity: a.unit === "MWh" ? a.quantity : round(a.quantity * 0.001, 6), unit: "MWh" }, distance: null, implied_fuel_economy: null }),
      gases: (s2) => GASES.map((gas) => ({ gas, activity: s2.result, ef: { value: region[gas], unit: `lb ${gas === "CO2" ? "CO₂" : gas === "CH4" ? "CH₄" : "N₂O"}/MWh`, source: `eGRID2023, subregion ${facilityRegion}; ${HUB}, Table 6, row ${region.row}` }, conv: 1 / LB_PER_T })),
    };
  }
  return null;
}

function gasLines(gases: GasPlan[], set: string, company?: Record<CalcGas, number> | null): { rows: CalcLineGas[]; results: CalcLineResults } {
  const g = gwpOf(set);
  const rows: CalcLineGas[] = gases.map((p) => {
    const mass = p.activity.quantity * p.ef.value * p.conv;
    return {
      gas: p.gas, activity: { value: p.activity.quantity, unit: p.activity.unit }, ef: p.ef, unit_conversion: p.conv, mass_t: round(mass, 9),
      gwp: { value: g[p.gas], source: `IPCC ${GWPS[set] ? set : "AR5"}` }, co2e_t: round(mass * g[p.gas], 9), biogenic: false,
      ...(company ? { company_co2e_t: round(company[p.gas], 9), difference_to_company_t: round(mass * g[p.gas] - company[p.gas], 9) } : {}),
    };
  });
  const mass_t = { CO2: 0, CH4: 0, N2O: 0 };
  const gas_co2e_t = { CO2: 0, CH4: 0, N2O: 0 };
  for (const r of rows) { mass_t[r.gas] = r.mass_t; gas_co2e_t[r.gas] = r.co2e_t; }
  const sum = gas_co2e_t.CO2 + gas_co2e_t.CH4 + gas_co2e_t.N2O;
  return { rows, results: { mass_t, gas_co2e_t, sum_co2e_t: sum, total_co2e_t: sum, biogenic_co2_t: 0 } };
}

function step1Of(rows: { r: ModelRecord; share: number }[]): { rows: CalcLineStep1Row[]; total: CalcQuantity } {
  const out: CalcLineStep1Row[] = rows.map(({ r, share }) => {
    const counted = round((r.quantity ?? 0) * share, 4);
    return {
      period_start: r.start, period_end: r.end, document_id: r.documentId, evidence_code: null, file_name: r.fileName, candidate_id: r.candidateId,
      review: r.decision === "edited" ? "edited" : "accepted", quantity: r.quantity, unit: r.unit ?? "", share_in_period: round(share, 6), counted_quantity: counted, counted_in_base: counted,
    };
  });
  const total = round(out.reduce((s, o) => s + (o.counted_in_base ?? 0), 0), 4);
  return { rows: out, total: { quantity: total, unit: rows[0]?.r.unit ?? "" } };
}

export interface LineBuild {
  line: CalculationLine;
  model: ModelLine;
  records: { r: ModelRecord; share: number }[];
  facilityName: string | null;
}

export interface Calculated {
  model: Model;
  inputs: Inputs;
  lines: CalcLineBuild[];
  awaiting: RecalcAwaitingReview[];
  excluded: ExcludedRecord[];
  categories: Partial<Record<CategoryKey, RecalcCategory | null>>;
}
export type CalcLineBuild = LineBuild;

const SOURCE_OF: Record<string, RollupSourceKey> = { stationary: "stationary_combustion", mobile: "mobile_combustion", fugitive: "fugitive_refrigerants", purchased_energy: "purchased_electricity" };
export const CALCULABLE = ["gas", "electricity", "fleet", "propane", "refrigerant"];

export function regionOf(facilityName: string, address: string | undefined, inputs: Inputs): { region: string | null; source: string | null } {
  const chosen = inputs.gridRegions[facilityName];
  if (chosen) return { region: chosen, source: "chosen under Recalculation inputs" };
  const zip = /(\d{5})(?:-\d{4})?\s*$/.exec(address ?? "")?.[1];
  const found = zip ? ZIP_SUBREGION[zip]?.[0] : undefined;
  return found ? { region: found, source: `ZIP code ${zip} (EPA Power Profiler, eGRID2023)` } : { region: null, source: null };
}

export function calculate(): Calculated {
  const model = buildModel();
  const inputs = inputsNow();
  const activity = { ...defaultCompanyActivity(model), ...(inputs.settings.reported_activity ?? {}) };
  const awaiting: RecalcAwaitingReview[] = [];
  const excluded: ExcludedRecord[] = [];
  const lines: LineBuild[] = [];

  for (const record of model.records) {
    if (!CALCULABLE.includes(record.kind)) continue;
    const source = SOURCE_OF[record.defaultTarget.split(":")[1]] ?? "stationary_combustion";
    if (record.processingStatus === "blocked") continue;
    if (!record.accepted && record.quantity !== null) {
      awaiting.push({ document_id: record.documentId, record: record.fileName, canonical_type_id: typeId(record), fields: record.waitingFields.length ? record.waitingFields : ["activity_quantity"], category: source });
    } else if (record.waiting.length) {
      awaiting.push({ document_id: record.documentId, record: record.fileName, canonical_type_id: typeId(record), fields: record.waitingFields, category: source });
    }
  }

  for (const ml of model.lines) {
    if (!["stationary", "mobile", "purchased_energy"].includes(ml.category)) continue;
    const on = recordsOn(model, ml.key).filter((r) => r.accepted && r.quantity !== null);
    const withShare = on.map((r) => ({ r, share: shareInPeriod(r, model.period) }));
    for (const { r, share } of withShare) {
      if (share === 0) excluded.push({ document_id: r.documentId, record: r.fileName, canonical_type_id: typeId(r), period: `${r.start ?? "?"} to ${r.end ?? "?"}`, reason: "outside_reporting_period" });
    }
    const used = withShare.filter((x) => x.share > 0);
    if (!used.length) continue;
    const facility = model.facilities.find((f) => f.facilityId === ml.facility_id);
    const region = facility ? regionOf(facility.name, facility.address, inputs).region : null;
    const plan = planFor(ml, inputs, region);
    if (!plan) continue;
    const share = (inputs.shares[ml.facility_id ?? ""] ?? 100) / 100;
    const step1 = step1Of(used);
    const step2 = plan.step2(step1.total);
    const own = gasLines(plan.gases(step2), inputs.gwp_set);
    const companyActivity = activity[ml.key] ?? null;
    let company: CalculationLine["company"] = null;
    if (companyActivity) {
      const cStep2 = plan.step2(companyActivity);
      const cg = gasLines(plan.gases(cStep2), inputs.gwp_set);
      company = { activity: companyActivity, step2: cStep2, step3: { gases: cg.rows }, results: cg.results };
    }
    const withCompany = company ? gasLines(plan.gases(step2), inputs.gwp_set, company.results.gas_co2e_t) : own;
    const results: CalcLineResults = {
      ...withCompany.results, total_co2e_t: round(withCompany.results.sum_co2e_t * share, 9),
      ...(company ? { company_total_co2e_t: company.results.total_co2e_t, company_gas_co2e_t: company.results.gas_co2e_t, difference_to_company_t: round(withCompany.results.sum_co2e_t * share - company.results.total_co2e_t, 9) } : {}),
    };
    const reportedLine = inputs.settings.reported_lines?.[ml.key];
    const reported = reportedLine ?? (company ? company.results.total_co2e_t : null);
    const difference = reported === null ? null : round(results.total_co2e_t - reported, 6);
    const pct = reported ? round(((results.total_co2e_t - reported) / reported) * 100, 2) : null;
    const status: CalcLineStatus = reported === null || pct === null ? "not_reported" : Math.abs(pct) > inputs.tolerance_pct ? "above" : "within";
    const flags: string[] = [];
    if (used.some((x) => x.share < 1)) flags.push("prorated_to_reporting_period");
    if (step2.factor !== 1) flags.push("unit_converted");
    if (ml.category === "purchased_energy" && facility && regionOf(facility.name, facility.address, inputs).source?.startsWith("ZIP")) flags.push("grid_region_from_zip");
    const source = SOURCE_OF[ml.category];
    const open = awaiting.some((a) => a.category === source && (ml.category !== "purchased_energy" || a.document_id && recordsOn(model, ml.key).some((r) => r.documentId === a.document_id)));
    const calc: CalculationLine = {
      key: ml.key, scope: ml.scope as "s1" | "s2", category: ml.category as CalculationLine["category"],
      counts_toward: (ml.category === "purchased_energy" ? "purchased_energy" : ml.category) as CalculationLine["counts_toward"],
      level2: ml.category === "mobile" ? DIESEL.name : ml.level2_label, level2_key: ml.level2,
      label: ml.label,
      facility_id: ml.facility_id, consolidated_share_pct: share * 100, method: { route: plan.route, equations: plan.equations },
      step1, step2, step3: { gases: withCompany.rows }, results, company,
      reported_total_co2e_t: reported, difference_t: difference, status, difference_pct_of_base: pct, inputs_incomplete: open, flags,
    };
    lines.push({ line: calc, model: ml, records: used, facilityName: facility?.name ?? null });
  }
  return { model, inputs, lines, awaiting, excluded, categories: {} };
}

export function typeId(r: ModelRecord): string {
  return { gas: "CT-S1-FUELQTY", propane: "CT-S1-FUELQTY", fleet: "CT-S1-MOBFUEL", electricity: "CT-S2-ELECBILL", refrigerant: "CT-S1-REFRIG", other: "CT-OTHER" }[r.kind];
}

/* ------------------------------------ categories ------------------------------------ */

const num = (value: number, unit: string, source: string | null = null) => ({ value, unit, source });

function docInputs(records: { r: ModelRecord; share: number }[], convert: (n: number) => number, unit: string) {
  return records.map(({ r, share }) => ({ document_id: r.documentId, record: r.fileName, quantity: round(convert((r.quantity ?? 0) * share), 4), unit, share_in_period: round(share, 6) }));
}

function totalsFor(lines: RecalcLine[], set: string, word: string, gwp: RecalcCategory["gwp"]): Pick<RecalcCategory, "total_mass_t" | "total_co2e_t" | "total_co2e" | "steps"> {
  const g = gwpOf(set);
  const steps: RecalcStep[] = [];
  const total_mass_t: Record<string, number> = {};
  const total_co2e_t: Record<string, number> = {};
  for (const gas of GASES) {
    const mass = lines.reduce((s, l) => s + (l.mass_t[gas] ?? 0), 0);
    total_mass_t[gas] = mass;
    total_co2e_t[gas] = mass * g[gas];
    steps.push(
      { label: `Total ${gas} emissions, in mass`, formula: `sum of all ${gas} outputs`, inputs: Object.fromEntries(lines.map((l) => [l.key, num(l.mass_t[gas] ?? 0, "t")])), result: mass, result_unit: "t" },
      { label: `Total ${gas} emissions, in CO2e`, formula: `total ${gas} mass x GWP`, inputs: { mass: num(mass, "t"), GWP: num(g[gas], "", gwp[gas].source) }, result: mass * g[gas], result_unit: "t CO2e" }
    );
  }
  const total = GASES.reduce((s, gas) => s + total_co2e_t[gas], 0);
  steps.push({ label: `Total ${word} emissions, in CO2e`, formula: "CO2 in CO2e + CH4 in CO2e + N2O in CO2e", inputs: Object.fromEntries(GASES.map((gas) => [gas, num(total_co2e_t[gas], "t CO2e")])), result: total, result_unit: "t CO2e" });
  return { total_mass_t, total_co2e_t, total_co2e: total, steps };
}

function gwpTable(set: string): RecalcCategory["gwp"] {
  const g = gwpOf(set);
  return Object.fromEntries(GASES.map((gas) => [gas, { value: g[gas], source: gwpSource(gas, set) }])) as RecalcCategory["gwp"];
}

export function buildCategories(c: Calculated): Partial<Record<CategoryKey, RecalcCategory | null>> {
  const set = c.inputs.gwp_set;
  const gwp = gwpTable(set);
  const out: Partial<Record<CategoryKey, RecalcCategory | null>> = {};
  const by = (cat: string) => c.lines.filter((l) => l.line.counts_toward === cat);

  // Stationary: one line per fuel, across facilities.
  const stationary = by("stationary");
  if (stationary.length) {
    const fuels = [...new Set(stationary.map((l) => l.line.level2))];
    const recLines: RecalcLine[] = [];
    const inputsList: NonNullable<RecalcCategory["details"]["inputs"]> = [];
    for (const fuel of fuels) {
      const group = stationary.filter((l) => l.line.level2 === fuel);
      const f = fuel === "Propane" ? FUELS.propane : FUELS.gas;
      const energy = group.reduce((s, l) => s + l.line.step2.result.quantity, 0);
      const mass_t = Object.fromEntries(GASES.map((gas) => [gas, group.reduce((s, l) => s + l.line.results.mass_t[gas], 0)])) as Record<CalcGas, number>;
      const efs: Record<CalcGas, [number, string]> = { CO2: [f.co2, "kg CO2 per mmBtu"], CH4: [f.ch4, "g CH4 per mmBtu"], N2O: [f.n2o, "g N2O per mmBtu"] };
      const flags = ["fuel_auto_matched", ...(group.some((l) => l.line.flags.includes("prorated_to_reporting_period")) ? ["prorated_to_reporting_period"] : [])];
      recLines.push({
        key: fuel, equations: { CO2: "Eq 1", CH4: "Eq 1", N2O: "Eq 1" }, mass_t,
        steps: GASES.map((gas) => ({ label: `${gas} (Eq 1)`, formula: "Fuel (mmBtu) x EF1", inputs: { "fuel energy": num(round(energy, 4), "mmBtu"), EF: num(efs[gas][0], efs[gas][1], `${HUB}, Table 1, row ${f.row}`) }, result: mass_t[gas], result_unit: "t" })),
        flags, biogenic_co2_t: 0,
      });
      inputsList.push({ fuel, unit: "MMBtu", quantity: round(energy, 4), documents: group.flatMap((l) => docInputs(l.records, (n) => n * l.line.step2.factor, "MMBtu")) });
    }
    out.stationary_combustion = {
      category: "stationary_combustion", lines: recLines, ...totalsFor(recLines, set, "stationary combustion", gwp), gwp, biogenic_co2_t: 0,
      flags: [...new Set(recLines.flatMap((l) => l.flags))], details: { inputs: inputsList }, gwp_set: set,
    };
  }

  // Mobile: one line per fuel.
  const mobile = by("mobile");
  if (mobile.length) {
    const gallons = mobile.reduce((s, l) => s + l.line.step1.total.quantity, 0);
    const distance = mobile[0].line.step2.distance;
    const mass_t = Object.fromEntries(GASES.map((gas) => [gas, mobile.reduce((s, l) => s + l.line.results.mass_t[gas], 0)])) as Record<CalcGas, number>;
    const g = c.inputs.vehicleGroup;
    const steps: RecalcStep[] = [{ label: "CO2 (Eq 1)", formula: "Fuel x EF1", inputs: { fuel: num(gallons, "gallon", `${c.lines.filter((l) => l.line.counts_toward === "mobile").reduce((s, l) => s + l.records.length, 0)} reviewed record(s)`), EF1: num(DIESEL.co2, "kg CO2 per gallon", `${HUB}, Table 2, row ${DIESEL.row}`) }, result: mass_t.CO2, result_unit: "t" }];
    if (distance) {
      steps.push(
        { label: "CH4 (Eq 4)", formula: "Distance x EF", inputs: { distance: num(distance.quantity, "mile"), EF: num(DIESEL.ch4, "g CH4 per mile", `${HUB}, Table 4, row ${DIESEL.chRow}`) }, result: mass_t.CH4, result_unit: "t" },
        { label: "N2O (Eq 4)", formula: "Distance x EF", inputs: { distance: num(distance.quantity, "mile"), EF: num(DIESEL.n2o, "g N2O per mile", `${HUB}, Table 4, row ${DIESEL.chRow}`) }, result: mass_t.N2O, result_unit: "t" }
      );
    }
    const line: RecalcLine = { key: DIESEL.name, equations: { CO2: "Eq 1", ...(distance ? { CH4: "Eq 4", N2O: "Eq 4" } : { N2O: "" }) }, mass_t, steps, flags: [...(distance ? [] : ["ch4_n2o_need_vehicle_groups"]), "fuel_auto_matched"], biogenic_co2_t: 0 };
    void g;
    out.mobile_combustion = {
      category: "mobile_combustion", lines: [line], ...totalsFor([line], set, "mobile combustion", gwp), gwp, biogenic_co2_t: 0, flags: [...line.flags],
      details: { inputs: [{ fuel: DIESEL.name, unit: "gal", quantity: gallons, documents: mobile.flatMap((l) => docInputs(l.records, (n) => n, "gal")) }] }, gwp_set: set,
    };
  }

  // Fugitive refrigerants: material balance, P_S only (what the service logs state).
  const refrig = c.model.records.filter((r) => r.kind === "refrigerant" && r.accepted && r.quantity !== null);
  if (refrig.length) {
    const kg = refrig.reduce((s, r) => s + (r.quantity ?? 0), 0);
    const g = gwpOf(set).r404a;
    const mass = kg / 1000;
    const row = set === "AR5" ? 567 : 567;
    const steps: RecalcStep[] = [
      { label: "R-404A emitted", formula: "(P_N - C_N) + P_S + (C_D - R_D)", inputs: { "P_S (added when servicing)": num(kg, "kg", `${refrig.length} reviewed record(s)`) }, result: kg, result_unit: "kg" },
      { label: "R-404A emitted in metric tons", formula: "kg / 1,000", inputs: { mass: num(kg, "kg") }, result: mass, result_unit: "t" },
      { label: "R-404A in CO2e", formula: "mass x GWP", inputs: { mass: num(mass, "t"), GWP: num(g, "", `${HUB}, Table 12, row ${row} (IPCC ${set})`) }, result: mass * g, result_unit: "t CO2e" },
    ];
    out.fugitive_refrigerants = {
      category: "fugitive_refrigerants", lines: [{ key: "R-404A", equations: { "R-404A": "(P_N - C_N) + P_S + (C_D - R_D)" }, mass_t: { "R-404A": mass }, steps, flags: [], biogenic_co2_t: 0 }],
      total_mass_t: { "R-404A": mass }, total_co2e_t: { "R-404A": mass * g }, total_co2e: mass * g, gwp: { "R-404A": { value: g, source: `${HUB}, Table 12, row ${row} (IPCC ${set})` } } as unknown as RecalcCategory["gwp"], biogenic_co2_t: 0,
      steps: [{ label: "Total refrigerant emissions in CO2e", formula: "sum of each refrigerant's emissions in CO2e", inputs: { "R-404A": num(mass * g, "t CO2e") }, result: mass * g, result_unit: "t CO2e" }],
      flags: [], gwp_set: set,
      details: { inputs: [{ fuel: "R-404A", unit: "kg", quantity: kg, documents: refrig.map((r) => ({ document_id: r.documentId, record: r.fileName, service_type: "service", quantity: r.quantity ?? 0, unit: "kg" })) }] },
    };
  }

  // Purchased electricity: location-based (per facility) and market-based (certificates).
  const power = by("purchased_energy");
  if (power.length) {
    const perFacility = power.map((l) => {
      const region = regionOf(l.facilityName ?? "", c.model.facilities.find((f) => f.facilityId === l.line.facility_id)?.address, c.inputs);
      return { l, region: region.region as string, source: region.source };
    });
    const build = (market: boolean, coverage: number): RecalcCategory => {
      const recLines: RecalcLine[] = perFacility.map(({ l, region }) => {
        const mwh = l.line.step2.result.quantity * (l.line.consolidated_share_pct / 100);
        const used = market ? mwh * (1 - coverage) : mwh;
        const f = EGRID[region];
        const steps: RecalcStep[] = [];
        const mass_t: Record<string, number> = {};
        if (market) steps.push({ label: "Remainder MWh", formula: "electricity (MWh) x (1 - coverage %)", inputs: { electricity: num(mwh, "MWh"), coverage: num(coverage, "fraction") }, result: used, result_unit: "MWh" });
        for (const gas of GASES) {
          const lb = used * f[gas];
          mass_t[gas] = lb / LB_PER_T;
          const input = market ? "remainder" : "electricity";
          steps.push(
            { label: `${gas} (${market ? "remainder" : "electricity"})`, formula: "MWh x EF", inputs: { [input]: num(used, "MWh", market ? null : "1 reviewed bill(s)"), [`EF (${region})`]: num(f[gas], "lb per MWh", `${HUB}, Table 6, row ${f.row}`) }, result: lb, result_unit: "lb" },
            { label: `${gas} in metric tons`, formula: "lb / 2,204.62", inputs: { emissions: num(lb, "lb") }, result: mass_t[gas], result_unit: "t" }
          );
        }
        return { key: l.facilityName ?? l.line.label, equations: { CO2: "Emissions = MWh x EF", CH4: "Emissions = MWh x EF", N2O: "Emissions = MWh x EF" }, mass_t, steps, flags: [], biogenic_co2_t: 0 };
      });
      const word = market ? "purchased electricity market based" : "purchased electricity location based";
      const details: RecalcCategory["details"] = {
        inputs: perFacility.map(({ l, region, source }) => ({
          fuel: l.facilityName ?? l.line.label, unit: "MWh", quantity: round(l.line.step2.result.quantity, 4), documents: docInputs(l.records, (n) => n * l.line.step2.factor, "MWh"),
          grid_region: region, grid_region_source: source,
        })),
      };
      if (market) {
        const total = perFacility.reduce((s, p) => s + p.l.line.step2.result.quantity, 0);
        const covered = c.inputs.certificates.reduce((s, x) => s + x.mwh, 0);
        Object.assign(details, {
          covered_mwh: covered, total_mwh: total, coverage,
          coverage_steps: [
            { label: "Total electricity covered by certificates", formula: "sum of certificate MWh", inputs: Object.fromEntries(c.inputs.certificates.map((x) => [x.label, num(x.mwh, "MWh")])), result: covered, result_unit: "MWh" },
            { label: "Certificate coverage percentage", formula: "covered MWh / total electricity consumption (max 100%)", inputs: { covered: num(covered, "MWh"), "total consumption": num(total, "MWh") }, result: coverage, result_unit: "fraction" },
          ],
        });
      }
      return {
        category: market ? "purchased_electricity_market_based" : "purchased_electricity_location_based", lines: recLines, ...totalsFor(recLines, set, word, gwp), gwp, biogenic_co2_t: 0,
        flags: [...new Set(perFacility.flatMap(({ l }) => l.line.flags).filter((f) => f === "grid_region_from_zip"))], details, gwp_set: set,
      };
    };
    const totalMwh = perFacility.reduce((s, p) => s + p.l.line.step2.result.quantity, 0);
    const certs = c.inputs.certificates.reduce((s, x) => s + x.mwh, 0);
    const coverage = totalMwh ? Math.min(1, certs / totalMwh) : 0;
    out.purchased_electricity_location_based = build(false, 0);
    out.purchased_electricity_market_based = build(true, c.inputs.certificates.length ? coverage : 0);
    if (!c.inputs.certificates.length) out.purchased_electricity_market_based.flags = ["no_certificates_market_equals_location"];
  }
  return out;
}
