/* @vitest-environment jsdom */
import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import type { LineTrace, LineTraceResponse } from "../api/calcTrace";
import type { CalculationLine, Recalculation } from "../api/recalculation";
import { TraceActionsProvider } from "../components/calc-trace/TraceActions";
import { TracePanel } from "../components/calc-trace/TracePanel";
import { panelIds } from "../components/CalculationPanels";
import { demoApi } from "../demo-backend";
import { resetDemoDecisions } from "../demo-backend/calcTrace/decisions";

const E = "ENG-CASCADE-2025";
const block = (t: LineTrace, id: string) => t.steps.flatMap((s) => s.blocks).find((b) => b.id === id)!;
const value = (t: LineTrace, id: string) => Number(block(t, id).recomputed!.result.value);

let lines: CalculationLine[] = [];
let recalc: Recalculation;
const trace = async (key: string) => (await demoApi<LineTraceResponse>(`/engagements/${E}/recalculation/lines/${encodeURIComponent(key)}/trace`)).trace!;

beforeEach(async () => {
  resetDemoDecisions();
  recalc = await demoApi<Recalculation>(`/engagements/${E}/recalculation`);
  lines = (recalc.calculation_lines ?? []).filter((l) => l.counts_toward === "fugitive");
});
afterEach(cleanup);

describe("fugitive refrigerants, simplified material balance (C4)", () => {
  it("has one R-404A line per facility with reviewed service records, and its own panel", () => {
    expect(lines.length).toBeGreaterThanOrEqual(2);
    for (const l of lines) {
      expect(l.level2).toBe("R-404A");
      expect(l.smb?.terms.P_S).toBe(l.step1.total.quantity);
    }
    expect(panelIds(recalc.calculation_lines ?? [])).toContain("fugitive");
  });

  it("works 12 kg of R-404A to 0.012 t and 47.316 t CO₂e on the Table 12 GWP, the components shown beside it", async () => {
    const line = lines.find((l) => l.smb?.terms.P_S === 12)!;
    const t = await trace(line.key);
    expect(t.panel).toBe("fugitive");
    expect(value(t, "emitted")).toBe(12);
    expect(value(t, "emitted_t")).toBeCloseTo(0.012, 12);
    expect(value(t, "co2e")).toBeCloseTo(47.316, 9);
    expect(value(t, "components.sum")).toBeCloseTo(0.012 * 3942.8, 9);
    expect(t.result.recomputed).toBeCloseTo(line.results.total_co2e_t, 12);
    expect(t.steps.find((s) => s.id === "gwp")!.note).toContain("counts in the totals");
    // the lines add up to the category the totals use
    const sum = lines.reduce((s, l) => s + l.results.sum_co2e_t, 0);
    expect(sum).toBeCloseTo(recalc.categories.fugitive_refrigerants!.total_co2e, 9);
  });

  it("draws the method pills, Step 1's records and Step 3's blend and component rows", async () => {
    const t = await trace(lines[0].key);
    render(<TracePanel trace={t} />);
    expect(screen.getByText(/Route:/).closest("p")!.textContent).toBe("Route: Simplified material balance");
    const pills = screen.getAllByRole("group", { name: "Calculation method" })[0];
    expect(within(pills).getByText("Screening")).toBeTruthy();
    expect(screen.getByRole("table", { name: /Step 1 · Inputs · Added during service · P_S/ })).toBeTruthy();
    expect(screen.getByRole("table", { name: /R-404A · blend GWP \(counts\)/ })).toBeTruthy();
    expect(screen.getByRole("table", { name: /HFC-143a · 52% of the blend/ })).toBeTruthy();
  });

  it("a blend waiting for component GWPs says so, and offers the entry where the value is awaited", async () => {
    const t = structuredClone(await trace(lines[0].key));
    const id = "component_gwp.HFO-1234yf";
    t.state = "blocked";
    t.blocking = [{ input_id: id, message: "component GWPs. Enter the AR5 GWP of HFO-1234yf, with its source (the safety data sheet, say)." }];
    t.inputs[id] = { id, label: "HFO-1234yf GWP (AR5, 100-year)", kind: "reviewer_entered", required_for: ["smb"], recomputed: { value: null, unit: "t CO2e/t", status: "awaiting_review" }, decidable: true };
    const gwp = block(t, "component.HFC-125");
    gwp.recomputed = { terms: gwp.recomputed!.terms.map((term, i) => (i === 2 ? { ...term, operand: { ...term.operand, value: null, input_id: id } } : term)), result: { column: "co2e", value: null, unit: "t CO2e" } };
    render(
      <TraceActionsProvider value={{ canAct: true, busy: false, engagementId: E, lineKey: t.line_key, act: async () => null }}>
        <TracePanel trace={t} />
      </TraceActionsProvider>,
    );
    expect(screen.getByText(/Awaiting review: component GWPs/)).toBeTruthy();
    expect(screen.getByRole("button", { name: "Actions for HFO-1234yf GWP (AR5, 100-year)" })).toBeTruthy();
  });

  it("says a negative balance is kept", async () => {
    const t = structuredClone(await trace(lines[0].key));
    t.flags = ["negative_refrigerant_emissions"];
    render(<TracePanel trace={t} />);
    expect(screen.getByText(/Negative balance: check the service records/)).toBeTruthy();
  });
});
