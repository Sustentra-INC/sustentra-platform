/* @vitest-environment jsdom */
import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import {
  coverageFromRecalculation,
  inScopeFieldsFrom,
  recalculationMateriality,
  recalculationRows,
  type DataPointOption,
  type Recalculation,
} from "../api/recalculation";
import { SetupScreen } from "../components/SetupScreen";
import { engagementConfig } from "../fixtures/engagementConfig";
import workbookExample from "./fixtures/recalculationWorkbookExample.json";

const POINTS: DataPointOption[] = [
  { key: "scope1_total", label: "Scope 1 (Total)", workbook_row: 22, unit: "t CO2e", layer: "scope1",
    requirement: "Required", check: "recalculated" },
  { key: "scope2_market_total", label: "Scope 2 (Total), market-based", workbook_row: 29, unit: "t CO2e",
    layer: "scope2", requirement: "Required", check: "recalculated" },
  { key: "purchased_steam_total", label: "Indirect emissions from purchased steam", workbook_row: 48,
    unit: "t CO2e", layer: "scope2", requirement: "Optional", check: "not_recalculated" },
];

describe("in-scope data points", () => {
  it("lists the workbook's data points with the engagement's choices", () => {
    const fields = inScopeFieldsFrom(POINTS, ["purchased_steam_total"]);
    expect(fields.map((f) => [f.methodologyFieldId, f.inScope, f.workbookRow, f.checkedBy])).toEqual([
      ["scope1_total", true, 22, "Recalculated from reviewed evidence"],
      ["scope2_market_total", true, 29, "Recalculated from reviewed evidence"],
      ["purchased_steam_total", false, 48, "Not recalculated yet"],
    ]);
  });

  it("shows the live list in Setup and reports an unticked data point", () => {
    const onInScopeChange = vi.fn();
    render(
      <SetupScreen engagement={engagementConfig} onChange={vi.fn()} inScopeFields={inScopeFieldsFrom(POINTS, [])}
        onInScopeChange={onInScopeChange} />
    );
    expect(screen.getByText("3 of 3 in scope")).toBeTruthy();
    expect(screen.getByRole("columnheader", { name: "Workbook row" })).toBeTruthy();
    const row = screen.getByText("Indirect emissions from purchased steam").closest("tr")!;
    expect(within(row).getByText("Not recalculated yet")).toBeTruthy();
    fireEvent.click(within(row).getByRole("checkbox"));
    expect(onInScopeChange.mock.calls[0][0].filter((f: { inScope: boolean }) => !f.inScope)
      .map((f: { methodologyFieldId: string }) => f.methodologyFieldId)).toEqual(["purchased_steam_total"]);
  });

  it("shows a data point set out of scope as not in scope, outside coverage and materiality", () => {
    const base = workbookExample as unknown as Recalculation;
    const scoped: Recalculation = {
      ...base,
      comparisons: base.comparisons.map((c) => (c.key === "scope2_location_total" ? { ...c, status: "not_in_scope" } : c)),
    };
    const row = recalculationRows(scoped).find((r) => r.methodologyFieldId === "scope2_location_total")!;
    expect(row.checkOutcome).toBe("out_of_scope");
    expect(row.checkReason).toBe("Not in scope for this engagement (set in Setup).");
    const scope1 = base.comparisons.find((c) => c.key === "scope1_total")!;
    expect(recalculationMateriality(scoped).total).toBeCloseTo(scope1.reported ?? 0, 4);
    const reported = coverageFromRecalculation(scoped).find((r) => r.ruleId === "COV-REPORTED")!;
    expect(reported.appliesTo).not.toContain("Scope 2 (Total), location-based");
  });
});
