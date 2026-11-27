/**
 * Demo: a fugitive line by EPA's material balance (backend/app/services/calc_trace/fugitive.py, `_material`), in the
 * backend's trace shapes. E = (I_B − I_E) + (P − S) + (C_B − C_E). No record gives the six terms: each is "not
 * reported" until a reviewer enters it (0 allowed), and the method is blocked until all six are.
 */
import type { TraceBlock, TraceBlocking, TraceColumn, TraceInput, TraceOpSymbol, TraceOperand, TraceOperation } from "../../api/calcTrace";
import type { DemoDecided } from "./fugitiveScreening";

export const MB_TERMS = ["I_B", "I_E", "P", "S", "C_B", "C_E"] as const;
type MbTerm = (typeof MB_TERMS)[number];
const MB_LABEL: Record<MbTerm, string> = {
  I_B: "In storage at the start of the year", I_E: "In storage at the end of the year", P: "Purchased or acquired",
  S: "Sold or sent off-site", C_B: "Equipment capacity at the start of the year", C_E: "Equipment capacity at the end of the year",
};
const MB_OP: Record<MbTerm, TraceOpSymbol | null> = { I_B: null, I_E: "−", P: "+", S: "−", C_B: "+", C_E: "−" };
export const MB_EQUATION = "Emitted = (I_B − I_E) + (P − S) + (C_B − C_E)";
export const MB_ROUTE = "Material balance: (I_B − I_E) + (P − S) + (C_B − C_E), to metric tons, × GWP";
const NOT_REPORTED = "not reported. Enter it from the company's records, or 0 if there was none";
const NEGATIVE = "negative balance: check the inventory, purchase and capacity figures. The negative value is kept";

const operand = (column: string, value: number | null, unit?: string, extra: Partial<TraceOperand> = {}): TraceOperand => ({ column, value, ...(unit ? { unit } : {}), ...extra });
const col = (key: string, label: string, unit: string | undefined, isResult = false, display: TraceColumn["display"] = {}): TraceColumn => ({ key, label, ...(unit ? { unit } : {}), is_result: isResult, display });
/** A decided term: a finite number of at least 0 (the backend refuses a negative one). */
const termOf = (decided: DemoDecided, t: MbTerm): number | null => {
  const v = decided.inputs[t];
  return typeof v === "number" && Number.isFinite(v) && v >= 0 ? v : null;
};

/** The six terms, on every trace of the line, each awaiting a reviewer until entered. */
export function materialInputs(unit: string, decided: DemoDecided): Record<string, TraceInput> {
  return Object.fromEntries(MB_TERMS.map((t) => {
    const v = termOf(decided, t);
    const input: TraceInput = { id: t, label: MB_LABEL[t], symbol: t, kind: "reviewer_entered", required_for: ["material_balance"], decidable: true,
      recomputed: v === null ? { value: null, unit, status: "awaiting_review" } : { value: v, unit, status: "edited" } };
    return [t, input];
  }));
}

/** Steps 1 and 2 of the material balance, to the refrigerant emitted in the line's unit. */
export function materialSteps(unit: string, decided: DemoDecided) {
  const values = Object.fromEntries(MB_TERMS.map((t) => [t, termOf(decided, t)])) as Record<MbTerm, number | null>;
  const step1: TraceBlock[] = MB_TERMS.map((t) => {
    const v = values[t];
    const op: TraceOperation = { terms: [{ op: null, operand: operand("amount", v, unit, { input_id: t }) }], result: operand("amount", v, unit, { input_id: t }) };
    return { id: `term.${t}`, label: `${MB_LABEL[t]} · ${t}`, columns: [col("amount", "Total", unit, true, { sig: 6 })], recomputed: op, ...(v === null ? { warning: NOT_REPORTED } : {}) };
  });
  const missing = MB_TERMS.filter((t) => values[t] === null);
  let emitted: number | null = null;
  if (!missing.length) {
    emitted = 0;
    for (const t of MB_TERMS) emitted = MB_OP[t] === "−" ? emitted - values[t]! : emitted + values[t]!;
  }
  const balance: TraceOperation = { terms: MB_TERMS.map((t) => ({ op: MB_OP[t], operand: operand(t, values[t], unit, { step_ref: `term.${t}` }) })), result: operand("emitted", emitted, unit) };
  const step2: TraceBlock[] = [{ id: "emitted", label: "Refrigerant emitted", columns: [...MB_TERMS.map((t) => col(t, t, unit)), col("emitted", "Emitted", unit, true, { sig: 6 })], recomputed: balance, ...(emitted !== null && emitted < 0 ? { warning: NEGATIVE } : {}) }];
  const blocking: TraceBlocking[] = missing.length
    ? [{ input_id: missing[0], message: `material balance terms. Not reported: ${missing.join(", ")}. Enter each from the company's inventory, purchase and equipment records; enter 0 for a term that was nil.` }]
    : [];
  const note = "The gas in storage, bought and sold, and the equipment's full charge at the start and end of the year, as entered by a reviewer";
  return { step1, step2, emitted, blocking, equation: MB_EQUATION, note, route: MB_ROUTE };
}
