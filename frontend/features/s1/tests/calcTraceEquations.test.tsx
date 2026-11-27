/* @vitest-environment jsdom */
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import fixture from "../api/__fixtures__/calcTraceStationary.json";
import type { LineTrace } from "../api/calcTrace";
import type { CalculationLine } from "../api/recalculation";
import { TracePanel } from "../components/calc-trace/TracePanel";
import { traceFromLine } from "../demo-backend/calcTrace/fromLine";
import calcLines from "./fixtures/calculationLines.json";

afterEach(cleanup);

const stationary = (calcLines as unknown as CalculationLine[]).filter((l) => l.category === "stationary");

describe("stationary equation picker (Eq. 1 / 2 / 3)", () => {
  it("the backend's trace offers three equations per gas and uses Eq. 1", () => {
    const trace = fixture as unknown as LineTrace;
    for (const gas of ["CO2", "CH4", "N2O"]) {
      const choice = trace.choices.find((c) => c.id === `equation:${gas}`)!;
      expect(choice.options.map((o) => o.id)).toEqual(["eq_1", "eq_2", "eq_3"]);
      expect(choice.chosen).toBe("eq_1");
      expect(choice.options.map((o) => o.available)).toEqual([true, false, false]);
      expect(choice.options[1].why_unavailable).toMatch(/already measured in energy/);
    }
    expect(trace.choices.find((c) => c.id === "equation:CH4")!.options[2].why_unavailable).toMatch(/CO₂ only/);
  });

  it("the demo trace of every stationary line matches: Eq. 1 chosen, Eq. 2 and Eq. 3 unavailable with a reason", () => {
    expect(stationary.length).toBeGreaterThan(0);
    for (const line of stationary) {
      const trace = traceFromLine(line);
      for (const choice of trace.choices.filter((c) => c.id.startsWith("equation:"))) {
        expect(choice.options.map((o) => o.id)).toEqual(["eq_1", "eq_2", "eq_3"]);
        expect(choice.chosen).toBe("eq_1");
        expect(choice.options.map((o) => o.available)).toEqual([true, false, false]);
        for (const o of choice.options.slice(1)) expect(o.why_unavailable).toBeTruthy();
      }
    }
  });

  it("a demo line in a physical unit shows the site inputs as awaiting review, never a value", () => {
    const line = structuredClone(stationary[0]);
    line.step2 = { ...line.step2, to_unit: "short_ton" };
    const trace = traceFromLine(line);
    expect(trace.inputs.hhv.recomputed).toMatchObject({ value: null, unit: "MMBtu/short_ton", status: "awaiting_review" });
    expect(trace.inputs.cc.recomputed).toMatchObject({ value: null, unit: "% by mass", status: "awaiting_review" });
    expect(trace.choices.find((c) => c.id === "equation:CO2")!.options[1].why_unavailable).toMatch(/site heat content/);
    expect(trace.choices.find((c) => c.id === "equation:CH4")!.options[2].why_unavailable).toMatch(/CO₂ only/);
  });

  it("the panel draws the three pills per gas with Eq. 1 chosen and the others marked unavailable", () => {
    render(<TracePanel trace={fixture as unknown as LineTrace} />);
    const groups = screen.getAllByRole("group", { name: /equation/ });
    expect(groups).toHaveLength(3);
    for (const group of groups) {
      expect(group.textContent).toContain("Eq. 1");
      expect(group.querySelectorAll(".is-chosen")).toHaveLength(1);
      expect(group.querySelectorAll(".is-unavailable")).toHaveLength(2);
    }
  });
});
