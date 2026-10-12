import { api } from "../../../lib/api";
import type {
  CheckOutcome,
  MaterialityFigures,
  ResultLayer,
  VerificationRow,
  WorkingSpec,
} from "../types";

/**
 * Emissions recalculation for an engagement (GET /engagements/{id}/recalculation).
 * The backend recalculates Scope 1 and Scope 2 from reviewed evidence only, on the
 * EPA GHG Emission Factors Hub 2025, following the equations in Claire's GHG Required
 * Data workbook, and compares each reported data point to the recalculated value.
 * Its inputs live in the engagement's settings.recalculation.
 */

export interface RecalcInput {
  value: number;
  unit: string;
  source: string | null;
}

export interface RecalcStep {
  label: string;
  formula: string;
  inputs: Record<string, RecalcInput>;
  result: number;
  result_unit: string;
}

export interface RecalcLine {
  key: string;
  equations: Record<string, string>;
  mass_t: Record<string, number>;
  steps: RecalcStep[];
  flags: string[];
  biogenic_co2_t: number;
}

export interface RecalcDocument {
  document_id: string;
  record: string;
  quantity: number;
  unit: string;
  share_in_period?: number;
}

export interface RecalcCategory {
  category: string;
  lines: RecalcLine[];
  total_mass_t: Record<string, number>;
  total_co2e_t: Record<string, number>;
  total_co2e: number;
  gwp: Record<string, { value: number; source: string }>;
  biogenic_co2_t: number;
  steps: RecalcStep[];
  flags: string[];
  details: {
    inputs?: { fuel: string; unit: string; quantity: number; documents: RecalcDocument[] }[];
    covered_mwh?: number;
    total_mwh?: number;
    coverage?: number;
    [key: string]: unknown;
  };
  gwp_set: string;
}

export type ComparisonStatus =
  | "within_tolerance"
  | "exceeds_tolerance"
  | "not_reported"
  | "no_evidence"
  | "not_recalculated";

export interface RecalcComparison {
  key: string;
  data_point: string;
  workbook_row: number;
  unit: string;
  reported: number | null;
  recalculated: number | null;
  difference: number | null;
  difference_pct: number | null;
  status: ComparisonStatus;
  tolerance_pct?: number;
  inputs_incomplete: boolean;
}

export interface RecalcNeedsInput {
  kind: "grid_region" | "fuel_choice" | "quantity" | "fuel_line" | "mobile";
  key: string;
  message: string;
  options?: string[];
}

export interface RecalcAwaitingReview {
  document_id: string;
  record: string;
  canonical_type_id: string;
  fields: string[];
}

export type CategoryKey =
  | "stationary_combustion"
  | "mobile_combustion"
  | "purchased_electricity_location_based"
  | "purchased_electricity_market_based";

export interface Recalculation {
  engagement_id: string;
  gwp_set: string;
  reporting_period: { start: string | null; end: string | null };
  tolerance_pct: number;
  categories: Record<CategoryKey, RecalcCategory | null>;
  scope_totals: Record<"scope1" | "scope2_location" | "scope2_market", { total_co2e: number } | null>;
  comparisons: RecalcComparison[];
  needs_input: RecalcNeedsInput[];
  awaiting_review: RecalcAwaitingReview[];
  not_recalculated: string[];
  documents_considered: number;
}

export interface RecalculationReference {
  dataset: string;
  gwp_sets: string[];
  default_gwp_set: string;
  egrid_subregions: { egrid_subregion: string; name: string }[];
  stationary_fuels: string[];
  mobile_fuels: string[];
  reported_data_points: { key: string; label: string; workbook_row: number; unit: string }[];
}

export function getRecalculation(engagementId: string): Promise<Recalculation> {
  return api<Recalculation>(`/engagements/${encodeURIComponent(engagementId)}/recalculation`);
}

export function getRecalculationReference(): Promise<RecalculationReference> {
  return api<RecalculationReference>("/reference/recalculation");
}

// --- comparison → Verification Results row ---------------------------------------------

/** Which calculation each reported data point comes from. */
const SOURCES: Record<string, CategoryKey[]> = {
  scope1_total: ["stationary_combustion", "mobile_combustion"],
  scope1_co2: ["stationary_combustion", "mobile_combustion"],
  scope1_ch4: ["stationary_combustion", "mobile_combustion"],
  scope1_n2o: ["stationary_combustion", "mobile_combustion"],
  biogenic_co2: ["stationary_combustion", "mobile_combustion"],
  stationary_combustion_total: ["stationary_combustion"],
  mobile_combustion_total: ["mobile_combustion"],
  scope2_location_total: ["purchased_electricity_location_based"],
  scope2_co2: ["purchased_electricity_location_based"],
  scope2_ch4: ["purchased_electricity_location_based"],
  scope2_n2o: ["purchased_electricity_location_based"],
  purchased_electricity_total: ["purchased_electricity_location_based"],
  scope2_market_total: ["purchased_electricity_market_based"],
};

const FORMULA: Record<CategoryKey, string> = {
  stationary_combustion:
    "Per fuel: CO₂ = fuel × EF (Eq 1, heat content or carbon content where given); CH₄, N₂O = fuel × EF. " +
    "CO₂e = Σ gas mass × GWP.",
  mobile_combustion:
    "Per fuel: CO₂ = fuel (gal or scf) × EF. CH₄, N₂O need distance by vehicle type and model year (Eq 4) or " +
    "non-road fuel use (Eq 5). CO₂e = Σ gas mass × GWP.",
  purchased_electricity_location_based:
    "Per facility: gas mass (t) = MWh × eGRID subregion factor (lb/MWh) ÷ 2,204.62. CO₂e = Σ gas mass × GWP.",
  purchased_electricity_market_based:
    "Certificate coverage = certificate MWh ÷ consumption (max 100%). Per facility: uncovered MWh × eGRID factor " +
    "(lb/MWh) ÷ 2,204.62. CO₂e = Σ gas mass × GWP.",
};

const FLAG_NOTE: Record<string, string> = {
  fuel_auto_matched: "Fuel matched to the EPA fuel automatically.",
  fuel_chosen_by_reviewer: "EPA fuel chosen by the reviewer.",
  diesel_matched_to_distillate_fuel_oil_no_2: "Stationary diesel treated as Distillate Fuel Oil No. 2.",
  prorated_to_reporting_period: "A bill crossing the reporting period was prorated by days.",
  outside_reporting_period: "A bill entirely outside the reporting period was left out.",
  no_service_period: "A bill had no service period, so all of it was counted.",
  no_reporting_period: "The engagement has no reporting period, so bills were not prorated.",
  service_period_reversed: "A bill's service period ends before it starts; all of it was counted.",
  biogenic_co2_reported_separately: "Biomass CO₂ is reported separately as biogenic, not in the total.",
  ch4_n2o_need_vehicle_groups: "CH₄ and N₂O are not included: they need vehicle type, model year and distance.",
  no_certificates_market_equals_location: "No certificates entered, so market-based equals location-based.",
  certificates_exceed_consumption: "Certificates exceed consumption; coverage was capped at 100%.",
  unit_converted: "Quantities were converted to the EPA factor's unit.",
};

const SCOPE2 = new Set(["scope2_location_total", "scope2_market_total", "scope2_co2", "scope2_ch4", "scope2_n2o",
  "purchased_electricity_total"]);

/** Two decimals for tonnes and MWh ("243.70"); small gas masses keep their significant digits. */
export function formatNumber(n: number): string {
  if (Math.abs(n) >= 1 || n === 0) return n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  return n.toLocaleString("en-US", { maximumSignificantDigits: 4 });
}

/** Inputs and factors as the source states them: no padding, up to four decimals ("1,200", "240.99"). */
function formatQuantity(n: number): string {
  return n.toLocaleString("en-US", { maximumFractionDigits: 4 });
}

function formatPct(n: number): string {
  return `${n > 0 ? "+" : ""}${n.toFixed(2)}%`;
}

function signed(n: number, text: string): string {
  return n > 0 ? `+${text}` : text;
}

function unitLabel(unit: string): string {
  return unit === "t CO2e" ? "tCO₂e" : unit;
}

function outcomeOf(c: RecalcComparison): { outcome: CheckOutcome; reason: string } {
  const tolerance = c.tolerance_pct ?? 5;
  if (c.status === "not_recalculated") {
    return { outcome: "out_of_scope", reason: "Not recalculated yet: needs purchased-gas (refrigerant) records." };
  }
  if (c.status === "no_evidence") {
    return { outcome: "could_not_check", reason: "No reviewed evidence feeds this data point yet." };
  }
  if (c.inputs_incomplete) {
    return {
      outcome: "could_not_check",
      reason: "Recalculation incomplete: some evidence is awaiting review or an input is missing.",
    };
  }
  if (c.status === "not_reported") {
    return { outcome: "could_not_check", reason: "Enter the reported value under Recalculation inputs." };
  }
  const pct = c.difference_pct ?? 0;
  return c.status === "within_tolerance"
    ? { outcome: "held", reason: `Within the ±${tolerance}% materiality tolerance.` }
    : { outcome: "exception", reason: `Exceeds the ±${tolerance}% materiality tolerance by ${(Math.abs(pct) - tolerance).toFixed(2)} points.` };
}

function sourceOf(category: RecalcCategory, line: RecalcLine): string | undefined {
  const input = category.details.inputs?.find((item) => item.fuel === line.key);
  if (!input) return undefined;
  return input.documents
    .map((doc) => {
      const share = doc.share_in_period !== undefined && doc.share_in_period < 1
        ? ` (${Math.round(doc.share_in_period * 100)}% in period)` : "";
      return `${doc.record}${share}`;
    })
    .join(" · ");
}

function workingFor(c: RecalcComparison, result: Recalculation): WorkingSpec | undefined {
  const categories = (SOURCES[c.key] ?? [])
    .map((key) => [key, result.categories[key]] as const)
    .filter((entry): entry is readonly [CategoryKey, RecalcCategory] => entry[1] !== null);
  if (categories.length === 0) return undefined;

  const inputs: WorkingSpec["inputs"] = [];
  const factors = new Map<string, { label: string; value: string; source: string }>();
  const references = new Set<string>();
  const notes = new Set<string>();

  for (const [, category] of categories) {
    for (const line of category.lines) {
      const activity = Object.values(line.steps[0]?.inputs ?? {})[0];
      if (activity) {
        inputs.push({
          label: line.key,
          value: `${formatQuantity(activity.value)} ${activity.unit}`,
          source: sourceOf(category, line),
        });
      }
      for (const step of line.steps) {
        for (const [name, input] of Object.entries(step.inputs)) {
          if (!input.source) continue;
          const label = `${line.key} · ${step.label.replace(/ in metric tons$/, "")}`;
          factors.set(`${label}|${name}`, {
            label: name === "EF" ? label : `${label} · ${name}`,
            value: `${formatQuantity(input.value)} ${input.unit}`,
            source: input.source,
          });
          references.add(input.source.replace(/, row \d+.*$/, ""));
        }
      }
      line.flags.forEach((flag) => FLAG_NOTE[flag] && notes.add(FLAG_NOTE[flag]));
    }
    category.flags.forEach((flag) => FLAG_NOTE[flag] && notes.add(FLAG_NOTE[flag]));
    for (const [gas, gwp] of Object.entries(category.gwp)) {
      factors.set(`GWP|${gas}`, { label: `GWP ${gas} (${category.gwp_set})`, value: String(gwp.value), source: gwp.source });
    }
    const coverage = category.details.coverage;
    if (typeof coverage === "number") {
      inputs.push({
        label: "Certificates",
        value: `${formatQuantity(category.details.covered_mwh ?? 0)} of ${formatQuantity(category.details.total_mwh ?? 0)} MWh`,
        source: `${formatQuantity(coverage * 100)}% coverage, applied pro rata to each facility`,
      });
    }
  }

  const unit = unitLabel(c.unit);
  let resultText: string | undefined;
  if (c.recalculated !== null) {
    resultText = `Recalculated ${formatNumber(c.recalculated)} ${unit}`;
    if (c.reported !== null && c.difference !== null) {
      resultText += ` vs reported ${formatNumber(c.reported)} ${unit}: difference ${signed(c.difference, formatNumber(c.difference))} ${unit}`;
      if (c.difference_pct !== null) resultText += ` (${formatPct(c.difference_pct)})`;
      resultText += c.status === "exceeds_tolerance" ? ", exceeds tolerance." : ", within tolerance.";
    } else {
      resultText += ". Reported value not entered yet.";
    }
  }

  return {
    formula: categories.map(([key]) => FORMULA[key]).join(" "),
    inputs,
    factors: Array.from(factors.values()),
    result: resultText,
    references: [
      ...Array.from(references),
      `GHG Required Data workbook, row ${c.workbook_row} (${c.data_point})`,
    ],
    note: notes.size ? Array.from(notes).join(" ") : undefined,
  };
}

export function recalculationRows(result: Recalculation): VerificationRow[] {
  return result.comparisons.map((c) => {
    const layer: ResultLayer = SCOPE2.has(c.key) ? "scope2" : "scope1";
    const { outcome, reason } = outcomeOf(c);
    const scopeBasis = c.key === "scope2_market_total" ? "market" : SCOPE2.has(c.key) ? "location" : undefined;
    return {
      dataPointId: `RECALC-${c.key}`,
      methodologyFieldId: c.key,
      label: c.data_point,
      layer,
      scopeBasis,
      reportedValue: c.reported !== null ? formatNumber(c.reported) : "",
      unit: unitLabel(c.unit),
      recomputed: c.recalculated !== null ? formatNumber(c.recalculated) : null,
      recomputeReason: c.recalculated === null
        ? c.status === "not_recalculated" ? "fugitive gases are not recalculated yet" : "no reviewed evidence yet"
        : undefined,
      delta: c.difference_pct !== null ? formatPct(c.difference_pct) : null,
      checkOutcome: outcome,
      checkReason: reason,
      working: workingFor(c, result),
    };
  });
}

/** Materiality on the headline totals only (Scope 1 + Scope 2 location-based), so nothing is counted twice. */
export function recalculationMateriality(result: Recalculation): MaterialityFigures {
  const headline = result.comparisons.filter((c) => c.key === "scope1_total" || c.key === "scope2_location_total");
  const reported = headline.filter((c) => c.reported !== null);
  const total = reported.reduce((sum, c) => sum + (c.reported ?? 0), 0);
  const checked = headline.filter((c) => c.difference !== null && !c.inputs_incomplete);
  const misstatement = checked.reduce((sum, c) => sum + Math.abs(c.difference ?? 0), 0);
  const uncorrected = checked
    .filter((c) => c.status === "exceeds_tolerance")
    .reduce((sum, c) => sum + Math.abs(c.difference ?? 0), 0);
  const open = result.needs_input.length + result.awaiting_review.length;
  return {
    total,
    totalBasis: reported.length === headline.length ? "Scope 1 + Scope 2, as reported" : "Reported totals entered so far",
    tolerancePct: result.tolerance_pct,
    misstatement,
    uncorrected,
    note:
      `Misstatement is the difference between reported and recalculated Scope 1 and Scope 2 (location-based) ` +
      `totals, from ${result.documents_considered} document(s) with reviewed values, at ${result.gwp_set} GWPs. ` +
      (open
        ? `${open} item(s) still need an input or a review, so the conclusion stays provisional.`
        : "Nothing is waiting on an input or a review."),
  };
}
