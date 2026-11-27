/* @vitest-environment jsdom */
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const calls = vi.hoisted(() => ({ fail: false, trace: null as unknown }));
vi.mock("../../../lib/api", () => ({
  api: vi.fn(() => (calls.fail ? Promise.reject(new Error("boom")) : Promise.resolve({ line_key: "k", trace: calls.trace }))),
}));

import fixture from "../api/__fixtures__/calcTraceStationary.json";
import type { LineTrace, TraceOperation } from "../api/calcTrace";
import type { CalculationLine } from "../api/recalculation";
import { TracePanel } from "../components/calc-trace/TracePanel";
import { TraceSection } from "../components/calc-trace/TraceSection";
import { differenceText, formatNumber } from "../components/calc-trace/format";
import { traceFromLine } from "../demo-backend/calcTrace/fromLine";
import calcLines from "./fixtures/calculationLines.json";

const base = () => structuredClone(fixture) as unknown as LineTrace;
const block = (t: LineTrace, id: string) => t.steps.flatMap((s) => s.blocks).find((b) => b.id === id)!;

afterEach(cleanup);

describe("TracePanel", () => {
  it("draws the CO2 row of the stationary fixture and its result", () => {
    render(<TracePanel trace={base()} />);
    const table = screen.getByRole("table", { name: "Step 3 · Emissions per gas · CO₂" });
    const rows = within(table).getAllByRole("row");
    const recomputed = rows.find((r) => r.textContent?.startsWith("Recomputed"))!;
    expect(recomputed.textContent).toContain("65,000 MMBtu");
    expect(recomputed.textContent).toContain("53.06 kg/MMBtu");
    expect(recomputed.textContent).toContain("0.001 t/kg");
    expect(recomputed.textContent).toContain("=");
    expect(recomputed.textContent).toContain("3,448.9 t");
    expect(table.querySelector(".s1-cp-out-head")?.textContent).toBe("Mass (t)");
    // the line total, with the share as a percent
    const total = screen.getByRole("table", { name: "Results · Line total" });
    expect(total.textContent).toContain("3,452.44 t CO₂e");
    expect(total.textContent).toContain("100%");
    // the route and the per-gas equation pills
    expect(screen.getAllByText(/Energy content × per-MMBtu factor/).length).toBeGreaterThan(0);
    expect(screen.getAllByRole("group", { name: /equation/ }).length).toBe(3);
  });

  it("shows a difference in red parentheses, and none that rounds away", () => {
    const t = base();
    const co2 = block(t, "emissions.CO2").recomputed!;
    co2.result.value = 3793.8;
    co2.result.difference = 344.9;
    co2.terms[1].operand.difference = 0.0000004;
    render(<TracePanel trace={t} />);
    const table = screen.getByRole("table", { name: "Step 3 · Emissions per gas · CO₂" });
    const diffs = [...table.querySelectorAll(".s1-cp-diff")].map((d) => d.textContent);
    expect(diffs).toEqual([" (+344.9)"]);
    expect(differenceText(-30, 100, { dp: 0 })).toBe("−30");
    expect(differenceText(0.4, 100, { dp: 0 })).toBeNull();
  });

  it("shows no diff against a company value that was not reported", () => {
    const t = base();
    const b = block(t, "emissions.CO2");
    delete b.company;
    b.recomputed!.result.difference = 344.9;
    b.recomputed!.terms[0].operand.difference = 5000;
    render(<TracePanel trace={t} />);
    const table = screen.getByRole("table", { name: "Step 3 · Emissions per gas · CO₂" });
    expect(within(table).getByText("not reported").tagName).toBe("EM");
    expect(table.querySelector(".s1-cp-diff")).toBeNull();
  });

  it("marks non-numeric operands that differ, and greys unused blocks with their tags", () => {
    const t = base();
    const b = block(t, "emissions.CH4");
    b.tag = "not_used_for_this_line";
    block(t, "emissions.N2O").tag = "detected_from_evidence";
    const op = b.recomputed!.terms[1].operand;
    op.value = "NWPP";
    op.differs = true;
    render(<TracePanel trace={t} />);
    expect(screen.getByText("Not used for this line")).toBeTruthy();
    expect(screen.getByText("Detected from the evidence")).toBeTruthy();
    expect(screen.getByText("(differs)")).toBeTruthy();
    expect(document.querySelector(".s1-cp-block.is-unused")).toBeTruthy();
  });

  it("shows no recomputed number for an input awaiting review", () => {
    const t = base();
    t.state = "blocked";
    t.blocking = [{ input_id: "ef.CO2", message: "CO₂ emission factor has no accepted value" }];
    t.inputs["ef.CO2"].recomputed = { value: null, status: "awaiting_review" };
    const b = block(t, "emissions.CO2");
    b.recomputed!.terms[1].operand.value = null;
    render(<TracePanel trace={t} />);
    expect(screen.getByText(/Awaiting review: CO₂ emission factor/)).toBeTruthy();
    const table = screen.getByRole("table", { name: "Step 3 · Emissions per gas · CO₂" });
    expect(within(table).getAllByText("Awaiting review").length).toBeGreaterThan(0);
  });

  it("opens a source popover from every dotted value, reachable by keyboard", () => {
    const t = base();
    t.inputs["ef.CO2"].company = { value: 53.06, unit: "kg/MMBtu", status: "accepted", source: { kind: "workbook_cell", document_id: "WB-1", file_name: "co.xlsx", sheet: "S", cell: "D14" } };
    const open = vi.fn();
    render(<TracePanel trace={t} onOpenDocument={open} />);
    const triggers = [...document.querySelectorAll<HTMLButtonElement>(".s1-cp-src")];
    expect(triggers.length).toBeGreaterThan(8);
    for (const trigger of triggers) {
      expect(trigger.tagName).toBe("BUTTON");
      expect(trigger.tabIndex).toBeGreaterThanOrEqual(0);
      trigger.focus();
      expect(document.activeElement).toBe(trigger);
    }
    const co = screen.getByRole("table", { name: "Step 3 · Emissions per gas · CO₂" }).querySelector<HTMLButtonElement>(".s1-cp-co .s1-cp-src:nth-of-type(1)");
    const factor = [...document.querySelectorAll<HTMLButtonElement>(".s1-cp-co .s1-cp-src")].find((b) => b.textContent === "53.06 kg/MMBtu")!;
    expect(co).toBeTruthy();
    fireEvent.click(factor);
    const dialog = screen.getByRole("dialog");
    expect(dialog.textContent).toContain("Company-prepared workbook · cell D14");
    fireEvent.click(within(dialog).getByText("Open in Evidence →"));
    expect(open).toHaveBeenCalledWith("WB-1", undefined);
    fireEvent.click(factor);
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  /** Step 1 as the backend builds it: one term per evidence part, the company's one figure, the difference on the total only. */
  function twelveParts(): LineTrace {
    const t = base();
    const each = 50000;
    const parts = Array.from({ length: 12 }, (_, i) => ({ id: `G${i + 1}/c`, label: `2025-${String(i + 1).padStart(2, "0")}-01 to 2025-${String(i + 1).padStart(2, "0")}-28`, recomputed: { value: each, unit: "therm", status: "accepted" as const, source: { kind: "document" as const, document_id: `G${i + 1}`, file_name: `bill-${i + 1}.pdf` } } }));
    t.inputs["activity.total"].rows = parts;
    const b = block(t, "activity");
    b.company = { terms: [{ op: null, operand: { column: "activity", value: 650000, unit: "therm", input_id: "activity.total" } }], result: { column: "activity", value: 650000, unit: "therm", input_id: "activity.total" } };
    b.recomputed = {
      terms: parts.map((p, i) => ({ op: i === 0 ? null : ("+" as const), operand: { column: "activity", value: each, unit: "therm", input_id: "activity.total" } })),
      result: { column: "activity", value: 12 * each, unit: "therm", input_id: "activity.total", difference: 12 * each - 650000, differs: true },
    };
    return t;
  }

  it("draws Step 1 with twelve parts as twelve rows and a total aligned under its columns", () => {
    render(<TracePanel trace={twelveParts()} />);
    const table = screen.getByRole("table", { name: "Step 1 · Activity data · Activity data" });
    const rows = within(table).getAllByRole("row");
    // header + 12 records + the total
    expect(rows.length).toBe(14);
    const total = rows[13];
    const cells = within(total).getAllByRole("cell");
    // Annual total | company under Company-reported | recomputed under Recomputed
    expect(cells[0].textContent).toBe("Activity data");
    expect(cells[1].textContent).toContain("650,000.00 therm");
    expect(cells[2].textContent).toContain("600,000.00 therm");
    expect(cells[2].querySelector(".s1-cp-diff")?.textContent).toBe(" (−50,000.00)");
    // the parts show no difference, and no part sits under the company's figure
    expect(within(rows[1]).getByText("not reported")).toBeTruthy();
    expect(table.querySelectorAll(".s1-cp-diff").length).toBe(1);
  });

  it("shows a long record label wrapped, not breaking the row", () => {
    const t = twelveParts();
    t.inputs["activity.total"].rows![0].label = "Mar 2025 ".repeat(200);
    expect(() => render(<TracePanel trace={t} />)).not.toThrow();
  });

  it("survives hostile data: no steps, huge and odd numbers, unicode, missing columns", () => {
    const t = base();
    t.steps = [];
    t.choices = [];
    expect(() => render(<TracePanel trace={t} />)).not.toThrow();
    cleanup();
    const h = base();
    const b = block(h, "emissions.CO2").recomputed!;
    b.terms[0].operand.value = 1e300;
    b.terms[1].operand.value = Number.NaN;
    b.terms[2].operand.unit = "µg/ß 🌍";
    block(h, "emissions.CO2").columns = [];
    expect(() => render(<TracePanel trace={h} />)).not.toThrow();
    expect(formatNumber(1e21, { sig: 99, dp: 99 })).toBeTruthy();
    expect(formatNumber(-0.0000001, { dp: 2 })).toBe("0.00");
  });
});

describe("TraceSection", () => {
  const summary = <p>Summary numbers</p>;

  it("contains a failed fetch in the panel and keeps the summary numbers", async () => {
    calls.fail = true;
    render(<TraceSection engagementId="E1" lineKey="k" version="1" fallback={summary} />);
    expect((await screen.findByRole("alert")).textContent).toContain("could not be loaded");
    expect(screen.getByText("Summary numbers")).toBeTruthy();
    calls.fail = false;
  });

  it("shows the summary when the line has no trace, and without an engagement", async () => {
    render(<TraceSection engagementId="E1" lineKey="k" version="1" fallback={summary} />);
    await waitFor(() => expect(screen.getByText("Summary numbers")).toBeTruthy());
    expect(screen.queryByRole("alert")).toBeNull();
    cleanup();
    render(<TraceSection lineKey="k" version="1" fallback={summary} />);
    expect(screen.getByText("Summary numbers")).toBeTruthy();
  });
});

describe("TraceSection recovery", () => {
  it("draws again when the line's figures change after a trace that could not be drawn", async () => {
    const broken = base();
    (broken.steps[0].blocks[0] as unknown as { columns: unknown }).columns = null;
    calls.trace = broken;
    const { rerender } = render(<TraceSection engagementId="E1" lineKey="k" version="1" fallback={<p>Summary numbers</p>} />);
    expect((await screen.findByRole("alert")).textContent).toContain("could not be loaded");
    calls.trace = base();
    rerender(<TraceSection engagementId="E1" lineKey="k" version="2" fallback={<p>Summary numbers</p>} />);
    await waitFor(() => expect(screen.queryByRole("alert")).toBeNull());
    expect(document.querySelector(".s1-cp-trace")).toBeTruthy();
    calls.trace = null;
  });
});

describe("number display", () => {
  it("shows a dp column's fixed decimals, and no difference between two sides that display the same", () => {
    expect(formatNumber(1, { dp: 2 })).toBe("1.00");
    expect(differenceText(0.001, 1.001, { dp: 2 })).toBeNull();
    expect(differenceText(5, 6, { dp: 2 })).toBe("+5.00");
  });

  it("keeps the precision of the larger side, so 0 against 0.6 shows 0.6", () => {
    expect(differenceText(-0.6, 0, { sig: 6 })).toBe("−0.6");
    expect(differenceText(0, 0.6, { sig: 6 })).toBeNull();
    expect(formatNumber(0, { sig: 6 })).toBe("0");
  });
});

describe("demo trace", () => {
  const evaluate = (op: TraceOperation) =>
    op.terms.reduce((acc, t, i) => (i === 0 ? Number(t.operand.value) : t.op === "×" ? acc * Number(t.operand.value) : t.op === "÷" ? acc / Number(t.operand.value) : t.op === "+" ? acc + Number(t.operand.value) : acc - Number(t.operand.value)), 0);

  it("restates every demo line, and its recomputed total is the line's", () => {
    for (const line of (calcLines as unknown as CalculationLine[]).filter((l) => l.category !== "biogenic")) {
      const trace = traceFromLine(line);
      for (const step of trace.steps)
        for (const b of step.blocks)
          for (const op of [b.company, b.recomputed]) {
            // The company's line total is the row's own Reported figure (checked below), not a recomputation.
            if (op && !(b.id === "results.total" && op === b.company)) expect(Math.abs(evaluate(op) - Number(op.result.value))).toBeLessThanOrEqual(1e-9 * Math.max(1, Math.abs(Number(op.result.value))));
          }
      const companyTotal = block(trace, "results.total").company?.result.value ?? null;
      expect(companyTotal).toBe(line.reported_total_co2e_t ?? null);
      const total = block(trace, "results.total").recomputed!.result.value as number;
      expect(total).toBeCloseTo(line.results.total_co2e_t, 4);
      expect(() => render(<TracePanel trace={trace} />)).not.toThrow();
      cleanup();
    }
  });
});
