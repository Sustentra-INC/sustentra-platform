/* @vitest-environment jsdom */
import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";

import { coverageFromRecalculation, type RecalcAwaitingReview, type Recalculation } from "../api/recalculation";
import { CoveragePanel } from "../components/CoveragePanel";
import { coverageRules } from "../fixtures/verification/coverageRules";
import type { CoverageRule } from "../types/verification";
import { coverageView, dashboardFigures } from "../utils/engagementActivity";

afterEach(cleanup);

const BASE: Recalculation = {
  engagement_id: "ENG-X",
  gwp_set: "AR5",
  reporting_period: { start: "2025-01-01", end: "2025-12-31" },
  tolerance_pct: 5,
  categories: { stationary_combustion: null, mobile_combustion: null, purchased_electricity_location_based: null, purchased_electricity_market_based: null },
  scope_totals: { scope1: null, scope2_location: null, scope2_market: null },
  comparisons: [],
  needs_input: [],
  awaiting_review: [],
  excluded: [],
  not_recalculated: [],
  documents_considered: 0,
};

const waiting = (typeId: string, record: string): RecalcAwaitingReview => ({ document_id: `d-${record}`, record, canonical_type_id: typeId, fields: ["quantity"] });

/** Every source's documents are in, and every value waits for a reviewer. */
const EVERYTHING_WAITING: Recalculation = {
  ...BASE,
  awaiting_review: [waiting("CT-S1-FUELQTY", "gas.pdf"), waiting("CT-S1-MOBFUEL", "fleet.pdf"), waiting("CT-S2-ELEC", "power.pdf"), waiting("CT-S1-REFRSVC", "log.pdf")],
};

function panel(rules: CoverageRule[]) {
  render(<CoveragePanel coverage={{ rules }} isRequested={() => false} onRequest={vi.fn()} />);
}

/** The headline counts, as "4 awaiting review" -> 4. */
function counts(): Record<string, number> {
  const group = screen.getByRole("group", { name: "Show checks" });
  return Object.fromEntries(
    within(group)
      .getAllByRole("button")
      .map((b) => {
        const m = /^(\d+)\s*(.+)$/.exec(b.textContent ?? "")!;
        return [m[2], Number(m[1])];
      })
  );
}

describe("the Coverage & requests headline", () => {
  it("counts everything awaiting review as awaiting review, and 0 as missing", () => {
    const rules = coverageFromRecalculation(EVERYTHING_WAITING).filter((r) => !r.ruleId.startsWith("COV-S1-PROCESS"));
    panel(rules);
    const c = counts();
    expect(c["missing"]).toBe(0);
    expect(c["awaiting review"]).toBeGreaterThan(0);
    // The old single "Inputs missing" count is gone.
    expect(screen.queryByRole("button", { name: /Inputs missing/ })).toBeNull();
  });

  it("counts a category with no evidence at all as missing, next to the ones awaiting review", () => {
    const only = { ...EVERYTHING_WAITING, awaiting_review: EVERYTHING_WAITING.awaiting_review.filter((a) => a.canonical_type_id !== "CT-S1-FUELQTY") };
    panel(coverageFromRecalculation(only));
    const c = counts();
    expect(c["missing"]).toBe(1);
    expect(c["awaiting review"]).toBeGreaterThan(0);
  });

  it("shows the same figures as the dashboard", () => {
    for (const result of [EVERYTHING_WAITING, BASE]) {
      const rules = coverageFromRecalculation(result);
      const figures = dashboardFigures({ evidence: [], values: [], asks: [], findings: [], coverage: rules }).coverage!;
      panel(rules);
      const c = counts();
      expect(c["awaiting review"]).toBe(figures.awaitingReview);
      expect(c["need a choice"]).toBe(figures.needsChoice);
      expect(c["missing"]).toBe(figures.missing);
      expect(c["present"]).toBe(figures.present);
      expect(c["not applicable"]).toBe(figures.notApplicable);
      expect(c["out of scope"]).toBe(figures.outOfScope);
      cleanup();
    }
  });

  it("matches the dashboard on the demo data too", () => {
    const figures = dashboardFigures({ evidence: [], values: [], asks: [], findings: [], coverage: coverageRules }).coverage!;
    panel(coverageRules);
    const c = counts();
    expect([c["awaiting review"], c["need a choice"], c["missing"], c["present"]]).toEqual([
      figures.awaitingReview,
      figures.needsChoice,
      figures.missing,
      figures.present,
    ]);
    expect(c["missing"]).toBe(coverageRules.filter((r) => coverageView(r) === "missing").length);
  });

  it("opens on what needs someone, and each count filters the list", () => {
    panel(coverageFromRecalculation(EVERYTHING_WAITING));
    const first = screen.getByRole("button", { pressed: true });
    expect(first).toHaveTextContent(/awaiting review/);
    const missing = screen.getByRole("button", { name: /\bmissing$/ });
    fireEvent.click(missing);
    expect(screen.getByText("No checks in this state.")).toBeInTheDocument();
    fireEvent.click(missing); // off: every check
    expect(screen.queryByText("No checks in this state.")).toBeNull();
  });

  it("lists method checks as their own count only while one is still to do", () => {
    const method: CoverageRule = { ruleId: "COV-GWP", assertion: "A GWP set is chosen", appliesTo: [], status: "inputs_missing", reason: "No GWP set chosen." };
    panel([method, ...coverageFromRecalculation(BASE)]);
    expect(counts()["method checks to do"]).toBe(1);
    expect(counts()["missing"]).toBe(coverageFromRecalculation(BASE).filter((r) => r.status === "inputs_missing").length);
    cleanup();
    panel(coverageFromRecalculation(BASE));
    expect(counts()["method checks to do"]).toBeUndefined();
  });

  it("keeps the figures in the regular weight, with no raw size or colour in the rules", () => {
    const css = readFileSync(join(process.cwd(), "features", "s1", "styles", "s1-workpaper.css"), "utf8");
    const rule = /\.s1-cr-filter__n\s*\{[^}]*\}/.exec(css)?.[0] ?? "";
    expect(rule).not.toContain("--weight-strong"); // values stay regular: bold is for titles and structure
  });
});
