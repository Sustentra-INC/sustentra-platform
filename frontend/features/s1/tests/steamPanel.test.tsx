/* @vitest-environment jsdom */
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import type { LineTrace, LineTraceResponse } from "../api/calcTrace";
import type { CalculationLine, Recalculation } from "../api/recalculation";
import { TracePanel } from "../components/calc-trace/TracePanel";
import { panelIds } from "../components/CalculationPanels";
import { demoApi } from "../demo-backend";
import { resetDemoDecisions } from "../demo-backend/calcTrace/decisions";

const E = "ENG-CASCADE-2025";
const block = (t: LineTrace, id: string) => t.steps.flatMap((s) => s.blocks).find((b) => b.id === id)!;
const value = (t: LineTrace, id: string) => Number(block(t, id).recomputed!.result.value);

let line: CalculationLine;
let recalc: Recalculation;
const trace = async (key: string) => (await demoApi<LineTraceResponse>(`/engagements/${E}/recalculation/lines/${encodeURIComponent(key)}/trace`)).trace!;

beforeEach(async () => {
  resetDemoDecisions();
  recalc = await demoApi<Recalculation>(`/engagements/${E}/recalculation`);
  line = (recalc.calculation_lines ?? []).find((l) => l.counts_toward === "steam")!;
});
afterEach(cleanup);

describe("purchased steam: mass × net enthalpy and four emission factor options (C9)", () => {
  it("has Kent Cannery's steam line, 15,800 Mlb on twelve statements, on its own panel", () => {
    expect(line.label).toContain("Kent Cannery");
    expect(line.step1.rows).toHaveLength(12);
    expect(line.step1.total.quantity).toBe(15800);
    expect(panelIds(recalc.calculation_lines ?? [])).toContain("steam");
    expect(recalc.categories.purchased_steam_location_based!.total_co2e).toBeCloseTo(line.results.sum_co2e_t, 9);
  });

  it("works 15,800 Mlb × 1,048 Btu/lb to 16,558.4 MMBtu and EPA Table 7 to 1,098.318672 t CO₂", async () => {
    const t = await trace(line.key);
    expect(t.panel).toBe("steam");
    expect(value(t, "mass")).toBeCloseTo(16558.4, 9);
    expect(Number(block(t, "mass").company!.result.value)).toBeCloseTo(15800, 9);
    expect(block(t, "mass").recomputed!.result.difference).toBeCloseTo(758.4, 9);
    expect(value(t, "emissions.CO2")).toBeCloseTo(1098.318672, 9);
    expect(value(t, "emissions.CH4")).toBeCloseTo(0.020698, 12);
    expect(value(t, "emissions.N2O")).toBeCloseTo(0.0020698, 12);
    expect(t.result.recomputed).toBeCloseTo(1099.446713, 6);
    expect(t.result.recomputed).toBeCloseTo(line.results.total_co2e_t, 9);
    expect(block(t, "ef.chp_allocated.CO2").tag).toBe("not_used_for_this_line");
    expect(block(t, "cost_only").recomputed!.result.value).toBe("Request quantities");
    expect(t.steps.find((s) => s.n === 3)!.note).toContain("53.06 ÷ 0.80 = 66.325");
  });

  it("draws the tagged blocks, the option pills and an assumption as a muted tag", async () => {
    const t = structuredClone(await trace(line.key));
    t.inputs.condensate_f.assumption = "Default: no condensate return, gross enthalpy (32 °F) · not confirmed";
    render(<TracePanel trace={t} />);
    expect(screen.getByRole("group", { name: "Emission factor" })).toBeTruthy();
    expect(screen.getAllByText("Not used for this line").length).toBeGreaterThan(3);
    expect(screen.getAllByText("Detected from the evidence").length).toBeGreaterThan(0);
    expect(screen.getByText("Default: no condensate return, gross enthalpy (32 °F) · not confirmed")).toBeTruthy();
    expect(screen.getByRole("table", { name: /Step 2 · Conversion · Mass/ })).toBeTruthy();
  });
});
