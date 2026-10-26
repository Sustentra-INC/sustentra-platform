/* @vitest-environment jsdom */
import { beforeEach, describe, expect, it, vi } from "vitest";
import "@testing-library/jest-dom/vitest";
import { act, fireEvent, render, screen } from "@testing-library/react";

vi.mock("../../../lib/api", () => ({
  api: vi.fn(),
  apiPath: (path: string) => `/api/v1${path}`,
}));

import { api } from "../../../lib/api";
import {
  coverageFromRecalculation,
  METHOD_CHECK_RULE_IDS,
  missingReportedTotals,
  type Recalculation,
} from "../api/recalculation";
import { BackendDashboard } from "../components/BackendDashboard";
import { DashboardScreen } from "../components/DashboardScreen";
import { engagementConfig } from "../fixtures/engagementConfig";
import { coverageRules } from "../fixtures/verification/coverageRules";
import type { EngagementConfig } from "../types";
import type { Examination } from "../types/verification";
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

/** The workbook example's engagement, with both dates of its period set. */
const WORKBOOK_ENGAGEMENT: EngagementConfig = { ...engagementConfig, engagementId: RESULT.engagement_id };

/** The workbook example with no reported total for the given headline data points. */
const withoutReported = (...keys: string[]): Recalculation => ({
  ...RESULT,
  comparisons: RESULT.comparisons.map((c) =>
    keys.includes(c.key) ? { ...c, reported: null, difference: null, difference_pct: null, status: "not_reported" } : c
  ),
});

/** Every recalculated result examined, so only the reported totals can hold the Assessment step open. */
const examinedAll = (result: Recalculation): Record<string, Examination> =>
  Object.fromEntries(
    result.comparisons
      .filter((c) => c.recalculated !== null && c.status !== "not_in_scope")
      .map((c) => [`RECALC-${c.key}`, { examinationState: "examined_no_exceptions", nextActionWith: "none" }])
  );

const figuresFor = (coverage: Parameters<typeof dashboardFigures>[0]["coverage"]) =>
  dashboardFigures({ evidence: [], values: [], asks: [], findings: [], coverage });

const attentionRows = () =>
  screen.getAllByRole("button").filter((b) => b.className.includes("s1-attention__item"));

const assessmentStep = () => screen.getByText("Assessment").closest("li");

/** The live dashboard, with the recalculation the backend returns, once that has landed. */
async function renderLive(
  engagement: EngagementConfig,
  result: Recalculation,
  options: { examinations?: Record<string, Examination>; onNavigate?: (key: string) => void } = {}
) {
  vi.mocked(api).mockResolvedValue(result);
  const props = {
    engagement,
    evidence: [],
    values: [],
    asks: [],
    findings: [],
    examinations: options.examinations ?? {},
    onNavigate: options.onNavigate,
    onError: () => false,
  };
  const view = render(<BackendDashboard {...props} />);
  await act(() => new Promise((resolve) => setTimeout(resolve, 0)));
  return { ...view, props };
}

beforeEach(() => {
  vi.mocked(api).mockReset();
});

describe("dashboard evidence figures: live coverage", () => {
  it("counts only evidence checks, not the method checks Coverage & requests also lists", () => {
    const rules = coverageFromRecalculation(EMPTY);
    // The live rules include a GWP basis (always present) and an unset period (missing) ...
    expect(rules.find((r) => r.ruleId === "COV-GWP")?.status).toBe("inputs_present");
    expect(rules.find((r) => r.ruleId === "COV-PERIOD")?.status).toBe("inputs_missing");

    // ... and neither is evidence for a data point.
    expect(figuresFor(rules).coverage).toMatchObject({ present: 0, missing: 0 });
  });

  it("reads 'Nothing uploaded yet' on a brand-new engagement, and sends the missing end date to Setup", async () => {
    const onNavigate = vi.fn();
    await renderLive(NEW_ENGAGEMENT, EMPTY, { onNavigate });
    expect(api).toHaveBeenCalledWith("/engagements/ENG-NEW/recalculation");

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

  it("clears the reporting period row as soon as Setup saves the end date, before the recalculation catches up", async () => {
    const { rerender, props } = await renderLive(NEW_ENGAGEMENT, EMPTY);
    expect(screen.getByText("Reporting period needs a start and an end date")).toBeInTheDocument();

    // The recalculation already fetched still has no end date; the engagement now has one.
    rerender(<BackendDashboard {...props} engagement={{ ...NEW_ENGAGEMENT, reportingPeriod: { start: "2026-10-08", end: "2027-10-07" } }} />);
    expect(screen.queryByText(/Reporting period needs/)).toBeNull();
    expect(api).toHaveBeenCalledTimes(1);

    // And it comes back at once if a date is cleared.
    rerender(<BackendDashboard {...props} engagement={{ ...NEW_ENGAGEMENT, reportingPeriod: { start: "", end: "2027-10-07" } }} />);
    expect(screen.getByText("Reporting period needs a start and an end date")).toBeInTheDocument();
  });

  it("shows no reporting period row before an engagement is chosen", async () => {
    await renderLive({ ...NEW_ENGAGEMENT, clientName: "", engagementId: "", reportingPeriod: { start: "", end: "" } }, EMPTY);
    expect(api).not.toHaveBeenCalled();
    expect(screen.queryByText(/Reporting period needs/)).toBeNull();
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

  it("flags a missing reported total on its own row, not as a data point missing evidence", async () => {
    const result = withoutReported("scope1_total");
    const rules = coverageFromRecalculation(result);
    expect(rules.find((r) => r.ruleId === "COV-REPORTED")).toMatchObject({
      status: "inputs_missing",
      reason: "Reported value not entered for Scope 1 (Total).",
    });
    expect(missingReportedTotals(result)).toEqual(["Scope 1 (Total)"]);
    // Gas, location-based and market-based electricity: the evidence checks with inputs present.
    expect(figuresFor(rules).coverage).toMatchObject({ present: 3, missing: 0 });

    const onNavigate = vi.fn();
    await renderLive(WORKBOOK_ENGAGEMENT, result, { onNavigate });
    expect(screen.getByText("3 of 3 in-scope data points have their evidence")).toBeInTheDocument();
    expect(screen.queryByText(/missing evidence/)).toBeNull();
    expect(screen.queryByText(/Reporting period needs/)).toBeNull();

    const row = attentionRows().find((b) => b.textContent?.startsWith("Reported total"));
    expect(row).toHaveTextContent(/^Reported total not enteredResults$/);
    fireEvent.click(row!);
    expect(onNavigate).toHaveBeenCalledWith("results");
  });

  it("says 'Reported totals not entered' when more than one is missing", async () => {
    const result = withoutReported("scope1_total", "scope2_market_total");
    expect(missingReportedTotals(result)).toEqual(["Scope 1 (Total)", "Scope 2 (Total), market-based"]);
    await renderLive(WORKBOOK_ENGAGEMENT, result);
    expect(screen.getByText("Reported totals not entered")).toBeInTheDocument();
    expect(screen.queryByText("Reported total not entered")).toBeNull();
  });

  it("keeps the Assessment step open until the reported totals are entered", async () => {
    const missing = withoutReported("scope1_total");
    const first = await renderLive(WORKBOOK_ENGAGEMENT, missing, { examinations: examinedAll(missing) });
    expect(screen.getByText(/results examined/)).toHaveTextContent(/^(\d+) of \1 results examined$/);
    expect(assessmentStep()).not.toHaveClass("s1-timeline__step--done");
    first.unmount();

    await renderLive(WORKBOOK_ENGAGEMENT, RESULT, { examinations: examinedAll(RESULT) });
    expect(missingReportedTotals(RESULT)).toEqual([]);
    expect(screen.queryByText(/Reported totals? not entered/)).toBeNull();
    expect(assessmentStep()).toHaveClass("s1-timeline__step--done");
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
    // The live dashboard's own rows; the demo sets neither.
    expect(figures.reportingPeriodIncomplete).toBeUndefined();
    expect(figures.reportedTotalsMissing).toBeUndefined();

    render(<DashboardScreen engagement={engagementConfig} figures={figures} />);
    const covered = count("inputs_present") + count("inputs_missing");
    expect(screen.getByText(`${count("inputs_present")} of ${covered} in-scope data points have their evidence`)).toBeInTheDocument();
    expect(screen.getByText("data points missing evidence")).toBeInTheDocument();
    expect(screen.queryByText(/Reporting period needs/)).toBeNull();
    expect(screen.queryByText(/Reported totals? not entered/)).toBeNull();
  });
});
