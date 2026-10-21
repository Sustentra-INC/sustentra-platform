import type { ResultLine } from "../types/verificationResults";
import { buildResultBoxes, differs, facilityRecomputed, facilityReported, lineRecomputed, lineReported } from "./verificationTable";

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
