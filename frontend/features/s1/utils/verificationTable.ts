import {
  SCOPE1_CATEGORIES,
  type FacilityResult,
  type ResultBoxKey,
  type ResultLine,
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
 * Lines and facilities hold unrounded tCO2e: everything is summed first and rounded
 * once, at display.
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
}

export function examinationKey(lineId: string, facilityId: string): string {
  return `vr:${lineId}:${facilityId}`;
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

export function lineReported(line: ResultLine): number | null {
  return line.facilities ? sumOf(line.facilities, (f) => f.reported) : null;
}

export function lineRecomputed(line: ResultLine): number | null {
  return line.facilities ? sumOf(line.facilities, (f) => f.recomputed) : null;
}

function emptyRow(key: string, activity: string, categoryLabel: string | null): ResultRow {
  return {
    key, line: null, activity, categoryLabel, notReported: true, notTested: false, reported: null, recomputed: null,
    difference: null, pctDifference: null, share: null, pctMaterial: null, examined: 0, facilities: 0,
  };
}

function rowOf(line: ResultLine, isExamined: (lineId: string, facilityId: string) => boolean): ResultRow {
  const reported = lineReported(line);
  if (reported === null || !line.facilities) return emptyRow(line.id, line.activity, null);
  const recomputed = lineRecomputed(line);
  const difference = recomputed === null ? null : recomputed - reported;
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
    pctDifference: difference !== null && reported !== 0 ? difference / reported : null,
    share: null,
    pctMaterial: null,
    examined: line.facilities.filter((f) => isExamined(line.id, f.facilityId)).length,
    facilities: line.facilities.length,
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
  isExamined: (lineId: string, facilityId: string) => boolean = () => false
): ResultBox[] {
  return RESULT_BOXES.map(({ key, title, totalLabel }) => {
    const own = lines.filter((line) => line.box === key);
    const rows = own.map((line) => rowOf(line, isExamined));
    const reportedRows = rows.filter((r) => !r.notReported);
    const reportedTotal = reportedRows.reduce((sum, r) => sum + (r.reported ?? 0), 0);
    for (const row of reportedRows) {
      row.share = reportedTotal ? (row.reported ?? 0) / reportedTotal : null;
      row.pctMaterial = row.pctDifference !== null && row.share !== null ? row.pctDifference * row.share : null;
    }
    const tested = reportedRows.filter((r) => !r.notTested);
    const difference = tested.reduce((sum, r) => sum + (r.difference ?? 0), 0);
    const share = tested.reduce((sum, r) => sum + (r.share ?? 0), 0);
    const pctMaterial = tested.reduce((sum, r) => sum + (r.pctMaterial ?? 0), 0);
    const totals: ResultTotals = {
      reported: reportedTotal,
      recomputed: tested.reduce((sum, r) => sum + (r.recomputed ?? 0), 0),
      difference,
      pctDifference: reportedTotal ? difference / reportedTotal : null,
      pctMaterial,
      share,
      examined: reportedRows.reduce((sum, r) => sum + r.examined, 0),
      facilities: reportedRows.reduce((sum, r) => sum + r.facilities, 0),
    };
    const ordered = key === "scope1" ? scope1Order(rows, own) : fixedOrder(key, rows);
    return {
      key, title, totalLabel, rows: ordered, totals,
      normalizedMaterial: reportedRows.length && share > 0 && share < 1 - 1e-9 ? pctMaterial / share : null,
    };
  });
}

/** Categories in fixed order, activities by materiality; categories with nothing reported last. */
function scope1Order(rows: ResultRow[], lines: ResultLine[]): ResultRow[] {
  const categoryOf = new Map(lines.map((line) => [line.id, line.category]));
  const reported: ResultRow[] = [];
  const unreported: ResultRow[] = [];
  SCOPE1_CATEGORIES.forEach((category: Scope1Category) => {
    const group = rows.filter((r) => categoryOf.get(r.key) === category);
    const present = group.filter((r) => !r.notReported).sort(byMateriality);
    const absent = group.filter((r) => r.notReported);
    if (!present.length) {
      unreported.push({ ...emptyRow(`scope1:${category}`, "", category) });
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
  const absent = FIXED_ROWS[key].filter((name) => !named.has(name)).map((name) => emptyRow(`${key}:${name}`, name, null));
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

/** Coverage line: a whole-number percentage. */
export function formatWholePercent(fraction: number): string {
  return `${Math.round(fraction * 100)}%`;
}

/** A difference worth flagging: one that does not round to zero tonnes. */
export function differs(difference: number | null): boolean {
  return difference !== null && Math.round(difference) !== 0;
}
