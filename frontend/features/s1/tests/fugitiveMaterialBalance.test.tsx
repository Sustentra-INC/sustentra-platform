/* @vitest-environment jsdom */
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import type { LineDecisions, LineTrace } from "../api/calcTrace";
import { TracePanel } from "../components/calc-trace/TracePanel";
import { fugitiveLine, fugitiveTrace, withChosenMethod } from "../demo-backend/calcTrace/fugitive";
import type { DemoDecided } from "../demo-backend/calcTrace/fugitiveScreening";
import type { ModelLine, ModelRecord } from "../demo-backend/linesModel";

afterEach(cleanup);

const T_PER_LB = 0.45359237 / 1000;
const ml = { key: "s1:fugitive:hfc-134a:fac-1", scope: "s1", category: "fugitive", level2: "hfc-134a", level2_label: "HFC-134a", anchor_kind: "facility", anchor_id: "fac-1", label: "HFC-134a · Plant", facility_id: "fac-1", created_by_user: false } as ModelLine;
const record = { documentId: "DOC-1", fileName: "chiller.pdf", start: "2025-04-01", end: null, quantity: 10, unit: "lb", candidateId: "c1", decision: "accepted" } as unknown as ModelRecord;
const PLAN = { I_B: 500, I_E: 450, P: 200, S: 50, C_B: 1000, C_E: 1050 };

function trace(decided?: DemoDecided): LineTrace {
  const line = fugitiveLine(ml, [record], { gwp: 1300, set: "AR5", share: 1, company: null, tolerance: 5, reported: null, incomplete: false });
  return fugitiveTrace(line, decided)!;
}
const value = (t: LineTrace, id: string) => t.steps.flatMap((s) => s.blocks).find((b) => b.id === id)?.recomputed?.result.value;

describe("demo fugitive material balance (C6)", () => {
  it("works the plan's example: 150 lb → 0.0680388555 t × 1,300 = 88.45 t CO₂e", () => {
    const t = trace({ choices: { method: "material_balance" }, inputs: PLAN });
    expect(t.state).toBe("complete");
    expect(value(t, "emitted")).toBe(150);
    expect(value(t, "emitted_t")).toBeCloseTo(0.0680388555, 12);
    expect(t.result.recomputed).toBeCloseTo(150 * T_PER_LB * 1300, 9);
    expect(t.result.recomputed!.toFixed(2)).toBe("88.45");
    expect(t.choices[0]).toMatchObject({ chosen: "material_balance", chosen_by: "reviewer" });
  });

  it("keeps a negative balance and flags it", () => {
    const t = trace({ choices: { method: "material_balance" }, inputs: { ...PLAN, I_E: 750 } });
    expect(value(t, "emitted")).toBe(-150);
    expect(t.flags).toContain("negative_refrigerant_emissions");
    expect(t.steps.flatMap((s) => s.blocks).find((b) => b.id === "emitted")?.warning).toMatch(/^negative balance/);
  });

  it("shows a term not reported, blocks the method, and offers it with no decision", () => {
    const plain = trace();
    expect(plain.choices[0].options.find((o) => o.id === "material_balance")).toMatchObject({ available: true });
    expect(plain.inputs.I_B).toMatchObject({ decidable: true, recomputed: { value: null, status: "awaiting_review" } });
    const t = trace({ choices: { method: "material_balance" }, inputs: { I_B: 500, I_E: 450, P: 0, S: 0 } });
    expect(t.state).toBe("blocked");
    expect(t.blocking[0].message).toMatch(/^material balance terms\. Not reported: C_B, C_E\./);
    expect(t.result.recomputed).toBeNull();
    const decisions: LineDecisions = {
      applied: [{ target: "choice", id: "method", side: null, status: "edited", uses: "Material balance is chosen but blocked (awaiting material balance terms). Counting the simplified material balance (5.90 t) until then." }],
      not_applied: [],
    } as unknown as LineDecisions;
    render(<TracePanel trace={t} decisions={decisions} />);
    expect(screen.getByText(/^Material balance is chosen but blocked/)).toBeTruthy();
    expect(screen.getAllByText(/^Check: not reported\./)).toHaveLength(2);
    expect(screen.getByText(/^Awaiting review: material balance terms/)).toBeTruthy();
  });

  it("gives each term its source hint and labels C_B / C_E as the full charge", () => {
    const t = trace();
    expect(t.inputs.I_B.source_hint).toBe("inventory count");
    expect(t.inputs.S.source_hint).toBe("sales, return or disposal record");
    expect(t.inputs.C_E).toMatchObject({ label: "Full charge of equipment at the end of the year", source_hint: "equipment register (full charge)" });
  });

  it("routes the line by the chosen method once it is worked, and says what counts while it is blocked", () => {
    const line = fugitiveLine(ml, [record], { gwp: 1300, set: "AR5", share: 1, company: null, tolerance: 5, reported: null, incomplete: false });
    expect(withChosenMethod(line, { choices: {}, inputs: {} })).toBe(line);
    const worked = withChosenMethod(line, { choices: { method: "material_balance" }, inputs: PLAN });
    expect(worked.method.route).toBe("Material balance: (I_B − I_E) + (P − S) + (C_B − C_E), to metric tons, × GWP");
    expect(worked.decisions).toBeUndefined();
    // blocked, with P_S decided at 20 lb: the route stays the balance's, and the note counts the decided P_S
    const blocked = withChosenMethod(line, { choices: { method: "material_balance" }, inputs: { P_S: 20 } });
    expect(blocked.method.route).toBe(line.method.route);
    const total = (20 * T_PER_LB * 1300).toFixed(2);
    expect(blocked.decisions?.applied[0].uses).toBe(`Material balance is chosen but blocked (awaiting material balance terms). Counting the simplified material balance (${total} t) until then.`);
    const screening = withChosenMethod(line, { choices: { method: "screening" }, inputs: {} });
    // C5's screening too: blocked on a capacity, it counts the balance (10 lb → 5.90 t)
    expect(screening.decisions?.applied[0].uses).toBe("Screening is chosen but blocked (awaiting equipment capacity). Counting the simplified material balance (5.90 t) until then.");
  });
});
