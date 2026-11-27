/* @vitest-environment jsdom */
import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import type { LineTrace, LineTraceResponse } from "../api/calcTrace";
import type { CalculationLine, Recalculation } from "../api/recalculation";
import { TracePanel } from "../components/calc-trace/TracePanel";
import { demoApi } from "../demo-backend";
import { resetDemoDecisions } from "../demo-backend/calcTrace/decisions";
import { companyRegionCode } from "../demo-backend/calcTrace/companyRegion";
import { traceFromLine } from "../demo-backend/calcTrace/fromLine";

const E = "ENG-CASCADE-2025";
const block = (t: LineTrace, id: string) => t.steps.flatMap((s) => s.blocks).find((b) => b.id === id)!;
const value = (t: LineTrace, id: string) => Number(block(t, id).recomputed!.result.value);
const companyValue = (t: LineTrace, id: string) => Number(block(t, id).company!.result.value);

let line: CalculationLine;
let key = "";
const trace = async () => (await demoApi<LineTraceResponse>(`/engagements/${E}/recalculation/lines/${encodeURIComponent(key)}/trace`)).trace!;
const post = (body: unknown) => demoApi(`/engagements/${E}/calculation-lines/${encodeURIComponent(key)}/inputs/grid_region/company`, { method: "POST", body });

beforeEach(async () => {
  resetDemoDecisions();
  const all = (await demoApi<Recalculation>(`/engagements/${E}/recalculation`)).calculation_lines!;
  line = all.find((l) => l.category === "purchased_energy" && l.company)!;
  key = line.key;
});
afterEach(cleanup);

describe("electricity grid region (C8)", () => {
  it("shows the grid region as its own Step 1 block, the company's not reported, and no difference", async () => {
    const t = await trace();
    const grid = t.inputs.grid_region;
    expect(grid.recomputed!.value).toMatch(/^[A-Z]{4}$/);
    expect(grid.company).toMatchObject({ value: null, status: "not_reported" });
    expect(grid.differs).toBeUndefined();
    expect(grid.decidable).toBe(false);
    expect(block(t, "grid_region").recomputed!.result.value).toBe(grid.recomputed!.value);
  });

  it("a company region moves only the company side: its factors and total, and says (differs)", async () => {
    const before = await trace();
    const mine = String(before.inputs.grid_region.recomputed!.value);
    const other = mine === "NWPP" ? "CAMX" : "NWPP";
    await post({ action: "edit", value: `${other} · WECC`, reason: "From the company's EF source list" });
    const t = await trace();
    expect(String(t.inputs.grid_region.company!.value)).toBe(`${other} · WECC`); // not a subregion: shown, never used
    expect(t.flags).toContain("company_grid_region_not_recognised");
    expect(companyValue(t, "results.total")).toBeCloseTo(companyValue(before, "results.total"), 9);
    await post({ action: "revert" });
    await post({ action: "edit", value: other.toLowerCase(), reason: "From the company's EF source list" });
    const after = await trace();
    expect(after.inputs.grid_region.company!.value).toBe(other);
    expect(after.inputs.grid_region.differs).toBe(true);
    expect(block(after, "grid_region").recomputed!.result.differs).toBe(true);
    expect(value(after, "results.total")).toBeCloseTo(value(before, "results.total"), 9); // ours does not move
    expect(companyValue(after, "results.total")).not.toBeCloseTo(companyValue(before, "results.total"), 3);
    expect(after.inputs["ef.CO2"].company!.value).not.toBe(after.inputs["ef.CO2"].recomputed!.value);
  });

  it("reads a region the way a person writes it, and refuses hostile text", () => {
    expect(companyRegionCode("nwpp")).toBe("NWPP");
    expect(companyRegionCode(" NWPP - WECC Northwest ")).toBe("NWPP");
    expect(companyRegionCode("WECC Northwest")).toBe("NWPP");
    for (const bad of ["", "   ", "NWPP; DROP TABLE", "WECC", "x".repeat(5000), "NWPP\u0000", "🙂", null]) expect(companyRegionCode(bad)).toBeNull();
  });

  it("offers a choice only for a ZIP code in two subregions", async () => {
    const t = await trace();
    expect(t.choices.some((c) => c.id === "grid_region")).toBe(false);
    const two = traceFromLine(line, { region: "RFCE", source: "chosen under Recalculation inputs", zip: "07401", candidates: ["RFCE", "NYUP"], companyRegionText: null });
    const choice = two.choices.find((c) => c.id === "grid_region")!;
    expect(choice.options.map((o) => o.id)).toEqual(["RFCE", "NYUP"]);
    expect(choice.chosen).toBe("RFCE");
    expect(block(two, "grid_region").choice_id).toBe("grid_region");
    render(<TracePanel trace={two} />);
    const pills = screen.getAllByRole("group", { name: "Grid region" })[0];
    expect(within(pills).getAllByText(/RFCE|NYUP/).length).toBe(2);
  });

  it("draws the region row with (differs) on the recomputed side", () => {
    const t = traceFromLine(line, { region: "CAMX", source: "ZIP code 95354", zip: "95354", candidates: ["CAMX"], companyRegionText: "NWPP" });
    render(<TracePanel trace={t} />);
    const table = screen.getByRole("table", { name: /Grid region/ });
    const rows = within(table).getAllByRole("row");
    expect(rows.find((r) => r.textContent?.startsWith("Company"))!.textContent).toContain("NWPP");
    expect(rows.find((r) => r.textContent?.startsWith("Recomputed"))!.textContent).toContain("CAMX (differs)");
  });
});
