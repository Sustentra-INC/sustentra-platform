/* @vitest-environment jsdom */
import { act, fireEvent, render, renderHook, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

const responses = vi.hoisted(() => ({ byPath: {} as Record<string, unknown> }));
vi.mock("../../../lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../../../lib/api")>()),
  api: vi.fn((path: string) => Promise.resolve(responses.byPath[path])),
}));

import { api } from "../../../lib/api";
import { liveResultsFromRecalculation } from "../adapters/recalculationResultsAdapter";
import type { Recalculation, RecalculationReference } from "../api/recalculation";
import { BackendVerificationResults, examinerOptions } from "../components/BackendVerificationResults";
import { VerificationResults } from "../components/VerificationResults";
import { VerificationSource } from "../components/VerificationSource";
import { VerificationWorkspace } from "../components/VerificationWorkspace";
import { engagementConfig } from "../fixtures/engagementConfig";
import { verificationLines } from "../fixtures/verification/resultsDataset";
import type { EngagementConfig } from "../types";
import type { EvidenceSource, ResultLine } from "../types/verificationResults";
import { liveStatementFigures } from "../utils/outputStatement";
import { buildResultBoxes, examinationKey, lineRecomputed, testedExaminationKeys } from "../utils/verificationTable";
import { useWorkpaperSync } from "../verification/useWorkpaperSync";
import { useVerificationStore } from "../verification/verificationStore";
import liveExample from "./fixtures/recalculationLive.json";
import probeExample from "./fixtures/recalculationCompareProbes.json";
import oddExample from "./fixtures/recalculationOddQuantities.json";
import refrigerantExample from "./fixtures/recalculationRefrigerants.json";
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

  it("does not compare a line whose recalculation is still incomplete, as a box does not", () => {
    // Stationary combustion: reported 1,250, recalculated 1,274.7 so far, with April's bill awaiting review.
    expect(LIVE.rollup?.final_outputs.find((o) => o.key === "stationary_combustion_total")?.status).toBe("incomplete");
    expect(line["s1-stationary"].inconclusive).toBe(true);
    const [scope1] = buildResultBoxes(lines, () => false, boxTotals);
    const stationary = scope1.rows.find((r) => r.key === "s1-stationary")!;
    expect(stationary).toMatchObject({ reported: 1250, difference: null, pctDifference: null, pctMaterial: null, notTested: false });
    expect(stationary.recomputed).toBeCloseTo(1274.748, 3);
    // Lines whose data point concludes keep their comparison.
    expect(line["s2l-electricity"].inconclusive).toBeUndefined();
    const [, location] = buildResultBoxes(lines, () => false, boxTotals);
    expect(location.rows.find((r) => r.key === "s2l-electricity")?.difference).toBeCloseTo(0.008, 3);
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

describe("a refrigerant's material balance in the Source pane", () => {
  /*
   * recalculationRefrigerants.json is the backend's response for one R-410A balance with every
   * term: two service top-ups (P_S 40 + 5.5 lb), a new unit charged with 30 lb of a 25 lb full
   * charge (P_N, C_N) and a retired unit of 12 lb full charge with 9 lb recovered (C_D, R_D).
   */
  const BALANCE = refrigerantExample as unknown as Recalculation;

  it("shows a total only where the records' listed amounts make the term, and it equals the term", () => {
    const store = renderHook(() => useVerificationStore()).result.current;
    render(<VerificationWorkspace lines={liveResultsFromRecalculation(BALANCE).lines} store={store} team={[]} />);
    fireEvent.click(screen.getByRole("button", { name: "R-410A" }));
    const panel = screen.getByRole("complementary", { name: "Scope 1 · R-410A" });
    const balance = within(panel).getByText("R-410A emitted").closest("tr")!;
    const terms = within(balance).getAllByRole("button");
    expect(terms.map((t) => t.textContent)).toEqual(["30 lb", "25 lb", "45.5 lb", "12 lb", "9 lb"]);
    const shown: Record<string, string | null> = {};
    for (const term of terms) {
      fireEvent.click(term);
      const source = within(panel).getByRole("region", { name: "Source" });
      const total = source.querySelector("tfoot .s1-vw-num");
      shown[term.textContent ?? ""] = total?.textContent ?? null;
      if (total) expect(Number(total.textContent?.replace(/,/g, ""))).toBe(Number(term.textContent?.replace(/[^\d.]/g, "")));
      else expect(source.querySelector("td.s1-vw-num")).toBeNull(); // no amounts that contradict the term
    }
    // P_N, P_S and R_D add up their records; the full charges (C_N, C_D) list the records without amounts.
    expect(shown).toEqual({ "30 lb": "30", "25 lb": null, "45.5 lb": "45.5", "12 lb": null, "9 lb": "9" });
  });

  it("names the full-charge records and says where their capacity is read", () => {
    const [r410a] = byId(BALANCE)["s1-fugitive"].facilities ?? [];
    const cells = r410a.steps[0].how.filter((c) => c.source);
    const fullCharge = cells[1].source;
    expect(fullCharge).toMatchObject({ kind: "evidence", total: null, records: [{ record: "NEW-RTU.pdf", quantity: null }] });
    expect(fullCharge && "note" in fullCharge ? fullCharge.note : "").toMatch(/equipment capacity/);
    expect(cells[4].source).toMatchObject({ total: 9, records: [{ record: "RETIRED-RTU.pdf", quantity: 9 }] });
  });
});

describe("the calculation panel on live data", () => {
  const line = byId(LIVE);
  const text = (cells: { text: string }[]) => cells.map((c) => c.text).join("");

  it("shows the backend's own steps on the Recomputed side, the client's side honestly empty", () => {
    const [gas] = line["s1-stationary"].facilities ?? [];
    expect(gas.steps.map((s) => s.step)).toEqual(["CO₂ (Eq 1)", "CH₄ (Eq 1)", "N₂O (Eq 1)", "Total CO₂e"]);
    expect(text(gas.steps[0].how)).toBe("24,000 mmBtu × 53.06 kg CO₂ per mmBtu");
    expect(gas.steps.every((s) => s.reported === null)).toBe(true);
    expect(gas.note).toMatch(/only the client's totals are entered/);
  });

  it("rounds results as the demo card does (whole tCO₂e, gas tonnes to one decimal); factors as printed", () => {
    const [gas] = line["s1-stationary"].facilities ?? [];
    expect(gas.steps.map((s) => s.recomputed?.text)).toEqual(["1,273.4 t", "0.024 t", "0.0024 t", "1,275 tCO₂e"]);
    const total = gas.steps[gas.steps.length - 1];
    expect(total.total).toBe(true);
    // The masses it multiplies are inputs: printed to two decimals, so the line re-multiplies.
    expect(text(total.how)).toBe("CO₂ 1,273.44 t × GWP 1 + CH₄ 0.024 t × GWP 28 + N₂O 0.0024 t × GWP 265");
    // The electricity factors keep their printed decimals; the quantities read like the demo's.
    const [facilityA] = line["s2l-electricity"].facilities ?? [];
    expect(text(facilityA.steps[0].how)).toBe("1,200 MWh × 240.99 lb per MWh");
    expect(facilityA.steps[0].recomputed?.text).toBe("289,188 lb");
    expect(text(facilityA.steps[2].how)).toBe("1,200 MWh × 0.011 lb per MWh");
    expect(facilityA.steps[2].recomputed?.text).toBe("13.2 lb");
    const [r410a] = line["s1-fugitive"].facilities ?? [];
    expect(r410a.steps.map((s) => s.recomputed?.text)).toEqual(["40 lb", "0.018 t", "35 tCO₂e"]);
  });

  /*
   * recalculationOddQuantities.json is the backend's response for two NYUP electricity bills:
   * Facility C at a non-round 1,234.56 MWh, and a Kiosk at 40 MWh whose N₂O is 0.04 lb.
   */
  const ODD = byId(oddExample as unknown as Recalculation)["s2l-electricity"].facilities ?? [];
  const facility = (name: string) => ODD.find((f) => f.facility === name)!;
  const NUMBER = /−?[\d,]*\.?\d+/;
  const toNumber = (s: string) => Number(s.replace(/,/g, "").replace("−", "-"));

  /**
   * Re-multiplies a step's "how" line as a reader would, term by term ("1,234.56 MWh × 240.99
   * lb per MWh"; the Total row's "CO₂ 1,273.44 t × GWP 1 + …"), converting a factor in kg or
   * g to the result's tonnes, and returns how far it lands from the result shown, against
   * half a unit of the result's last digit.
   */
  function reMultiply(step: { step: string; how: { text: string }[]; recomputed: { text: string } | null }) {
    const shown = step.recomputed?.text ?? "";
    const [shownNumber, ...unit] = shown.split(" ");
    const resultUnit = unit.join(" ");
    const product = text(step.how)
      .split(" + ")
      .reduce(
        (sum, term) =>
          sum +
          term.split(" × ").reduce((p, factor) => {
            const match = NUMBER.exec(factor.replace(/GWP /, ""));
            const after = match ? factor.slice(match.index + match[0].length).trim() : "";
            const scale = resultUnit === "t" && after.startsWith("kg ") ? 1e-3 : resultUnit === "t" && after.startsWith("g ") ? 1e-6 : 1;
            return p * (match ? toNumber(match[0]) : NaN) * scale;
          }, 1),
        0
      );
    return {
      off: Math.abs(product - toNumber(shownNumber)),
      allowed: 0.5 * 10 ** -(shownNumber.split(".")[1] ?? "").length + 1e-9,
      label: `${step.step}: ${text(step.how)} = ${shown} (re-multiplied ${product})`,
    };
  }

  /** Every step of a card that multiplies (a plain product, or the Total CO₂e row). */
  const multipliedSteps = (result: Recalculation) =>
    liveResultsFromRecalculation(result)
      .lines.flatMap((l) => l.facilities ?? [])
      .flatMap((f) => f.steps)
      .filter((s) => / × /.test(text(s.how)) && !/: /.test(text(s.how)));

  it("never rounds a small result to nothing (0.04 lb, not 0.0 lb)", () => {
    const kiosk = facility("Kiosk");
    expect(kiosk.steps.map((s) => s.recomputed?.text)).toEqual([
      "9,640 lb", "4.4 t", "0.4 lb", "0.0002 t", "0.04 lb", "0.000018 t", "4 tCO₂e",
    ]);
    expect(text(kiosk.steps[4].how)).toBe("40 MWh × 0.001 lb per MWh");
    // The next step converts the input as its source prints it.
    expect(text(kiosk.steps[5].how)).toBe("lb / 2,204.62: emissions 0.04 lb");
  });

  it("prints the quantities a step multiplies as the source does, so they reproduce the result shown", () => {
    const c = facility("Facility C");
    expect(text(c.steps[0].how)).toBe("1,234.56 MWh × 240.99 lb per MWh");
    expect(c.steps[0].recomputed?.text).toBe("297,517 lb");
    const multiplied = c.steps.filter((s) => / × /.test(text(s.how)) && !s.total);
    expect(multiplied.map((s) => s.step)).toEqual(["CO₂ (electricity)", "CH₄ (electricity)", "N₂O (electricity)"]);
  });

  it("re-multiplies every step and every Total CO₂e row to the result shown, in every fixture", () => {
    // The R-410A balance: 53.5 lb = 0.024267 t, × 1,924 = 46.7, shown as 47 tCO₂e.
    const [r410a] = byId(refrigerantExample as unknown as Recalculation)["s1-fugitive"].facilities ?? [];
    const co2e = r410a.steps.find((s) => s.step === "R-410A in CO₂e")!;
    expect(text(co2e.how)).toBe("0.02427 t × 1,924");
    expect(co2e.recomputed?.text).toBe("47 tCO₂e");
    for (const result of [LIVE, oddExample, refrigerantExample] as unknown as Recalculation[]) {
      const steps = multipliedSteps(result);
      expect(steps.some((s) => s.step === "Total CO₂e")).toBe(result !== (refrigerantExample as unknown));
      for (const step of steps) {
        const { off, allowed, label } = reMultiply(step);
        expect(off, label).toBeLessThanOrEqual(allowed);
      }
    }
  });

  it("links an amount to the reviewed records it is summed from, and a factor or GWP to its citation", () => {
    const [gas] = line["s1-stationary"].facilities ?? [];
    expect(gas.steps[0].how[0].source).toMatchObject({
      kind: "evidence",
      unit: "MMBtu",
      total: 24000,
      records: [
        { documentId: "GAS-JAN", record: "GAS-JAN.pdf", quantity: 9000 },
        { documentId: "GAS-FEB", quantity: 8000 },
        { documentId: "GAS-MAR", quantity: 7000 },
      ],
    });
    expect(gas.steps[0].how[2].source).toMatchObject({
      kind: "basis",
      title: "EPA GHG Emission Factors Hub 2025",
      text: "EF = 53.06 kg CO₂ per mmBtu, cited from EPA GHG Emission Factors Hub 2025, Table 1, row 38.",
    });
    const gwp = gas.steps[3].how.find((c) => c.text === "GWP 28");
    expect(gwp?.source).toMatchObject({ kind: "basis", title: "GWP of CH₄ (AR5)" });
    // A refrigerant's term opens the service records; its CO₂e step is the total.
    const [r410a] = line["s1-fugitive"].facilities ?? [];
    expect(r410a.steps[0].how.find((c) => c.source)?.source).toMatchObject({ kind: "evidence", records: [{ serviceType: "service" }] });
    expect(r410a.steps[r410a.steps.length - 1]).toMatchObject({ step: "R-410A in CO₂e", total: true });
  });

  it("states causes only from data quality checks and flags, labelled as the system's", () => {
    const [gas] = line["s1-stationary"].facilities ?? [];
    expect(gas).toMatchObject({ causeBy: "system", causeTone: "review" });
    expect(gas.cause).toContain("no bill covers May 2025");
    expect(gas.cause).toContain("Fuel matched to the EPA fuel automatically.");
    const [facilityA] = line["s2l-electricity"].facilities ?? [];
    expect(facilityA).toMatchObject({ causeTone: "note", cause: "Recalculated from 2 reviewed records; no data quality signal." });
    const [steamB] = line["s2l-steam"].facilities ?? [];
    expect(steamB.causeTone).toBe("review");
    expect(steamB.cause).toContain("Facility B purchased steam: no bill covers Apr 2025");
  });

  it("reads a market-based remainder with its coverage as a percentage", () => {
    const [facilityA] = line["s2m-electricity"].facilities ?? [];
    expect(text(facilityA.steps[0].how)).toBe("electricity (MWh) x (1 - coverage %): electricity 1,200 MWh; coverage 30%");
  });

  it("opens the card with its steps, the system's cause and the records behind an amount", async () => {
    responses.byPath["/engagements/ENG-1/recalculation"] = LIVE;
    responses.byPath["/reference/recalculation"] = REFERENCE;
    const store = renderHook(() => useVerificationStore()).result;
    const opened: string[] = [];
    render(
      <BackendVerificationResults
        engagement={ENGAGEMENT}
        store={store.current}
        onSaveInputs={async () => {}}
        onError={() => false}
        onOpenDocument={(id) => opened.push(id)}
      />
    );
    fireEvent.click(await screen.findByRole("button", { name: "Natural Gas" }));
    const panel = screen.getByRole("complementary", { name: "Scope 1 · Natural Gas" });
    expect(within(panel).getByText("Checked by system")).toBeTruthy();
    expect(within(panel).getByText(/only the client's totals are entered/)).toBeTruthy();
    // The CO₂, CH₄ and N₂O steps each read the same fuel energy.
    fireEvent.click(within(panel).getAllByRole("button", { name: "24,000 mmBtu" })[0]);
    const source = within(panel).getByRole("region", { name: "Source" });
    expect(within(source).getByText("3 reviewed records")).toBeTruthy();
    fireEvent.click(within(source).getByRole("button", { name: "GAS-FEB.pdf" }));
    expect(opened).toEqual(["GAS-FEB"]);
  });
});

describe("one compare rule on Verification results and Output", () => {
  /*
   * recalculationCompareProbes.json is the backend's response for the mid-review engagement
   * with three probes: (b) purchased heating confirmed absent ("None at the client") with
   * 50 t reported; (c) stationary combustion still partial yet already above its reported
   * 1,000 t; (d) fugitive emissions set out of scope in Setup, with 30 t reported.
   */
  const PROBES = probeExample as unknown as Recalculation;
  const live = liveResultsFromRecalculation(PROBES);
  const line = Object.fromEntries(live.lines.map((l) => [l.id, l]));
  const boxes = buildResultBoxes(live.lines, () => false, live.boxTotals);
  const resultsRow = (id: string) => boxes.flatMap((b) => b.rows).find((r) => r.key === id)!;
  const output = liveStatementFigures(live.lines, live.boxTotals, live.inventory, PROBES.tolerance_pct);
  const outputRow = (label: string) => output.rows.find((r) => r.label === label)!;
  const status = (key: string) => PROBES.rollup?.final_outputs.find((o) => o.key === key)?.status;

  it("(b) compares a source confirmed absent: Results and Output both call 50 t against 0 above materiality", () => {
    expect(status("purchased_heating_total")).toBe("exceeds_tolerance");
    expect(line["s2l-heating"]).toMatchObject({ reported: 50, recomputed: 0, state: { label: "None at the client" } });
    expect(line["s2l-heating"].inconclusive).toBeUndefined();
    expect(resultsRow("s2l-heating")).toMatchObject({ difference: -50 });
    expect(Math.abs(resultsRow("s2l-heating").pctMaterial ?? 0)).toBeGreaterThanOrEqual(0.05);
    expect(outputRow("Scope 2 · heating")).toMatchObject({ outcome: "material", state: { label: "None at the client" } });
    expect(output.differences.map((d) => d.label)).toContain("Scope 2 · heating (location-based)");
  });

  it("(c) compares a partial value already beyond its reported one: both screens, above materiality", () => {
    expect(status("stationary_combustion_total")).toBe("exceeds_tolerance");
    expect(line["s1-stationary"].inconclusive).toBeUndefined();
    expect(resultsRow("s1-stationary").difference).toBeCloseTo(274.748, 3);
    expect(outputRow("Scope 1 · stationary combustion")).toMatchObject({ outcome: "material", state: { label: "Partial · 1 open" } });
    expect(output.differences.map((d) => d.label)).toContain("Scope 1 · stationary combustion");
  });

  it("(d) does not compare a data point out of scope, on either screen", () => {
    expect(status("fugitive_total")).toBe("not_in_scope");
    expect(line["s1-fugitive"]).toMatchObject({ reported: 30, inconclusive: true, state: { label: "Not in scope" } });
    expect(resultsRow("s1-fugitive")).toMatchObject({ difference: null, pctDifference: null, pctMaterial: null });
    expect(outputRow("Scope 1 · fugitive emissions")).toMatchObject({ outcome: null, state: { label: "Not in scope" } });
    expect(output.differences.map((d) => d.label)).not.toContain("Scope 1 · fugitive emissions");
    // A box that cannot conclude stays out of Differences found on Output as on Results.
    expect(output.differences.map((d) => d.label)).not.toContain("Scope 1 total");
  });

  it("renders (d) with its chip and no difference, and leaves it out of the box's \"differ\" count", () => {
    const store = renderHook(() => useVerificationStore()).result.current;
    render(<VerificationWorkspace lines={live.lines} store={store} team={[]} boxTotals={live.boxTotals} materiality={0.05} />);
    const fugitive = screen.getByRole("button", { name: "R-410A" }).closest("tr")!;
    expect(fugitive.textContent).toContain("Not in scope");
    expect(fugitive.querySelector(".s1-vw-delta")).toBeNull();
    expect(fugitive.className).not.toContain("is-different");
    // Stationary (c) differs; R-410A (d) does not count.
    expect(screen.getByRole("button", { name: /^Scope 1/ }).textContent).toContain("3 recomputed lines · 1 differ");
  });
});

describe("live % material colours", () => {
  const facility = (id: string, recomputed: number) => ({ facilityId: id, facility: id, reported: null, recomputed, steps: [], cause: "" });
  const lines: ResultLine[] = [
    { id: "s2l-electricity", box: "scope2_location", activity: "Electricity", facilities: [facility("a", 1010)], reported: 1000, recomputed: 1010, noBoundaryShare: true },
    { id: "s2l-steam", box: "scope2_location", activity: "Steam", facilities: [facility("a", 200)], reported: 100, recomputed: 200, noBoundaryShare: true },
    { id: "s2m-electricity", box: "scope2_market", activity: "Electricity", facilities: [facility("a", 50)], reported: null, reportedNote: "Total only", recomputed: 50, noBoundaryShare: true },
  ];
  const boxTotals = {
    scope2_location: { reported: 1100, recomputed: 1210, material: true },
    scope2_market: { reported: 0, recomputed: 50, material: true },
  };

  function renderBoxes(totals = boxTotals) {
    const store = renderHook(() => useVerificationStore()).result.current;
    render(<VerificationWorkspace lines={lines} store={store} team={[]} boxTotals={totals} materiality={0.05} />);
    fireEvent.click(screen.getByRole("button", { name: /^Scope 2, location-based/ }));
    fireEvent.click(screen.getByRole("button", { name: /^Scope 2, market-based/ }));
    return within(screen.getByRole("region", { name: "Reported vs recomputed" }));
  }

  it("reds a % material only at or above materiality, and ambers one below it", () => {
    const view = renderBoxes();
    const location = within(view.getByRole("button", { name: /^Scope 2, location-based/ }).closest(".s1-vw-box") as HTMLElement);
    const materialCell = (name: string) => location.getByRole("button", { name }).closest("tr")!.querySelectorAll("td")[5];
    expect(materialCell("Electricity").className).toContain("s1-vw-amber"); // +10 of 1,100: +0.9%
    expect(materialCell("Steam").className).toContain("s1-vw-red"); // +100 of 1,100: +9.1%
    expect(view.getByRole("button", { name: /^Scope 2, location-based/ }).querySelector(".s1-vw-pill--differs")).toBeTruthy();
  });

  it("ambers a box the backend keeps within tolerance, though it differs", () => {
    const view = renderBoxes({ ...boxTotals, scope2_location: { reported: 1100, recomputed: 1130, material: false } });
    const head = view.getByRole("button", { name: /^Scope 2, location-based/ });
    expect(head.querySelector(".s1-vw-pill--open")?.textContent).toBe("+2.7% material");
    expect(head.querySelector(".s1-vw-pill--differs")).toBeNull();
    expect(view.getByText("+2.7%", { selector: ".s1-vw-box__lines .s1-vw-amber" })).toBeTruthy();
  });

  it("shows no 0.0% material for a reported 0, and calls it above materiality", () => {
    const view = renderBoxes();
    const head = view.getByRole("button", { name: /^Scope 2, market-based/ });
    expect(head.querySelector(".s1-vw-pill--differs")?.textContent).toBe("Above materiality");
    expect(head.textContent).not.toMatch(/0\.0%/);
    const total = view.getByText("Scope 2 market-based total").closest("tr")!;
    expect(total.textContent).not.toMatch(/%/);
  });
});

describe("live calculation cards, Source pane and dialog", () => {
  const ODD = liveResultsFromRecalculation(oddExample as unknown as Recalculation);

  function openElectricity(onOpenDocument?: (id: string) => void) {
    const store = renderHook(() => useVerificationStore()).result.current;
    const view = render(
      <VerificationResults
        rows={[]}
        lines={ODD.lines}
        boxTotals={ODD.boxTotals}
        store={store}
        team={[]}
        registerFindings
        onOpenDocument={onOpenDocument}
        liveMateriality={0.05}
      />
    );
    fireEvent.click(screen.getByRole("button", { name: /^Scope 2, location-based/ }));
    fireEvent.click(screen.getByRole("button", { name: "Electricity" }));
    return { view, panel: screen.getByRole("complementary", { name: "Scope 2, location-based · Electricity" }) };
  }

  it("invents no consolidation: no Consolidated share column or step on a live card", () => {
    const { panel } = openElectricity();
    expect(within(panel).queryByText("Consolidated share")).toBeNull();
    expect(within(panel).queryByText("Consolidated")).toBeNull();
    expect(within(panel).queryByText(/consolidated share/)).toBeNull();
    // The demo keeps its own (its fixture has a boundary share to show).
    const store = renderHook(() => useVerificationStore()).result.current;
    render(<VerificationWorkspace lines={verificationLines} store={store} team={[]} />);
    fireEvent.click(screen.getAllByRole("button", { name: "Natural gas" })[0]);
    expect(screen.getAllByText("Consolidated share").length).toBeGreaterThan(0);
  });

  it("opens an amount in the Source pane as precisely as its cell: 1,234.56 MWh reads 1,234.56", () => {
    const { panel } = openElectricity();
    fireEvent.click(within(panel).getAllByRole("button", { name: "1,234.56 MWh" })[0]);
    const source = within(panel).getByRole("region", { name: "Source" });
    expect(within(source).getAllByText("1,234.56")).toHaveLength(2); // the record and the total
  });

  it("never prints a small reviewed amount as 0.0", () => {
    const evidence: EvidenceSource = {
      kind: "evidence", title: "Kiosk · reviewed evidence", unit: "MWh", total: 0.04,
      records: [{ documentId: "D-1", record: "kiosk.pdf", quantity: 0.04, unit: "MWh" }],
    };
    render(<VerificationSource source={evidence} />);
    expect(screen.getAllByText("0.04")).toHaveLength(2);
    expect(screen.queryByText(/^0\.0$/)).toBeNull();
  });

  it("closes the Register finding dialog on Escape, and the panel behind it only on the next Escape", () => {
    const { panel } = openElectricity();
    fireEvent.click(within(panel).getByRole("button", { name: "Register finding" }));
    expect(screen.getByRole("dialog", { name: "Register finding" })).toBeTruthy();
    act(() => {
      fireEvent.keyDown(screen.getByPlaceholderText("What is wrong, in plain words"), { key: "Escape" });
    });
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.getByRole("complementary", { name: "Scope 2, location-based · Electricity" })).toBeTruthy();
    act(() => {
      fireEvent.keyDown(window, { key: "Escape" });
    });
    expect(screen.queryByRole("complementary")).toBeNull();
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

const NOOP = () => {};

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
    expect(screen.queryByRole("button", { name: /Findings/ })).toBeNull();

    const scope1 = within(boxes).getByRole("button", { name: /^Scope 1/ });
    expect(scope1.textContent).toContain("1,600");
    expect(scope1.textContent).toContain("1,412");
    expect(scope1.textContent).toContain("Incomplete");
    // Stationary is still partial: shown, not compared, so nothing in Scope 1 "differs".
    expect(scope1.textContent).toContain("3 recomputed lines");
    expect(scope1.textContent).not.toContain("differ");
    const stationary = within(boxes).getByRole("button", { name: "Natural Gas" }).closest("tr")!;
    expect(stationary.className).not.toContain("is-different");
    expect(stationary.querySelector(".s1-vw-delta")).toBeNull();
    expect(stationary.textContent).not.toMatch(/\+2\.0%|\+1\.5%/);
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

  it("registers a finding on a line from its calculation card, as Output and the Excel export list them", async () => {
    const { store } = renderScreen();
    fireEvent.click(await screen.findByRole("button", { name: "Diesel Fuel" }));
    const panel = screen.getByRole("complementary", { name: "Scope 1 · Diesel Fuel" });
    fireEvent.click(within(panel).getByRole("button", { name: "Register finding" }));
    const dialog = screen.getByRole("dialog", { name: "Register finding" });
    expect(within(dialog).getByText("Scope 1 · Mobile combustion · Diesel Fuel")).toBeTruthy();
    fireEvent.change(within(dialog).getByPlaceholderText("What is wrong, in plain words"), {
      target: { value: "Fleet CH₄ and N₂O are left out: no vehicle groups." },
    });
    fireEvent.change(within(dialog).getByPlaceholderText("e.g. Emission factor mismatch"), { target: { value: "Incomplete inputs" } });
    act(() => {
      fireEvent.click(within(dialog).getByRole("button", { name: "Register finding" }));
    });
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(store.current.findings).toEqual([
      expect.objectContaining({
        dataPointId: "vr:s1-mobile",
        dataPointLabel: "Scope 1 · Mobile combustion · Diesel Fuel",
        sentence: "Fleet CH₄ and N₂O are left out: no vehicle groups.",
        cause: "Incomplete inputs",
        status: "Open",
      }),
    ]);
    // The workpaper sync saves it to the backend as a finding item, like every finding.
    responses.byPath["/engagements/ENG-1/workpaper-items"] = { items: [] };
    const findings = store.current.findings;
    renderHook(() =>
      useWorkpaperSync({
        enabled: true, engagementId: "ENG-1", asks: [], findings, examinations: {}, documents: {},
        replaceAsks: NOOP, replaceVerification: NOOP, replaceDocuments: NOOP, onError: NOOP,
      })
    );
    await waitFor(() =>
      expect(api).toHaveBeenCalledWith(
        `/engagements/ENG-1/workpaper-items/finding/${findings[0].id}`,
        expect.objectContaining({ method: "PUT", body: { payload: expect.objectContaining({ dataPointId: "vr:s1-mobile" }) } })
      )
    );
  });

  it("offers the engagement team as examiners when Setup has one", () => {
    const team = [{ name: "M. Osei", login: "mosei" }];
    expect(examinerOptions({ ...ENGAGEMENT, engagementTeam: team })).toBe(team);
    expect(examinerOptions({ ...ENGAGEMENT, signedInLogin: undefined })).toEqual([]);
  });
});
