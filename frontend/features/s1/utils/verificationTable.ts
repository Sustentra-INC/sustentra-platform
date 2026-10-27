import {
  OPTIONAL_SCOPE1_CATEGORIES,
  SCOPE1_CATEGORIES,
  type FacilityResult,
  type ResultBoxKey,
  type ResultBoxTotal,
  type ResultLine,
  type ResultState,
  type Scope1Category,
} from "../types/verificationResults";

/**
 * The left pane of Verification results: four boxes, each a table with a total row.
 *
 *   Difference_i   = Recomputed_i − Reported_i
 *   %Difference_i  = Difference_i ÷ Reported_i
 *   Share_i        = Reported_i ÷ the box's total Reported
 *   %Material_i    = %Difference_i × Share_i
 *
 * The total row sums Recomputed, Difference and %Material over the rows that have
 * both values; its Share is the coverage. Its Reported sums every reported row, so a
 * row reported but not tested lowers the coverage instead of vanishing from it.
 * A line's Reported and Recomputed sum its facilities after each one's consolidated
 * share (Scope 1 and 2; 100% for now). Lines and facilities hold unrounded tCO2e:
 * everything is summed first and rounded once, at display.
 *
 * Live results (backend mode) know the client's reported value only per category or data
 * point, not per facility: such a line carries its own `reported` (null when not entered),
 * and a box may carry its own totals (the reported scope total and the roll-up's), which
 * then stand in for the sum of its rows.
 */

export const RESULT_BOXES: { key: ResultBoxKey; title: string; totalLabel: string }[] = [
  { key: "scope1", title: "Scope 1", totalLabel: "Scope 1 total" },
  { key: "scope2_location", title: "Scope 2, location-based", totalLabel: "Scope 2 location-based total" },
  { key: "scope2_market", title: "Scope 2, market-based", totalLabel: "Scope 2 market-based total" },
  { key: "biogenic", title: "Biogenic CO₂", totalLabel: "Biogenic total" },
];

/** Fixed rows of the boxes other than Scope 1, in their listed order. */
export const FIXED_ROWS: Record<Exclude<ResultBoxKey, "scope1">, string[]> = {
  scope2_location: ["Electricity", "Steam", "Heating", "Cooling"],
  scope2_market: ["Electricity", "Steam", "Heating", "Cooling"],
  biogenic: ["Direct"],
};

export interface ResultRow {
  key: string;
  /** null for a fixed row or category the client's files do not contain. */
  line: ResultLine | null;
  activity: string;
  /** Scope 1: the category, shown on the first row of its group only. */
  categoryLabel: string | null;
  notReported: boolean;
  /** Reported but not recomputed. */
  notTested: boolean;
  reported: number | null;
  recomputed: number | null;
  difference: number | null;
  pctDifference: number | null;
  share: number | null;
  pctMaterial: number | null;
  examined: number;
  facilities: number;
  /** Live results: why a reported row has no reported value ("Not entered"); null otherwise. */
  reportedNote: string | null;
  /** Live results: what the numbers alone cannot say; null in the demo. */
  state: ResultState | null;
}

export interface ResultTotals {
  reported: number;
  recomputed: number;
  difference: number;
  pctDifference: number | null;
  pctMaterial: number;
  /** Σ Share of the tested rows: the coverage. */
  share: number;
  examined: number;
  facilities: number;
}

export interface ResultBox {
  key: ResultBoxKey;
  title: string;
  totalLabel: string;
  rows: ResultRow[];
  totals: ResultTotals;
  /** Total % material ÷ coverage; only when coverage is below 100%. */
  normalizedMaterial: number | null;
  /** Live results: the box's own totals, which `totals` follows; absent in the demo. */
  live?: ResultBoxTotal;
}

export function examinationKey(lineId: string, facilityId: string): string {
  return `vr:${lineId}:${facilityId}`;
}

/** The examination key of every facility row that has a recomputed value. */
export function testedExaminationKeys(lines: ResultLine[]): string[] {
  return lines.flatMap((line) =>
    (line.facilities ?? []).filter((f) => f.recomputed !== null).map((f) => examinationKey(line.id, f.facilityId))
  );
}

/** Σ of a facility value, or null when any facility lacks it. */
function sumOf(facilities: FacilityResult[], pick: (f: FacilityResult) => number | null): number | null {
  let total = 0;
  for (const facility of facilities) {
    const value = pick(facility);
    if (value === null) return null;
    total += value;
  }
  return facilities.length ? total : null;
}

/**
 * The share of a facility's emissions the line consolidates; null for biogenic CO₂,
 * which is reported outside the scopes and takes no share.
 */
export function consolidatedShare(line: ResultLine, facility: FacilityResult): number | null {
  return line.box === "biogenic" ? null : (facility.consolidatedShare ?? 1);
}

/** A facility's value after its consolidated share: what the line adds up. */
export function facilityReported(line: ResultLine, facility: FacilityResult): number | null {
  return facility.reported === null ? null : facility.reported * (consolidatedShare(line, facility) ?? 1);
}

export function facilityRecomputed(line: ResultLine, facility: FacilityResult): number | null {
  return facility.recomputed === null ? null : facility.recomputed * (consolidatedShare(line, facility) ?? 1);
}

/** The line's own reported value (live results), or its facilities' sum. */
export function lineReported(line: ResultLine): number | null {
  if (line.reported !== undefined) return line.reported;
  return line.facilities ? sumOf(line.facilities, (f) => facilityReported(line, f)) : null;
}

/** The line's own recalculated value (live results), or its facilities' sum. */
export function lineRecomputed(line: ResultLine): number | null {
  if (line.recomputed !== undefined) return line.recomputed;
  return line.facilities ? sumOf(line.facilities, (f) => facilityRecomputed(line, f)) : null;
}

function emptyRow(key: string, activity: string, categoryLabel: string | null, state: ResultState | null = null): ResultRow {
  return {
    key, line: null, activity, categoryLabel, notReported: true, notTested: false, reported: null, recomputed: null,
    difference: null, pctDifference: null, share: null, pctMaterial: null, examined: 0, facilities: 0,
    reportedNote: null, state,
  };
}

function rowOf(line: ResultLine, isExamined: (lineId: string, facilityId: string) => boolean): ResultRow {
  const reported = lineReported(line);
  // A live line knows when its reported value is not entered; in the demo null means "not reported".
  const ownReported = line.reported !== undefined;
  if (!line.facilities || (reported === null && !ownReported)) {
    return emptyRow(line.id, line.activity, null, line.state ?? null);
  }
  const recomputed = lineRecomputed(line);
  const difference = recomputed === null || reported === null ? null : recomputed - reported;
  return {
    key: line.id,
    line,
    activity: line.activity,
    categoryLabel: null,
    notReported: false,
    notTested: recomputed === null,
    reported,
    recomputed,
    difference,
    pctDifference: difference !== null && reported ? difference / reported : null,
    share: null,
    pctMaterial: null,
    examined: line.facilities.filter((f) => isExamined(line.id, f.facilityId)).length,
    facilities: line.facilities.length,
    reportedNote: reported === null ? line.reportedNote ?? "Not entered" : null,
    state: line.state ?? null,
  };
}

/** Largest |%Material| first; rows not tested after, in their given order. */
function byMateriality(a: ResultRow, b: ResultRow): number {
  const ma = a.pctMaterial === null ? -1 : Math.abs(a.pctMaterial);
  const mb = b.pctMaterial === null ? -1 : Math.abs(b.pctMaterial);
  return mb - ma;
}

export function buildResultBoxes(
  lines: ResultLine[],
  isExamined: (lineId: string, facilityId: string) => boolean = () => false,
  /** Live results: each box's own totals, in place of the sum of its rows. */
  boxTotals?: Partial<Record<ResultBoxKey, ResultBoxTotal>>
): ResultBox[] {
  return RESULT_BOXES.map(({ key, title, totalLabel }) => {
    const own = lines.filter((line) => line.box === key);
    const rows = own.map((line) => rowOf(line, isExamined));
    const live = boxTotals?.[key];
    const reportedRows = rows.filter((r) => !r.notReported);
    // Live: a row's share is of the reported box total, when that is entered.
    const reportedTotal = live?.reported ?? reportedRows.reduce((sum, r) => sum + (r.reported ?? 0), 0);
    for (const row of reportedRows) {
      row.share = reportedTotal && row.reported !== null ? row.reported / reportedTotal : null;
      row.pctMaterial = row.pctDifference !== null && row.share !== null ? row.pctDifference * row.share : null;
    }
    const tested = reportedRows.filter((r) => !r.notTested);
    const difference = tested.reduce((sum, r) => sum + (r.difference ?? 0), 0);
    const share = tested.reduce((sum, r) => sum + (r.share ?? 0), 0);
    const pctMaterial = tested.reduce((sum, r) => sum + (r.pctMaterial ?? 0), 0);
    const examined = reportedRows.reduce((sum, r) => sum + r.examined, 0);
    const facilities = reportedRows.reduce((sum, r) => sum + r.facilities, 0);
    const totals: ResultTotals = live
      ? liveTotals(live, share, examined, facilities)
      : {
          reported: reportedTotal,
          recomputed: tested.reduce((sum, r) => sum + (r.recomputed ?? 0), 0),
          difference,
          pctDifference: reportedTotal ? difference / reportedTotal : null,
          pctMaterial,
          share,
          examined,
          facilities,
        };
    const ordered = key === "scope1" ? scope1Order(rows, own) : fixedOrder(key, rows);
    return {
      key, title, totalLabel, rows: ordered, totals,
      normalizedMaterial: !live && reportedRows.length && share > 0 && share < 1 - 1e-9 ? pctMaterial / share : null,
      ...(live ? { live } : {}),
    };
  });
}

/** A box's totals from its own reported and recalculated figures: its % material is its % difference. */
function liveTotals(live: ResultBoxTotal, share: number, examined: number, facilities: number): ResultTotals {
  const difference = live.reported !== null && live.recomputed !== null ? live.recomputed - live.reported : null;
  const pctDifference = difference !== null && live.reported ? difference / live.reported : null;
  return {
    reported: live.reported ?? 0,
    recomputed: live.recomputed ?? 0,
    difference: difference ?? 0,
    pctDifference,
    pctMaterial: pctDifference ?? 0,
    share,
    examined,
    facilities,
  };
}

/** Categories in fixed order, activities by materiality; categories with nothing reported last. */
function scope1Order(rows: ResultRow[], lines: ResultLine[]): ResultRow[] {
  const categoryOf = new Map(lines.map((line) => [line.id, line.category]));
  const reported: ResultRow[] = [];
  const unreported: ResultRow[] = [];
  // An optional category (live results) is listed only when a line carries it.
  const optional = OPTIONAL_SCOPE1_CATEGORIES.filter((category) => lines.some((line) => line.category === category));
  [...SCOPE1_CATEGORIES, ...optional].forEach((category: Scope1Category) => {
    const group = rows.filter((r) => categoryOf.get(r.key) === category);
    const present = group.filter((r) => !r.notReported).sort(byMateriality);
    const absent = group.filter((r) => r.notReported);
    if (!present.length) {
      // A live category with nothing to show keeps its state (not in scope, not calculated yet).
      unreported.push({ ...emptyRow(`scope1:${category}`, "", category, absent.find((r) => r.state)?.state ?? null) });
      return;
    }
    [...present, ...absent].forEach((row, index) => reported.push({ ...row, categoryLabel: index === 0 ? category : null }));
  });
  return [...reported, ...unreported];
}

/** Rows by materiality; fixed rows the client did not report, greyed, at the bottom. */
function fixedOrder(key: Exclude<ResultBoxKey, "scope1">, rows: ResultRow[]): ResultRow[] {
  const present = rows.filter((r) => !r.notReported).sort(byMateriality);
  const named = new Set(present.map((r) => r.activity));
  // A live line with nothing to show keeps its state (not in scope, not calculated yet).
  const stated = new Map(rows.filter((r) => r.notReported && r.state).map((r) => [r.activity, r.state]));
  const absent = FIXED_ROWS[key]
    .filter((name) => !named.has(name))
    .map((name) => emptyRow(`${key}:${name}`, name, null, stated.get(name) ?? null));
  return [...present, ...absent];
}

/* ------------------------------- number formats ------------------------------- */

const MINUS = "−";

/** tCO2e: whole number with thousands separators. */
export function formatTonnes(value: number): string {
  const rounded = Math.round(value);
  return `${rounded < 0 ? MINUS : ""}${Math.abs(rounded).toLocaleString("en-US")}`;
}

/** A difference: "+345", "−206", "0". */
export function formatSignedTonnes(value: number): string {
  const rounded = Math.round(value);
  if (rounded === 0) return "0";
  return `${rounded > 0 ? "+" : MINUS}${Math.abs(rounded).toLocaleString("en-US")}`;
}

/** A fraction as a percentage with one decimal; signed adds + or − (none on 0.0%). */
export function formatPercent(fraction: number, signed = false): string {
  const tenths = Math.round(fraction * 1000);
  const text = `${(Math.abs(tenths) / 10).toFixed(1)}%`;
  if (!signed || tenths === 0) return tenths < 0 && !signed ? `${MINUS}${text}` : text;
  return `${tenths > 0 ? "+" : MINUS}${text}`;
}

/**
 * Tonnes of a gas itself (not CO₂e), as the per-gas data points report them: one decimal;
 * below 0.1 t two significant figures, so a small CH₄ or N₂O mass never reads as 0.0.
 */
export function formatGasTonnes(value: number): string {
  const magnitude = Math.abs(value);
  const text =
    magnitude !== 0 && magnitude < 0.1
      ? String(Number(magnitude.toPrecision(2)))
      : magnitude.toLocaleString("en-US", { minimumFractionDigits: 1, maximumFractionDigits: 1 });
  return value < 0 && text !== "0.0" ? `${MINUS}${text}` : text;
}

/** A per-gas difference: "+0.4", "−12.9", "0.0". */
export function formatSignedGasTonnes(value: number): string {
  const text = formatGasTonnes(Math.abs(value));
  if (text === "0.0" || value === 0) return text;
  return `${value > 0 ? "+" : MINUS}${text}`;
}

/** Coverage line: a whole-number percentage. */
export function formatWholePercent(fraction: number): string {
  return `${Math.round(fraction * 100)}%`;
}

/** A difference worth flagging: one that does not round to zero tonnes. */
export function differs(difference: number | null): boolean {
  return difference !== null && Math.round(difference) !== 0;
}
