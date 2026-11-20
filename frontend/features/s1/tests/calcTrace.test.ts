import { describe, expect, it, vi } from "vitest";

vi.mock("../../../lib/api", () => ({ api: vi.fn(async () => ({ line_key: "k", trace: null })) }));

import fixture from "../api/__fixtures__/calcTraceStationary.json";
import { api } from "../../../lib/api";
import { getLineTrace } from "../api/calcTrace";
import type { LineTrace, TraceOperation } from "../api/calcTrace";

// The JSON is the backend's own trace of Claire's Kent Cannery line (650,000 therm of natural gas); the cast
// is the compile-time check that calcTrace.ts describes what the backend sends.
const trace = fixture as unknown as LineTrace;

/** Left to right, as backend/app/services/calc_trace/ops.py does. */
function evaluate(operation: TraceOperation): number {
  let total = 0;
  operation.terms.forEach((term, i) => {
    const value = Number(term.operand.value);
    if (i === 0) total = value;
    else if (term.op === "×") total *= value;
    else if (term.op === "÷") total /= value;
    else if (term.op === "+") total += value;
    else total -= value;
  });
  return total;
}

describe("calculation trace contract", () => {
  it("carries the identity of the line", () => {
    expect(trace.trace_version).toBe(1);
    expect(trace.panel).toBe("stationary");
    expect(trace.state).toBe("complete");
    expect(trace.line_key).toBe("s1:stationary:natural-gas:fac-kc01");
  });

  it("is the calculation: every operation re-evaluates to its result", () => {
    const operations = trace.steps.flatMap((step) =>
      step.blocks.flatMap((block) => [block.recomputed, block.company]),
    );
    expect(operations.filter(Boolean).length).toBeGreaterThan(8);
    for (const operation of operations) {
      if (!operation) continue;
      const expected = Number(operation.result.value);
      expect(Math.abs(evaluate(operation) - expected)).toBeLessThanOrEqual(1e-9 * Math.max(1, Math.abs(expected)));
    }
  });

  it("matches the EPA Hub numbers", () => {
    const step = (id: string) => trace.steps.find((s) => s.id === id)!;
    const co2 = step("emissions").blocks.find((b) => b.id === "emissions.CO2")!.recomputed!;
    expect(co2.terms.map((t) => t.operand.value)).toEqual([65000, 53.06, 0.001]);
    expect(co2.result.value).toBeCloseTo(3448.9, 9);
    expect(trace.result.recomputed).toBeCloseTo(3452.4425, 9);
    expect(trace.inputs["ef.CO2"].recomputed?.source).toMatchObject({ kind: "reference", table: "Table 1", row: 38 });
  });

  it("keeps the first operator null and the company side separate", () => {
    const block = trace.steps.find((s) => s.id === "emissions")!.blocks[0];
    expect(block.recomputed!.terms[0].op).toBeNull();
    expect(block.company!.terms[1].operand.difference).toBeUndefined();
    expect(block.recomputed!.terms[1].operand).toMatchObject({ difference: 0, differs: false });
    expect(trace.result.difference).toBe(0);
  });

  it("is fetched per line, with the engagement and the line key encoded", async () => {
    await getLineTrace("ENG 1", "s1:stationary:natural-gas:fac-kc01");
    expect(api).toHaveBeenCalledWith(
      "/engagements/ENG%201/recalculation/lines/s1%3Astationary%3Anatural-gas%3Afac-kc01/trace",
    );
  });
});
