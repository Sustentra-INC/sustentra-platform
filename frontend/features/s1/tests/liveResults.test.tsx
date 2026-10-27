/* @vitest-environment jsdom */
import { act, fireEvent, render, renderHook, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

const responses = vi.hoisted(() => ({ byPath: {} as Record<string, unknown> }));
vi.mock("../../../lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../../../lib/api")>()),
  api: vi.fn((path: string) => Promise.resolve(responses.byPath[path])),
}));

import { liveResultsFromRecalculation } from "../adapters/recalculationResultsAdapter";
import type { Recalculation, RecalculationReference } from "../api/recalculation";
import { BackendVerificationResults, examinerOptions } from "../components/BackendVerificationResults";
import { engagementConfig } from "../fixtures/engagementConfig";
import { verificationLines } from "../fixtures/verification/resultsDataset";
import type { EngagementConfig } from "../types";
import { buildResultBoxes, examinationKey, lineRecomputed, testedExaminationKeys } from "../utils/verificationTable";
import { useVerificationStore } from "../verification/verificationStore";
import liveExample from "./fixtures/recalculationLive.json";
import workbookExample from "./fixtures/recalculationWorkbookExample.json";

/*
 * recalculationLive.json is the backend's own response (EngagementRecalculationService over
 * the test FakeStore), shaped like a staging engagement mid-review:
 *  - natural gas: three monthly bills reviewed, April's awaiting review (Scope 1 partial);
 *  - diesel fleet fuel without vehicle groups (CH4 and N2O held open);
 *  - R-410A topped up; electricity at Facility A (NYUP) and B (RFCE), 600 MWh of certificates;
 *    steam at Facility B; no heating evidence;
 *  - reported: Scope 1 1,600, stationary 1,250, Scope 1 CO2 1,580, Scope 2 location 420,
 *    market 300, electricity 348.14; agricultural sources set out of scope in Setup.
 */
const LIVE = liveExample as unknown as Recalculation;
const WORKBOOK = workbookExample as unknown as Recalculation;

const byId = (result: Recalculation) => Object.fromEntries(liveResultsFromRecalculation(result).lines.map((l) => [l.id, l]));

describe("the live recalculation as Verification results lines", () => {
  const { lines, boxTotals, gasRows } = liveResultsFromRecalculation(LIVE);
  const line = byId(LIVE);

  it("makes each Scope 1 category a line, reported where the client's value is entered", () => {
    expect(line["s1-stationary"]).toMatchObject({ box: "scope1", category: "Stationary combustion", activity: "Natural Gas", reported: 1250 });
    expect(line["s1-stationary"].recomputed).toBeCloseTo(1274.748, 3);
    // Not entered: the cell says so, it is never a 0.
    expect(line["s1-mobile"]).toMatchObject({ activity: "Diesel Fuel", reported: null });
    expect(line["s1-fugitive"]).toMatchObject({ activity: "R-410A", reported: null });
    expect(line["s1-fugitive"].recomputed).toBeCloseTo(34.908, 3);
  });

  it("breaks Scope 1 down by fuel across facilities, and Scope 2 by facility, adding up to the roll-up", () => {
    expect(line["s1-stationary"].facilities).toEqual([
      expect.objectContaining({ facilityId: "natural-gas", facility: "All facilities", activity: "Natural Gas", reported: null }),
    ]);
    expect(line["s2l-electricity"].facilities?.map((f) => [f.facilityId, f.facility])).toEqual([
      ["facility-a", "Facility A"],
      ["facility-b", "Facility B"],
    ]);
    for (const l of lines.filter((x) => x.facilities?.length)) {
      const sum = (l.facilities ?? []).reduce((s, f) => s + (f.recomputed ?? 0), 0);
      expect(sum, l.id).toBeCloseTo(lineRecomputed(l) ?? 0, 6);
    }
  });

  it("says why a number is missing or partial, from the roll-up's per-source status", () => {
    expect(line["s1-stationary"].state).toMatchObject({ tone: "open", label: "Partial · 1 open" });
    expect(line["s1-stationary"].state?.detail).toContain("GAS-APR.pdf");
    expect(line["s1-mobile"].state?.detail).toContain("vehicle groups");
    expect(line["s1-process"]).toMatchObject({ facilities: null, state: { tone: "na", label: "Not calculated yet" } });
    expect(line["s1-agricultural"]).toMatchObject({ facilities: null, state: { tone: "na", label: "Not in scope" } });
    expect(line["s2l-heating"]).toMatchObject({ facilities: null, state: { tone: "unverifiable", label: "No reviewed evidence" } });
    expect(line["s2l-cooling"].state?.label).toBe("Not calculated yet");
    // Fully recalculated lines carry no state: their numbers say it all.
    expect(line["s2l-electricity"].state).toBeUndefined();
  });

  it("gives market-based rows no reported value of their own: the workbook reports that basis as a total", () => {
    expect(line["s2m-electricity"]).toMatchObject({ reported: null, reportedNote: "Total only" });
    expect(line["s2m-electricity"].recomputed).toBeCloseTo(243.704, 3);
  });

  it("takes each box's totals from the reported scope total and the roll-up", () => {
    expect(boxTotals.scope1).toMatchObject({ reported: 1600, state: { tone: "open", label: "Incomplete" } });
    expect(boxTotals.scope1?.recomputed).toBeCloseTo(1411.756, 3);
    expect(boxTotals.scope1?.notes).toEqual([
      "Counted as 0 (not calculated yet): process sources, purchased industrial gases, agricultural sources.",
    ]);
    expect(boxTotals.scope2_location).toMatchObject({ reported: 420 });
    expect(boxTotals.scope2_location?.state).toBeUndefined();
    expect(boxTotals.scope2_market?.recomputed).toBeCloseTo(326.701, 3);
    expect(boxTotals.biogenic).toMatchObject({ reported: null, recomputed: null, state: { label: "Not calculated yet" } });

    const [scope1, location, market] = buildResultBoxes(lines, () => false, boxTotals);
    expect(scope1.live).toBe(boxTotals.scope1);
    expect(location.totals.pctMaterial).toBeCloseTo((431.146 - 420) / 420, 4);
    expect(market.totals.difference).toBeCloseTo(26.701, 3);
    expect(location.normalizedMaterial).toBeNull();
    // Scope 1 lists its categories in the fixed order, then agricultural (live only), greyed with its state.
    expect(scope1.rows.map((r) => [r.categoryLabel, r.activity, r.state?.label ?? null])).toEqual([
      ["Stationary combustion", "Natural Gas", "Partial · 1 open"],
      ["Mobile combustion", "Diesel Fuel", "Partial · 1 open"],
      ["Fugitive emissions", "R-410A", null],
      ["Process emissions", "", "Not calculated yet"],
      ["Agricultural emissions", "", "Not in scope"],
    ]);
    // A row's share is of the reported scope total: stationary 1,250 of 1,600.
    expect(scope1.rows[0].share).toBeCloseTo(1250 / 1600, 6);
    expect(scope1.rows[1]).toMatchObject({ reported: null, reportedNote: "Not entered", share: null, pctMaterial: null });
  });

  it("keys examinations the way the backend stores workpaper items", () => {
    const keys = testedExaminationKeys(lines);
    expect(keys).toContain("vr:s1-stationary:natural-gas");
    expect(keys).toContain("vr:s2l-electricity:facility-a");
    for (const key of keys) expect(key).toMatch(/^[A-Za-z0-9][A-Za-z0-9:._-]{0,199}$/);
  });

  it("keeps the Required per-gas data points, in tonnes of each gas", () => {
    expect(gasRows).toHaveLength(21);
    const co2 = gasRows.find((r) => r.key === "scope1_co2");
    expect(co2).toMatchObject({ group: "Scope 1", gas: "CO₂", unit: "t", reported: 1580, state: { label: "Incomplete" } });
    expect(gasRows.find((r) => r.key === "scope1_ch4")).toMatchObject({ reported: null });
    expect(gasRows.find((r) => r.key === "scope1_ch4")?.state).toBeUndefined();
    expect(gasRows.filter((r) => r.group === "Scope 2, market-based")).toHaveLength(7);
  });

  it("falls back to the comparisons for results computed before the roll-up", () => {
    const old = liveResultsFromRecalculation(WORKBOOK);
    expect(old.boxTotals.scope1).toMatchObject({ reported: 1400 });
    expect(old.boxTotals.scope1?.recomputed).toBeCloseTo(1492.517, 3);
    expect(byId(WORKBOOK)["s2l-electricity"].facilities).toHaveLength(2);
    expect(old.gasRows.map((r) => r.key)).toContain("scope1_co2");
  });

  it("shows a brand-new engagement as nothing recalculated yet, without inventing numbers", () => {
    const empty: Recalculation = {
      ...WORKBOOK,
      engagement_id: "ENG-NEW",
      categories: {
        stationary_combustion: null,
        mobile_combustion: null,
        purchased_electricity_location_based: null,
        purchased_electricity_market_based: null,
      },
      scope_totals: { scope1: null, scope2_location: null, scope2_market: null },
      comparisons: [],
    };
    const fresh = liveResultsFromRecalculation(empty);
    expect(fresh.boxTotals.scope1).toMatchObject({ reported: null, recomputed: null, state: { label: "No reviewed evidence" } });
    expect(fresh.lines.filter((l) => l.facilities !== null)).toEqual([]);
  });
});

describe("the demo's boxes", () => {
  it("carry no live totals or states, so the fixture demo looks as it did", () => {
    const boxes = buildResultBoxes(verificationLines);
    expect(boxes.every((b) => b.live === undefined)).toBe(true);
    expect(boxes.flatMap((b) => b.rows).every((r) => r.state === null && r.reportedNote === null)).toBe(true);
  });
});

/* ------------------------------------ the screen ------------------------------------ */

const REFERENCE: RecalculationReference = {
  dataset: "EPA GHG Emission Factors Hub 2025",
  gwp_sets: ["AR5", "AR6"],
  default_gwp_set: "AR5",
  egrid_subregions: [{ egrid_subregion: "NYUP", name: "NPCC Upstate NY" }],
  stationary_fuels: ["Natural Gas"],
  mobile_fuels: ["Diesel Fuel"],
  reported_data_points: [{ key: "scope1_total", label: "Scope 1 (Total)", workbook_row: 22, unit: "t CO2e" }],
};

const ENGAGEMENT: EngagementConfig = {
  ...engagementConfig,
  engagementId: "ENG-1",
  engagementTeam: [],
  signedInLogin: "dana@verifier.test",
  signedInName: "Dana",
};

function renderScreen(engagement: EngagementConfig = ENGAGEMENT) {
  responses.byPath["/engagements/ENG-1/recalculation"] = LIVE;
  responses.byPath["/reference/recalculation"] = REFERENCE;
  const store = renderHook(() => useVerificationStore()).result;
  const view = render(
    <BackendVerificationResults engagement={engagement} store={store.current} onSaveInputs={async () => {}} onError={() => false} />
  );
  return { store, view };
}

describe("Verification results in backend mode", () => {
  it("renders the demo's boxes from the live recalculation, with inputs and data quality checks above them", async () => {
    renderScreen();
    const boxes = await screen.findByRole("region", { name: "Reported vs recomputed" });
    expect(screen.getByRole("region", { name: "Recalculation inputs" })).toBeTruthy();
    expect(screen.getByRole("region", { name: "Data quality checks" })).toBeTruthy();
    // The legacy table and its Results / Findings switch are gone.
    expect(screen.queryByText("Register finding")).toBeNull();
    expect(screen.queryByRole("button", { name: /Findings/ })).toBeNull();

    const scope1 = within(boxes).getByRole("button", { name: /^Scope 1/ });
    expect(scope1.textContent).toContain("1,600");
    expect(scope1.textContent).toContain("1,412");
    expect(scope1.textContent).toContain("Incomplete");
    const market = within(boxes).getByRole("button", { name: /^Scope 2, market-based/ });
    expect(market.textContent).toContain("+8.9% material");
    expect(within(boxes).getByRole("button", { name: /^By gas/ }).textContent).toContain("1 of 21 reported values entered");
  });

  it("opens the calculation panel on a row and records the signed-in person as examiner", async () => {
    const { store } = renderScreen();
    fireEvent.click(await screen.findByRole("button", { name: "Natural Gas" }));
    const panel = screen.getByRole("complementary", { name: "Scope 1 · Natural Gas" });
    expect(within(panel).getByText("All facilities")).toBeTruthy();
    fireEvent.click(within(panel).getByRole("button", { name: /Record examination/ }));
    // No team in Setup: the signed-in person is the examiner, already chosen.
    expect(within(panel).getByRole("button", { name: /Dana/, pressed: true })).toBeTruthy();
    act(() => {
      fireEvent.click(within(panel).getByRole("button", { name: "Save" }));
    });
    expect(store.current.examinations[examinationKey("s1-stationary", "natural-gas")]).toMatchObject({
      examinedBy: "Dana",
      examinedByLogin: "dana@verifier.test",
    });
  });

  it("offers the engagement team as examiners when Setup has one", () => {
    const team = [{ name: "M. Osei", login: "mosei" }];
    expect(examinerOptions({ ...ENGAGEMENT, engagementTeam: team })).toBe(team);
    expect(examinerOptions({ ...ENGAGEMENT, signedInLogin: undefined })).toEqual([]);
  });
});
