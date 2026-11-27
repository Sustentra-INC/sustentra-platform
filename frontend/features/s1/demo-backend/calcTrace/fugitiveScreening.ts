/**
 * Demo: a fugitive line by EPA's screening method (backend/app/services/calc_trace/fugitive.py, `_screening`), in the
 * backend's trace shapes. Shown once a reviewer picks Screening for the line; the equipment type gives EPA's factors,
 * each a "Default … · not confirmed" tag until a reviewer enters it. Like every demo decision, it moves no total.
 */
import type { CalcLineStep1Row } from "../../api/recalculation";
import type { TraceBlock, TraceBlocking, TraceChoice, TraceColumn, TraceInput, TraceOpSymbol, TraceOperand, TraceOperation, TraceSide } from "../../api/calcTrace";

/** EPA's screening factors, in percent: reference-data/emission-factors/epa_fugitive_screening_factors.json (a test keeps the two equal). */
type Range = [number, number] | null;
/** EPA's value per factor (in %) and IPCC 2019 Table 7.9's range for it (page 7.32; EPA's value is its upper end). */
export const SCREENING_TYPES: { id: string; label: string; fire: boolean; k: number | null; x: number; y: number | null; z: number | null; ipcc: Record<"k" | "x" | "y" | "z", Range> | null }[] = [
  { id: "domestic_refrigeration", label: "Domestic refrigeration", fire: false, k: 1, x: 0.5, y: 80, z: 70, ipcc: { k: [0.2, 1], x: [0.1, 0.5], y: [0, 80], z: [0, 70] } },
  { id: "stand_alone_commercial", label: "Stand-alone commercial applications", fire: false, k: 3, x: 15, y: 80, z: 70, ipcc: { k: [0.5, 3], x: [1, 15], y: [0, 80], z: [0, 70] } },
  { id: "medium_large_commercial", label: "Medium & large commercial refrigeration", fire: false, k: 3, x: 35, y: 100, z: 70, ipcc: { k: [0.5, 3], x: [10, 35], y: [50, 100], z: [0, 70] } },
  { id: "transport_refrigeration", label: "Transport refrigeration", fire: false, k: 1, x: 50, y: 50, z: 70, ipcc: { k: [0.2, 1], x: [15, 50], y: [0, 50], z: [0, 70] } },
  { id: "industrial_refrigeration", label: "Industrial refrigeration including food processing and cold storage", fire: false, k: 3, x: 25, y: 100, z: 90, ipcc: { k: [0.5, 3], x: [7, 25], y: [50, 100], z: [0, 90] } },
  { id: "chillers", label: "Chillers", fire: false, k: 1, x: 15, y: 100, z: 95, ipcc: { k: [0.2, 1], x: [2, 15], y: [80, 100], z: [0, 95] } },
  { id: "residential_commercial_ac", label: "Residential and commercial A/C including heat pumps", fire: false, k: 1, x: 10, y: 80, z: 80, ipcc: { k: [0.2, 1], x: [1, 10], y: [0, 80], z: [0, 80] } },
  { id: "mobile_ac_maritime", label: "Mobile air conditioning - maritime", fire: false, k: 0.5, x: 40, y: 50, z: 50, ipcc: { k: [0.2, 0.5], x: [20, 40], y: [0, 50], z: [0, 50] } },
  { id: "mobile_ac_railway", label: "Mobile air conditioning - railway", fire: false, k: 0.5, x: 20, y: 50, z: 50, ipcc: { k: [0.2, 0.5], x: [5, 20], y: [0, 50], z: [0, 50] } },
  { id: "mobile_ac_buses", label: "Mobile air conditioning - buses", fire: false, k: 0.5, x: 20, y: 50, z: 50, ipcc: { k: [0.2, 0.5], x: null, y: [0, 50], z: [0, 50] } },
  { id: "mobile_ac_other", label: "Mobile air conditioning - other", fire: false, k: 0.5, x: 20, y: 50, z: 50, ipcc: { k: [0.2, 0.5], x: [10, 20], y: [0, 50], z: [0, 50] } },
  { id: "fire_fixed", label: "Fire suppression, fixed systems", fire: true, k: null, x: 2.5, y: null, z: null, ipcc: null },
  { id: "fire_portable", label: "Fire suppression, portable equipment", fire: true, k: null, x: 3.5, y: null, z: null, ipcc: null },
];

export const SCREENING_EQUATION = "Emitted = C_N × k + Σ (C × T) × x + C_D × y × (1 − z)";
const FIRE_EQUATION = "Emitted = Σ (C × T) × x";
const GUIDANCE = "EPA GHG Inventory Guidance: Direct Fugitive Emissions (December 2023)";
const FACTORS = ["k", "x", "y", "z"] as const;
type Factor = (typeof FACTORS)[number];
const FACTOR_LABEL: Record<Factor, string> = { k: "Installation loss", x: "Annual leak rate", y: "Left at disposal", z: "Recovery" };
const T_TAG = "Default 1.00 (in use the whole reporting period) · not confirmed. Enter months in use ÷ 12";
const FIRE_AGENTS = ["hfc-227ea", "hfc-236fa", "fk-5-1-12"];
const EITHER_USE = ["hfc-125", "hfc-23", "co2"];
/** Which equipment types a gas can be screened under (backend `fugitive.gas_use`). */
export function gasUse(gas: string): "fire" | "refrigerant" | "either" {
  const key = gas.trim().toLowerCase();
  if (FIRE_AGENTS.some((a) => key.startsWith(a))) return "fire";
  return EITHER_USE.includes(key) ? "either" : "refrigerant";
}
function typeRefusal(gas: string, fire: boolean): string | null {
  const use = gasUse(gas);
  if (fire && use === "refrigerant") return `${gas} is a refrigerant, not a fire-suppression agent: pick a refrigeration or A/C type.`;
  if (!fire && use === "fire") return `${gas} is a fire-suppression agent: pick fire suppression, fixed or portable.`;
  return null;
}

/** The decisions a demo line is worked with: picked options, and decided numbers by input id. */
export interface DemoDecided {
  choices: Record<string, string>;
  inputs: Record<string, number>;
}

type Term = { op: TraceOpSymbol | null; operand: TraceOperand };
const operand = (column: string, value: number | null, unit?: string, extra: Partial<TraceOperand> = {}): TraceOperand => ({ column, value, ...(unit ? { unit } : {}), ...extra });
const col = (key: string, label: string, unit: string | undefined, isResult = false, display: TraceColumn["display"] = {}): TraceColumn => ({ key, label, ...(unit ? { unit } : {}), is_result: isResult, display });
/** Left to right; an operand still awaited leaves the result awaited (null), never a number. */
function worked(terms: Term[], column: string, unit: string | undefined): TraceOperation {
  if (terms.some((t) => t.operand.value === null || t.operand.value === undefined)) return { terms, result: operand(column, null, unit) };
  let total = 0;
  terms.forEach((t, i) => {
    const v = Number(t.operand.value);
    if (i === 0) total = v;
    else if (t.op === "×") total *= v;
    else if (t.op === "+") total += v;
    else if (t.op === "−") total -= v;
    else total /= v;
  });
  return { terms, result: operand(column, total, unit) };
}
const one = (column: string, value: number | null, unit: string | undefined, inputId: string): TraceOperation => worked([{ op: null, operand: operand(column, value, unit, { input_id: inputId }) }], column, unit);
const fmt = (v: number) => Number(v.toPrecision(6)).toLocaleString("en-US");
function hash(text: string): string {
  let h = 0x811c9dc5;
  for (let i = 0; i < text.length; i++) h = Math.imul(h ^ text.charCodeAt(i), 0x01000193) >>> 0;
  return `u${h.toString(16).padStart(8, "0")}`;
}

interface Unit { uid: string; name: string; capacity: number | null }

/** One unit per record (the demo's service logs name no equipment): its capacity awaits a reviewer. */
export function screeningUnits(rows: CalcLineStep1Row[]): Unit[] {
  return rows.map((r, i) => ({ uid: hash(`${r.document_id}/${r.candidate_id ?? i}#${i}`), name: [r.file_name ?? r.document_id, r.period_start].filter(Boolean).join(" · "), capacity: null }));
}

export function screeningChoices(available: boolean, gas = ""): TraceChoice[] {
  const method: TraceChoice = { id: "method", label: "Calculation method", chosen: "smb", chosen_by: "default", options: [
    { id: "screening", label: "Screening", equation: SCREENING_EQUATION, available, ...(available ? {} : { why_unavailable: "No reviewed records of equipment on this line." }), required_inputs: ["equipment_type", ...FACTORS] },
    { id: "smb", label: "Simplified material balance", equation: "Emitted = (P_N − C_N) + P_S + (C_D − R_D)", available: true, required_inputs: ["P_N", "C_N", "P_S", "C_D", "R_D"] },
    { id: "material_balance", label: "Material balance", available: false, why_unavailable: "Sustentra cannot calculate this method yet.", required_inputs: [] },
  ] };
  if (!available) return [method];
  return [method, { id: "equipment_type", label: "Equipment type", chosen: "", chosen_by: "default", options: SCREENING_TYPES.map((t) => {
    const why = typeRefusal(gas, t.fire);
    return { id: t.id, label: t.label, equation: t.fire ? FIRE_EQUATION : SCREENING_EQUATION, available: why === null, ...(why ? { why_unavailable: why } : {}), required_inputs: [] };
  }) }];
}

/** Every input the screening reads, on every trace of the line (a decision is checked against the line's own working). */
/** The picked equipment type, unless the gas cannot be screened under it. */
function pickedType(decided: DemoDecided, gas: string) {
  const kind = SCREENING_TYPES.find((t) => t.id === decided.choices.equipment_type);
  return kind && typeRefusal(gas, kind.fire) === null ? kind : undefined;
}

/** "Default 10% (EPA Table 1; IPCC range 1–10%) · not confirmed". */
function defaultTag(kind: (typeof SCREENING_TYPES)[number], f: Factor, pct: number): string {
  if (kind.fire) return `Default ${fmt(pct)}% (EPA fugitive guidance §2.1.2) · not confirmed`;
  const range = kind.ipcc?.[f];
  return `Default ${fmt(pct)}% (EPA Table 1; ${range ? `IPCC range ${fmt(range[0])}–${fmt(range[1])}%` : "no IPCC range printed"}) · not confirmed`;
}

export function screeningInputs(units: Unit[], unit: string, decided: DemoDecided, gasOf = ""): Record<string, TraceInput> {
  const kind = pickedType(decided, gasOf);
  const entered = (id: string, value: number, u: string | undefined): TraceSide => ({ value, ...(u ? { unit: u } : {}), status: "edited" });
  const out: Record<string, TraceInput> = {};
  for (const u of units) {
    const c = `C.${u.uid}`;
    const t = `T.${u.uid}`;
    out[c] = { id: c, label: `${u.name} capacity`, symbol: "C", kind: "reviewer_entered", required_for: ["screening"], decidable: true,
      recomputed: c in decided.inputs ? entered(c, decided.inputs[c], unit) : u.capacity !== null ? { value: u.capacity, unit, status: "accepted" } : { value: null, unit, status: "awaiting_review" } };
    out[t] = { id: t, label: `${u.name} time in use`, symbol: "T", kind: "reviewer_entered", required_for: ["screening"], decidable: true,
      recomputed: t in decided.inputs ? entered(t, decided.inputs[t], undefined) : { value: 1, status: "derived", source: { kind: "derived", from: ["default: in use the whole reporting period"] } } };
  }
  for (const f of FACTORS) {
    const fallback = kind ? kind[f] : null;
    out[f] = { id: f, label: FACTOR_LABEL[f], symbol: f, kind: "reference", required_for: ["screening"], decidable: true,
      recomputed: f in decided.inputs ? entered(f, decided.inputs[f], "%") : fallback !== null && kind ? { value: fallback, unit: "%", status: "reference", source: { kind: "reference", dataset: GUIDANCE, table: kind.fire ? "EPA fugitive guidance §2.1.2" : "EPA Table 1", citation: `${GUIDANCE}, ${kind.fire ? "Section 2.1.2, page 5" : "Table 1, page 11"}: ${kind.label}` } } : { value: null, unit: "%", status: "awaiting_review" } };
  }
  return out;
}

const valueOf = (input: TraceInput | undefined): number | null => (typeof input?.recomputed?.value === "number" ? input.recomputed.value : null);

/** Steps 1 and 2 of the screening, to the refrigerant emitted in the line's unit. */
export function screeningSteps(units: Unit[], unit: string, terms: { P_N: number; C_D: number }, inputs: Record<string, TraceInput>, decided: DemoDecided, gas = "") {
  const kind = pickedType(decided, gas);
  const fire = Boolean(kind?.fire);
  const blocking: TraceBlocking[] = [];
  const step1: TraceBlock[] = [];
  const inUseTerms: Term[] = [];
  for (const u of units) {
    const c = `C.${u.uid}`;
    const t = `T.${u.uid}`;
    const op = worked([{ op: null, operand: operand("C", valueOf(inputs[c]), unit, { input_id: c }) }, { op: "×", operand: operand("T", valueOf(inputs[t]), undefined, { input_id: t }) }], "CT", unit);
    step1.push({ id: `unit.${u.uid}`, label: `${u.name} · equipment in use`, columns: [col("C", "Capacity · C", unit), col("T", "Time in use · T", undefined, false, { dp: 2 }), col("CT", "C × T", unit, true, { sig: 6 })], recomputed: op });
    if (!(t in decided.inputs) && inputs[t]) inputs[t].assumption = T_TAG;
    if (valueOf(inputs[c]) === null) blocking.push({ input_id: c, message: `equipment capacity. Enter the refrigerant capacity (C) of ${u.name}, from the equipment register or its nameplate.` });
    inUseTerms.push({ op: inUseTerms.length ? "+" : null, operand: operand("CT", op.result.value as number | null, unit, { step_ref: `unit.${u.uid}` }) });
  }
  const inUse = worked(inUseTerms, "in_use", unit);
  step1.push({ id: "in_use", label: "Total in use · Σ (C × T)", columns: [col("CT", "C × T", unit), col("in_use", "Σ (C × T)", unit, true, { sig: 6 })], recomputed: inUse });
  const needK = !fire && terms.P_N !== 0;
  const needYZ = !fire && terms.C_D !== 0;
  const needed = FACTORS.filter((f) => f === "x" || (f === "k" && needK) || ((f === "y" || f === "z") && needYZ));
  if (needK) step1.push({ id: "term.P_N", label: "New equipment charge · C_N", columns: [col("amount", "Total", unit, true, { sig: 6 })], recomputed: one("amount", terms.P_N, unit, "P_N") });
  if (needYZ) step1.push({ id: "term.C_D", label: "Retired equipment capacity · C_D", columns: [col("amount", "Total", unit, true, { sig: 6 })], recomputed: one("amount", terms.C_D, unit, "C_D") });
  const fraction: Partial<Record<Factor, number | null>> = {};
  for (const f of needed) {
    const pct = valueOf(inputs[f]);
    fraction[f] = pct === null ? null : pct / 100;
    const name = fire && f === "x" ? "Annual emission rate" : FACTOR_LABEL[f];
    const tag = !(f in decided.inputs) && pct !== null && kind ? defaultTag(kind, f, pct) : null;
    step1.push({ id: `factor.${f}`, label: `${name} · ${f}`, columns: [col(f, name, "%", true)], recomputed: one(f, fraction[f] ?? null, undefined, f) });
    if (tag && inputs[f]) inputs[f].assumption = tag;
  }
  const missing = needed.filter((f) => fraction[f] === null);
  if (missing.length) blocking.push(kind ? { input_id: missing[0], message: `screening factors. EPA gives no ${missing.join(", ")} for ${kind.label}: enter ${missing.length === 1 ? "it" : "them"}.` } : { input_id: "equipment_type", message: `the equipment type. Pick it under Equipment type to use EPA's screening factors, or enter ${missing.join(", ")} for this line.` });
  const step2: TraceBlock[] = [];
  const parts: Term[] = [];
  if (needK) {
    const install = worked([{ op: null, operand: operand("C_N", terms.P_N, unit, { step_ref: "term.P_N" }) }, { op: "×", operand: operand("k", fraction.k ?? null, undefined, { input_id: "k" }) }], "installation", unit);
    step2.push({ id: "installation", label: "Installation", columns: [col("C_N", "New equipment charge · C_N", unit), col("k", "Installation loss · k", "%"), col("installation", "Installation", unit, true, { sig: 6 })], recomputed: install });
    parts.push({ op: null, operand: operand("installation", install.result.value as number | null, unit, { step_ref: "installation" }) });
  }
  const operation = worked([{ op: null, operand: operand("in_use", inUse.result.value as number | null, unit, { step_ref: "in_use" }) }, { op: "×", operand: operand("x", fraction.x ?? null, undefined, { input_id: "x" }) }], "operation", unit);
  step2.push({ id: "operation", label: "Operation", columns: [col("in_use", "Σ (C × T)", unit), col("x", fire ? "Annual emission rate · x" : "Annual leak rate · x", "%"), col("operation", "Operation", unit, true, { sig: 6 })], recomputed: operation });
  parts.push({ op: parts.length ? "+" : null, operand: operand("operation", operation.result.value as number | null, unit, { step_ref: "operation" }) });
  if (needYZ) {
    const notRecovered = worked([{ op: null, operand: operand("all", 1) }, { op: "−", operand: operand("z", fraction.z ?? null, undefined, { input_id: "z" }) }], "not_recovered", undefined);
    step2.push({ id: "not_recovered", label: "Not recovered", columns: [col("all", "All", "%"), col("z", "Recovery · z", "%"), col("not_recovered", "Not recovered · 1 − z", "%", true)], recomputed: notRecovered });
    const disposal = worked([{ op: null, operand: operand("C_D", terms.C_D, unit, { step_ref: "term.C_D" }) }, { op: "×", operand: operand("y", fraction.y ?? null, undefined, { input_id: "y" }) }, { op: "×", operand: operand("not_recovered", notRecovered.result.value as number | null, undefined, { step_ref: "not_recovered" }) }], "disposal", unit);
    step2.push({ id: "disposal", label: "Disposal", columns: [col("C_D", "Retired capacity · C_D", unit), col("y", "Left at disposal · y", "%"), col("not_recovered", "Not recovered · 1 − z", "%"), col("disposal", "Disposal", unit, true, { sig: 6 })], recomputed: disposal });
    parts.push({ op: "+", operand: operand("disposal", disposal.result.value as number | null, unit, { step_ref: "disposal" }) });
  }
  const emitted = worked(parts, "emitted", unit);
  step2.push({ id: "emitted", label: "Refrigerant emitted", columns: [...parts.map((p) => col(p.operand.column, p.operand.column.replace("_", " ").replace(/^./, (s) => s.toUpperCase()), unit)), col("emitted", "Emitted", unit, true, { sig: 6 })], recomputed: emitted });
  const note = kind ? `Each piece of equipment's capacity × its time in use, and EPA's screening factors for ${kind.label}` : "Each piece of equipment's capacity × its time in use. Pick the equipment type for EPA's screening factors";
  return { step1, step2, emitted: typeof emitted.result.value === "number" ? emitted.result.value : null, blocking, equation: fire ? FIRE_EQUATION : SCREENING_EQUATION, note, route: fire ? "Screening (EPA), fire suppression: Σ (C × T) × rate, to metric tons, × GWP" : "Screening (EPA): C_N × k + Σ (C × T) × x + C_D × y × (1 − z), to metric tons, × GWP" };
}
