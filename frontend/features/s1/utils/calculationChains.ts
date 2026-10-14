import type { CalcCell, CalcStep, SourceRef } from "../types/verificationResults";

/**
 * The calculation behind one facility's value, run twice: once from the client's
 * inputs (Reported) and once from the evidence (Recomputed). Each builder returns the
 * card's rows and both totals in tCO2e, unrounded.
 *
 * A factor is one value with its source when both sides used it; it reads in the How
 * column ("× 53.06 kg/MMBtu"). When the client applied a different one, the factor
 * leaves the How column and gets its own row with both values, like a consumption.
 */

export interface Quantity {
  value: number;
  unit: string;
  source?: SourceRef;
}

export interface Factor {
  value: number;
  /** As printed, e.g. "53.06"; defaults to the value. */
  text?: string;
  unit: string;
  source?: SourceRef;
}

/** One value, or one per side when the client's differs from the evidence's. */
export type Sided<T> = T | { reported: T; recomputed: T };

export interface Chain {
  steps: CalcStep[];
  reported: number;
  recomputed: number;
}

const LB_TO_TONNES = 0.00045359237;

function sides<T>(value: Sided<T>): { reported: T; recomputed: T; same: boolean } {
  if (typeof value === "object" && value !== null && "reported" in value && "recomputed" in value) {
    const pair = value as { reported: T; recomputed: T };
    return { ...pair, same: false };
  }
  return { reported: value as T, recomputed: value as T, same: true };
}

function factorSides(factor: Sided<Factor>): { reported: Factor; recomputed: Factor; same: boolean } {
  const pair = sides(factor);
  return { ...pair, same: pair.same || pair.reported.value === pair.recomputed.value };
}

/** Whole numbers from 100 up, one decimal below ("24.6 kg"). */
export function formatQuantity(value: number): string {
  const digits = Math.abs(value) >= 100 || Number.isInteger(value) ? 0 : 1;
  return value.toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

/** One decimal; below 0.1 t, two significant figures so a small gas never reads as 0.0 t. */
function tonnes(value: number): string {
  if (value !== 0 && Math.abs(value) < 0.1) return `${Number(value.toPrecision(2))} t`;
  return `${value.toLocaleString("en-US", { minimumFractionDigits: 1, maximumFractionDigits: 1 })} t`;
}

function totalText(value: number): string {
  return `${Math.round(value).toLocaleString("en-US")} tCO₂e`;
}

function factorText(factor: Factor): string {
  return `${factor.text ?? factor.value.toLocaleString("en-US")} ${factor.unit}`.trim();
}

function quantityCell(quantity: Quantity): CalcCell {
  return { text: `${formatQuantity(quantity.value)} ${quantity.unit}`, source: quantity.source };
}

function inputRow(step: string, how: string, value: Sided<Quantity>): CalcStep {
  const pair = sides(value);
  return { step, how: [{ text: how }], reported: quantityCell(pair.reported), recomputed: quantityCell(pair.recomputed) };
}

/** The How cells for "× factor" (or "× <name>" when the factor has its own row), and that row. */
function applyFactor(name: string, factor: Sided<Factor>): { how: CalcCell[]; row: CalcStep | null; pair: ReturnType<typeof factorSides> } {
  const pair = factorSides(factor);
  if (pair.same) return { how: [{ text: "× " }, { text: factorText(pair.recomputed), source: pair.recomputed.source }], row: null, pair };
  return {
    how: [{ text: `× ${name}` }],
    row: {
      step: name.charAt(0).toUpperCase() + name.slice(1),
      how: [{ text: "The client's factor, then the one applied" }],
      reported: { text: factorText(pair.reported), source: pair.reported.source },
      recomputed: { text: factorText(pair.recomputed), source: pair.recomputed.source },
    },
    pair,
  };
}

interface GasTerm {
  label: "CO₂" | "CH₄" | "N₂O" | "CO₂e";
  factor: Sided<Factor>;
  /** Converts base × factor to tonnes of the gas (e.g. kg → t is 1e-3). */
  scale: number;
  gwp?: Factor;
}

/** Rows for each gas over a base amount per side, then the Total row. */
function gasRows(base: { reported: number; recomputed: number }, terms: GasTerm[]): Chain {
  const steps: CalcStep[] = [];
  let reported = 0;
  let recomputed = 0;
  for (const term of terms) {
    const used = applyFactor(`${term.label} factor`, term.factor);
    if (used.row) steps.push(used.row);
    const how: CalcCell[] = [...used.how];
    const gwp = term.gwp?.value ?? 1;
    if (term.gwp) how.push({ text: " × GWP " }, { text: term.gwp.text ?? String(term.gwp.value), source: term.gwp.source });
    const rep = base.reported * used.pair.reported.value * term.scale * gwp;
    const rec = base.recomputed * used.pair.recomputed.value * term.scale * gwp;
    steps.push({ step: term.label, how, reported: { text: tonnes(rep) }, recomputed: { text: tonnes(rec) } });
    reported += rep;
    recomputed += rec;
  }
  steps.push({
    step: "Total",
    how: [{ text: terms.map((t) => t.label).join(" + ") }],
    reported: { text: totalText(reported) },
    recomputed: { text: totalText(recomputed) },
    total: true,
  });
  return { steps, reported, recomputed };
}

export interface Gwps {
  ch4: Factor;
  n2o: Factor;
}

/** Stationary fuel: consumption × heat content → MMBtu; × kg or g per MMBtu (× GWP). */
export function fuelByEnergy(input: {
  consumption: Sided<Quantity>;
  how?: string;
  heatContent: Sided<Factor>;
  co2: Sided<Factor>;
  ch4: Sided<Factor>;
  n2o: Sided<Factor>;
  gwp: Gwps;
}): Chain {
  const consumption = sides(input.consumption);
  const steps = [inputRow("Annual consumption", input.how ?? "Sum of monthly utility bills", input.consumption)];
  const heat = applyFactor("heat content", input.heatContent);
  if (heat.row) steps.push(heat.row);
  const energy = {
    reported: consumption.reported.value * heat.pair.reported.value,
    recomputed: consumption.recomputed.value * heat.pair.recomputed.value,
  };
  steps.push({
    step: "Unit conversion",
    how: heat.how,
    reported: { text: `${formatQuantity(energy.reported)} MMBtu` },
    recomputed: { text: `${formatQuantity(energy.recomputed)} MMBtu` },
  });
  const gases = gasRows(energy, [
    { label: "CO₂", factor: input.co2, scale: 1e-3 },
    { label: "CH₄", factor: input.ch4, scale: 1e-6, gwp: input.gwp.ch4 },
    { label: "N₂O", factor: input.n2o, scale: 1e-6, gwp: input.gwp.n2o },
  ]);
  return { ...gases, steps: [...steps, ...gases.steps] };
}

/** Purchased steam or heat, already in MMBtu: × kg or g per MMBtu (× GWP). */
export function thermalByEnergy(input: {
  energy: Sided<Quantity>;
  how?: string;
  co2: Sided<Factor>;
  ch4: Sided<Factor>;
  n2o: Sided<Factor>;
  gwp: Gwps;
}): Chain {
  const energy = sides(input.energy);
  const gases = gasRows({ reported: energy.reported.value, recomputed: energy.recomputed.value }, [
    { label: "CO₂", factor: input.co2, scale: 1e-3 },
    { label: "CH₄", factor: input.ch4, scale: 1e-6, gwp: input.gwp.ch4 },
    { label: "N₂O", factor: input.n2o, scale: 1e-6, gwp: input.gwp.n2o },
  ]);
  return { ...gases, steps: [inputRow("Energy delivered", input.how ?? "Sum of monthly statements", input.energy), ...gases.steps] };
}

/** Biogenic CO2 from biomass: tons × heat content → MMBtu × kg CO2 per MMBtu. */
export function biogenicByEnergy(input: {
  consumption: Sided<Quantity>;
  how?: string;
  heatContent: Sided<Factor>;
  co2: Sided<Factor>;
}): Chain {
  const consumption = sides(input.consumption);
  const steps = [inputRow("Annual consumption", input.how ?? "Sum of delivery tickets", input.consumption)];
  const heat = applyFactor("heat content", input.heatContent);
  if (heat.row) steps.push(heat.row);
  const energy = {
    reported: consumption.reported.value * heat.pair.reported.value,
    recomputed: consumption.recomputed.value * heat.pair.recomputed.value,
  };
  steps.push({
    step: "Unit conversion",
    how: heat.how,
    reported: { text: `${formatQuantity(energy.reported)} MMBtu` },
    recomputed: { text: `${formatQuantity(energy.recomputed)} MMBtu` },
  });
  const gases = gasRows(energy, [{ label: "CO₂", factor: input.co2, scale: 1e-3 }]);
  return { ...gases, steps: [...steps, ...gases.steps] };
}

/** On-road vehicles: CO2 from gallons; CH4 and N2O from miles driven. */
export function vehiclesByDistance(input: {
  fuel: Sided<Quantity>;
  distance: Sided<Quantity>;
  how?: string;
  co2: Sided<Factor>;
  ch4: Sided<Factor>;
  n2o: Sided<Factor>;
  gwp: Gwps;
}): Chain {
  const fuel = sides(input.fuel);
  const distance = sides(input.distance);
  const co2 = gasRows({ reported: fuel.reported.value, recomputed: fuel.recomputed.value }, [
    { label: "CO₂", factor: input.co2, scale: 1e-3 },
  ]);
  const others = gasRows({ reported: distance.reported.value, recomputed: distance.recomputed.value }, [
    { label: "CH₄", factor: input.ch4, scale: 1e-6, gwp: input.gwp.ch4 },
    { label: "N₂O", factor: input.n2o, scale: 1e-6, gwp: input.gwp.n2o },
  ]);
  const reported = co2.reported + others.reported;
  const recomputed = co2.recomputed + others.recomputed;
  return {
    steps: [
      inputRow("Fuel purchased", input.how ?? "Sum of monthly fuel card statements", input.fuel),
      ...co2.steps.filter((s) => !s.total),
      inputRow("Distance driven", "Odometer readings on the same statements", input.distance),
      ...others.steps.filter((s) => !s.total),
      {
        step: "Total",
        how: [{ text: "CO₂ + CH₄ + N₂O" }],
        reported: { text: totalText(reported) },
        recomputed: { text: totalText(recomputed) },
        total: true,
      },
    ],
    reported,
    recomputed,
  };
}

/** Non-road equipment: every gas per gallon. */
export function equipmentByFuel(input: {
  fuel: Sided<Quantity>;
  how?: string;
  co2: Sided<Factor>;
  ch4: Sided<Factor>;
  n2o: Sided<Factor>;
  gwp: Gwps;
}): Chain {
  const fuel = sides(input.fuel);
  const gases = gasRows({ reported: fuel.reported.value, recomputed: fuel.recomputed.value }, [
    { label: "CO₂", factor: input.co2, scale: 1e-3 },
    { label: "CH₄", factor: input.ch4, scale: 1e-6, gwp: input.gwp.ch4 },
    { label: "N₂O", factor: input.n2o, scale: 1e-6, gwp: input.gwp.n2o },
  ]);
  return { ...gases, steps: [inputRow("Fuel purchased", input.how ?? "Sum of delivery tickets", input.fuel), ...gases.steps] };
}

/** Refrigerant: kg added during service × GWP. */
export function refrigerantByMass(input: { added: Sided<Quantity>; how?: string; gwp: Sided<Factor> }): Chain {
  const added = sides(input.added);
  const gwp = factorSides(input.gwp);
  const used = applyFactor("GWP", input.gwp);
  const reported = (added.reported.value * gwp.reported.value) / 1000;
  const recomputed = (added.recomputed.value * gwp.recomputed.value) / 1000;
  const steps: CalcStep[] = [inputRow("Refrigerant added", input.how ?? "Sum of service records", input.added)];
  if (used.row) steps.push(used.row);
  steps.push(
    {
      step: "CO₂e",
      how: used.row ? [{ text: "× GWP ÷ 1,000" }] : [{ text: "× GWP " }, used.how[1], { text: " ÷ 1,000" }],
      reported: { text: tonnes(reported) },
      recomputed: { text: tonnes(recomputed) },
    },
    { step: "Total", how: [{ text: "Refrigerant added × GWP" }], reported: { text: totalText(reported) }, recomputed: { text: totalText(recomputed) }, total: true }
  );
  return { steps, reported, recomputed };
}

/** Purchased electricity, location-based: MWh × eGRID lb per MWh (× GWP). */
export function electricityByGrid(input: {
  consumption: Sided<Quantity>;
  how?: string;
  co2: Sided<Factor>;
  ch4: Sided<Factor>;
  n2o: Sided<Factor>;
  gwp: Gwps;
}): Chain {
  const consumption = sides(input.consumption);
  const gases = gasRows({ reported: consumption.reported.value, recomputed: consumption.recomputed.value }, [
    { label: "CO₂", factor: input.co2, scale: LB_TO_TONNES },
    { label: "CH₄", factor: input.ch4, scale: LB_TO_TONNES, gwp: input.gwp.ch4 },
    { label: "N₂O", factor: input.n2o, scale: LB_TO_TONNES, gwp: input.gwp.n2o },
  ]);
  return { ...gases, steps: [inputRow("Annual consumption", input.how ?? "Sum of monthly utility bills", input.consumption), ...gases.steps] };
}

/** Purchased electricity, market-based: what contracts do not cover × the grid factor. */
export function electricityByContract(input: {
  consumption: Sided<Quantity>;
  covered: Sided<Quantity>;
  how?: string;
  co2: Sided<Factor>;
  ch4: Sided<Factor>;
  n2o: Sided<Factor>;
  gwp: Gwps;
}): Chain {
  const consumption = sides(input.consumption);
  const covered = sides(input.covered);
  const uncovered = {
    reported: Math.max(consumption.reported.value - covered.reported.value, 0),
    recomputed: Math.max(consumption.recomputed.value - covered.recomputed.value, 0),
  };
  const gases = gasRows(uncovered, [
    { label: "CO₂", factor: input.co2, scale: LB_TO_TONNES },
    { label: "CH₄", factor: input.ch4, scale: LB_TO_TONNES, gwp: input.gwp.ch4 },
    { label: "N₂O", factor: input.n2o, scale: LB_TO_TONNES, gwp: input.gwp.n2o },
  ]);
  return {
    ...gases,
    steps: [
      inputRow("Annual consumption", input.how ?? "Sum of monthly utility bills", input.consumption),
      inputRow("Covered by contract", "Certificates retired under the supply contract", input.covered),
      {
        step: "Not covered",
        how: [{ text: "Consumption − covered" }],
        reported: { text: `${formatQuantity(uncovered.reported)} MWh` },
        recomputed: { text: `${formatQuantity(uncovered.recomputed)} MWh` },
      },
      ...gases.steps,
    ],
  };
}
