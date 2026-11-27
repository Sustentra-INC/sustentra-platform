/* @vitest-environment jsdom */
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const calls = vi.hoisted(() => ({ fail: false }));
vi.mock("../../../lib/api", () => ({
  api: vi.fn(() => (calls.fail ? Promise.reject(new Error("boom")) : Promise.resolve({ line_key: "k", trace: null }))),
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
    expect(within(table).getByText("Mass (t)")).toBeTruthy();
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

  it("shows the Step 1 parts with the company total, not reported rows and the total's difference", () => {
    const t = base();
    t.inputs["activity.total"].rows!.push({ id: "r2", label: "Mar 2025 ".repeat(200), recomputed: { value: 65000, unit: "therm", status: "accepted" } });
    block(t, "activity").recomputed!.result.difference = 65000;
    render(<TracePanel trace={t} />);
    const table = screen.getByRole("table", { name: "Step 1 · Activity data · Activity data" });
    expect(within(table).getAllByText("not reported").length).toBe(2);
    expect(table.textContent).toContain("650,000 therm");
    expect(table.querySelector(".s1-vw-steps__total .s1-cp-diff")?.textContent).toBe(" (+65,000)");
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
    expect(formatNumber(-0.0000001, { dp: 2 })).toBe("0");
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

describe("demo trace", () => {
  const evaluate = (op: TraceOperation) =>
    op.terms.reduce((acc, t, i) => (i === 0 ? Number(t.operand.value) : t.op === "×" ? acc * Number(t.operand.value) : t.op === "÷" ? acc / Number(t.operand.value) : t.op === "+" ? acc + Number(t.operand.value) : acc - Number(t.operand.value)), 0);

  it("restates every demo line, and its recomputed total is the line's", () => {
    for (const line of (calcLines as unknown as CalculationLine[]).filter((l) => l.category !== "biogenic")) {
      const trace = traceFromLine(line);
      for (const step of trace.steps)
        for (const b of step.blocks)
          for (const op of [b.company, b.recomputed]) {
            if (op) expect(Math.abs(evaluate(op) - Number(op.result.value))).toBeLessThanOrEqual(1e-9 * Math.max(1, Math.abs(Number(op.result.value))));
          }
      const total = block(trace, "results.total").recomputed!.result.value as number;
      expect(total).toBeCloseTo(line.results.total_co2e_t, 4);
      expect(() => render(<TracePanel trace={trace} />)).not.toThrow();
      cleanup();
    }
  });
});
