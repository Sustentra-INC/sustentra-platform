/**
 * Demo trace of a calculation line (stationary, mobile, electricity): the line the demo's
 * recalculation already computed, restated step by step in the backend's trace shape
 * (api/calcTrace.ts). It reads the line's own numbers, so every total agrees with the lines table
 * and the Results page; each operation's result is re-evaluated from its terms.
 */
import type { CalcGas, CalcLineGas, CalculationLine } from "../../api/recalculation";
import type {
  LineTrace,
  TraceBlock,
  TraceColumn,
  TraceInput,
  TraceOpSymbol,
  TraceOperand,
  TraceOperation,
  TraceSide,
  TraceSourceRef,
  TraceStep,
} from "../../api/calcTrace";

const GASES: CalcGas[] = ["CO2", "CH4", "N2O"];
const GAS_LABEL: Record<CalcGas, string> = { CO2: "CO₂", CH4: "CH₄", N2O: "N₂O" };

type Term = { op: TraceOpSymbol | null; operand: TraceOperand };

const operand = (column: string, value: number, unit: string | undefined, extra: Partial<TraceOperand> = {}): TraceOperand => ({ column, value, ...(unit ? { unit } : {}), ...extra });

/** Left to right, as the backend's evaluator does. */
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

function operation(terms: Term[], resultColumn: string, unit: string | undefined, extra: Partial<TraceOperand> = {}): TraceOperation {
  return { terms, result: operand(resultColumn, evaluate(terms), unit, extra) };
}

/** The recomputed operation with each operand's difference to the company's, where both are numbers. */
function withDifferences(recomputed: TraceOperation, company: TraceOperation | undefined): TraceOperation {
  if (!company) return recomputed;
  const diff = (r: TraceOperand, c: TraceOperand | undefined): TraceOperand =>
    typeof r.value === "number" && typeof c?.value === "number" ? { ...r, difference: r.value - c.value } : r;
  return {
    // Terms pair by position only when both sides have the same shape (twelve bills against one figure do not).
    terms: recomputed.terms.length === company.terms.length ? recomputed.terms.map((t, i) => ({ ...t, operand: diff(t.operand, company.terms[i]?.operand) })) : recomputed.terms,
    result: diff(recomputed.result, company.result),
  };
}

const col = (key: string, label: string, unit: string | undefined, is_result: boolean, display: TraceColumn["display"] = {}): TraceColumn => ({ key, label, ...(unit ? { unit } : {}), is_result, display });

const tonnesPer = (efUnit: string) => (/^kg/.test(efUnit) ? "t/kg" : /^g\b/.test(efUnit) ? "t/g" : /^lb/.test(efUnit) ? "t/lb" : "t");

const ref = (citation: string): TraceSourceRef => ({ kind: "reference", citation });
const side = (value: number, unit: string, status: TraceSide["status"], source?: TraceSourceRef): TraceSide => ({ value, unit, status, ...(source ? { source } : {}) });

function period(start: string | null, end: string | null, fallback: string): string {
  if (!start || !end) return start ?? end ?? fallback;
  return start === end ? start : `${start} to ${end}`;
}

const SET_ELSEWHERE: Record<string, string> = {
  unit_conversion: "the unit conversion comes from the conversion table",
  share: "the consolidated share is set under Recalculation inputs",
  grid_region: "the grid region is set under Recalculation inputs or in Setup",
};

/** `decidable` and `why_not` on each input, by the backend's rule (calc_trace/decisions.py `not_decidable`). */
function markDecidable(inputs: Record<string, TraceInput>): void {
  for (const [id, input] of Object.entries(inputs)) {
    const why = SET_ELSEWHERE[id] ?? (id.startsWith("gwp.") ? "the GWP is chosen for the whole engagement on the Methodology page" : id === "activity.total" || id === "distance" || id.startsWith("ef.") ? null : "this input cannot be decided for a line");
    input.decidable = why === null;
    if (why !== null) input.why_not = why;
  }
}

export function traceFromLine(line: CalculationLine): LineTrace {
  const co = line.company;
  const inputs: Record<string, TraceInput> = {};
  const total = line.step1.total;

  // Step 1: the summed activity, with its parts.
  inputs["activity.total"] = {
    id: "activity.total",
    label: "Activity data",
    kind: "evidence_sum",
    required_for: [],
    ...(co ? { company: side(co.activity.quantity, co.activity.unit, "accepted") } : {}),
    recomputed: side(total.quantity, total.unit, "derived", { kind: "derived", from: line.step1.rows.map((r) => r.candidate_id ?? r.document_id) }),
    ...(co ? { difference: total.quantity - co.activity.quantity } : {}),
    rows: line.step1.rows.map((r, i) => ({
      id: `${r.document_id}:${i}`,
      label: period(r.period_start, r.period_end, r.file_name ?? r.document_id),
      recomputed: {
        value: r.counted_in_base ?? r.counted_quantity,
        unit: r.counted_in_base === null ? r.unit : total.unit,
        status: r.review,
        source: { kind: "document", document_id: r.document_id, ...(r.candidate_id ? { candidate_id: r.candidate_id } : {}), file_name: r.file_name ?? r.document_id },
      },
    })),
  };
  const actCol = [col("activity", "Activity data", total.unit, true, { dp: 2 })];
  const act = (a: { quantity: number; unit: string }, id?: string) =>
    operation([{ op: null, operand: operand("activity", a.quantity, a.unit, { input_id: id }) }], "activity", a.unit, { input_id: id });
  // The recomputed side is one term per evidence record, as the backend builds it; the company gives one figure.
  const parts = line.step1.rows.filter((r) => r.counted_in_base !== null);
  const sum = (): TraceOperation =>
    parts.length > 1
      ? operation(
          parts.map((r, i) => ({ op: i === 0 ? null : ("+" as TraceOpSymbol), operand: operand("activity", r.counted_in_base ?? 0, total.unit, { input_id: "activity.total" }) })),
          "activity",
          total.unit,
          { input_id: "activity.total" },
        )
      : act(total, "activity.total");
  const step1: TraceStep = {
    id: "activity",
    n: 1,
    title: "Step 1 · Activity data",
    note: "Sum of accepted evidence values for this line",
    blocks: [
      {
        id: "activity",
        label: "Annual activity data",
        columns: actCol,
        ...(co ? { company: act(co.activity, "activity.total") } : {}),
        recomputed: withDifferences(sum(), co ? act(co.activity) : undefined),
      },
    ],
  };

  // Step 2: conversion to the factor's unit (and the on-road distance, an entered input).
  const s2 = line.step2;
  const convUnit = `${s2.to_unit}/${s2.from_unit}`;
  if (s2.factor !== 1) {
    inputs.unit_conversion = { id: "unit_conversion", label: "Unit conversion", kind: "constant", required_for: [], recomputed: side(s2.factor, convUnit, "reference", ref(s2.source ?? "Unit conversion table.")) };
    if (co) inputs.unit_conversion.company = side(co.step2.factor, convUnit, "reference", ref(co.step2.source ?? "Unit conversion table."));
  }
  const conv = (a: { quantity: number; unit: string }, s: typeof s2): TraceOperation =>
    operation(
      [
        { op: null, operand: operand("activity", a.quantity, a.unit, { step_ref: "activity" }) },
        { op: "×", operand: operand("factor", s.factor, s.factor === 1 ? undefined : convUnit, s.factor === 1 ? {} : { input_id: "unit_conversion" }) },
      ],
      "converted",
      s.to_unit,
    );
  const step2: TraceStep = {
    id: "conversion",
    n: 2,
    title: "Step 2 · Unit conversion",
    note: "Shared by all three gases",
    blocks: [
      {
        id: "conversion",
        label: "Conversion",
        columns: [col("activity", "Activity data", total.unit, false), col("factor", "Unit conversion", convUnit, false), col("converted", "Converted quantity", s2.to_unit, true, { dp: 2 })],
        ...(co ? { company: conv(co.activity, co.step2) } : {}),
        recomputed: withDifferences(conv(total, s2), co ? conv(co.activity, co.step2) : undefined),
      },
    ],
  };
  if (s2.distance) {
    inputs.distance = {
      id: "distance",
      label: "Distance",
      kind: "reviewer_entered",
      required_for: [],
      recomputed: side(s2.distance.quantity, s2.distance.unit, "accepted", { kind: "entered", by: s2.distance.source }),
    };
  }

  // Step 3: mass per gas. Step 4: CO2e per gas.
  const mass: TraceBlock[] = [];
  const gwp: TraceBlock[] = [];
  const recomputedCo2e: Partial<Record<CalcGas, number>> = {};
  const companyCo2e: Partial<Record<CalcGas, number>> = {};
  const pair = (gas: CalcGas): CalcLineGas | undefined => co?.step3.gases.find((g) => g.gas === gas);
  for (const g of line.step3.gases) {
    const label = GAS_LABEL[g.gas];
    const cg = pair(g.gas);
    inputs[`ef.${g.gas}`] = {
      id: `ef.${g.gas}`,
      label: `${label} emission factor`,
      kind: "reference",
      required_for: [],
      recomputed: side(g.ef.value, g.ef.unit, "reference", ref(g.ef.source)),
      ...(cg ? { company: side(cg.ef.value, cg.ef.unit, "reference", ref(cg.ef.source)) } : {}),
    };
    inputs[`gwp.${g.gas}`] = {
      id: `gwp.${g.gas}`,
      label: `${label} global warming potential`,
      kind: "reference",
      required_for: [],
      recomputed: side(g.gwp.value, "t CO2e/t", "reference", ref(g.gwp.source)),
      ...(cg ? { company: side(cg.gwp.value, "t CO2e/t", "reference", ref(cg.gwp.source)) } : {}),
    };
    const massOp = (x: CalcLineGas) =>
      operation(
        [
          { op: null, operand: operand("activity", x.activity.value, x.activity.unit, { step_ref: x.activity.unit === s2.to_unit ? "conversion" : "activity" }) },
          { op: "×", operand: operand("ef", x.ef.value, x.ef.unit, { input_id: `ef.${g.gas}` }) },
          { op: "×", operand: operand("conversion", x.unit_conversion, tonnesPer(x.ef.unit)) },
        ],
        "mass",
        "t",
      );
    mass.push({
      id: `emissions.${g.gas}`,
      label,
      choice_id: `equation:${g.gas}`,
      columns: [col("activity", "Activity", undefined, false), col("ef", "Emission factor", undefined, false), col("conversion", "To metric tons", undefined, false), col("mass", "Mass", "t", true, { dp: 3 })],
      ...(cg ? { company: massOp(cg) } : {}),
      recomputed: withDifferences(massOp(g), cg ? massOp(cg) : undefined),
    });
    const gwpOp = (x: CalcLineGas) =>
      operation([{ op: null, operand: operand("mass", Number(massOp(x).result.value), "t", { step_ref: `emissions.${g.gas}` }) }, { op: "×", operand: operand("gwp", x.gwp.value, "t CO2e/t", { input_id: `gwp.${g.gas}` }) }], "co2e", "t CO2e");
    recomputedCo2e[g.gas] = Number(gwpOp(g).result.value);
    if (cg) companyCo2e[g.gas] = Number(gwpOp(cg).result.value);
    gwp.push({
      id: `gwp.${g.gas}`,
      label,
      columns: [col("mass", "Mass", "t", false, { dp: 3 }), col("gwp", "GWP", "t CO2e/t", false), col("co2e", "CO₂e", "t CO2e", true, { dp: 2 })],
      ...(cg ? { company: gwpOp(cg) } : {}),
      recomputed: withDifferences(gwpOp(g), cg ? gwpOp(cg) : undefined),
    });
  }

  // Results: the gases added, then the consolidated share.
  inputs.share = { id: "share", label: "Consolidated share", kind: "methodology", required_for: [], recomputed: side(line.consolidated_share_pct / 100, "", "reference", { kind: "methodology", field: "consolidated_share", label: "Consolidated share" }) };
  const gases = GASES.filter((gas) => line.step3.gases.some((g) => g.gas === gas));
  const sumOp = (byGas: Partial<Record<CalcGas, number>>) =>
    operation(gases.map((gas, i) => ({ op: i === 0 ? null : ("+" as TraceOpSymbol), operand: operand("co2e", byGas[gas] ?? 0, "t CO2e", { step_ref: `gwp.${gas}` }) })), "sum", "t CO2e");
  const companySum = co ? sumOp(companyCo2e) : undefined;
  const recomputedSum = sumOp(recomputedCo2e);
  const totalOp = (sum: TraceOperation, withShare: boolean): TraceOperation =>
    withShare
      ? operation([{ op: null, operand: operand("sum", Number(sum.result.value), "t CO2e", { step_ref: "sum" }) }, { op: "×", operand: operand("share", line.consolidated_share_pct / 100, undefined, { input_id: "share" }) }], "total", "t CO2e")
      : // The demo's company figure is the sum as reported, before any consolidated share.
        operation([{ op: null, operand: operand("sum", Number(sum.result.value), "t CO2e", { step_ref: "sum" }) }], "total", "t CO2e");
  // The company's line total is the figure the row reports (Reported), so the panel and the row agree. When the
  // reviewer entered a total that is not the company's own sum, the row's figure is shown and the trace says so.
  const reported = line.reported_total_co2e_t;
  // A line the company gave only a total for (no step-by-step) still shows that total, as the row does.
  const companyTotal = companySum
    ? totalOp(companySum, false)
    : reported !== null
      ? operation([{ op: null, operand: operand("total", reported, "t CO2e") }], "total", "t CO2e")
      : undefined;
  const reportedIsEntered = Boolean(companySum) && reported !== null && Math.abs(reported - Number(companyTotal?.result.value)) > 1e-6;
  if (companyTotal && reported !== null) companyTotal.result.value = reported;
  const results: TraceStep = {
    id: "results",
    n: null,
    title: "Results",
    note: "Sum of gases × consolidated share",
    blocks: [
      {
        id: "results.sum",
        label: "Gases added",
        columns: [col("co2e", "CO₂e", "t CO2e", false, { dp: 2 }), col("sum", "Sum of gases", "t CO2e", true, { dp: 2 })],
        ...(companySum ? { company: companySum } : {}),
        recomputed: withDifferences(recomputedSum, companySum),
      },
      {
        id: "results.total",
        label: "Line total",
        columns: [col("sum", "Sum of gases", "t CO2e", false, { dp: 2 }), col("share", "Consolidated share", undefined, false), col("total", "Total", "t CO2e", true, { dp: 2 })],
        ...(companyTotal ? { company: companyTotal } : {}),
        recomputed: withDifferences(totalOp(recomputedSum, true), companyTotal),
      },
    ],
  };

  const steps = [step1, step2, { id: "emissions", n: 3, title: "Step 3 · Emissions by gas", note: "One equation per gas", blocks: mass } as TraceStep, { id: "gwp", n: 4, title: "Step 4 · CO₂e", note: "Mass × global warming potential", blocks: gwp } as TraceStep, results];
  markDecidable(inputs);
  const equation = (gas: CalcGas) => line.method.equations[gas];
  return {
    trace_version: 1,
    line_key: line.key,
    panel: line.category === "mobile" ? "mobile" : line.category === "purchased_energy" ? "electricity" : "stationary",
    state: "complete",
    blocking: [],
    choices: [
      { id: "method", label: "Calculation method", options: [{ id: "route", label: line.method.route, available: true, required_inputs: [] }], chosen: "route", chosen_by: "default" },
      ...gases
        .filter((gas) => equation(gas))
        .map((gas) => ({
          id: `equation:${gas}`,
          label: `${GAS_LABEL[gas]} equation`,
          options: [
            { id: "eq", label: equation(gas) ?? "", equation: equation(gas), available: true, required_inputs: [] },
            { id: "eq2", label: "Eq. 2 · site heating value", available: false, why_unavailable: "Needs an accepted site heating value (HHV).", required_inputs: ["hhv"] },
          ],
          chosen: "eq",
          chosen_by: "default" as const,
        })),
    ],
    inputs,
    steps,
    result: {
      unit: "t CO2e",
      company: companyTotal ? Number(companyTotal.result.value) : null,
      recomputed: line.results.total_co2e_t,
      difference: line.difference_t,
    },
    method_mismatch: false,
    flags: reportedIsEntered ? [...line.flags, "company_total_is_reported_figure"] : line.flags,
  };
}
