import type { ResultBoxKey, ResultBoxTotal, ResultLine, ResultState } from "../types/verificationResults";
import {
  buildResultBoxes,
  differs,
  facilityRecomputed,
  facilityReported,
  lineRecomputed,
  lineReported,
  RESULT_BOXES,
} from "./verificationTable";

/**
 * The statement on Output, from the same results as Verification results: what the client
 * reported, what the evidence recomputes, and whether a difference is above materiality.
 * Biogenic CO₂ is reported outside the scopes and stays out of the totals.
 */

export interface StatementRow {
  label: string;
  basis: string;
  reported: number;
  verified: number;
  /** "agrees": no difference; "differs": below materiality; "material": at or above it. */
  outcome: "agrees" | "differs" | "material";
}

export interface StatementFinding {
  facility: string;
  activity: string;
  difference: number;
  cause: string;
}

export interface StatementFigures {
  location: { reported: number; verified: number };
  market: { reported: number; verified: number };
  /** Verified minus reported, location-based. */
  misstatement: number;
  misstatementPct: number;
  /** A fraction, e.g. 0.05. */
  materiality: number;
  materialityTonnes: number;
  rows: StatementRow[];
  /** Boxes whose difference is at or above materiality, e.g. "Scope 2, market-based · +8.2%". */
  materialBoxes: { title: string; pctMaterial: number }[];
  findings: StatementFinding[];
}

/** "5%" or "5% of total" -> 0.05; anything unreadable -> 0.05. */
export function materialityFraction(threshold: string | undefined): number {
  const match = /([\d.]+)\s*%/.exec(threshold ?? "");
  const pct = match ? Number(match[1]) : NaN;
  return Number.isFinite(pct) && pct > 0 ? pct / 100 : 0.05;
}

export function statementFigures(lines: ResultLine[], materialityThreshold?: string): StatementFigures {
  const materiality = materialityFraction(materialityThreshold);
  const boxes = buildResultBoxes(lines);
  const box = (key: string) => boxes.find((b) => b.key === key)!;
  const scope1 = box("scope1");
  const location = box("scope2_location");
  const market = box("scope2_market");

  const outcome = (difference: number, base: number): StatementRow["outcome"] =>
    !differs(difference) ? "agrees" : base && Math.abs(difference / base) >= materiality ? "material" : "differs";

  const rows: StatementRow[] = [];
  // Scope 1 by category, Scope 2 by data point, each against its own box's reported total.
  const scope1Lines = lines.filter((l) => l.box === "scope1" && l.facilities);
  for (const category of [...new Set(scope1Lines.map((l) => l.category))]) {
    const own = scope1Lines.filter((l) => l.category === category);
    const reported = own.reduce((s, l) => s + (lineReported(l) ?? 0), 0);
    const verified = own.reduce((s, l) => s + (lineRecomputed(l) ?? lineReported(l) ?? 0), 0);
    rows.push({ label: `Scope 1 · ${(category ?? "other").toLowerCase()}`, basis: own.map((l) => l.activity).join(", "), reported, verified, outcome: outcome(verified - reported, scope1.totals.reported) });
  }
  for (const [key, basis] of [["scope2_location", "Location-based"], ["scope2_market", "Market-based"]] as const) {
    const total = box(key).totals.reported;
    for (const l of lines.filter((x) => x.box === key && x.facilities)) {
      const reported = lineReported(l) ?? 0;
      const verified = lineRecomputed(l) ?? reported;
      rows.push({ label: `Scope 2 · ${l.activity.toLowerCase()}`, basis, reported, verified, outcome: outcome(verified - reported, total) });
    }
  }

  const findings: StatementFinding[] = lines
    .filter((l) => l.box !== "biogenic")
    .flatMap((l) =>
      (l.facilities ?? []).map((f) => {
        const reported = facilityReported(l, f);
        const recomputed = facilityRecomputed(l, f);
        return { facility: f.facility, activity: l.activity, difference: reported === null || recomputed === null ? 0 : recomputed - reported, cause: f.cause };
      })
    )
    .filter((f) => differs(f.difference))
    // One line per facility and activity (Scope 2 appears under both bases).
    .filter((f, i, all) => all.findIndex((g) => g.facility === f.facility && g.activity === f.activity) === i)
    .sort((a, b) => Math.abs(b.difference) - Math.abs(a.difference));

  const lbReported = scope1.totals.reported + location.totals.reported;
  const lbVerified = scope1.totals.recomputed + location.totals.recomputed;
  const misstatement = lbVerified - lbReported;
  return {
    location: { reported: lbReported, verified: lbVerified },
    market: { reported: scope1.totals.reported + market.totals.reported, verified: scope1.totals.recomputed + market.totals.recomputed },
    misstatement,
    misstatementPct: lbReported ? misstatement / lbReported : 0,
    materiality,
    materialityTonnes: materiality * lbReported,
    rows,
    materialBoxes: [scope1, location, market]
      .filter((b) => Math.abs(b.totals.pctMaterial) >= materiality)
      .map((b) => ({ title: b.title, pctMaterial: b.totals.pctMaterial })),
    findings,
  };
}

/* ------------------------------ the live statement ------------------------------ */

/**
 * Output in backend mode: the same statement from the live results (Verification results'
 * lines and box totals), where a reported value may be missing and a total may still be
 * partial. Nothing is filled in: a missing value stays missing, and a state says why.
 */

/** An inventory total (Scope 1 + Scope 2 on one basis). */
export interface InventoryTotal {
  /** Both reported scope totals added; null while either is not entered. */
  reported: number | null;
  /** The roll-up's inventory total; null when not available. */
  recomputed: number | null;
  /** Open work remains, so the recalculated total is a lower bound. */
  partial: boolean;
}

export interface LiveStatementRow {
  label: string;
  basis: string;
  reported: number | null;
  /** Why there is no reported value: "Not entered", "Total only". */
  reportedNote: string | null;
  verified: number | null;
  /** null when a state stands instead (partial, no evidence) or a value is missing. */
  outcome: StatementRow["outcome"] | null;
  state: ResultState | null;
  /** A scope total. */
  total: boolean;
}

export interface LiveDifference {
  label: string;
  difference: number;
  /** A fraction of the reported value. */
  pct: number | null;
  outcome: StatementRow["outcome"] | null;
  state: ResultState | null;
}

export interface LiveStatementFigures {
  location: InventoryTotal;
  market: InventoryTotal;
  /** Recalculated minus reported, location-based; null until both are there and both boxes conclude. */
  misstatement: number | null;
  misstatementPct: number | null;
  /** The inventory is partial, or Scope 1 or Scope 2 (location-based) cannot be compared yet. */
  misstatementOpen: boolean;
  /** A fraction, e.g. 0.05. */
  materiality: number;
  materialityTonnes: number | null;
  /** What the threshold is a share of: the reported total, or the recalculated one while it is not entered. */
  materialityBase: "reported" | "recalculated" | null;
  rows: LiveStatementRow[];
  /** Boxes compared at or above materiality; pctMaterial null when the reported total is 0. */
  materialBoxes: { title: string; pctMaterial: number | null; difference: number }[];
  /** Boxes that cannot be compared yet, with why. */
  openBoxes: { title: string; state: ResultState }[];
  /** Every compared value whose difference does not round to zero, largest first. */
  differences: LiveDifference[];
}

const BOX_TITLE = Object.fromEntries(RESULT_BOXES.map((b) => [b.key, b])) as Record<ResultBoxKey, (typeof RESULT_BOXES)[number]>;

export function liveStatementFigures(
  lines: ResultLine[],
  boxTotals: Partial<Record<ResultBoxKey, ResultBoxTotal>>,
  inventory: { location: InventoryTotal; market: InventoryTotal },
  /** The engagement's tolerance, a percentage (5 for ±5%). */
  tolerancePct: number
): LiveStatementFigures {
  const materiality = tolerancePct / 100;
  // At or above materiality; a reported 0 that the evidence does not match counts as above
  // it, as the backend calls it (reported_zero).
  const outcome = (difference: number, base: number | null): StatementRow["outcome"] =>
    !differs(difference)
      ? "agrees"
      : base === 0 || (base !== null && Math.abs(difference / base) >= materiality)
        ? "material"
        : "differs";

  const rows: LiveStatementRow[] = [];
  const differences: LiveDifference[] = [];
  /**
   * The same rule as Verification results: a line compares unless it is `inconclusive`
   * (still partial, or out of scope); a box unless it has a state. A line's other states
   * (None at the client, a partial value already beyond its reported one) still compare.
   * Only what compares, and differs, is a difference found.
   */
  const compare = (
    label: string,
    reported: number | null,
    verified: number | null,
    comparable: boolean,
    base: number | null,
    state: ResultState | null
  ) => {
    if (reported === null || verified === null || !comparable) return null;
    const result = outcome(verified - reported, base);
    if (result !== "agrees") {
      differences.push({ label, difference: verified - reported, pct: reported ? (verified - reported) / reported : null, outcome: result, state });
    }
    return result;
  };

  for (const key of ["scope1", "scope2_location", "scope2_market"] as const) {
    const total = boxTotals[key];
    const basis = key === "scope2_location" ? "Location-based" : key === "scope2_market" ? "Market-based" : "";
    // Lines with values, and lines with only a state (not in scope, no reviewed evidence,
    // not calculated yet), which keep their row and chip.
    const own = lines.filter((l) => l.box === key && (l.facilities || l.state));
    // A line's % material is of its box's reported total, as on Verification results.
    const rowsReported = own.reduce((sum, l) => sum + (lineReported(l) ?? 0), 0);
    const boxBase = total?.reported ?? rowsReported;
    for (const line of own) {
      const label = key === "scope1" ? `Scope 1 · ${(line.category ?? "other").toLowerCase()}` : `Scope 2 · ${line.activity.toLowerCase()}`;
      const reported = lineReported(line);
      const verified = lineRecomputed(line);
      const state = line.state ?? null;
      rows.push({
        label,
        basis: key === "scope1" ? line.activity : basis,
        reported,
        reportedNote: reported === null ? line.reportedNote ?? "Not entered" : null,
        verified,
        outcome: compare(
          key === "scope1" ? label : `${label} (${basis.toLowerCase()})`,
          reported,
          verified,
          !line.inconclusive,
          reported === 0 ? 0 : boxBase,
          state
        ),
        state,
        total: false,
      });
    }
    if (total) {
      const { totalLabel } = BOX_TITLE[key];
      rows.push({
        label: totalLabel,
        basis: "",
        reported: total.reported,
        reportedNote: total.reported === null ? "Not entered" : null,
        verified: total.recomputed,
        outcome: compare(totalLabel, total.reported, total.recomputed, !total.state, total.reported, total.state ?? null),
        state: total.state ?? null,
        total: true,
      });
    }
  }

  const { location } = inventory;
  // Not compared while the inventory is partial or either of its boxes cannot conclude.
  const misstatementOpen = location.partial || Boolean(boxTotals.scope1?.state) || Boolean(boxTotals.scope2_location?.state);
  const misstatement =
    !misstatementOpen && location.reported !== null && location.recomputed !== null ? location.recomputed - location.reported : null;
  const base = location.reported ?? location.recomputed;
  const scopes = (["scope1", "scope2_location", "scope2_market"] as const).map((key) => ({ key, total: boxTotals[key] }));
  return {
    location,
    market: inventory.market,
    misstatement,
    misstatementPct: misstatement !== null && location.reported ? misstatement / location.reported : null,
    misstatementOpen,
    materiality,
    materialityTonnes: base === null ? null : materiality * base,
    materialityBase: location.reported !== null ? "reported" : location.recomputed !== null ? "recalculated" : null,
    rows,
    materialBoxes: scopes.flatMap(({ key, total }) =>
      total && !total.state && total.reported !== null && total.recomputed !== null &&
      outcome(total.recomputed - total.reported, total.reported) === "material"
        ? [{
            title: BOX_TITLE[key].title,
            pctMaterial: total.reported ? (total.recomputed - total.reported) / total.reported : null,
            difference: total.recomputed - total.reported,
          }]
        : []
    ),
    openBoxes: scopes.flatMap(({ key, total }) => (total?.state ? [{ title: BOX_TITLE[key].title, state: total.state }] : [])),
    differences: differences.sort((a, b) => Math.abs(b.difference) - Math.abs(a.difference)),
  };
}
