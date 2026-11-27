/**
 * Demo fugitive lines (refrigerants, simplified material balance) and their traces, in the backend's shapes
 * (backend/app/services/calc_trace/fugitive.py). One line per refrigerant and facility: the demo's R-404A service
 * logs are service records (P_S) in kg. The blend GWP from EPA Table 12 counts; the split by component is shown
 * beside it for reference (AR5 only: the reference data holds no AR4 or AR6 component GWPs).
 */
import type { CalcLineSmb, CalcLineStep1Row, CalcQuantity, CalculationLine } from "../../api/recalculation";
import type { LineTrace, TraceBlock, TraceColumn, TraceInput, TraceOpSymbol, TraceOperand, TraceOperation, TraceSide, TraceStep } from "../../api/calcTrace";
import type { ModelLine, ModelRecord } from "../linesModel";
import { type DemoDecided, screeningChoices, screeningInputs, screeningSteps, screeningUnits } from "./fugitiveScreening";
import { materialInputs, materialSteps } from "./fugitiveMaterialBalance";

const HUB = "EPA GHG Emission Factors Hub 2025";
export const TERMS = ["P_N", "C_N", "P_S", "C_D", "R_D"] as const;
type TermId = (typeof TERMS)[number];
const TERM_LABEL: Record<TermId, string> = {
  P_N: "New equipment charge", C_N: "New equipment capacity", P_S: "Added during service", C_D: "Retired equipment capacity", R_D: "Recovered from retired equipment",
};
const TERM_OP: Record<TermId, TraceOpSymbol | null> = { P_N: null, C_N: "−", P_S: "+", C_D: "+", R_D: "−" };
const EQUATION = "Emitted = (P_N − C_N) + P_S + (C_D − R_D)";
const ROUTE = "Simplified material balance: (P_N − C_N) + P_S + (C_D − R_D), to metric tons, × GWP";
const T_PER: Record<string, number> = { kg: 0.001, lb: 0.00045359237 };
const GWP_UNIT = "t CO2e/t";
/** EPA Hub Table 12, row 567, and its components' Table 11 AR5 GWPs. */
const R404A = { row: 567, composition: "44% HFC-125 , 4% HFC-134a , 52% HFC-143a", components: [
  { name: "HFC-125", share: 0.44, gwp: 3170, row: 530 },
  { name: "HFC-134a", share: 0.04, gwp: 1300, row: 532 },
  { name: "HFC-143a", share: 0.52, gwp: 4800, row: 534 },
] };

type Term = { op: TraceOpSymbol | null; operand: TraceOperand };
const operand = (column: string, value: number | null, unit?: string, extra: Partial<TraceOperand> = {}): TraceOperand => ({ column, value, ...(unit ? { unit } : {}), ...extra });
function evaluate(terms: Term[]): number {
  let total = 0;
  terms.forEach((t, i) => {
    const v = Number(t.operand.value);
    if (i === 0) total = v;
    else if (t.op === "×") total *= v;
    else if (t.op === "+") total += v;
    else if (t.op === "−") total -= v;
    else total /= v;
  });
  return total;
}
/** An operand still awaited (the screening's) leaves the result awaited: null, never a number. */
const operation = (terms: Term[], column: string, unit: string | undefined): TraceOperation => ({ terms, result: operand(column, terms.some((t) => t.operand.value === null) ? null : evaluate(terms), unit) });
const num = (v: unknown): number | null => (typeof v === "number" ? v : null);
const single = (column: string, value: number, unit: string, inputId: string): TraceOperation => ({ terms: [{ op: null, operand: operand(column, value, unit, { input_id: inputId }) }], result: operand(column, value, unit, { input_id: inputId }) });
const col = (key: string, label: string, unit: string | undefined, isResult = false, display: TraceColumn["display"] = {}): TraceColumn => ({ key, label, ...(unit ? { unit } : {}), is_result: isResult, display });
const side = (value: number | null, unit: string | undefined, status: TraceSide["status"], citation?: string): TraceSide => ({ value, ...(unit ? { unit } : {}), status, ...(citation ? { source: { kind: "reference", citation } } : {}) });
function withDifference(mine: TraceOperation, theirs: TraceOperation | undefined): TraceOperation {
  if (!theirs || typeof mine.result.value !== "number" || typeof theirs.result.value !== "number" || mine.result.unit !== theirs.result.unit) return mine;
  return { ...mine, result: { ...mine.result, difference: mine.result.value - theirs.result.value } };
}
const gwpCitation = (set: string) => `${HUB}, Table 12, row ${R404A.row} (IPCC ${set})`;

/** One fugitive line of the demo: its service records summed as P_S, to metric tons, × the Table 12 GWP. */
export function fugitiveLine(ml: ModelLine, used: ModelRecord[], opts: { gwp: number; set: string; share: number; company: CalcQuantity | null; tolerance: number; reported: number | null; incomplete: boolean }): CalculationLine {
  const unit = used[0]?.unit ?? "kg";
  const factor = T_PER[unit] ?? 0.001;
  const rows: CalcLineStep1Row[] = used.map((r) => ({
    period_start: r.start, period_end: r.end ?? r.start, document_id: r.documentId, evidence_code: null, file_name: r.fileName, candidate_id: r.candidateId,
    review: r.decision === "edited" ? "edited" : "accepted", quantity: r.quantity, unit, share_in_period: 1, counted_quantity: r.quantity ?? 0, counted_in_base: r.quantity ?? 0,
  }));
  const terms = { P_N: 0, C_N: 0, P_S: used.reduce((s, r) => s + (r.quantity ?? 0), 0), C_D: 0, R_D: 0 };
  const emitted = terms.P_N - terms.C_N + terms.P_S + terms.C_D - terms.R_D;
  const emittedT = emitted * factor;
  const co2e = emittedT * opts.gwp;
  const total = co2e * opts.share;
  const gas = ml.level2_label;
  const smb: CalcLineSmb = { gas, unit, terms, emitted, factor, emitted_t: emittedT, gwp: { value: opts.gwp, source: gwpCitation(opts.set) }, gwp_set: opts.set };
  const companyT = opts.company && T_PER[opts.company.unit] !== undefined ? opts.company.quantity * T_PER[opts.company.unit] : null;
  const companyTotal = companyT === null ? null : companyT * opts.gwp * opts.share;
  const reported = opts.reported;
  const pct = reported ? ((total - reported) / reported) * 100 : null;
  return {
    key: ml.key, scope: "s1", category: "fugitive", counts_toward: "fugitive", level2: gas, level2_key: ml.level2, label: ml.label,
    facility_id: ml.facility_id, consolidated_share_pct: opts.share * 100, method: { route: ROUTE, equations: {} },
    step1: { rows, total: { quantity: emitted, unit } },
    step2: { from_unit: unit, to_unit: "t", factor, source: "fuel_units conversion table", result: { quantity: emittedT, unit: "t" }, distance: null, implied_fuel_economy: null },
    step3: { gases: [] },
    results: {
      mass_t: { [gas]: emittedT }, gas_co2e_t: { [gas]: co2e }, sum_co2e_t: co2e, total_co2e_t: total, biogenic_co2_t: 0,
      ...(companyTotal !== null ? { company_total_co2e_t: companyTotal, difference_to_company_t: total - companyTotal } : {}),
    } as unknown as CalculationLine["results"],
    company: companyT !== null && opts.company
      ? { activity: opts.company, step2: { from_unit: opts.company.unit, to_unit: "t", factor: T_PER[opts.company.unit], source: null, result: { quantity: companyT, unit: "t" }, distance: null, implied_fuel_economy: null }, step3: { gases: [] }, results: { mass_t: { [gas]: companyT }, gas_co2e_t: { [gas]: companyT * opts.gwp }, sum_co2e_t: companyT * opts.gwp, total_co2e_t: companyTotal ?? 0, biogenic_co2_t: 0 } as unknown as CalculationLine["results"] }
      : null,
    reported_total_co2e_t: reported, difference_t: reported === null ? null : total - reported,
    status: reported === null || pct === null ? "not_reported" : Math.abs(pct) > opts.tolerance ? "above" : "within",
    difference_pct_of_base: pct, inputs_incomplete: opts.incomplete, flags: emitted < 0 ? ["negative_refrigerant_emissions"] : [], smb,
  };
}

/** The trace of a demo fugitive line, from the line's own numbers. */
export function fugitiveTrace(line: CalculationLine, decided: DemoDecided = { choices: {}, inputs: {} }): LineTrace | null {
  const smb = line.smb;
  if (!smb || !smb.gwp) return null;
  const { unit, gas, factor } = smb;
  const inputs: Record<string, TraceInput> = {};
  const step1: TraceBlock[] = TERMS.map((term) => {
    const rows = term === "P_S" ? line.step1.rows.map((r) => ({ id: `${r.document_id}/${r.candidate_id ?? "1"}`, label: [r.file_name ?? r.document_id, r.period_start].filter(Boolean).join(" · "), recomputed: { ...side(r.counted_quantity, unit, r.review), source: { kind: "document" as const, document_id: r.document_id, ...(r.candidate_id ? { candidate_id: r.candidate_id } : {}), ...(r.file_name ? { file_name: r.file_name } : {}) } } })) : [];
    const op = rows.length
      ? operation(rows.map((r, i) => ({ op: i ? "+" : null, operand: operand("amount", Number(r.recomputed.value), unit, { input_id: term }) })), "amount", unit)
      : single("amount", 0, unit, term);
    op.result.input_id = term;
    inputs[term] = { id: term, label: TERM_LABEL[term], symbol: term, kind: "evidence_sum", required_for: ["smb"], recomputed: side(Number(op.result.value), unit, rows.length ? "accepted" : "derived"), rows, decidable: true };
    return { id: `term.${term}`, label: `${TERM_LABEL[term]} · ${term}`, columns: [col("amount", "Total", unit, true, { sig: 6 })], recomputed: op };
  });
  const balance = operation(TERMS.map((t) => ({ op: TERM_OP[t], operand: operand(t, smb.terms[t], unit, { step_ref: `term.${t}` }) })), "emitted", unit);
  // The screening method (C5): its inputs are on every trace; its working once a reviewer picks it.
  const units = screeningUnits(line.step1.rows);
  if (units.length) Object.assign(inputs, screeningInputs(units, unit, decided, gas));
  // The material balance (C6): its six terms are on every trace too; its working once a reviewer picks it.
  Object.assign(inputs, materialInputs(unit, decided));
  const screen = units.length && decided.choices.method === "screening" ? screeningSteps(units, unit, { P_N: smb.terms.P_N, C_D: smb.terms.C_D }, inputs, decided, gas) : decided.choices.method === "material_balance" ? materialSteps(unit, decided) : null;
  const emittedValue = screen ? screen.emitted : num(balance.result.value);
  inputs.unit_conversion = { id: "unit_conversion", label: "Unit conversion", kind: "constant", required_for: [], recomputed: side(factor, `t/${unit}`, "reference", "fuel_units conversion table: 1 lb = 0.45359237 kg exactly; 1 t = 1,000 kg"), decidable: false, why_not: "the unit conversion comes from the conversion table" };
  const toT = operation([{ op: null, operand: operand("emitted", emittedValue, unit, { step_ref: "emitted" }) }, { op: "×", operand: operand("factor", factor, `t/${unit}`, { input_id: "unit_conversion" }) }], "emitted_t", "t");
  const companyT = line.company ? line.company.step2.result.quantity : null;
  const companyToT = line.company ? operation([{ op: null, operand: operand("emitted", line.company.activity.quantity, line.company.activity.unit, { step_ref: "emitted" }) }, { op: "×", operand: operand("factor", line.company.step2.factor, `t/${line.company.activity.unit}`, { input_id: "unit_conversion" }) }], "emitted_t", "t") : undefined;
  const gwpId = `gwp.${gas}`;
  const why = "the GWP is chosen for the whole engagement on the Methodology page";
  inputs[gwpId] = { id: gwpId, label: `${gas} GWP (blend)`, symbol: "GWP", kind: "reference", required_for: ["smb"], recomputed: side(smb.gwp.value, GWP_UNIT, "reference", smb.gwp.source ?? undefined), decidable: false, why_not: why };
  const gwpTerms = (t: number | null): Term[] => [{ op: null, operand: operand("emitted_t", t, "t", { step_ref: "emitted_t" }) }, { op: "×", operand: operand("gwp", smb.gwp?.value ?? null, GWP_UNIT, { input_id: gwpId }) }];
  const gwpCols = [col("emitted_t", "Emitted", "t"), col("gwp", "GWP", GWP_UNIT), col("co2e", "CO₂e", "t CO2e", true, { dp: 2 })];
  const co2e = operation(gwpTerms(num(toT.result.value)), "co2e", "t CO2e");
  const companyCo2e = companyT !== null ? operation(gwpTerms(companyT), "co2e", "t CO2e") : undefined;
  const step3: TraceBlock[] = [{ id: "co2e", label: `${gas} · blend GWP (counts)`, columns: gwpCols, recomputed: withDifference(co2e, companyCo2e), ...(companyCo2e ? { company: companyCo2e } : {}) }];
  const ar5 = smb.gwp_set === "AR5" && gas === "R-404A";
  let note = `The ${gas} GWP (${smb.gwp.value.toLocaleString("en-US")}, EPA Table 12) counts in the totals. The split by component is not shown: Sustentra's reference data has no ${smb.gwp_set} GWP for its components.`;
  if (ar5) {
    const sum: Term[] = [];
    for (const c of R404A.components) {
      inputs[`share.${c.name}`] = { id: `share.${c.name}`, label: `${c.name} share of ${gas}`, symbol: "share", kind: "reference", required_for: [], recomputed: side(c.share, undefined, "reference", `${HUB}, Table 12, row ${R404A.row}: ${R404A.composition}`), decidable: false, why_not: "a blend's composition comes from the reference data" };
      inputs[`gwp.${c.name}`] = { id: `gwp.${c.name}`, label: `${c.name} GWP`, symbol: "GWP", kind: "reference", required_for: [], recomputed: side(c.gwp, GWP_UNIT, "reference", `${HUB}, Table 11, row ${c.row} (IPCC AR5)`), decidable: false, why_not: why };
      const terms = (t: number | null): Term[] => [{ op: null, operand: operand("emitted_t", t, "t", { step_ref: "emitted_t" }) }, { op: "×", operand: operand("share", c.share, undefined, { input_id: `share.${c.name}` }) }, { op: "×", operand: operand("gwp", c.gwp, GWP_UNIT, { input_id: `gwp.${c.name}` }) }];
      const mine = operation(terms(num(toT.result.value)), "co2e", "t CO2e");
      const theirs = companyT !== null ? operation(terms(companyT), "co2e", "t CO2e") : undefined;
      sum.push({ op: sum.length ? "+" : null, operand: operand("co2e", num(mine.result.value), "t CO2e", { step_ref: `component.${c.name}` }) });
      step3.push({ id: `component.${c.name}`, label: `${c.name} · ${c.share * 100}% of the blend`, columns: [col("emitted_t", "Emitted", "t"), col("share", "Share of blend", undefined), col("gwp", "GWP", GWP_UNIT), col("co2e", "CO₂e", "t CO2e", true, { dp: 2 })], recomputed: withDifference(mine, theirs), ...(theirs ? { company: theirs } : {}) });
    }
    step3.push({ id: "components.sum", label: "Components added", columns: [col("co2e", "CO₂e", "t CO2e"), col("sum", "Sum", "t CO2e", true, { dp: 2 })], recomputed: operation(sum, "sum", "t CO2e") });
    const effective = R404A.components.reduce((s, c) => s + c.share * c.gwp, 0);
    note = `The ${gas} GWP (${smb.gwp.value.toLocaleString("en-US")}, EPA Table 12) counts in the totals. The split by component (${Number(effective.toPrecision(6)).toLocaleString("en-US")}: each component's share × GWP) is shown for reference.`;
  }
  const share = line.consolidated_share_pct;
  inputs.share = { id: "share", label: "Consolidated share", symbol: "share", kind: "methodology", required_for: [], recomputed: { ...side(share, "%", share !== 100 ? "accepted" : "derived"), source: { kind: "methodology", field: "consolidated_share", label: "Consolidated share" } }, decidable: false, why_not: "the consolidated share is set under Recalculation inputs" };
  const totalTerms = (v: number | null): Term[] => [{ op: null, operand: operand("co2e", v, "t CO2e", { step_ref: "co2e" }) }, { op: "×", operand: operand("share", share / 100, undefined, { input_id: "share" }) }];
  const total = operation(totalTerms(num(co2e.result.value)), "total", "t CO2e");
  const companyTotal = companyCo2e ? operation(totalTerms(Number(companyCo2e.result.value)), "total", "t CO2e") : undefined;
  const steps: TraceStep[] = [
    { id: "inputs", n: 1, title: "Step 1 · Inputs", note: screen ? screen.note : "The reviewed service records, added up per term", blocks: screen ? screen.step1 : step1 },
    { id: "emitted", n: 2, title: "Step 2 · Refrigerant emitted", note: `${screen ? screen.equation : EQUATION}, then to metric tons`, blocks: [
      ...(screen ? screen.step2 : [{ id: "emitted", label: "Refrigerant emitted", columns: [...TERMS.map((t) => col(t, t, unit)), col("emitted", "Emitted", unit, true, { sig: 6 })], recomputed: balance }]),
      { id: "emitted_t", label: "Unit conversion", columns: [col("emitted", line.company ? "Emitted (as reported)" : "Emitted", unit), col("factor", "Unit conversion", undefined), col("emitted_t", "Emitted", "t", true, { sig: 6 })], recomputed: withDifference(toT, companyToT), ...(companyToT ? { company: companyToT } : {}) },
    ] },
    { id: "gwp", n: 3, title: "Step 3 · Emissions by gas", note, blocks: step3 },
    { id: "results", n: null, title: "Results", blocks: [{ id: "results.total", label: "Line total", columns: [col("co2e", "CO₂e", "t CO2e"), col("share", "Consolidated share", undefined), col("total", "Total", "t CO2e", true, { dp: 2 })], recomputed: withDifference(total, companyTotal), ...(companyTotal ? { company: companyTotal } : {}) }] },
  ];
  const recomputed = num(total.result.value);
  const company = companyTotal ? Number(companyTotal.result.value) : null;
  const choices = screeningChoices(units.length > 0, gas);
  for (const c of choices) {
    const picked = decided.choices[c.id];
    if (picked && c.options.some((o) => o.id === picked && o.available)) Object.assign(c, { chosen: picked, chosen_by: "reviewer" });
  }
  const blocking = screen?.blocking ?? [];
  return {
    trace_version: 1, line_key: line.key, panel: "fugitive", state: blocking.length ? "blocked" : "complete", blocking,
    choices, inputs, steps, method_mismatch: false,
    flags: screen ? [...line.flags.filter((f) => f !== "negative_refrigerant_emissions"), ...(emittedValue !== null && emittedValue < 0 ? ["negative_refrigerant_emissions"] : [])] : [...line.flags],
    result: { unit: "t CO2e", company, recomputed, difference: company === null || recomputed === null ? null : recomputed - company },
  };
}
