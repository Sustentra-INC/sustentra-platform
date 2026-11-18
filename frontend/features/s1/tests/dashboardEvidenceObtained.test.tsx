/* @vitest-environment jsdom */
import { describe, expect, it } from "vitest";
import "@testing-library/jest-dom/vitest";
import { render, screen } from "@testing-library/react";

import { coverageFromRecalculation, type RecalcAwaitingReview, type Recalculation } from "../api/recalculation";
import { DashboardScreen } from "../components/DashboardScreen";
import { engagementConfig } from "../fixtures/engagementConfig";
import { dashboardFigures } from "../utils/engagementActivity";

const BASE: Recalculation = {
  engagement_id: "ENG-X",
  gwp_set: "AR5",
  reporting_period: { start: "2026-01-01", end: "2026-12-31" },
  tolerance_pct: 5,
  categories: {
    stationary_combustion: null,
    mobile_combustion: null,
    purchased_electricity_location_based: null,
    purchased_electricity_market_based: null,
  },
  scope_totals: { scope1: null, scope2_location: null, scope2_market: null },
  comparisons: [],
  needs_input: [],
  awaiting_review: [],
  excluded: [],
  not_recalculated: [],
  documents_considered: 22,
};

const waiting = (typeId: string, record: string): RecalcAwaitingReview => ({
  document_id: `doc-${record}`,
  record,
  canonical_type_id: typeId,
  fields: ["quantity"],
});

/** Stationary, vehicle, electricity and refrigerant documents are all in; nothing is accepted yet. */
const ALL_AWAITING: Recalculation = {
  ...BASE,
  awaiting_review: [
    waiting("CT-S1-FUELQTY", "Müller Käserei – Zürich Erdgas"),
    waiting("CT-S1-MOBFUEL", "燃料 receipt"),
    waiting("CT-S2-ELEC", "Strom CO₂ 12 °F"),
    waiting("CT-S1-REFRSVC", "Service 1"),
  ],
};

type Cov = Parameters<typeof dashboardFigures>[0]["coverage"];
const figuresFor = (coverage: Cov) => dashboardFigures({ evidence: [], values: [], asks: [], findings: [], coverage });
const figuresOf = (result: Recalculation) => figuresFor(coverageFromRecalculation(result));
const show = (figures: ReturnType<typeof figuresFor>) =>
  render(<DashboardScreen engagement={engagementConfig} figures={figures} />);

const rule = (ruleId: string, status: "inputs_present" | "inputs_missing", missingBecause?: "awaiting_review" | "needs_input" | "no_evidence") => ({
  ruleId,
  assertion: ruleId,
  appliesTo: [],
  status,
  reason: "",
  ...(missingBecause ? { missingBecause } : {}),
});

describe("dashboard: documents in, values not yet accepted", () => {
  it("counts them as evidence obtained and names none as missing", () => {
    const rules = coverageFromRecalculation(ALL_AWAITING);
    expect(rules.filter((r) => r.missingBecause === "awaiting_review")).toHaveLength(4);
    // The Coverage panel is unchanged: status still says inputs are not ready.
    expect(rules.filter((r) => r.missingBecause).every((r) => r.status === "inputs_missing")).toBe(true);

    expect(figuresOf(ALL_AWAITING).coverage).toMatchObject({
      present: 0,
      awaitingReview: 4,
      needsChoice: 0,
      missing: 0,
      obtained: 4,
      inScope: 4,
    });

    show(figuresOf(ALL_AWAITING));
    expect(screen.getByText("4 of 4 in-scope data points have their evidence")).toBeInTheDocument();
    expect(screen.getByText("data points waiting for review")).toBeInTheDocument();
    expect(screen.queryByText(/missing evidence/)).toBeNull();
    const step = screen.getByText("Assessment").closest("li");
    expect(step).toHaveTextContent("4 data points waiting for review");
    expect(step).not.toHaveTextContent("missing evidence");
  });

  it("keeps the record names (non-ASCII) in the coverage reasons", () => {
    const rules = coverageFromRecalculation(ALL_AWAITING);
    expect(rules.find((r) => r.ruleId === "COV-S2-LOCATION")?.reason).toContain("Strom CO₂ 12 °F");
    expect(rules.find((r) => r.ruleId === "COV-S1-STATIONARY")?.reason).toContain("Müller Käserei – Zürich Erdgas");
    expect(rules.find((r) => r.ruleId === "COV-S1-MOBILE")?.reason).toContain("燃料 receipt");
  });

  it("with some data points reviewed, counts present and waiting together", () => {
    const some: Recalculation = {
      ...ALL_AWAITING,
      awaiting_review: ALL_AWAITING.awaiting_review.filter((a) => a.canonical_type_id !== "CT-S1-FUELQTY"),
      categories: {
        ...BASE.categories,
        stationary_combustion: {
          lines: [{ key: "Natural gas" }],
          flags: [],
          details: { inputs: [{ documents: ["d1"] }] },
        } as unknown as Recalculation["categories"]["stationary_combustion"],
      },
    };
    expect(figuresOf(some).coverage).toMatchObject({ present: 1, awaitingReview: 3, missing: 0, obtained: 4, inScope: 4 });
  });
});

describe("dashboard: a choice is needed, or evidence is absent", () => {
  it("a grid region not chosen is 'needs a choice', not missing", () => {
    const result: Recalculation = {
      ...BASE,
      needs_input: [{ kind: "grid_region", key: "Zürich plant", message: "Choose a grid region." }],
    };
    expect(figuresOf(result).coverage).toMatchObject({ needsChoice: 1, awaitingReview: 0, missing: 0, obtained: 1 });
    show(figuresOf(result));
    expect(screen.getByText("data point needs a choice")).toBeInTheDocument();
    expect(screen.queryByText(/missing evidence/)).toBeNull();
    expect(screen.getByText("Assessment").closest("li")).toHaveTextContent("1 data point needs a choice");
  });

  it("a rule with no recorded reason still counts as missing evidence", () => {
    const figures = figuresFor([rule("COV-A", "inputs_present"), rule("COV-B", "inputs_missing")]);
    expect(figures.coverage).toMatchObject({ present: 1, missing: 1, obtained: 1, inScope: 2 });
    show(figures);
    expect(screen.getByText("1 of 2 in-scope data points have their evidence")).toBeInTheDocument();
    expect(screen.getByText("data point missing evidence")).toBeInTheDocument();
  });

  it("one data point with no documents is the only one missing", () => {
    const figures = figuresFor([
      rule("COV-A", "inputs_present"),
      rule("COV-B", "inputs_missing", "awaiting_review"),
      rule("COV-C", "inputs_missing", "no_evidence"),
    ]);
    expect(figures.coverage).toMatchObject({ obtained: 2, inScope: 3, missing: 1 });
  });

  it("shows each attention line only when its count is above zero, mixing all three", () => {
    show(
      figuresFor([
        rule("COV-A", "inputs_missing", "awaiting_review"),
        rule("COV-B", "inputs_missing", "needs_input"),
        rule("COV-C", "inputs_missing", "no_evidence"),
      ])
    );
    expect(screen.getByText("2 of 3 in-scope data points have their evidence")).toBeInTheDocument();
    expect(screen.getByText("data point waiting for review")).toBeInTheDocument();
    expect(screen.getByText("data point needs a choice")).toBeInTheDocument();
    expect(screen.getByText("data point missing evidence")).toBeInTheDocument();
  });

  it("an empty engagement keeps its empty state", () => {
    const empty = { ...BASE, documents_considered: 0 };
    expect(figuresOf(empty).coverage).toMatchObject({ obtained: 0, inScope: 0, missing: 0 });
    show(figuresOf(empty));
    expect(screen.getAllByText("Not started").length).toBeGreaterThan(0);
    expect(screen.queryByText(/data points? (waiting|need|missing)/)).toBeNull();
  });
});
