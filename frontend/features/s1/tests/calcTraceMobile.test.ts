import { beforeEach, describe, expect, it } from "vitest";

import fixture from "../api/__fixtures__/calcTraceMobile.json";
import type { LineTrace, LineTraceResponse, TraceOperation } from "../api/calcTrace";
import type { Recalculation } from "../api/recalculation";
import { demoApi } from "../demo-backend";
import { resetDemoDecisions } from "../demo-backend/calcTrace/decisions";

// The JSON is the backend's own trace of Claire's diesel line: 380,000 gal at 7.00 mpg (2,660,000 mi).
const backend = fixture as unknown as LineTrace;
const E = "ENG-CASCADE-2025";

function evaluate(op: TraceOperation): number {
  let total = 0;
  op.terms.forEach((t, i) => {
    const v = Number(t.operand.value);
    if (i === 0) total = v;
    else if (t.op === "×") total *= v;
    else total /= v;
  });
  return total;
}
const block = (t: LineTrace, id: string) => t.steps.flatMap((s) => s.blocks).find((b) => b.id === id)!;

describe("mobile trace contract (backend fixture)", () => {
  it("shows the distance as fuel × fuel economy, and the fuel economy as a decidable input", () => {
    const d = block(backend, "distance").recomputed!;
    expect(d.terms.map((t) => t.operand.input_id)).toEqual([undefined, "fuel_economy"]);
    expect(Number(d.result.value)).toBeCloseTo(2_660_000, 6);
    expect(Math.abs(evaluate(d) - Number(d.result.value))).toBeLessThan(1e-6);
    expect(backend.inputs.fuel_economy).toMatchObject({ decidable: true, recomputed: { unit: "mi/gal", status: "derived" } });
    expect(backend.result.recomputed).toBeCloseTo(3910.88875, 9);
  });
});

describe("demo mobile trace", () => {
  let key = "";
  beforeEach(async () => {
    resetDemoDecisions();
    const lines = (await demoApi<Recalculation>(`/engagements/${E}/recalculation`)).calculation_lines!;
    key = lines.find((l) => l.category === "mobile" && l.step2.distance)!.key;
  });
  const trace = async () => (await demoApi<LineTraceResponse>(`/engagements/${E}/recalculation/lines/${encodeURIComponent(key)}/trace`)).trace!;

  it("offers a fuel economy that reproduces the line's distance", async () => {
    const t = await trace();
    const d = block(t, "distance").recomputed!;
    expect(t.inputs.fuel_economy.decidable).toBe(true);
    expect(Math.abs(evaluate(d) - Number(d.result.value))).toBeLessThan(1e-6);
    const ch4 = block(t, "emissions.CH4").recomputed!;
    expect(Number(d.result.value)).toBeCloseTo(Number(ch4.terms[0].operand.value), 6);
  });

  it("takes an edit of the fuel economy like any decidable input, and refuses a wrong unit", async () => {
    const post = (body: unknown) => demoApi<Record<string, unknown>>(`/engagements/${E}/calculation-lines/${encodeURIComponent(key)}/inputs/fuel_economy/recomputed`, { method: "POST", body });
    await post({ action: "edit", value: 6.55, unit: "mi/gal", reason: "Fleet manager's log" });
    expect((await trace()).inputs.fuel_economy.recomputed!.decision).toMatchObject({ status: "edited", value: 6.55, unit: "mi/gal" });
    await expect(post({ action: "edit", value: 6.55, unit: "km/L", reason: "x" })).rejects.toMatchObject({ status: 422 });
  });
});
