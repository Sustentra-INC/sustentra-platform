/* @vitest-environment jsdom */
import { readFileSync } from "node:fs";
import { join } from "node:path";

import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import type { LineDecisions, LineTrace } from "../api/calcTrace";
import { TracePanel } from "../components/calc-trace/TracePanel";
import { fugitiveLine, fugitiveTrace } from "../demo-backend/calcTrace/fugitive";
import { SCREENING_TYPES, gasUse, type DemoDecided } from "../demo-backend/calcTrace/fugitiveScreening";
import type { ModelLine, ModelRecord } from "../demo-backend/linesModel";

afterEach(cleanup);

const T_PER_LB = 0.45359237 / 1000;
const ml = { key: "s1:fugitive:r-410a:fac-1", scope: "s1", category: "fugitive", level2: "r-410a", level2_label: "R-410A", anchor_kind: "facility", anchor_id: "fac-1", label: "R-410A · Office", facility_id: "fac-1", created_by_user: false } as ModelLine;
const record = (n: number, quantity: number) => ({ documentId: `DOC-${n}`, fileName: `rtu-${n}.pdf`, start: `2025-0${n}-01`, end: null, quantity, unit: "lb", candidateId: `c${n}`, decision: "accepted" }) as unknown as ModelRecord;

/** The board's office: three units (132, 16 and 8 lb), the last retired half way through the year (C_D 8 lb). */
function office(decided?: (ids: { c: string[]; t: string[] }) => DemoDecided): LineTrace {
  const line = fugitiveLine(ml, [record(1, 4), record(2, 2), record(3, 1)], { gwp: 1924, set: "AR5", share: 1, company: null, tolerance: 5, reported: null, incomplete: false });
  line.smb!.terms.C_D = 8;
  const plain = fugitiveTrace(line)!;
  const c = Object.keys(plain.inputs).filter((k) => k.startsWith("C."));
  const t = Object.keys(plain.inputs).filter((k) => k.startsWith("T."));
  return decided ? fugitiveTrace(line, decided({ c, t }))! : plain;
}

const board = ({ c, t }: { c: string[]; t: string[] }): DemoDecided => ({
  choices: { method: "screening", equipment_type: "residential_commercial_ac" },
  inputs: { [c[0]]: 132, [c[1]]: 16, [c[2]]: 8, [t[2]]: 0.5 },
});
const value = (trace: LineTrace, id: string) => trace.steps.flatMap((s) => s.blocks).find((b) => b.id === id)?.recomputed?.result.value;

describe("demo fugitive screening (C5)", () => {
  it("keeps the same EPA factors as the reference data", () => {
    const data = JSON.parse(readFileSync(join(process.cwd(), "..", "reference-data", "emission-factors", "epa_fugitive_screening_factors.json"), "utf8"));
    const rows = [...data.refrigeration.rows.map((r: Record<string, unknown>) => ({ ...r, fire: false })), ...data.fire_suppression.rows.map((r: Record<string, unknown>) => ({ ...r, fire: true, k: null, y: null, z: null, ipcc_range: null }))];
    expect(SCREENING_TYPES).toEqual(rows.map((r) => ({ id: r.id, label: r.label, fire: r.fire, k: r.k, x: r.x, y: r.y, z: r.z, ipcc: r.ipcc_range })));
  });

  it("works the board's example: 152.0 lb × 10% + 8 lb × 80% × 20% = 16.48 lb → 14.38 t CO₂e", () => {
    const trace = office(board);
    expect(trace.state).toBe("complete");
    expect(value(trace, "in_use")).toBe(152);
    expect(value(trace, "operation")).toBeCloseTo(15.2, 12);
    expect(value(trace, "disposal")).toBeCloseTo(1.28, 12);
    expect(value(trace, "emitted")).toBeCloseTo(16.48, 12);
    expect(trace.result.recomputed).toBeCloseTo(16.48 * T_PER_LB * 1924, 9);
    expect(trace.result.recomputed!.toFixed(4)).toBe("14.3823");
    expect(trace.choices[0]).toMatchObject({ chosen: "screening", chosen_by: "reviewer" });
  });

  it("waits for the equipment type and each capacity, and computes nothing meanwhile", () => {
    const trace = office(() => ({ choices: { method: "screening" }, inputs: {} }));
    expect(trace.state).toBe("blocked");
    expect(trace.blocking.map((b) => b.message.split(".")[0])).toContain("the equipment type");
    expect(trace.result.recomputed).toBeNull();
    expect(value(trace, "emitted_t")).toBeNull();
  });

  it("draws the factors as percentages with their default tags, and the equipment type only for screening", () => {
    render(<TracePanel trace={office(board)} />);
    const tag = screen.getByText("Default 10% (EPA Table 1; IPCC range 1–10%) · not confirmed");
    expect(tag.className).toBe("s1-cp-tag s1-cp-tag--assumed");
    expect(screen.getAllByText(/^Default 1\.00 \(in use the whole reporting period\)/)).toHaveLength(2);
    const operation = screen.getByRole("table", { name: "Step 2 · Refrigerant emitted · Operation" });
    expect(operation.textContent).toContain("152 lb");
    expect(operation.textContent).toContain("10%");
    expect(operation.textContent).toContain("15.2 lb");
    expect(screen.getByRole("group", { name: "Equipment type" })).toBeTruthy();
    cleanup();
    render(<TracePanel trace={office()} />);
    expect(screen.queryByRole("group", { name: "Equipment type" })).toBeNull();
    expect(screen.queryByText(/not confirmed/)).toBeNull();
  });

  it("leads with what counts while screening is blocked, and lists every held decision", () => {
    const decisions: LineDecisions = {
      applied: [
        { target: "choice", id: "method", side: null, status: "edited", uses: "Screening is chosen but blocked (awaiting the equipment type). Counting the simplified material balance (54.11 t) until then." },
        { target: "input", id: "x", side: "recomputed", status: "edited", uses: "held: the screening method awaits the equipment type" },
        { target: "input", id: "P_S", side: "recomputed", status: "edited" },
      ],
      not_applied: [],
    };
    render(<TracePanel trace={office(() => ({ choices: { method: "screening" }, inputs: {} }))} decisions={decisions} />);
    const notes = screen.getAllByRole("status").map((n) => n.textContent);
    expect(notes[0]).toBe("Screening is chosen but blocked (awaiting the equipment type). Counting the simplified material balance (54.11 t) until then.");
    expect(notes).toContain("Annual leak rate: held: the screening method awaits the equipment type");
    expect(notes.some((n) => n?.startsWith("Added during service"))).toBe(false);
  });

  it("shows a capacity warning on its unit", () => {
    const trace = office(board);
    const unit = trace.steps[0].blocks[0];
    unit.warning = "Capacities differ between records (130 lb, 132 lb): the largest is used. Check it, or enter the capacity.";
    render(<TracePanel trace={trace} />);
    const warning = screen.getByText(/^Check: Capacities differ between records/);
    expect(warning.className).toBe("s1-cp-tag s1-cp-tag--warn");
    expect(warning.closest(".s1-cp-block")?.querySelector("h6")?.textContent).toBe(unit.label);
  });

  it("refuses an equipment type that does not fit the gas", () => {
    const types = office().choices.find((c) => c.id === "equipment_type")!;
    expect(types.options.find((o) => o.id === "fire_fixed")).toMatchObject({ available: false, why_unavailable: "R-410A is a refrigerant, not a fire-suppression agent: pick a refrigeration or A/C type." });
    expect(types.options.find((o) => o.id === "chillers")?.available).toBe(true);
    expect([gasUse("HFC-227ea"), gasUse("CO2"), gasUse("R-404A")]).toEqual(["fire", "either", "refrigerant"]);
  });
});
