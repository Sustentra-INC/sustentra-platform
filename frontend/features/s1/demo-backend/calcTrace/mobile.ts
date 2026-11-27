/**
 * Demo trace of an on-road vehicle group's line: Step 2 gains the distance as fuel × fuel economy, and the fuel
 * economy is an input a reviewer can decide (backend/app/services/calc_trace/mobile.py, which this mirrors).
 *
 * The demo's recalculation states the group's distance; the fuel economy shown is the one that distance implies
 * (distance ÷ the line's gallons), for the company and for Sustentra alike. Like every demo decision, an edited
 * fuel economy is recorded and shown (decisions.ts) and moves no total.
 */
import type { CalculationLine } from "../../api/recalculation";
import type { LineTrace, TraceBlock, TraceInput, TraceOperand, TraceOperation } from "../../api/calcTrace";

const ECONOMY_UNIT = "mi/gal";
const DERIVED = { kind: "derived", from: ["distance", "activity.total"] } as const;

const operand = (column: string, value: number, unit: string, extra: Partial<TraceOperand> = {}): TraceOperand => ({ column, value, unit, ...extra });

function distanceOperation(fuel: number, economy: number): TraceOperation {
  return {
    terms: [
      { op: null, operand: operand("fuel", fuel, "gal", { step_ref: "conversion" }) },
      { op: "×", operand: operand("economy", economy, ECONOMY_UNIT, { input_id: "fuel_economy" }) },
    ],
    result: operand("distance", fuel * economy, "mi"),
  };
}

const positive = (n: unknown): n is number => typeof n === "number" && Number.isFinite(n) && n > 0;

/** The trace with the fuel economy and the distance block, or the trace as it was when the line has no honest fuel economy. */
export function withFuelEconomy(trace: LineTrace, line: CalculationLine): LineTrace {
  const { distance, implied_fuel_economy: implied, result, to_unit } = { ...line.step2 };
  const fuel = result.quantity;
  if (trace.panel !== "mobile" || !distance || !implied || to_unit !== "gal" || distance.unit !== "mi" || !positive(fuel) || !positive(distance.quantity) || line.flags.includes("mixed_units_or_fuels")) return trace;
  const out = structuredClone(trace);
  const step2 = out.steps.find((s) => s.id === "conversion");
  if (!step2) return trace;
  const economy = distance.quantity / fuel;
  const co = line.company;
  const companyMiles = co?.step3.gases.find((g) => g.gas === "CH4")?.activity;
  const companyFuel = co?.step2.result;
  const companyEconomy = companyMiles && companyFuel && positive(companyFuel.quantity) && positive(companyMiles.value) && companyMiles.unit === "mi" && companyFuel.unit === "gal" ? companyMiles.value / companyFuel.quantity : null;
  const mine = distanceOperation(fuel, economy);
  const theirs = companyEconomy !== null && companyFuel ? distanceOperation(companyFuel.quantity, companyEconomy) : undefined;
  if (theirs) {
    mine.terms = mine.terms.map((t, i) => ({ ...t, operand: { ...t.operand, difference: Number(t.operand.value) - Number(theirs.terms[i].operand.value) } }));
    mine.result = { ...mine.result, difference: Number(mine.result.value) - Number(theirs.result.value) };
  }
  const input: TraceInput = {
    id: "fuel_economy",
    label: "Fuel economy",
    symbol: "mpg",
    kind: "reviewer_entered",
    required_for: ["eq4_distance"],
    decidable: true,
    source_hint: "fleet records or manufacturer rating",
    recomputed: { value: economy, unit: ECONOMY_UNIT, status: "derived", source: { ...DERIVED, from: [...DERIVED.from] } },
    ...(companyEconomy !== null ? { company: { value: companyEconomy, unit: ECONOMY_UNIT, status: "derived" as const, source: { ...DERIVED, from: [...DERIVED.from] } }, difference: economy - companyEconomy } : {}),
  };
  const block: TraceBlock = {
    id: "distance",
    label: "Distance driven",
    columns: [
      { key: "fuel", label: "Fuel", unit: "gal", is_result: false, display: {} },
      { key: "economy", label: "Fuel economy", unit: ECONOMY_UNIT, is_result: false, display: {} },
      { key: "distance", label: "Distance", unit: "mi", is_result: true, display: { dp: 0 } },
    ],
    ...(theirs ? { company: theirs } : {}),
    recomputed: mine,
  };
  step2.blocks.push(block);
  step2.note = "To the unit the emission factor is in, then fuel × fuel economy = distance";
  out.inputs.fuel_economy = input;
  return out;
}
