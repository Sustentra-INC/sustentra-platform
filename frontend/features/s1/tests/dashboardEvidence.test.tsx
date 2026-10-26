/* @vitest-environment jsdom */
import { describe, expect, it, vi } from "vitest";
import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen } from "@testing-library/react";

import { coverageFromRecalculation, METHOD_CHECK_RULE_IDS, type Recalculation } from "../api/recalculation";
import { DashboardScreen } from "../components/DashboardScreen";
import { engagementConfig } from "../fixtures/engagementConfig";
import { coverageRules } from "../fixtures/verification/coverageRules";
import type { EngagementConfig } from "../types";
import { dashboardFigures } from "../utils/engagementActivity";
import workbookExample from "./fixtures/recalculationWorkbookExample.json";

/** Claire's workbook example: reviewed gas and electricity bills, reported totals entered. */
const RESULT = workbookExample as unknown as Recalculation;

/** What the backend returns for a brand-new engagement: no documents, a start date and no end date. */
const EMPTY: Recalculation = {
  engagement_id: "ENG-NEW",
  gwp_set: "AR5",
  reporting_period: { start: "2026-10-08", end: null },
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
  not_recalculated: ["Scope 1 process sources"],
  documents_considered: 0,
};

const NEW_ENGAGEMENT: EngagementConfig = {
  ...engagementConfig,
  engagementId: "ENG-NEW",
  reportingPeriod: { start: "2026-10-08", end: "" },
};

const figuresFor = (coverage: Parameters<typeof dashboardFigures>[0]["coverage"]) =>
  dashboardFigures({ evidence: [], values: [], asks: [], findings: [], coverage });

const attentionRows = () =>
  screen.getAllByRole("button").filter((b) => b.className.includes("s1-attention__item"));

describe("dashboard evidence figures: live coverage", () => {
  it("counts only evidence checks, not the method checks Coverage & requests also lists", () => {
    const rules = coverageFromRecalculation(EMPTY);
    // The live rules include a GWP basis (always present) and an unset period (missing) ...
    expect(rules.find((r) => r.ruleId === "COV-GWP")?.status).toBe("inputs_present");
    expect(rules.find((r) => r.ruleId === "COV-PERIOD")?.status).toBe("inputs_missing");

    // ... and neither is evidence for a data point.
    const figures = figuresFor(rules);
    expect(figures.coverage).toMatchObject({ present: 0, missing: 0 });
    expect(figures.reportingPeriodIncomplete).toBe(true);
  });

  it("reads 'Nothing uploaded yet' on a brand-new engagement, and sends the missing end date to Setup", () => {
    const onNavigate = vi.fn();
    render(
      <DashboardScreen
        engagement={NEW_ENGAGEMENT}
        figures={figuresFor(coverageFromRecalculation(EMPTY))}
        onNavigate={onNavigate}
      />
    );

    const meter = screen.getByRole("button", { name: /Evidence obtained/ });
    expect(meter).toHaveTextContent("Evidence obtained0%Nothing uploaded yet");
    expect(screen.queryByText(/in-scope data points/)).toBeNull();
    expect(screen.queryByText(/of 0/)).toBeNull();

    const rows = attentionRows();
    expect(rows.map((b) => b.textContent)).toEqual(["Reporting period needs a start and an end dateSetup"]);
    expect(screen.queryByText(/missing evidence/)).toBeNull();
    fireEvent.click(rows[0]);
    expect(onNavigate).toHaveBeenCalledWith("setup");
  });

  it("falls back to documents read while no evidence check is in play", () => {
    const figures = {
      ...figuresFor(coverageFromRecalculation(EMPTY)),
      documents: 4,
      documentsReadable: 1,
    };
    render(<DashboardScreen engagement={NEW_ENGAGEMENT} figures={figures} />);
    expect(screen.getByRole("button", { name: /Evidence obtained/ })).toHaveTextContent("25%1 of 4 documents read");
  });

  it("leaves a missing reported total out of 'data points missing evidence'", () => {
    const withoutScope1Reported: Recalculation = {
      ...RESULT,
      comparisons: RESULT.comparisons.map((c) =>
        c.key === "scope1_total" ? { ...c, reported: null, difference: null, difference_pct: null, status: "not_reported" } : c
      ),
    };
    const rules = coverageFromRecalculation(withoutScope1Reported);
    expect(rules.find((r) => r.ruleId === "COV-REPORTED")?.status).toBe("inputs_missing");

    const figures = figuresFor(rules);
    // Gas, location-based and market-based electricity: the evidence checks with inputs present.
    expect(figures.coverage).toMatchObject({ present: 3, missing: 0 });
    expect(figures.reportingPeriodIncomplete).toBe(false);

    render(<DashboardScreen engagement={engagementConfig} figures={figures} />);
    expect(screen.getByText("3 of 3 in-scope data points have their evidence")).toBeInTheDocument();
    expect(screen.queryByText(/missing evidence/)).toBeNull();
    expect(screen.queryByText(/Reporting period needs/)).toBeNull();
  });

  it("names every method check the recalculation can produce", () => {
    const everything: Recalculation = {
      ...RESULT,
      excluded: [{ document_id: "GAS-1", record: "gas.pdf", canonical_type_id: "CT-S1-FUELQTY", period: "", reason: "withdrawn" }],
    };
    const ids = coverageFromRecalculation(everything).map((r) => r.ruleId);
    expect(METHOD_CHECK_RULE_IDS.filter((id) => !ids.includes(id))).toEqual([]);
  });
});

describe("dashboard evidence figures: demo coverage", () => {
  it("counts every fixture rule, as before", () => {
    expect(coverageRules.some((r) => METHOD_CHECK_RULE_IDS.includes(r.ruleId))).toBe(false);
    const figures = figuresFor(coverageRules);
    const count = (status: string) => coverageRules.filter((r) => r.status === status).length;
    expect(figures.coverage).toEqual({
      present: count("inputs_present"),
      missing: count("inputs_missing"),
      notApplicable: count("not_applicable"),
      outOfScope: count("out_of_scope"),
    });
    expect(figures.reportingPeriodIncomplete).toBe(false);

    render(<DashboardScreen engagement={engagementConfig} figures={figures} />);
    const covered = count("inputs_present") + count("inputs_missing");
    expect(screen.getByText(`${count("inputs_present")} of ${covered} in-scope data points have their evidence`)).toBeInTheDocument();
    expect(screen.getByText("data points missing evidence")).toBeInTheDocument();
    expect(screen.queryByText(/Reporting period needs/)).toBeNull();
  });
});
