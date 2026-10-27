import {
  describeLeftOut,
  FLAG_NOTE,
  type CategoryKey,
  type MissingReason,
  type NodeStatus,
  type OutputStatus,
  type RecalcCategory,
  type RecalcInput,
  type RecalcLine,
  type RecalcStep,
  type Recalculation,
  type RollupCategory,
  type RollupMissing,
  type RollupSourceKey,
} from "../api/recalculation";
import type {
  CalcCell,
  CalcStep,
  EvidenceSource,
  FacilityResult,
  GasResultRow,
  ResultBoxKey,
  ResultBoxTotal,
  ResultLine,
  ResultState,
  Scope1Category,
} from "../types/verificationResults";
import { formatQuantity } from "../utils/calculationChains";
import type { InventoryTotal } from "../utils/outputStatement";
import { formatGasTonnes, formatPercent, formatTonnes } from "../utils/verificationTable";

/**
 * The engagement's live recalculation (GET /engagements/{id}/recalculation) as the demo's
 * Verification results: the same boxes, rows and calculation panel, filled only with what
 * the backend computed from reviewed evidence.
 *
 * What the backend has, and where it goes:
 *  - Recalculated values per category and source (roll-up nodes): the rows; per fuel or
 *    refrigerant (Scope 1, summed across facilities) and per facility (Scope 2): the rows
 *    of the calculation panel.
 *  - The client's reported values only per data point of the GHG Required Data workbook
 *    (scope totals, category rows 43-51), typed in under Recalculation inputs: a line's own
 *    `reported`, and each box's reported total. Nothing is reported per fuel or facility, so
 *    those cells stay empty rather than invented, and the card says why.
 *  - Each panel row's card: the backend's own steps (Recomputed side), its amounts linked to
 *    the reviewed records they are summed from, its factors and GWPs to their citations, and
 *    a cause built only from data quality checks and the recalculation's flags, labelled
 *    "Checked by system".
 *  - What the numbers cannot say (a partial total, no reviewed evidence, not in scope, not
 *    calculated yet) becomes a state with its reason, from the roll-up's per-source status.
 *  - The per-gas data points (rows 23-37) as their own rows, in tonnes of each gas.
 * Results computed before the roll-up fall back to the comparisons and category totals.
 */

export interface LiveResults {
  lines: ResultLine[];
  boxTotals: Partial<Record<ResultBoxKey, ResultBoxTotal>>;
  gasRows: GasResultRow[];
  /** Output's inventory totals (Scope 1 + Scope 2), per Scope 2 basis. */
  inventory: { location: InventoryTotal; market: InventoryTotal };
}

/* ------------------------------ the result, normalised ------------------------------ */

interface Output {
  reported: number | null;
  recalculated: number | null;
  difference: number | null;
  /** A percentage, as the backend gives it (8.9 for +8.9%). */
  differencePct: number | null;
  status: OutputStatus;
  unit: string | null;
  unitHint: string | null;
}

interface NodeValue {
  co2e: number | null;
  status: NodeStatus;
  missing: RollupMissing[];
  countedAsZero: RollupMissing[];
}

function outputOf(result: Recalculation, key: string): Output | null {
  const final = result.rollup?.final_outputs.find((o) => o.key === key);
  if (final) {
    return {
      reported: final.reported,
      recalculated: final.recalculated,
      difference: final.difference,
      differencePct: final.difference_pct,
      status: final.status,
      unit: final.unit,
      unitHint: final.unit_hint ?? null,
    };
  }
  const c = result.comparisons.find((item) => item.key === key);
  if (!c) return null;
  // Older results: "inputs incomplete" is engagement-wide, so a comparison it touches is not concluded.
  const concluded = c.status === "within_tolerance" || c.status === "exceeds_tolerance";
  return {
    reported: c.reported,
    recalculated: c.recalculated,
    difference: c.difference,
    differencePct: c.difference_pct,
    status: c.inputs_incomplete && concluded ? "incomplete" : c.status,
    unit: c.unit,
    unitHint: null,
  };
}

function categoryOf(result: Recalculation, key: CategoryKey): RecalcCategory | null {
  return (result.categories as Partial<Record<CategoryKey, RecalcCategory | null>>)[key] ?? null;
}

function nodeOf(result: Recalculation, key: string, fallback: CategoryKey[]): NodeValue {
  const node = result.rollup?.nodes[key];
  if (node) {
    return { co2e: node.co2e_t, status: node.status, missing: node.missing, countedAsZero: node.counted_as_zero ?? [] };
  }
  const parts = fallback.map((k) => categoryOf(result, k)).filter((c): c is RecalcCategory => c !== null);
  const co2e = outputOf(result, key)?.recalculated ?? (parts.length ? parts.reduce((s, c) => s + c.total_co2e, 0) : null);
  return { co2e, status: co2e === null ? "not_available" : "complete", missing: [], countedAsZero: [] };
}

/* ------------------------------------- words -------------------------------------- */

const SOURCE_WORDS: Record<RollupSourceKey, string> = {
  stationary_combustion: "stationary combustion",
  mobile_combustion: "mobile combustion",
  process_sources: "process sources",
  fugitive_refrigerants: "refrigerants and fire suppression",
  fugitive_purchased_gases: "purchased industrial gases",
  agricultural_sources: "agricultural sources",
  purchased_electricity: "purchased electricity",
  purchased_steam: "purchased steam",
  purchased_heating: "purchased heating",
  purchased_cooling: "purchased cooling",
};

/** The document type each source is read from, for "every record is left out". */
const SOURCE_TYPE: Partial<Record<RollupSourceKey, string>> = {
  stationary_combustion: "CT-S1-FUELQTY",
  mobile_combustion: "CT-S1-MOBFUEL",
  fugitive_refrigerants: "CT-S1-REFRSVC",
  purchased_electricity: "CT-S2-ELEC",
  purchased_steam: "CT-S2-THERMAL",
  purchased_heating: "CT-S2-THERMAL",
};

const ZERO_REASON: Partial<Record<MissingReason, string>> = {
  not_built: "not calculated yet",
  no_evidence: "no reviewed evidence",
  awaiting_inputs: "awaiting review",
};

const GAP_WORDS: Partial<Record<MissingReason, string>> = {
  vehicle_groups_missing:
    "CH₄ and N₂O need vehicle groups (vehicle type, model year, distance) under Recalculation inputs",
  gas_split_unknown: "a refrigerant's gases are not known, so its split into the seven gases is open",
};

function listed(items: string[], max = 3): string {
  const unique = Array.from(new Set(items));
  return unique.length <= max ? unique.join(", ") : `${unique.slice(0, max).join(", ")} and ${unique.length - max} more`;
}

function sentence(text: string): string {
  return text ? text[0].toUpperCase() + text.slice(1) : text;
}

const NOT_IN_SCOPE: ResultState = {
  tone: "na",
  label: "Not in scope",
  detail: "Setup leaves this data point out of the engagement, so it is shown but not compared.",
};

/** What holds a source open: records awaiting review, questions under Recalculation inputs, gaps. */
function openItems(result: Recalculation, sources: RollupSourceKey[]): string[] {
  const own = (category?: RollupSourceKey) => category !== undefined && sources.includes(category);
  const awaiting = result.awaiting_review.filter((a) => own(a.category));
  const asks = result.needs_input.filter((n) => own(n.category));
  const gaps = sources.flatMap((s) => result.rollup?.categories[s]?.gaps ?? []).filter((g) => g.affects_total);
  return [
    awaiting.length ? `${awaiting.length} ${awaiting.length === 1 ? "record" : "records"} awaiting review (${listed(awaiting.map((a) => a.record))})` : "",
    ...asks.map((a) => a.message.replace(/\.$/, "")),
    ...gaps.map((g) => GAP_WORDS[g.gap] ?? g.gap.replace(/_/g, " ")),
  ].filter(Boolean);
}

function noEvidenceDetail(result: Recalculation, sources: RollupSourceKey[]): string {
  const types = new Set(sources.map((s) => SOURCE_TYPE[s]).filter(Boolean));
  const leftOut = (result.excluded ?? []).filter((e) => types.has(e.canonical_type_id));
  return leftOut.length
    ? `Every reviewed record for this is left out (${describeLeftOut(leftOut)}), so the totals count it as 0.`
    : "No reviewed evidence feeds this yet, so the totals count it as 0.";
}

/** A line's state from its node and sources; none when its numbers say it all. */
function lineState(result: Recalculation, out: Output | null, node: NodeValue, sources: RollupSourceKey[]): ResultState | undefined {
  if (out?.status === "not_in_scope") return NOT_IN_SCOPE;
  const words = listed(sources.map((s) => SOURCE_WORDS[s]));
  if (node.status === "not_available") {
    const reasons = new Set([...node.missing, ...node.countedAsZero].map((m) => m.reason));
    if (out?.status === "not_recalculated" || (reasons.size && [...reasons].every((r) => r === "not_built"))) {
      return { tone: "na", label: "Not calculated yet", detail: `Sustentra does not calculate ${words} yet, so the totals count it as 0.` };
    }
    if (reasons.has("awaiting_inputs")) {
      const open = openItems(result, sources);
      return { tone: "open", label: "Awaiting review", detail: `${open.length ? `${sentence(open.join("; "))}. ` : ""}Until then the totals count it as 0.` };
    }
    return { tone: "unverifiable", label: "No reviewed evidence", detail: noEvidenceDetail(result, sources) };
  }
  const absent = sources.map((s) => result.rollup?.categories[s]).find((c): c is RollupCategory => c?.status === "confirmed_absent");
  if (absent && node.co2e === 0) {
    return { tone: "resolved", label: "None at the client", detail: absent.absent_reason ?? "Confirmed absent by the reviewer." };
  }
  if (node.status === "partial") {
    const open = openItems(result, sources);
    return {
      tone: "open",
      label: open.length ? `Partial · ${open.length} open` : "Partial",
      detail: `A lower bound until this closes: ${open.length ? open.join("; ") : "an input is still open"}.`,
    };
  }
  return undefined;
}

/* ------------------------------------ the lines ------------------------------------ */

/** A stable id for examination keys: letters, digits and dashes (the backend allows : . _ - too). */
function slug(text: string): string {
  return (
    text
      .normalize("NFKD")
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-+|-+$/g, "")
      .slice(0, 60) || "item"
  );
}

function uniqueIds(names: string[]): string[] {
  const seen = new Map<string, number>();
  return names.map((name) => {
    const base = slug(name);
    const n = (seen.get(base) ?? 0) + 1;
    seen.set(base, n);
    return n === 1 ? base : `${base}-${n}`;
  });
}

/** A line's CO₂e as the totals count it: the roll-up's split into the 7 gases, else mass × GWP. */
function lineCo2e(category: RecalcCategory, line: RecalcLine, rollup: RollupCategory | undefined): number {
  const split = rollup?.gas_split?.[line.key];
  if (split) return Object.values(split.groups).reduce((sum, g) => sum + (g?.co2e_t ?? 0), 0);
  return Object.entries(line.mass_t).reduce((sum, [gas, mass]) => sum + mass * (category.gwp[gas]?.value ?? 0), 0);
}

/**
 * The calculation panel's rows: Scope 1 one per fuel or refrigerant, summed across facilities
 * (the backend's grain); Scope 2 one per facility, as Setup names it. Each carries the
 * backend's own steps (the Recomputed side) and what the system found about it.
 */
function breakdown(result: Recalculation, key: CategoryKey, source: RollupSourceKey, byFuel: boolean): FacilityResult[] {
  const category = categoryOf(result, key);
  if (!category) return [];
  const ids = uniqueIds(category.lines.map((l) => l.key));
  return category.lines.map((line, i) => {
    const co2e = lineCo2e(category, line, result.rollup?.categories[source]);
    const input = category.details.inputs?.find((item) => item.fuel === line.key);
    const why = causeOf(result, source, line, input, byFuel ? null : line.key);
    return {
      facilityId: ids[i],
      facility: byFuel ? "All facilities" : line.key,
      ...(byFuel ? { activity: line.key } : {}),
      reported: null,
      recomputed: co2e,
      steps: stepsOf(category, line, input, co2e),
      cause: why.cause,
      causeBy: "system" as const,
      causeTone: why.tone,
      note: REPORTED_SIDE_NOTE,
    };
  });
}

/* ---------------------------- the calculation, step by step ---------------------------- */

/** The empty Reported column, said once under the steps. */
export const REPORTED_SIDE_NOTE =
  "Reported: only the client's totals are entered (under Recalculation inputs), so its own calculation is not shown step by step.";

type CategoryInput = NonNullable<RecalcCategory["details"]["inputs"]>[number];

const SUBSCRIPT: [RegExp, string][] = [
  [/\bCO2e\b/g, "CO₂e"],
  [/\bCO2\b/g, "CO₂"],
  [/\bCH4\b/g, "CH₄"],
  [/\bN2O\b/g, "N₂O"],
  [/\bSF6\b/g, "SF₆"],
  [/\bNF3\b/g, "NF₃"],
];

function chemistry(text: string): string {
  return SUBSCRIPT.reduce((out, [pattern, to]) => out.replace(pattern, to), text);
}

function unitText(unit: string): string {
  return unit === "t CO2e" ? "tCO₂e" : chemistry(unit);
}

/** A factor as its source prints it: up to four decimals; a very small one keeps three significant digits. */
function factorNumber(value: number): string {
  return value !== 0 && Math.abs(value) < 0.01
    ? value.toLocaleString("en-US", { maximumSignificantDigits: 3 })
    : value.toLocaleString("en-US", { maximumFractionDigits: 4 });
}

/**
 * An amount in the demo card's formats (utils/calculationChains, utils/verificationTable):
 * tCO₂e in whole tonnes; tonnes of a gas to one decimal, two significant figures below
 * 0.1 t; any other quantity whole from 100 up and to one decimal below; a fraction as a
 * percentage to one decimal.
 */
function amount(value: number, unit: string): string {
  if (unit === "fraction") return formatPercent(value);
  if (unit === "t CO2e") return `${formatTonnes(value)} tCO₂e`;
  if (unit === "t") return `${formatGasTonnes(value)} t`;
  // A negative refrigerant balance takes the true minus sign, as the demo's figures do.
  return `${formatQuantity(value).replace(/^-/, "−")} ${unitText(unit)}`.trim();
}

const GAS_ORDER = ["CO2", "CH4", "N2O"];

/** Which material-balance records feed each refrigerant term. */
const TERM_SERVICE: Record<string, string> = { P_S: "service", P_N: "installation", C_N: "installation",
  C_D: "disposal", R_D: "disposal" };

/** The reviewed records behind an evidence input, for the Source pane. */
function evidenceOf(input: CategoryInput | undefined, line: RecalcLine, term?: string): EvidenceSource | undefined {
  if (!input?.documents.length) return undefined;
  const termKey = term?.slice(0, 3);
  const serviceType = termKey ? TERM_SERVICE[termKey] : undefined;
  // The recalculation lists a refrigerant record's charged (P_N, P_S) or recovered (R_D)
  // amount; a full charge (C_N, C_D) is the record's equipment capacity, which it does not
  // list. Those records are shown without amounts rather than with ones that contradict the term.
  const fullCharge = termKey !== undefined && FULL_CHARGE_TERMS.has(termKey);
  const records = input.documents
    .filter((doc) => !serviceType || !doc.service_type || doc.service_type === serviceType)
    .map((doc) => ({
      documentId: doc.document_id,
      record: doc.record,
      quantity: fullCharge ? null : doc.quantity,
      unit: doc.unit,
      ...(doc.share_in_period !== undefined ? { shareInPeriod: doc.share_in_period } : {}),
      ...(doc.service_type ? { serviceType: doc.service_type } : {}),
    }));
  if (!records.length) return undefined;
  const region = input.grid_region ? ` · eGRID ${input.grid_region}` : "";
  // A refrigerant term counts only its own records; a fuel or facility counts them all.
  const total = fullCharge
    ? null
    : serviceType
      ? records.reduce((sum, r) => sum + (r.unit === input.unit ? (r.quantity ?? 0) : 0), 0)
      : input.quantity;
  return {
    kind: "evidence",
    title: `${line.key} · reviewed evidence${region}`,
    unit: input.unit,
    total,
    ...(fullCharge ? { note: "The full charge is each record's equipment capacity: open a record to see it." } : {}),
    records,
  };
}

/** Material-balance terms that are a full charge (equipment capacity), not a listed amount. */
const FULL_CHARGE_TERMS = new Set(["C_N", "C_D"]);

/** An input a reviewed record gave (an amount), not a factor or a figure worked out in a step. */
const EVIDENCE_INPUT = /^(fuel|fuel energy|electricity|thermal energy|[PCR]_[A-Z])/;
const EVIDENCE_SOURCE = /reviewed (record|bill)/i;

function inputCell(name: string, input: RecalcInput, line: RecalcLine, evidence: CategoryInput | undefined): CalcCell {
  const text = amount(input.value, input.unit);
  if ((input.source && EVIDENCE_SOURCE.test(input.source)) || (!input.source && EVIDENCE_INPUT.test(name))) {
    const records = evidenceOf(evidence, line, name);
    return records ? { text, source: records } : { text };
  }
  if (input.source) {
    // A factor, printed as its source prints it; cited, not drawn (no endpoint returns the
    // reference table's rows yet).
    const printed = `${factorNumber(input.value)} ${unitText(input.unit)}`.trim();
    const [title] = input.source.split(", ");
    return { text: printed, source: { kind: "basis", title, text: `${chemistry(name)} = ${printed}, cited from ${input.source}.` } };
  }
  return { text };
}

/** "Fuel x EF1" with its two inputs reads "10,000 gallon × 10.21 kg CO₂ per gallon"; anything else lists them. */
function howCells(step: RecalcStep, line: RecalcLine, evidence: CategoryInput | undefined): CalcCell[] {
  const entries = Object.entries(step.inputs);
  const operands = step.formula.split(" x ");
  const simple = operands.every((op) => /^[A-Za-z][\w ]*( \([A-Za-z]+\))?$|^\d+\/\d+$/.test(op.trim()));
  const cells = entries.map(([name, input]) => inputCell(name, input, line, evidence));
  if (simple && operands.length > 1 && operands.length === entries.length) {
    return cells.flatMap((cell, i) => (i ? [{ text: " × " }, cell] : [cell]));
  }
  return [
    { text: `${chemistry(step.formula)}: ` },
    ...entries.flatMap(([name], i) => [{ text: `${i ? "; " : ""}${chemistry(name)} ` }, cells[i]]),
  ];
}

/** The line's steps as the card's rows; the CO₂e total last, with each GWP underlined to its source. */
function stepsOf(category: RecalcCategory, line: RecalcLine, evidence: CategoryInput | undefined, co2e: number): CalcStep[] {
  const steps: CalcStep[] = line.steps.map((step) => ({
    step: chemistry(step.label),
    how: howCells(step, line, evidence),
    reported: null,
    recomputed: { text: amount(step.result, step.result_unit) },
  }));
  const last = line.steps[line.steps.length - 1];
  if (last && last.result_unit === "t CO2e" && Math.abs(last.result - co2e) < 1e-6) {
    steps[steps.length - 1] = { ...steps[steps.length - 1], total: true };
    return steps;
  }
  const order = (gas: string) => (GAS_ORDER.indexOf(gas) + 1 || GAS_ORDER.length + 1);
  const gases = Object.entries(line.mass_t).sort(([a], [b]) => order(a) - order(b));
  const how: CalcCell[] = gases.flatMap(([gas, mass], i) => {
    const gwp = category.gwp[gas];
    const term: CalcCell[] = [{ text: `${i ? " + " : ""}${chemistry(gas)} ${amount(mass, "t")} × ` }];
    term.push(
      gwp
        ? {
            text: `GWP ${formatQuantity(gwp.value)}`,
            source: { kind: "basis", title: `GWP of ${chemistry(gas)} (${category.gwp_set})`, text: `${factorNumber(gwp.value)}, from ${gwp.source}.` },
          }
        : { text: "GWP not given" }
    );
    return term;
  });
  steps.push({ step: "Total CO₂e", how, reported: null, recomputed: { text: amount(co2e, "t CO2e") }, total: true });
  return steps;
}

/** What the system found about one row: data quality signals on its records, then the recalculation's flags. */
function causeOf(
  result: Recalculation,
  source: RollupSourceKey,
  line: RecalcLine,
  input: CategoryInput | undefined,
  facility: string | null
): { cause: string; tone: "note" | "review" } {
  const documents = new Set(input?.documents.map((d) => d.document_id) ?? []);
  const checks = (result.quality_checks ?? []).filter(
    (q) => q.category === source && q.severity !== "info" && (q.documents.some((d) => documents.has(d)) || q.facility === facility)
  );
  const flags = line.flags.map((flag) => FLAG_NOTE[flag]).filter(Boolean);
  const review = checks.length > 0 || line.flags.some((f) => REVIEW_FLAGS.has(f));
  const records = new Set(input?.documents.map((d) => d.record) ?? []).size;
  const parts = [...checks.map((q) => q.message), ...flags];
  return {
    cause: parts.length
      ? parts.join(" ")
      : `Recalculated from ${records} reviewed ${records === 1 ? "record" : "records"}; no data quality signal.`,
    tone: review ? "review" : "note",
  };
}

/** Flags that ask the reviewer to act, not just say how a value was handled. */
const REVIEW_FLAGS = new Set(["ch4_n2o_need_vehicle_groups", "negative_refrigerant_emissions", "certificates_exceed_consumption",
  "service_period_reversed", "no_service_period"]);

interface LineSpec {
  id: string;
  box: ResultBoxKey;
  category?: Scope1Category;
  activity: string;
  /** The final output with the client's reported value; none for market-based rows. */
  output: string | null;
  node: string;
  sources: RollupSourceKey[];
  /** Recalculation categories behind the line, for the panel's rows and older results. */
  categories: CategoryKey[];
}

function scope1(id: string, category: Scope1Category, output: string, sources: RollupSourceKey[], categories: CategoryKey[]): LineSpec {
  return { id, box: "scope1", category, activity: "", output, node: output, sources, categories };
}

const SPECS: LineSpec[] = [
  scope1("s1-stationary", "Stationary combustion", "stationary_combustion_total", ["stationary_combustion"], ["stationary_combustion"]),
  scope1("s1-mobile", "Mobile combustion", "mobile_combustion_total", ["mobile_combustion"], ["mobile_combustion"]),
  scope1("s1-fugitive", "Fugitive emissions", "fugitive_total", ["fugitive_refrigerants", "fugitive_purchased_gases"], ["fugitive_refrigerants"]),
  scope1("s1-process", "Process emissions", "process_total", ["process_sources"], []),
  scope1("s1-agricultural", "Agricultural emissions", "agricultural_total", ["agricultural_sources"], []),
  ...(
    [
      ["Electricity", "electricity", "purchased_electricity"],
      ["Steam", "steam", "purchased_steam"],
      ["Heating", "heating", "purchased_heating"],
      ["Cooling", "cooling", "purchased_cooling"],
    ] as const
  ).flatMap(([activity, word, source]): LineSpec[] => {
    const built = source !== "purchased_cooling";
    return [
      {
        id: `s2l-${word}`, box: "scope2_location", activity, output: `${source}_total`, node: `${source}_total`,
        sources: [source], categories: built ? [`${source}_location_based` as CategoryKey] : [],
      },
      {
        id: `s2m-${word}`, box: "scope2_market", activity, output: null, node: `${source}_market_total`,
        sources: [source], categories: built ? [`${source}_market_based` as CategoryKey] : [],
      },
    ];
  }),
];

const NO_FUEL: Partial<Record<Scope1Category, string>> = {
  "Stationary combustion": "All fuels",
  "Mobile combustion": "All fuels",
  "Fugitive emissions": "All refrigerants",
};

function lineOf(result: Recalculation, spec: LineSpec): ResultLine {
  const out = spec.output ? outputOf(result, spec.output) : null;
  const node = nodeOf(result, spec.node, spec.categories);
  const state = lineState(result, out, node, spec.sources);
  const [key] = spec.categories;
  const facilities = key ? breakdown(result, key, spec.sources[0], spec.box === "scope1") : [];
  const reported = out ? out.reported : null;
  const activity =
    spec.box === "scope1"
      ? facilities.map((f) => f.activity).join(", ") || (NO_FUEL[spec.category as Scope1Category] ?? sentence(SOURCE_WORDS[spec.sources[0]]))
      : spec.activity;
  // Nothing reported and nothing recalculated: a greyed row with its state, nothing to open.
  const empty = reported === null && node.co2e === null && facilities.length === 0;
  return {
    id: spec.id,
    box: spec.box,
    ...(spec.category ? { category: spec.category } : {}),
    activity,
    facilities: empty ? null : facilities,
    reported,
    ...(spec.output ? {} : { reportedNote: "Total only" }),
    recomputed: node.co2e,
    ...(state ? { state } : {}),
    // Still partial: shown, not compared (the backend never calls a partial value within tolerance).
    ...(out?.status === "incomplete" ? { inconclusive: true } : {}),
  };
}

/* ------------------------------------ the boxes ------------------------------------ */

const BOX_SPECS: { box: ResultBoxKey; output: string; categories: CategoryKey[]; sources: RollupSourceKey[] }[] = [
  {
    box: "scope1", output: "scope1_total", categories: ["stationary_combustion", "mobile_combustion", "fugitive_refrigerants"],
    sources: ["stationary_combustion", "mobile_combustion", "process_sources", "fugitive_refrigerants", "fugitive_purchased_gases", "agricultural_sources"],
  },
  {
    box: "scope2_location", output: "scope2_location_total",
    categories: ["purchased_electricity_location_based", "purchased_steam_location_based", "purchased_heating_location_based"],
    sources: ["purchased_electricity", "purchased_steam", "purchased_heating", "purchased_cooling"],
  },
  {
    box: "scope2_market", output: "scope2_market_total",
    categories: ["purchased_electricity_market_based", "purchased_steam_market_based", "purchased_heating_market_based"],
    sources: ["purchased_electricity", "purchased_steam", "purchased_heating", "purchased_cooling"],
  },
];

/** "Counted as 0 (not calculated yet): process sources, agricultural sources". */
function countedAsZero(items: RollupMissing[]): string[] {
  const byReason = new Map<string, string[]>();
  for (const item of items) {
    if (item.source === "biogenic_combustion") continue;
    const reason = ZERO_REASON[item.reason] ?? item.reason.replace(/_/g, " ");
    byReason.set(reason, [...(byReason.get(reason) ?? []), SOURCE_WORDS[item.source]]);
  }
  return [...byReason].map(([reason, sources]) => `Counted as 0 (${reason}): ${listed(sources, 4)}.`);
}

function boxTotal(result: Recalculation, spec: (typeof BOX_SPECS)[number]): ResultBoxTotal {
  const out = outputOf(result, spec.output);
  const node = nodeOf(result, spec.output, spec.categories);
  const notes = countedAsZero(node.countedAsZero);
  const reported = out?.reported ?? null;
  const open = node.missing.map((m) => m.source).filter((s): s is RollupSourceKey => s !== "biogenic_combustion");
  let state: ResultState | undefined;
  if (out?.status === "not_in_scope") state = NOT_IN_SCOPE;
  else if (node.co2e === null || (node.co2e === 0 && spec.sources.every((s) => node.countedAsZero.some((z) => z.source === s)))) {
    state = { tone: "unverifiable", label: "No reviewed evidence", detail: "Nothing in this box is recalculated from reviewed evidence yet." };
  } else if (out?.status === "incomplete") {
    const items = openItems(result, open);
    state = {
      tone: "open",
      label: "Incomplete",
      detail:
        `Open work on ${listed(open.map((s) => SOURCE_WORDS[s]))}, so the recalculated total is at least ` +
        `${formatTonnes(node.co2e)} tCO₂e and is not compared yet${items.length ? `: ${items.join("; ")}` : ""}.`,
    };
  } else if (reported === null) {
    state = {
      tone: "unverifiable",
      label: "Reported total not entered",
      detail: "Enter the client's reported total under Recalculation inputs to compare it.",
    };
  } else if (node.status === "partial") {
    notes.unshift(`Partial: at least ${formatTonnes(node.co2e)} tCO₂e while ${listed(open.map((s) => SOURCE_WORDS[s]))} ${open.length === 1 ? "is" : "are"} open.`);
  }
  return { reported, recomputed: node.co2e, ...(state ? { state } : {}), ...(notes.length ? { notes } : {}) };
}

const BIOGENIC_STATE: ResultState = {
  tone: "na",
  label: "Not calculated yet",
  detail:
    "Biogenic CO₂ from biomass fuels is a placeholder until its calculation is agreed. It is reported outside the " +
    "scopes and added to no total.",
};

function biogenic(result: Recalculation): { line: ResultLine; total: ResultBoxTotal } {
  const out = outputOf(result, "biogenic_co2");
  const node = nodeOf(result, "biogenic_co2", []);
  const reported = out?.reported ?? null;
  const state = out?.status === "not_in_scope" ? NOT_IN_SCOPE : node.co2e === null ? BIOGENIC_STATE : undefined;
  return {
    line: {
      id: "bio-direct",
      box: "biogenic",
      activity: "Direct",
      facilities: reported === null && node.co2e === null ? null : [],
      reported,
      recomputed: node.co2e,
      ...(state ? { state } : {}),
    },
    total: { reported, recomputed: node.co2e, ...(state ? { state } : {}) },
  };
}

/* ------------------------------------- by gas -------------------------------------- */

const GAS_LABEL: Record<string, string> = {
  co2: "CO₂", ch4: "CH₄", n2o: "N₂O", hfcs: "HFCs", pfcs: "PFCs", sf6: "SF₆", nf3: "NF₃",
};
const GAS_KEY = /^(scope1|scope2_market|scope2)_(co2|ch4|n2o|hfcs|pfcs|sf6|nf3)$/;
const GAS_GROUP: Record<string, string> = {
  scope1: "Scope 1",
  scope2: "Scope 2, location-based",
  scope2_market: "Scope 2, market-based",
};

function gasState(out: Output, tolerance: number): ResultState | undefined {
  switch (out.status) {
    case "within_tolerance":
      return { tone: "resolved", label: `Within ±${tolerance}%` };
    case "exceeds_tolerance":
      return { tone: "blocking", label: `Exceeds ±${tolerance}%` };
    case "incomplete":
      return { tone: "open", label: "Incomplete", detail: "A source is still open, so the recalculated value is a lower bound." };
    case "needs_unit":
      return {
        tone: "open",
        label: "Unit to confirm",
        detail:
          "Confirm under Recalculation inputs whether the client reported tonnes of the gas or tonnes of CO₂e." +
          (out.unitHint ? ` The reported value matches ${out.unitHint === "t" ? "tonnes of the gas" : "tonnes of CO₂e"}.` : ""),
      };
    case "not_in_scope":
      return NOT_IN_SCOPE;
    case "no_evidence":
      return { tone: "unverifiable", label: "No reviewed evidence" };
    case "not_recalculated":
      return { tone: "na", label: "Not calculated yet" };
    default:
      // not_reported: the Reported cell says "Not entered".
      return undefined;
  }
}

function gasRows(result: Recalculation): GasResultRow[] {
  const keys = result.rollup ? result.rollup.final_outputs.map((o) => o.key) : result.comparisons.map((c) => c.key);
  return keys.flatMap((key) => {
    const match = GAS_KEY.exec(key);
    const out = match ? outputOf(result, key) : null;
    if (!match || !out) return [];
    const state = gasState(out, result.tolerance_pct);
    return [{
      key,
      group: GAS_GROUP[match[1]],
      gas: GAS_LABEL[match[2]],
      unit: out.unit === "t CO2e" ? "tCO₂e" : out.unit,
      reported: out.reported,
      recomputed: out.recalculated,
      difference: out.difference,
      pctDifference: out.differencePct === null ? null : out.differencePct / 100,
      ...(state ? { state } : {}),
    }];
  });
}

/* --------------------------------------------------------------------------------- */

/** Scope 1 + Scope 2 on one basis: the roll-up's Step 2 total, against both reported scope totals. */
function inventoryTotal(result: Recalculation, basis: "location" | "market"): InventoryTotal {
  const scope2 = basis === "location" ? "scope2_location_total" : "scope2_market_total";
  const parts = [outputOf(result, "scope1_total"), outputOf(result, scope2)];
  const reported = parts.every((p) => p?.reported !== null && p?.reported !== undefined)
    ? parts.reduce((sum, p) => sum + (p?.reported ?? 0), 0)
    : null;
  const node = result.rollup?.nodes[`inventory_${basis}_total`];
  if (node) return { reported, recomputed: node.co2e_t, partial: node.status === "partial" };
  const values = parts.map((p) => p?.recalculated ?? null);
  return {
    reported,
    recomputed: values.every((v) => v !== null) ? values.reduce((sum: number, v) => sum + (v ?? 0), 0) : null,
    partial: parts.some((p) => p?.status === "incomplete"),
  };
}

export function liveResultsFromRecalculation(result: Recalculation): LiveResults {
  const bio = biogenic(result);
  const boxTotals: Partial<Record<ResultBoxKey, ResultBoxTotal>> = { biogenic: bio.total };
  for (const spec of BOX_SPECS) boxTotals[spec.box] = boxTotal(result, spec);
  return {
    lines: [...SPECS.map((spec) => lineOf(result, spec)), bio.line],
    boxTotals,
    gasRows: gasRows(result),
    inventory: { location: inventoryTotal(result, "location"), market: inventoryTotal(result, "market") },
  };
}
