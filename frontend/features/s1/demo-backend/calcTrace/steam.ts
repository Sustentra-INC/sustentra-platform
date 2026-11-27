/**
 * Demo purchased steam lines and their traces, in the backend's shapes (backend/app/services/calc_trace/steam.py and
 * _thermal_ef.py). Kent Cannery buys steam by weight on a direct line from a neighbouring CHP plant (boards 06 to 08):
 * twelve monthly statements in Mlb, a heat content of 1,048 Btu/lb entered for the facility under Recalculation inputs,
 * and EPA Table 7 (no supplier or CHP factor is in the evidence yet, so the other three options are "Not used"). The
 * company reports 15,800 Mlb at 1,000 Btu/lb.
 */
import type { CalcGas, CalcLineGas, CalcLineSteam, CalcLineStep1Row, CalcQuantity, CalculationLine } from "../../api/recalculation";
import type { LineTrace, TraceBlock, TraceColumn, TraceInput, TraceOpSymbol, TraceOperand, TraceOperation, TraceSide, TraceStep } from "../../api/calcTrace";
import type { ModelLine, ModelRecord } from "../linesModel";

const HUB = "EPA GHG Emission Factors Hub 2025";
const GASES: CalcGas[] = ["CO2", "CH4", "N2O"];
const GAS_LABEL: Record<CalcGas, string> = { CO2: "CO₂", CH4: "CH₄", N2O: "N₂O" };
const UNIT: Record<CalcGas, string> = { CO2: "kg/MMBtu", CH4: "g/MMBtu", N2O: "g/MMBtu" };
const TO_T: Record<CalcGas, number> = { CO2: 0.001, CH4: 0.000001, N2O: 0.000001 };
/** EPA Hub Table 7 (row 410) and, for fuel and efficiency, Table 1 natural gas (row 38). */
const TABLE7: Record<CalcGas, number> = { CO2: 66.33, CH4: 1.25, N2O: 0.125 };
const NATURAL_GAS: Record<CalcGas, number> = { CO2: 53.06, CH4: 1, N2O: 0.1 };
const OPTIONS = [
  { id: "supplier_specific", label: "Supplier-specific", prefix: "supplier_ef.", what: "Factor stated by the supplier" },
  { id: "chp_allocated", label: "CHP allocated", prefix: "chp_ef.", what: "CHP allocation stated by the supplier" },
  { id: "fuel_and_efficiency", label: "Calculated from fuel and efficiency", prefix: "fuel_ef.", what: "" },
  { id: "epa_table7", label: "EPA default", prefix: "table7.", what: "EPA Hub Table 7, steam and heat" },
] as const;
const ROUTE = "Location-based: steam energy (MMBtu) × emission factor, per gas, × GWP";
const EQUATION = "Emissions (t CO₂e) = Σ per gas [ Steam energy (MMBtu) × emission factor × GWP ]";
const TABLE7_NOTE = "EPA Table 7 is natural gas at 80% efficiency, rounded: 53.06 ÷ 0.80 = 66.325 kg CO₂ per MMBtu, printed as 66.33.";
const HEAT_CONTENT_SOURCE = "Steam heat content entered under Recalculation inputs";
const CONVERSION_UNIT = "lb·MMBtu/Mlb·Btu";
/** The demo's Recalculation inputs: Kent Cannery's steam heat content, Btu per lb. */
export const DEMO_STEAM_HEAT_CONTENT: Record<string, number> = { "facility-kent": 1048 };
/** What the company reports for the line: its steam in Mlb and its net enthalpy. */
export const DEMO_STEAM_COMPANY = { quantity: 15800, unit: "Mlb", enthalpy: 1000 };

type Term = { op: TraceOpSymbol | null; operand: TraceOperand };
const operand = (column: string, value: number | string | null, unit?: string, extra: Partial<TraceOperand> = {}): TraceOperand => ({ column, value, ...(unit ? { unit } : {}), ...extra });
function evaluate(terms: Term[]): number {
  let total = 0;
  terms.forEach((t, i) => {
    const v = Number(t.operand.value);
    if (i === 0) total = v;
    else if (t.op === "×") total *= v;
    else if (t.op === "÷") total /= v;
    else if (t.op === "+") total += v;
    else total -= v;
  });
  return total;
}
const operation = (terms: Term[], column: string, unit: string, inputId?: string): TraceOperation => ({ terms, result: operand(column, evaluate(terms), unit, inputId ? { input_id: inputId } : {}) });
const single = (column: string, value: number | null, unit: string, inputId: string): TraceOperation => ({ terms: [{ op: null, operand: operand(column, value, unit, { input_id: inputId }) }], result: operand(column, value, unit, { input_id: inputId }) });
const col = (key: string, label: string, unit?: string, isResult = false, display: TraceColumn["display"] = {}): TraceColumn => ({ key, label, ...(unit ? { unit } : {}), is_result: isResult, display });
const reference = (value: number | null, unit: string | undefined, citation: string, dataset = HUB): TraceSide => ({ value, ...(unit ? { unit } : {}), status: "reference", source: { kind: "reference", dataset, citation } });
function withDifference(mine: TraceOperation, theirs: TraceOperation | undefined): TraceOperation {
  if (!theirs || typeof mine.result.value !== "number" || typeof theirs.result.value !== "number") return mine;
  const terms = mine.terms.map((t, i) => {
    const twin = theirs.terms[i]?.operand;
    return twin && typeof t.operand.value === "number" && typeof twin.value === "number" && twin.unit === t.operand.unit && t.operand.value !== twin.value ? { ...t, operand: { ...t.operand, difference: t.operand.value - twin.value } } : t;
  });
  return { terms, result: { ...mine.result, difference: mine.result.value - theirs.result.value } };
}
const unused = (columns: TraceColumn[]): TraceOperation => ({ terms: columns.slice(0, -1).map((c, i) => ({ op: i ? "×" : null, operand: operand(c.key, "—") })), result: operand(columns[columns.length - 1].key, "—") });
const costOnly = (): TraceOperation => ({ terms: [{ op: null, operand: operand("billed", "—") }], result: operand("mmbtu", "Request quantities") });

/** One demo steam line: its monthly statements by weight × the facility's heat content, × EPA Table 7. */
export function steamLine(ml: ModelLine, used: ModelRecord[], opts: { gwp: Record<CalcGas, number>; gwpSource: (gas: CalcGas) => string; set: string; share: number; reported: number | null; tolerance: number; incomplete: boolean }): CalculationLine {
  const enthalpy = DEMO_STEAM_HEAT_CONTENT[ml.facility_id ?? ""] ?? null;
  const rows: CalcLineStep1Row[] = used.map((r) => ({
    period_start: r.start, period_end: r.end ?? r.start, document_id: r.documentId, evidence_code: null, file_name: r.fileName, candidate_id: r.candidateId,
    review: r.decision === "edited" ? "edited" : "accepted", quantity: r.quantity, unit: "klb", share_in_period: 1, counted_quantity: r.quantity ?? 0, counted_in_base: r.quantity ?? 0,
  }));
  const mlb = rows.reduce((s, r) => s + r.counted_quantity, 0);
  const mmbtu = enthalpy === null ? 0 : mlb * enthalpy * 0.001;
  const results = (energy: number) => {
    const mass_t = Object.fromEntries(GASES.map((g) => [g, (energy * TABLE7[g] * TO_T[g])])) as Record<CalcGas, number>;
    const gas_co2e_t = Object.fromEntries(GASES.map((g) => [g, mass_t[g] * opts.gwp[g]])) as Record<CalcGas, number>;
    const sum = GASES.reduce((s, g) => s + gas_co2e_t[g], 0);
    return { mass_t, gas_co2e_t, sum_co2e_t: sum, total_co2e_t: sum * opts.share, biogenic_co2_t: 0 };
  };
  const own = results(mmbtu);
  const companyMmbtu = DEMO_STEAM_COMPANY.quantity * DEMO_STEAM_COMPANY.enthalpy * 0.001;
  const theirs = results(companyMmbtu);
  const gasRows = (energy: number, r: ReturnType<typeof results>, company?: ReturnType<typeof results>): CalcLineGas[] => GASES.map((g) => ({
    gas: g, activity: { value: energy, unit: "MMBtu" }, ef: { value: TABLE7[g], unit: UNIT[g].replace("/", " per "), source: `${HUB}, Table 7, row 410` }, unit_conversion: TO_T[g],
    mass_t: r.mass_t[g], gwp: { value: opts.gwp[g], source: opts.gwpSource(g) }, co2e_t: r.gas_co2e_t[g], biogenic: false,
    ...(company ? { company_co2e_t: company.gas_co2e_t[g], difference_to_company_t: r.gas_co2e_t[g] - company.gas_co2e_t[g] } : {}),
  }));
  const steam: CalcLineSteam = {
    facility: ml.label.split(", ").slice(1).join(", ") || ml.label, mass_mlb: mlb, energy_mmbtu: 0, mmbtu,
    enthalpy: enthalpy === null ? null : { value: enthalpy, source: HEAT_CONTENT_SOURCE }, option: "epa_table7", factors: { ...TABLE7 }, gwp_set: opts.set,
    ...(enthalpy === null ? { awaiting: "the steam's net enthalpy" } : {}),
  };
  const reported = opts.reported ?? theirs.total_co2e_t;
  const pct = reported ? ((own.total_co2e_t - reported) / reported) * 100 : null;
  const company: CalculationLine["company"] = {
    activity: { quantity: DEMO_STEAM_COMPANY.quantity, unit: DEMO_STEAM_COMPANY.unit } as CalcQuantity,
    step2: { from_unit: "klb", to_unit: "MMBtu", factor: DEMO_STEAM_COMPANY.enthalpy * 0.001, source: null, result: { quantity: companyMmbtu, unit: "MMBtu" }, distance: null, implied_fuel_economy: null },
    step3: { gases: gasRows(companyMmbtu, theirs) }, results: theirs,
  };
  return {
    key: ml.key, scope: "s2", category: "purchased_energy" as CalculationLine["category"], counts_toward: "steam", level2: ml.level2_label, level2_key: ml.level2, label: ml.label,
    facility_id: ml.facility_id, consolidated_share_pct: opts.share * 100, method: { route: ROUTE, equations: { CO2: "Emissions = MMBtu x EF", CH4: "Emissions = MMBtu x EF", N2O: "Emissions = MMBtu x EF" } },
    step1: { rows, total: { quantity: mlb, unit: "Mlb" } as CalcQuantity },
    step2: { from_unit: "Mlb", to_unit: "MMBtu", factor: enthalpy === null ? 1 : enthalpy * 0.001, source: "net enthalpy (Btu/lb) × 0.001", result: { quantity: mmbtu, unit: "MMBtu" } as CalcQuantity, distance: null, implied_fuel_economy: null },
    step3: { gases: gasRows(mmbtu, own, theirs) },
    results: { ...own, company_total_co2e_t: theirs.total_co2e_t, company_gas_co2e_t: theirs.gas_co2e_t, difference_to_company_t: own.total_co2e_t - theirs.total_co2e_t } as CalculationLine["results"],
    company, reported_total_co2e_t: reported, difference_t: own.total_co2e_t - reported,
    status: pct === null ? "not_reported" : Math.abs(pct) > opts.tolerance ? "above" : "within", difference_pct_of_base: pct,
    inputs_incomplete: opts.incomplete, flags: enthalpy === null ? ["steam_enthalpy_needed"] : [], steam,
  };
}

/** The trace of a demo steam line, from the line's own numbers (the backend's blocks, ids and labels). */
export function steamTrace(line: CalculationLine): LineTrace | null {
  const steam = line.steam;
  if (!steam || steam.enthalpy === null) return null;
  const inputs: Record<string, TraceInput> = {};
  const company = line.company;
  const companyMlb = company ? company.activity.quantity : null;
  const companyH = DEMO_STEAM_COMPANY.enthalpy;
  const why = { reference: "this input cannot be decided for a line", conversion: "the unit conversion comes from the conversion table" };

  // Step 1
  const rows = line.step1.rows.map((r) => ({ id: `${r.document_id}/${r.candidate_id ?? "1"}`, label: [r.file_name ?? r.document_id, r.period_start].filter(Boolean).join(" · "), recomputed: { value: r.counted_quantity, unit: "Mlb", status: r.review, source: { kind: "document" as const, document_id: r.document_id, ...(r.candidate_id ? { candidate_id: r.candidate_id } : {}), ...(r.file_name ? { file_name: r.file_name } : {}) } } }));
  const mass = operation(rows.map((r, i) => ({ op: i ? "+" : null, operand: operand("mass", Number(r.recomputed.value), "Mlb", { input_id: "mass" }) })), "mass", "Mlb", "mass");
  const companyMass = companyMlb !== null ? single("mass", companyMlb, "Mlb", "mass") : undefined;
  inputs.mass = { id: "mass", label: "Steam purchased by weight", symbol: "Mlb", kind: "evidence_sum", required_for: ["location_based"], recomputed: { value: steam.mass_mlb, unit: "Mlb", status: "accepted", source: { kind: "derived", from: rows.map((r) => r.id) } }, rows, decidable: true, ...(companyMlb !== null ? { company: { value: companyMlb, unit: "Mlb", status: "accepted" as const }, difference: steam.mass_mlb - companyMlb } : {}) };
  inputs.energy = { id: "energy", label: "Steam purchased as energy", symbol: "E", kind: "evidence_sum", required_for: ["location_based"], recomputed: { value: 0, unit: "MMBtu", status: "derived", source: { kind: "derived", from: ["no bill of this kind on the line"] } }, rows: [], decidable: true };
  const h = steam.enthalpy.value;
  inputs.net_enthalpy = { id: "net_enthalpy", label: "Net steam enthalpy", symbol: "h", kind: "reviewer_entered", required_for: ["location_based"], recomputed: { value: h, unit: "Btu/lb", status: "accepted", source: { kind: "methodology", field: "steam_heat_content", label: HEAT_CONTENT_SOURCE } }, company: { value: companyH, unit: "Btu/lb", status: "accepted" }, difference: h - companyH, decidable: true };
  inputs.pressure_psig = { id: "pressure_psig", label: "Steam pressure (saturated)", symbol: "p", kind: "reviewer_entered", required_for: [], recomputed: { value: null, unit: "psig", status: "awaiting_review" }, decidable: true };
  inputs.condensate_f = { id: "condensate_f", label: "Condensate returned at", symbol: "T", kind: "reviewer_entered", required_for: [], recomputed: reference(32, "°F", "No condensate return stated: none returned (gross enthalpy)", "Saturated steam and water, IAPWS-IF97"), decidable: true };
  const step1: TraceBlock[] = [
    { id: "input.mass", label: "Steam purchased by weight", columns: [col("mass", "Total", "Mlb", true, { dp: 2 })], recomputed: withDifference(mass, companyMass), ...(companyMass ? { company: companyMass } : {}) },
    { id: "input.net_enthalpy", label: "Net steam enthalpy · heat content entered under Recalculation inputs", columns: [col("h", "Net enthalpy", "Btu/lb", true, { dp: 2 })], recomputed: withDifference(single("h", h, "Btu/lb", "net_enthalpy"), single("h", companyH, "Btu/lb", "net_enthalpy")), company: single("h", companyH, "Btu/lb", "net_enthalpy") },
    { id: "input.pressure", label: "Steam pressure", columns: [col("p", "Gauge pressure", "psig", true)], recomputed: single("p", null, "psig", "pressure_psig") },
    { id: "input.condensate", label: "Condensate return", columns: [col("t", "Returned at", "°F", true)], recomputed: single("t", 32, "°F", "condensate_f") },
  ];

  // Step 2
  inputs.energy_conversion = { id: "energy_conversion", label: "Unit conversion", kind: "constant", required_for: [], recomputed: reference(1, "MMBtu/MMBtu", "1 MMBtu = 1 MMBtu", "fuel_units conversion table"), decidable: false, why_not: why.reference };
  inputs.unit_conversion = { id: "unit_conversion", label: "Unit conversion", kind: "constant", required_for: [], recomputed: reference(0.001, CONVERSION_UNIT, "1 Mlb = 1,000 lb; 1 MMBtu = 1,000,000 Btu: 0.001 MMBtu per Mlb·Btu/lb", "fuel_units conversion table"), decidable: false, why_not: why.conversion };
  const eCols = [col("energy", "Activity data", "MMBtu"), col("factor", "Unit conversion"), col("mmbtu", "Steam energy", "MMBtu", true, { dp: 1 })];
  const mCols = [col("mass", "Activity data", "Mlb"), col("h", "Net enthalpy", "Btu/lb"), col("factor", "Unit conversion"), col("mmbtu", "Steam energy", "MMBtu", true, { dp: 1 })];
  const massTerms = (m: number, hh: number): Term[] => [{ op: null, operand: operand("mass", m, "Mlb", { step_ref: "input.mass" }) }, { op: "×", operand: operand("h", hh, "Btu/lb", { input_id: "net_enthalpy" }) }, { op: "×", operand: operand("factor", 0.001, CONVERSION_UNIT, { input_id: "unit_conversion" }) }];
  const mine = operation(massTerms(steam.mass_mlb, h), "mmbtu", "MMBtu");
  const theirs = companyMlb !== null ? operation(massTerms(companyMlb, companyH), "mmbtu", "MMBtu") : undefined;
  const mmbtu = Number(mine.result.value);
  const sumOp = operation([{ op: null, operand: operand("mmbtu", mmbtu, "MMBtu", { step_ref: "mass" }) }], "mmbtu", "MMBtu");
  const theirSum = theirs ? operation([{ op: null, operand: operand("mmbtu", Number(theirs.result.value), "MMBtu") }], "mmbtu", "MMBtu") : undefined;
  const step2: TraceBlock[] = [
    { id: "energy", label: "Energy", columns: eCols, recomputed: unused(eCols), tag: "not_used_for_this_line" },
    { id: "mass", label: "Mass", columns: mCols, recomputed: withDifference(mine, theirs), ...(theirs ? { company: theirs } : {}), tag: "detected_from_evidence" },
    { id: "cost_only", label: "Cost only · not usable", columns: [col("billed", "Amount billed", "$"), col("mmbtu", "Steam energy", "MMBtu", true)], recomputed: costOnly(), company: costOnly(), tag: "not_used_for_this_line" },
    { id: "mmbtu", label: "Steam energy", columns: [col("mmbtu", "Steam energy", "MMBtu", true, { dp: 1 })], recomputed: withDifference(sumOp, theirSum), ...(theirSum ? { company: theirSum } : {}) },
  ];

  // Step 3: the four options; EPA Table 7 is used (it carries no tag when used), the others are not
  const step3: TraceBlock[] = [];
  for (const o of OPTIONS) {
    for (const g of GASES) {
      const id = `${o.prefix}${g}`;
      const tag = o.id === "epa_table7" ? undefined : ("not_used_for_this_line" as const);
      if (o.id === "fuel_and_efficiency") {
        inputs[id] = { id, label: `Boiler fuel ${GAS_LABEL[g]} factor`, symbol: "EF", kind: "reference", required_for: [o.id], recomputed: reference(NATURAL_GAS[g], UNIT[g], `${HUB}, Table 1, row 38`), decidable: true };
        step3.push({ id: `ef.${o.id}.${g}`, label: `${o.label} · ${GAS_LABEL[g]}`, tag: "not_used_for_this_line", columns: [col("fuel_ef", `Boiler fuel ${GAS_LABEL[g]} factor`, UNIT[g]), col("share", "Thermal efficiency"), col("ef", "Emission factor", UNIT[g], true, { sig: 6 })],
          recomputed: { terms: [{ op: null, operand: operand("fuel_ef", NATURAL_GAS[g], UNIT[g], { input_id: id }) }, { op: "÷", operand: operand("share", null, undefined, { input_id: "efficiency" }) }], result: operand("ef", null, UNIT[g]) } });
        continue;
      }
      const value = o.id === "epa_table7" ? TABLE7[g] : null;
      inputs[id] = o.id === "epa_table7"
        ? { id, label: `EPA Table 7 ${GAS_LABEL[g]} factor`, symbol: "EF", kind: "reference", required_for: [o.id], recomputed: reference(TABLE7[g], UNIT[g], `${HUB}, Table 7, row 410`), decidable: false, why_not: why.reference }
        : { id, label: `${o.label} ${GAS_LABEL[g]} factor`, symbol: "EF", kind: "reviewer_entered", required_for: [o.id], recomputed: { value: null, unit: UNIT[g], status: "awaiting_review" }, decidable: true };
      const op = single("ef", value, UNIT[g], id);
      step3.push({ id: `ef.${o.id}.${g}`, label: `${o.label} · ${GAS_LABEL[g]}`, columns: [col("ef", o.what, UNIT[g], true, { sig: 6 })], recomputed: op, ...(o.id === "epa_table7" ? { company: op } : {}), ...(tag ? { tag } : {}) });
    }
  }
  inputs.efficiency = { id: "efficiency", label: "Boiler thermal efficiency", symbol: "η", kind: "reviewer_entered", required_for: ["fuel_and_efficiency"], recomputed: { value: null, unit: "%", status: "awaiting_review" }, decidable: true };

  // Step 4 and results
  const step4: TraceBlock[] = [];
  const sum: Term[] = [];
  const theirSumTerms: Term[] = [];
  for (const g of GASES) {
    const gas = line.step3.gases.find((r) => r.gas === g)!;
    inputs[`to_t.${g}`] = { id: `to_t.${g}`, label: "Unit conversion", kind: "constant", required_for: [], recomputed: reference(TO_T[g], `t/${UNIT[g].split("/")[0]}`, "1 t = 1,000 kg = 1,000,000 g", "fuel_units conversion table"), decidable: false, why_not: why.reference };
    inputs[`gwp.${g}`] = { id: `gwp.${g}`, label: `${GAS_LABEL[g]} GWP`, symbol: "GWP", kind: "reference", required_for: [], recomputed: reference(gas.gwp.value, "t CO2e/t", gas.gwp.source), decidable: false, why_not: "the GWP is chosen for the whole engagement on the Methodology page" };
    const emitted = (energy: number): Term[] => [{ op: null, operand: operand("mmbtu", energy, "MMBtu", { step_ref: "mmbtu" }) }, { op: "×", operand: operand("ef", TABLE7[g], UNIT[g], { input_id: `table7.${g}` }) }, { op: "×", operand: operand("to_t", TO_T[g], `t/${UNIT[g].split("/")[0]}`, { input_id: `to_t.${g}` }) }];
    const m = operation(emitted(mmbtu), "mass", "t");
    const mc = theirs ? operation(emitted(Number(theirs.result.value)), "mass", "t") : undefined;
    const co2e = (t: number): Term[] => [{ op: null, operand: operand("mass", t, "t", { step_ref: `emissions.${g}` }) }, { op: "×", operand: operand("gwp", gas.gwp.value, "t CO2e/t", { input_id: `gwp.${g}` }) }];
    const c = operation(co2e(Number(m.result.value)), "co2e", "t CO2e");
    const cc = mc ? operation(co2e(Number(mc.result.value)), "co2e", "t CO2e") : undefined;
    sum.push({ op: sum.length ? "+" : null, operand: operand("co2e", Number(c.result.value), "t CO2e", { step_ref: `gwp.${g}` }) });
    if (cc) theirSumTerms.push({ op: theirSumTerms.length ? "+" : null, operand: operand("co2e", Number(cc.result.value), "t CO2e", { step_ref: `gwp.${g}` }) });
    step4.push(
      { id: `emissions.${g}`, label: GAS_LABEL[g], columns: [col("mmbtu", "Steam energy", "MMBtu"), col("ef", "Emission factor", UNIT[g]), col("to_t", "Unit conversion"), col("mass", "Mass", "t", true, { sig: 6 })], recomputed: withDifference(m, mc), ...(mc ? { company: mc } : {}) },
      { id: `gwp.${g}`, label: `${GAS_LABEL[g]} in CO₂e`, columns: [col("mass", "Mass", "t"), col("gwp", "GWP"), col("co2e", "CO₂e", "t CO2e", true, { dp: 2 })], recomputed: withDifference(c, cc), ...(cc ? { company: cc } : {}) },
    );
  }
  const share = line.consolidated_share_pct;
  inputs.share = { id: "share", label: "Consolidated share", symbol: "share", kind: "methodology", required_for: [], recomputed: { value: share, unit: "%", status: share !== 100 ? "accepted" : "derived", source: { kind: "methodology", field: "consolidated_share", label: "Consolidated share" } }, decidable: false, why_not: "the consolidated share is set under Recalculation inputs" };
  const summed = operation(sum, "sum", "t CO2e");
  const theirSummed = theirSumTerms.length === 3 ? operation(theirSumTerms, "sum", "t CO2e") : undefined;
  const totalTerms = (v: number): Term[] => [{ op: null, operand: operand("sum", v, "t CO2e", { step_ref: "results.sum" }) }, { op: "×", operand: operand("share", share / 100, undefined, { input_id: "share" }) }];
  const total = operation(totalTerms(Number(summed.result.value)), "total", "t CO2e");
  const theirTotal = theirSummed ? operation(totalTerms(Number(theirSummed.result.value)), "total", "t CO2e") : undefined;
  const steps: TraceStep[] = [
    { id: "inputs", n: 1, title: "Step 1 · Inputs", note: "The reviewed steam bills, the enthalpy and the steam conditions", blocks: step1 },
    { id: "conversion", n: 2, title: "Step 2 · Conversion", note: "To MMBtu: energy as billed, or mass × net enthalpy", blocks: step2 },
    { id: "factor", n: 3, title: "Step 3 · Emission factor", note: TABLE7_NOTE, blocks: step3 },
    { id: "emissions", n: 4, title: "Step 4 · Emissions by gas", note: "MMBtu × emission factor, then × GWP", blocks: step4 },
    { id: "results", n: null, title: "Results", blocks: [
      { id: "results.sum", label: "Gases added", columns: [col("co2e", "CO₂e", "t CO2e"), col("sum", "Emissions", "t CO2e", true, { dp: 2 })], recomputed: withDifference(summed, theirSummed), ...(theirSummed ? { company: theirSummed } : {}) },
      { id: "results.total", label: "Line total", columns: [col("sum", "Emissions", "t CO2e"), col("share", "Consolidated share"), col("total", "Total", "t CO2e", true, { dp: 2 })], recomputed: withDifference(total, theirTotal), ...(theirTotal ? { company: theirTotal } : {}) },
    ] },
  ];
  const recomputed = Number(total.result.value);
  const theirValue = theirTotal ? Number(theirTotal.result.value) : null;
  return {
    trace_version: 1, line_key: line.key, panel: "steam", state: "complete", blocking: [],
    choices: [
      { id: "method", label: "Calculation method", chosen: "location_based", chosen_by: "default", options: [{ id: "location_based", label: "Location-based", equation: EQUATION, available: true, required_inputs: [] }] },
      { id: "ef_option", label: "Emission factor", chosen: "epa_table7", chosen_by: "default", company: "epa_table7", options: OPTIONS.map((o) => ({
        id: o.id, label: o.label, equation: "Emissions = MMBtu × EF", available: true,
        required_inputs: o.id === "fuel_and_efficiency" ? ["efficiency"] : o.id === "epa_table7" ? [] : GASES.map((g) => `${o.prefix}${g}`),
        ...(o.id === "epa_table7" ? {} : { detection: "not_used_for_this_line" as const }),
      })) },
    ],
    inputs, steps, method_mismatch: false, flags: [...line.flags],
    result: { unit: "t CO2e", company: theirValue, recomputed, difference: theirValue === null ? null : recomputed - theirValue },
  };
}
