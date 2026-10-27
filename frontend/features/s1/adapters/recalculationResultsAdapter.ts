import {
  describeLeftOut,
  type CategoryKey,
  type MissingReason,
  type NodeStatus,
  type OutputStatus,
  type RecalcCategory,
  type RecalcLine,
  type Recalculation,
  type RollupCategory,
  type RollupMissing,
  type RollupSourceKey,
} from "../api/recalculation";
import type {
  FacilityResult,
  GasResultRow,
  ResultBoxKey,
  ResultBoxTotal,
  ResultLine,
  ResultState,
  Scope1Category,
} from "../types/verificationResults";
import { formatTonnes } from "../utils/verificationTable";

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
 *    those cells stay empty rather than invented.
 *  - What the numbers cannot say (a partial total, no reviewed evidence, not in scope, not
 *    calculated yet) becomes a state with its reason, from the roll-up's per-source status.
 *  - The per-gas data points (rows 23-37) as their own rows, in tonnes of each gas.
 * Results computed before the roll-up fall back to the comparisons and category totals.
 */

export interface LiveResults {
  lines: ResultLine[];
  boxTotals: Partial<Record<ResultBoxKey, ResultBoxTotal>>;
  gasRows: GasResultRow[];
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

/** Scope 1: one row per fuel or refrigerant, summed across facilities (the backend's grain). */
function byFuel(result: Recalculation, key: CategoryKey, source: RollupSourceKey): FacilityResult[] {
  const category = categoryOf(result, key);
  if (!category) return [];
  const ids = uniqueIds(category.lines.map((l) => l.key));
  return category.lines.map((line, i) => ({
    facilityId: ids[i],
    facility: "All facilities",
    activity: line.key,
    reported: null,
    recomputed: lineCo2e(category, line, result.rollup?.categories[source]),
    steps: [],
    cause: "",
  }));
}

/** Scope 2: one row per facility, as Setup names it. */
function byFacility(result: Recalculation, key: CategoryKey | null, source: RollupSourceKey): FacilityResult[] {
  const category = key ? categoryOf(result, key) : null;
  if (!category) return [];
  const ids = uniqueIds(category.lines.map((l) => l.key));
  return category.lines.map((line, i) => ({
    facilityId: ids[i],
    facility: line.key,
    reported: null,
    recomputed: lineCo2e(category, line, result.rollup?.categories[source]),
    steps: [],
    cause: "",
  }));
}

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
  const facilities = !key
    ? []
    : spec.box === "scope1"
      ? byFuel(result, key, spec.sources[0])
      : byFacility(result, key, spec.sources[0]);
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

export function liveResultsFromRecalculation(result: Recalculation): LiveResults {
  const bio = biogenic(result);
  const boxTotals: Partial<Record<ResultBoxKey, ResultBoxTotal>> = { biogenic: bio.total };
  for (const spec of BOX_SPECS) boxTotals[spec.box] = boxTotal(result, spec);
  return {
    lines: [...SPECS.map((spec) => lineOf(result, spec)), bio.line],
    boxTotals,
    gasRows: gasRows(result),
  };
}
