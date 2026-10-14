import { api } from "../../../lib/api";
import type {
  CheckOutcome,
  CoverageRule,
  InScopeField,
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
  /** Refrigerant records: service, installation or disposal. */
  service_type?: string;
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
    inputs?: {
      fuel: string;
      unit: string;
      quantity: number;
      documents: RecalcDocument[];
      /** Electricity: the facility's eGRID subregion and where it came from. */
      grid_region?: string;
      grid_region_source?: string | null;
    }[];
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
  | "not_recalculated"
  /** Setup says the engagement does not cover it: shown, never judged. */
  | "not_in_scope";

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
  kind:
    | "grid_region"
    | "fuel_choice"
    | "quantity"
    | "fuel_line"
    | "mobile"
    | "refrigerant_gwp"
    | "vehicle_group"
    | "refrigerant_record";
  key: string;
  message: string;
  options?: string[];
  /** The roll-up source the question holds open (absent from older results). */
  category?: RollupSourceKey;
}

export interface RecalcAwaitingReview {
  document_id: string;
  record: string;
  canonical_type_id: string;
  fields: string[];
  /** The roll-up source the record belongs to (absent from older results). */
  category?: RollupSourceKey;
}

/** Why a reviewed record was left out of the numbers. */
export type ExcludedReason =
  | "outside_reporting_period"
  | "withdrawn"
  | "duplicate"
  | "superseded"
  | "montreal_protocol_gas";

const EXCLUDED_LABEL: Record<ExcludedReason, string> = {
  outside_reporting_period: "outside the reporting period",
  withdrawn: "withdrawn by the reviewer",
  duplicate: "marked as a duplicate",
  superseded: "superseded by a newer document",
  montreal_protocol_gas: "a CFC or HCFC, which Scope 1 leaves out",
};

export interface ExcludedRecord {
  document_id: string;
  record: string;
  canonical_type_id: string;
  period: string;
  reason?: ExcludedReason;
  /** Refrigerant left out as a Montreal Protocol gas. */
  gas?: string;
}

function reasonOf(item: { reason?: ExcludedReason }): ExcludedReason {
  return item.reason ?? "outside_reporting_period";
}

/** "1 withdrawn by the reviewer, 2 outside the reporting period". */
function describeLeftOut(items: { reason?: ExcludedReason }[]): string {
  const counts = new Map<ExcludedReason, number>();
  items.forEach((item) => counts.set(reasonOf(item), (counts.get(reasonOf(item)) ?? 0) + 1));
  return [...counts].map(([reason, n]) => `${n} ${EXCLUDED_LABEL[reason]}`).join(", ");
}

export function leftOutMessage(item: { record: string; period: string; reason?: ExcludedReason; gas?: string }): string {
  const reason = reasonOf(item);
  if (reason === "montreal_protocol_gas") {
    return `${item.record}: ${item.gas ?? "the refrigerant"} is a CFC or HCFC (a Montreal Protocol gas). The GHG ` +
      "Protocol reports these outside Scope 1, so it is not counted.";
  }
  return reason === "outside_reporting_period"
    ? `${item.record} (${item.period}) is outside the reporting period, so it is not counted.`
    : `${item.record} is ${EXCLUDED_LABEL[reason]}, so it is not counted.`;
}

export type CategoryKey =
  | "stationary_combustion"
  | "mobile_combustion"
  | "fugitive_refrigerants"
  | "purchased_electricity_location_based"
  | "purchased_electricity_market_based";

export interface Recalculation {
  engagement_id: string;
  gwp_set: string;
  reporting_period: { start: string | null; end: string | null };
  tolerance_pct: number;
  /** fugitive_refrigerants is missing from results computed before refrigerants were added. */
  categories: Record<Exclude<CategoryKey, "fugitive_refrigerants">, RecalcCategory | null> &
    Partial<Record<"fugitive_refrigerants", RecalcCategory | null>>;
  scope_totals: Record<"scope1" | "scope2_location" | "scope2_market", { total_co2e: number } | null>;
  comparisons: RecalcComparison[];
  needs_input: RecalcNeedsInput[];
  awaiting_review: RecalcAwaitingReview[];
  /** Reviewed records entirely outside the reporting period: listed, never counted. */
  excluded?: ExcludedRecord[];
  not_recalculated: string[];
  documents_considered: number;
  /** Category results to Scope 1, Scope 2 and inventory totals, then the final outputs.
   *  Absent from results computed before the roll-up; fall back to `comparisons`. */
  rollup?: Rollup;
}

// ---------------------------------------------------------------------------------------
// Emissions roll-up (backend/app/services/emissions_rollup.py). Numbers are unrounded
// metric tonnes; null means "not available", never 0.
// ---------------------------------------------------------------------------------------
export type GasGroup = "CO2" | "CH4" | "N2O" | "HFCs" | "PFCs" | "SF6" | "NF3" | "other";

export type RollupSourceKey =
  | "stationary_combustion"
  | "mobile_combustion"
  | "process_sources"
  | "fugitive_refrigerants"
  | "fugitive_purchased_gases"
  | "agricultural_sources"
  | "purchased_electricity"
  | "purchased_steam"
  | "purchased_heating"
  | "purchased_cooling";

/** calculated / partial carry numbers; confirmed_absent is a true 0 (the reviewer said the
 *  company has none); the rest are null. */
export type SourceStatus =
  | "calculated"
  | "partial"
  | "awaiting_inputs"
  | "confirmed_absent"
  | "no_evidence"
  | "not_built";

export type NodeStatus = "complete" | "partial" | "not_available";

export type MissingReason =
  | "not_built"
  | "no_evidence"
  | "awaiting_inputs"
  | "inputs_open"
  | "vehicle_groups_missing"
  | "gas_split_unknown";

/** The comparison statuses plus incomplete (a partial total: never within tolerance) and
 *  needs_unit (a per-gas row whose unit, t or t CO2e, is not set). */
export type OutputStatus = ComparisonStatus | "incomplete" | "needs_unit";

export interface GasAmount {
  mass_t: number;
  co2e_t: number;
}

export interface RollupCategory {
  label: string;
  scope: "scope1" | "scope2";
  workbook_row: number;
  built: boolean;
  backend_categories: Partial<Record<"location" | "market", string>>;
  gases: GasGroup[];
  status: SourceStatus;
  open_items: number;
  gaps: { gap: MissingReason; gases: GasGroup[]; affects_total: boolean }[];
  absent_reason: string | null;
  flags: string[];
  /** Fugitive refrigerants: each line split into gas groups. */
  gas_split?: Record<string, { groups: Partial<Record<GasGroup, GasAmount>>; flags: string[] }>;
}

export interface RollupTerm {
  /** "category:<source>" or "node:<node key>". */
  ref: string;
  co2e_t: number | null;
  mass_t?: number | null;
  status: SourceStatus | NodeStatus;
}

export interface RollupMissing {
  source: RollupSourceKey;
  reason: MissingReason;
}

export interface RollupNode {
  step: "step_1a" | "step_1b" | "step_2";
  label: string;
  kind: "category" | "gas" | "total" | "memo";
  scope: "scope1" | "scope2_location" | "scope2_market" | "inventory_location" | "inventory_market";
  unit: string;
  formula: string;
  co2e_t: number | null;
  /** Gas nodes only: tonnes of the gas itself. */
  gas?: GasGroup;
  mass_t?: number | null;
  status: NodeStatus;
  terms: RollupTerm[];
  missing: RollupMissing[];
  /** A partial value that can only grow (no negative contributions). */
  lower_bound: boolean;
  flags: string[];
  /** Category nodes: the value split into gas groups. */
  gases?: Partial<Record<GasGroup, GasAmount>>;
  basis?: "structural_zero";
}

export interface RollupFinalOutput {
  key: string;
  label: string;
  workbook_row: number;
  requirement: "Required" | "Optional";
  node: string;
  measure: "co2e_t" | "mass_t" | null;
  unit: "t CO2e" | "t" | null;
  reported: number | null;
  reported_unit: "t" | "t CO2e" | null;
  recalculated: number | null;
  difference: number | null;
  difference_pct: number | null;
  tolerance_pct: number;
  within_threshold: boolean | null;
  status: OutputStatus;
  reason: string | null;
  completeness: NodeStatus;
  missing: RollupMissing[];
  flags: string[];
  /** Per-gas rows: both measures, until the reported unit is known. */
  candidates?: { mass_t: number | null; co2e_t: number | null };
  unit_hint?: "t" | "t CO2e" | null;
}

export interface RollupStep {
  key: "step_1a" | "step_1b" | "step_2" | "final_outputs";
  label: string;
  order: number;
  node_keys?: string[];
  output_keys?: string[];
}

export interface Rollup {
  version: number;
  gwp_set: string;
  tolerance_pct: number;
  gas_groups: GasGroup[];
  steps: RollupStep[];
  categories: Record<RollupSourceKey, RollupCategory>;
  nodes: Record<string, RollupNode>;
  final_outputs: RollupFinalOutput[];
  /** Each total against the sum of its gases, and each inventory total against its scopes. */
  checks: { key: string; total: number; sum: number; ok: boolean }[];
}

/** The roll-up's structure with no values (GET /v1/reference/recalculation). */
export interface RollupLayout {
  version: number;
  steps: RollupStep[];
  sources: { key: RollupSourceKey; label: string; scope: "scope1" | "scope2"; workbook_row: number; built: boolean;
    gases: GasGroup[] }[];
  nodes: { key: string; step: RollupNode["step"]; label: string; unit: string; kind: RollupNode["kind"];
    scope: RollupNode["scope"]; gas: GasGroup | null; formula: string; terms: string[]; structural_zero: boolean }[];
  final_outputs: { key: string; label: string; workbook_row: number; requirement: "Required" | "Optional";
    node: string; default_measure: "co2e_t" | "mass_t" | null; unit: "t CO2e" | "t" | null;
    unit_settable: boolean }[];
}

/** A vehicle type with CH4/N2O factors: on-road (Tables 3-4) or non-road (Table 5). */
export interface VehicleTypeOption {
  vehicle_type: string;
  fuel_type: string;
  on_road: boolean;
  by_model_year: boolean;
  first_model_year: number | null;
  last_model_year: number | null;
}

/** A reported data point in the GHG Required Data workbook (rows 22-50). */
export interface DataPointOption {
  key: string;
  label: string;
  workbook_row: number;
  unit: string;
  layer: "scope1" | "scope2";
  requirement: "Required" | "Optional";
  check: "recalculated" | "compared_under_fugitive" | "not_recalculated";
}

export interface RecalculationReference {
  dataset: string;
  gwp_sets: string[];
  default_gwp_set: string;
  egrid_subregions: { egrid_subregion: string; name: string }[];
  stationary_fuels: string[];
  mobile_fuels: string[];
  /** Absent from an API that predates vehicle groups. */
  vehicle_types?: VehicleTypeOption[];
  reported_data_points: { key: string; label: string; workbook_row: number; unit: string }[];
  /** Absent from an API that predates the in-scope list. */
  data_points?: DataPointOption[];
  /** Absent from an API that predates the roll-up. */
  rollup_layout?: RollupLayout;
}

const CHECKED_BY: Record<DataPointOption["check"], string> = {
  recalculated: "Recalculated from reviewed evidence",
  compared_under_fugitive: "Compared under fugitive sources",
  not_recalculated: "Not recalculated yet",
};

/** Setup's in-scope rows from the workbook's data points and the engagement's choices. */
export function inScopeFieldsFrom(points: DataPointOption[], outOfScope: string[] | undefined): InScopeField[] {
  const out = new Set(outOfScope ?? []);
  return points.map((p) => ({
    methodologyFieldId: p.key,
    label: p.label,
    layer: p.layer,
    requirementLevel: p.requirement,
    valueOrigin: null,
    inScope: !out.has(p.key),
    completenessStatus: null,
    workbookRow: p.workbook_row,
    checkedBy: CHECKED_BY[p.check],
  }));
}

export function getRecalculation(engagementId: string): Promise<Recalculation> {
  return api<Recalculation>(`/engagements/${encodeURIComponent(engagementId)}/recalculation`);
}

export function getRecalculationReference(): Promise<RecalculationReference> {
  return api<RecalculationReference>("/reference/recalculation");
}

/** The ZIP code ending a US address ("Albany, NY 12207-1234" -> "12207"). A 5-digit number
 *  elsewhere is a street number ("12345 Main St"), never a ZIP code. Same rule as the backend. */
export function zipFromAddress(address: string | null | undefined): string | null {
  const text = (address ?? "").split(/\s+/).filter(Boolean).join(" ");
  const match = /(?<![\d-])(\d{5})(?:-\d{4})?\s*(?:,?\s*(?:USA|U\.S\.A\.|US|United States))?\s*$/i.exec(text);
  return match ? match[1] : null;
}

/** eGRID subregions for a ZIP code (EPA Power Profiler, eGRID2023); [] when EPA does not list it. */
export function lookupEgridZip(zip: string): Promise<string[]> {
  return api<{ zip: string; subregions: string[] }>(`/reference/egrid-zip/${encodeURIComponent(zip)}`).then(
    (body) => body.subregions,
    () => []
  );
}

// --- comparison → Verification Results row ---------------------------------------------

/** Which calculation each reported data point comes from. */
const SOURCES: Record<string, CategoryKey[]> = {
  scope1_total: ["stationary_combustion", "mobile_combustion", "fugitive_refrigerants"],
  scope1_co2: ["stationary_combustion", "mobile_combustion"],
  scope1_ch4: ["stationary_combustion", "mobile_combustion"],
  scope1_n2o: ["stationary_combustion", "mobile_combustion"],
  biogenic_co2: ["stationary_combustion", "mobile_combustion"],
  stationary_combustion_total: ["stationary_combustion"],
  mobile_combustion_total: ["mobile_combustion"],
  fugitive_total: ["fugitive_refrigerants"],
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
  fugitive_refrigerants:
    "Per refrigerant (simplified material balance): emissions = (P_N − C_N) + P_S + (C_D − R_D). P_S is " +
    "refrigerant added when servicing; P_N and C_N are refrigerant charged into new equipment and its full charge; " +
    "C_D and R_D are the full charge of retired equipment and what was recovered. CO₂e = mass × GWP (EPA Hub " +
    "Table 11, blends Table 12).",
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
  ch4_n2o_need_vehicle_groups:
    "CH₄ and N₂O are not included for a fuel without vehicle groups: add them under Recalculation inputs.",
  model_year_newer_than_table:
    "A vehicle newer than the EPA table's latest model year uses that latest year's factor.",
  model_year_older_than_table:
    "A vehicle older than the EPA table's first model year uses that first year's factor.",
  no_certificates_market_equals_location: "No certificates entered, so market-based equals location-based.",
  grid_region_from_zip: "A facility's eGRID subregion came from its ZIP code (EPA Power Profiler, eGRID2023).",
  certificates_exceed_consumption: "Certificates exceed consumption; coverage was capped at 100%.",
  unit_converted: "Quantities were converted to the EPA factor's unit.",
  negative_refrigerant_emissions:
    "A refrigerant's balance is negative (more recovered than the retired equipment held, or new equipment charged " +
    "below its full charge). Check those records.",
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

/** Which document type feeds each category-level data point (for "why is there no number"). */
const DATA_POINT_TYPE: Record<string, string> = {
  stationary_combustion_total: "CT-S1-FUELQTY",
  mobile_combustion_total: "CT-S1-MOBFUEL",
  fugitive_total: "CT-S1-REFRSVC",
  purchased_electricity_total: "CT-S2-ELEC",
  scope2_location_total: "CT-S2-ELEC",
  scope2_market_total: "CT-S2-ELEC",
};

function outcomeOf(c: RecalcComparison, result?: Recalculation): { outcome: CheckOutcome; reason: string } {
  const tolerance = c.tolerance_pct ?? 5;
  if (c.status === "not_in_scope") {
    return { outcome: "out_of_scope", reason: "Not in scope for this engagement (set in Setup)." };
  }
  if (c.status === "not_recalculated") {
    return {
      outcome: "out_of_scope",
      reason: "Per-gas HFC, PFC and SF6 totals are not compared yet. Refrigerant emissions are recalculated under " +
        "Direct emissions from fugitive sources.",
    };
  }
  if (c.status === "no_evidence") {
    const typeId = DATA_POINT_TYPE[c.key];
    const leftOut = typeId ? (result?.excluded ?? []).filter((e) => e.canonical_type_id === typeId) : [];
    return {
      outcome: "could_not_check",
      reason: leftOut.length
        ? `Every reviewed record for this is left out (${describeLeftOut(leftOut)}), so none are counted.`
        : "No reviewed evidence feeds this data point yet.",
    };
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

/** Which refrigerant records feed each material-balance term. */
const TERM_SERVICE: Record<string, string> = { P_S: "service", P_N: "installation", C_N: "installation",
  C_D: "disposal", R_D: "disposal" };

function sourceOf(category: RecalcCategory, line: RecalcLine, term?: string): string | undefined {
  const input = category.details.inputs?.find((item) => item.fuel === line.key);
  if (!input) return undefined;
  const serviceType = term ? TERM_SERVICE[term.slice(0, 3)] : undefined;
  const region = input.grid_region
    ? ` · subregion ${input.grid_region}${input.grid_region_source?.startsWith("ZIP")
      ? ` from ${input.grid_region_source.split(" (")[0]}`
      : input.grid_region_source ? ` ${input.grid_region_source}` : ""}`
    : "";
  return input.documents
    .filter((doc) => !serviceType || !doc.service_type || doc.service_type === serviceType)
    .map((doc) => {
      const share = doc.share_in_period !== undefined && doc.share_in_period < 1
        ? ` (${Math.round(doc.share_in_period * 100)}% in period)` : "";
      return `${doc.record}${share}`;
    })
    .join(" · ") + region;
}

function workingFor(c: RecalcComparison, result: Recalculation): WorkingSpec | undefined {
  const categories = (SOURCES[c.key] ?? [])
    .map((key) => [key, result.categories[key] ?? null] as const)
    .filter((entry): entry is readonly [CategoryKey, RecalcCategory] => entry[1] !== null);
  if (categories.length === 0) return undefined;

  const inputs: WorkingSpec["inputs"] = [];
  const factors = new Map<string, { label: string; value: string; source: string }>();
  const references = new Set<string>();
  const notes = new Set<string>();

  for (const [, category] of categories) {
    for (const line of category.lines) {
      if (category.category === "fugitive_refrigerants") {
        // Every material-balance term the records gave: "R-410A · P_S (added when servicing)".
        for (const [term, input] of Object.entries(line.steps[0]?.inputs ?? {})) {
          inputs.push({ label: `${line.key} · ${term}`, value: `${formatQuantity(input.value)} ${input.unit}`,
            source: sourceOf(category, line, term) });
        }
      }
      const activity = category.category === "fugitive_refrigerants" ? undefined : Object.values(line.steps[0]?.inputs ?? {})[0];
      if (activity) {
        inputs.push({
          label: line.key,
          value: `${formatQuantity(activity.value)} ${activity.unit}`,
          source: sourceOf(category, line),
        });
      }
      for (const step of line.steps) {
        // A refrigerant's amounts are inputs (listed above) and its GWP is listed once per gas below.
        if (category.category === "fugitive_refrigerants") continue;
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
      if (category.category === "fugitive_refrigerants") references.add(gwp.source.replace(/, row \d+.*$/, ""));
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
    const { outcome, reason } = outcomeOf(c, result);
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
        ? c.status === "not_in_scope"
          ? "not in scope"
          : c.status === "not_recalculated"
          ? "compared under fugitive sources"
          : DATA_POINT_TYPE[c.key] && (result.excluded ?? []).some((e) => e.canonical_type_id === DATA_POINT_TYPE[c.key])
            ? "its records are left out (see why)"
            : "no reviewed evidence yet"
        : undefined,
      delta: c.difference_pct !== null ? formatPct(c.difference_pct) : null,
      checkOutcome: outcome,
      checkReason: reason,
      working: workingFor(c, result),
    };
  });
}

/** Materiality on the headline totals only (Scope 1 + Scope 2 location-based), so nothing is
 *  counted twice. The total is what was reported; where a total was not entered yet, the
 *  recalculated one stands in (and the label says so) rather than shrinking the threshold. */
export function recalculationMateriality(result: Recalculation): MaterialityFigures {
  const headline = result.comparisons.filter(
    (c) =>
      (c.key === "scope1_total" || c.key === "scope2_location_total") &&
      c.status !== "not_in_scope" &&
      (c.reported !== null || c.recalculated !== null)
  );
  const total = headline.reduce((sum, c) => sum + (c.reported ?? c.recalculated ?? 0), 0);
  const allReported = headline.every((c) => c.reported !== null);
  const checked = headline.filter((c) => c.difference !== null && !c.inputs_incomplete);
  const misstatement = checked.reduce((sum, c) => sum + Math.abs(c.difference ?? 0), 0);
  const uncorrected = checked
    .filter((c) => c.status === "exceeds_tolerance")
    .reduce((sum, c) => sum + Math.abs(c.difference ?? 0), 0);
  const open = result.needs_input.length + result.awaiting_review.length;
  return {
    total,
    totalBasis: allReported
      ? "Scope 1 + Scope 2, as reported"
      : "Scope 1 + Scope 2: reported where entered, recalculated otherwise",
    tolerancePct: result.tolerance_pct,
    misstatement,
    uncorrected,
    note:
      `Misstatement is the difference between reported and recalculated Scope 1 and Scope 2 (location-based) ` +
      `totals, from ${result.documents_considered} document(s) with reviewed values, at ${result.gwp_set} GWPs. ` +
      (open
        ? `${open} item(s) still need an input or a review, so the conclusion stays provisional.`
        : allReported
          ? "Nothing is waiting on an input or a review."
          : "Enter every reported total to compare them all; until then the threshold uses the recalculated figure."),
  };
}

// --- recalculation → Check coverage ----------------------------------------------------

const TYPE_LABEL: Record<string, string> = {
  "CT-S1-FUELQTY": "stationary fuel",
  "CT-S1-MOBFUEL": "vehicle fuel",
  "CT-S1-REFRSVC": "refrigerant",
  "CT-S2-ELEC": "electricity",
};

function awaitingFor(result: Recalculation, typeId: string): string[] {
  return result.awaiting_review.filter((a) => a.canonical_type_id === typeId).map((a) => a.record);
}

function listed(items: string[], max = 3): string {
  const unique = Array.from(new Set(items));
  return unique.length <= max ? unique.join(", ") : `${unique.slice(0, max).join(", ")} and ${unique.length - max} more`;
}

/**
 * What the recalculation could and could not check, from its own result: which inputs
 * are present, which are missing and why. Nothing here is a guess about rules that did
 * not run; every row restates something the backend reported.
 */
export function coverageFromRecalculation(result: Recalculation): CoverageRule[] {
  const rules: CoverageRule[] = [];
  const reported = (key: string) => result.comparisons.find((c) => c.key === key);

  const fuelRule = (
    ruleId: string,
    assertion: string,
    category: RecalcCategory | null,
    typeId: string,
    kind: "stationary" | "mobile",
    appliesTo: string[]
  ) => {
    const waiting = awaitingFor(result, typeId);
    const choices = result.needs_input.filter(
      (n) => n.key.startsWith(`${kind}:`) || (kind === "mobile" && (n.kind === "mobile" || n.kind === "vehicle_group"))
    );
    if (waiting.length || choices.length) {
      const parts = [
        category ? `Recalculated so far: ${category.lines.map((l) => l.key).join(", ")}` : "",
        waiting.length ? `${waiting.length} record(s) awaiting review (${listed(waiting)})` : "",
        choices.length ? choices.map((c) => c.message).join(" ") : "",
      ].filter(Boolean);
      rules.push({ ruleId, assertion, appliesTo, status: "inputs_missing", reason: parts.join(". ") });
    } else if (category) {
      const docs = (category.details.inputs ?? []).reduce((n, i) => n + i.documents.length, 0);
      const vehicles = category.flags.includes("ch4_n2o_need_vehicle_groups")
        ? " CH4 and N2O need vehicle groups (type, model year, distance), so they are not included for every fuel yet."
        : "";
      rules.push({
        ruleId,
        assertion,
        appliesTo,
        status: "inputs_present",
        reason: `${category.lines.map((l) => l.key).join(", ")} from ${docs} reviewed record(s).${vehicles}`,
      });
    } else {
      const leftOut = (result.excluded ?? []).filter((e) => e.canonical_type_id === typeId);
      rules.push({
        ruleId,
        assertion,
        appliesTo,
        status: "not_applicable",
        reason: leftOut.length
          ? `Every reviewed ${TYPE_LABEL[typeId]} record is left out (${describeLeftOut(leftOut)}), so none are counted.`
          : `No reviewed ${TYPE_LABEL[typeId]} documents in this engagement.`,
      });
    }
  };

  fuelRule(
    "COV-S1-STATIONARY",
    "Fuel burned on site is recalculated from reviewed bills with EPA Hub Table 1 factors",
    result.categories.stationary_combustion,
    "CT-S1-FUELQTY",
    "stationary",
    ["Direct emissions from stationary combustion", "Scope 1 (Total)"]
  );
  fuelRule(
    "COV-S1-MOBILE",
    "Vehicle fuel is recalculated from reviewed fuel records with EPA Hub Table 2 factors",
    result.categories.mobile_combustion,
    "CT-S1-MOBFUEL",
    "mobile",
    ["Direct emissions from mobile combustion", "Scope 1 (Total)"]
  );

  const regions = result.needs_input.filter((n) => n.kind === "grid_region");
  const elecWaiting = awaitingFor(result, "CT-S2-ELEC");
  const location = result.categories.purchased_electricity_location_based;
  const elecAppliesTo = ["Scope 2 (Total), location-based", "Indirect emissions from purchased electricity"];
  if (regions.length || elecWaiting.length) {
    rules.push({
      ruleId: "COV-S2-LOCATION",
      assertion: "Purchased electricity is recalculated with each facility's eGRID subregion factor (EPA Hub Table 6)",
      appliesTo: elecAppliesTo,
      status: "inputs_missing",
      reason: [
        regions.length ? `Grid region not chosen for ${listed(regions.map((r) => r.key))}` : "",
        elecWaiting.length ? `${elecWaiting.length} bill(s) awaiting review (${listed(elecWaiting)})` : "",
      ].filter(Boolean).join(". "),
    });
  } else if (location) {
    rules.push({
      ruleId: "COV-S2-LOCATION",
      assertion: "Purchased electricity is recalculated with each facility's eGRID subregion factor (EPA Hub Table 6)",
      appliesTo: elecAppliesTo,
      status: "inputs_present",
      reason: `${location.lines.length} facilit${location.lines.length === 1 ? "y" : "ies"}: ${location.lines.map((l) => l.key).join(", ")}.`,
    });
  } else {
    rules.push({
      ruleId: "COV-S2-LOCATION",
      assertion: "Purchased electricity is recalculated with each facility's eGRID subregion factor (EPA Hub Table 6)",
      appliesTo: elecAppliesTo,
      status: "not_applicable",
      reason: "No reviewed electricity bills in this engagement.",
    });
  }

  const market = result.categories.purchased_electricity_market_based;
  if (market) {
    const noCerts = market.flags.includes("no_certificates_market_equals_location");
    rules.push({
      ruleId: "COV-S2-MARKET",
      assertion: "Market-based Scope 2 applies renewable energy certificates pro rata to each facility",
      appliesTo: ["Scope 2 (Total), market-based"],
      status: "inputs_present",
      reason: noCerts
        ? "No certificates entered, so market-based equals location-based."
        : `${formatQuantity(market.details.covered_mwh ?? 0)} of ${formatQuantity(market.details.total_mwh ?? 0)} MWh covered by certificates.`,
    });
  }

  const missingReported = ["scope1_total", "scope2_location_total", "scope2_market_total"]
    .map(reported)
    .filter((c): c is RecalcComparison => !!c && c.status !== "not_in_scope" && c.recalculated !== null && c.reported === null);
  const headline = ["scope1_total", "scope2_location_total", "scope2_market_total"].map(reported).filter(
    (c): c is RecalcComparison => !!c && c.status !== "not_in_scope" && c.recalculated !== null
  );
  if (headline.length) {
    rules.push({
      ruleId: "COV-REPORTED",
      assertion: "The client's reported totals are compared with the recalculation at the materiality tolerance",
      appliesTo: headline.map((c) => c.data_point),
      status: missingReported.length ? "inputs_missing" : "inputs_present",
      reason: missingReported.length
        ? `Reported value not entered for ${listed(missingReported.map((c) => c.data_point))}.`
        : `All entered; tolerance ±${result.tolerance_pct}%.`,
    });
  }

  const excluded = (result.excluded ?? []).filter((e) => reasonOf(e) === "outside_reporting_period");
  const setAside = (result.excluded ?? []).filter(
    (e) => reasonOf(e) !== "outside_reporting_period" && reasonOf(e) !== "montreal_protocol_gas"
  );
  if (setAside.length) {
    rules.push({
      ruleId: "COV-DECISIONS",
      assertion: "Documents the reviewer withdrew, marked as duplicates or replaced are left out of the numbers",
      appliesTo: ["All recalculated data points"],
      status: "inputs_present",
      reason: setAside.map((e) => `${e.record} (${EXCLUDED_LABEL[reasonOf(e)]})`).join("; ") + ".",
    });
  }
  rules.push({
    ruleId: "COV-PERIOD",
    assertion: "Bills are counted only for the days inside the reporting period",
    appliesTo: ["All recalculated data points"],
    status: result.reporting_period.start && result.reporting_period.end ? "inputs_present" : "inputs_missing",
    reason:
      result.reporting_period.start && result.reporting_period.end
        ? `${result.reporting_period.start} to ${result.reporting_period.end}.` +
          (excluded.length
            ? ` ${excluded.length} record(s) fall entirely outside it and are not counted: ${listed(excluded.map((e) => `${e.record} (${e.period})`))}.`
            : "")
        : "Set the reporting period in Setup; until then bills are counted in full.",
  });

  rules.push({
    ruleId: "COV-GWP",
    assertion: "CH4, N2O and other gases are converted to CO2e on one documented GWP basis",
    appliesTo: ["All CO2e data points"],
    status: "inputs_present",
    reason: `${result.gwp_set} (${result.gwp_set === "AR5" ? "EPA Hub Table 11" : "IPCC AR6"}).`,
  });

  rules.push(refrigerantRule(result));

  for (const item of result.not_recalculated) {
    rules.push({
      ruleId: `COV-NOT-${item.replace(/\W+/g, "-").toUpperCase()}`,
      assertion: `${item} are recalculated`,
      appliesTo: [item],
      status: "out_of_scope",
      reason: "Not built yet.",
    });
  }

  return rules;
}

/** Refrigerants and fire suppression: reviewed service records through the material balance. */
function refrigerantRule(result: Recalculation): CoverageRule {
  const base = {
    ruleId: "COV-S1-FUGITIVE",
    assertion: "Refrigerant and fire-suppression gas emissions are recalculated with the simplified material balance",
    appliesTo: ["Direct emissions from fugitive sources", "Scope 1 (Total)"],
  };
  const category = result.categories.fugitive_refrigerants ?? null;
  const waiting = awaitingFor(result, "CT-S1-REFRSVC");
  const gwps = result.needs_input.filter((n) => n.kind === "refrigerant_gwp");
  const amounts = result.needs_input.filter((n) => n.kind === "quantity" && /refrigerant|equipment_capacity/.test(n.key));
  const hcfcs = (result.excluded ?? []).filter((e) => reasonOf(e) === "montreal_protocol_gas");
  const hcfcNote = hcfcs.length
    ? ` ${hcfcs.length} record(s) of CFCs or HCFCs (${listed(hcfcs.map((e) => e.gas ?? e.record))}) are listed but not counted in Scope 1.`
    : "";
  if (waiting.length || gwps.length || amounts.length) {
    return {
      ...base,
      status: "inputs_missing",
      reason: [
        category ? `Recalculated so far: ${category.lines.map((l) => l.key).join(", ")}` : "",
        waiting.length ? `${waiting.length} record(s) awaiting review (${listed(waiting)})` : "",
        gwps.length ? `GWP needed for ${listed(gwps.map((g) => g.key))} (not in the EPA Hub)` : "",
        amounts.length ? amounts.map((a) => a.message).join(" ") : "",
      ].filter(Boolean).join(". ") + "." + hcfcNote,
    };
  }
  if (category) {
    const docs = (category.details.inputs ?? []).reduce((n, i) => n + i.documents.length, 0);
    return {
      ...base,
      status: "inputs_present",
      reason: `${category.lines.map((l) => l.key).join(", ")} from ${docs} reviewed record(s).${hcfcNote}`,
    };
  }
  const leftOut = (result.excluded ?? []).filter(
    (e) => e.canonical_type_id === "CT-S1-REFRSVC" && reasonOf(e) !== "montreal_protocol_gas"
  );
  return {
    ...base,
    status: "not_applicable",
    reason: leftOut.length
      ? `Every reviewed refrigerant record is left out (${describeLeftOut(leftOut)}), so none are counted.${hcfcNote}`
      : `No reviewed refrigerant service records in this engagement.${hcfcNote}`,
  };
}
