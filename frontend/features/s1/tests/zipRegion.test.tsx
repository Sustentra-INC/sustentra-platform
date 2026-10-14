/* @vitest-environment jsdom */
import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { recalculationRows, zipFromAddress, type Recalculation, type RecalculationReference } from "../api/recalculation";
import { RecalculationInputs } from "../components/RecalculationInputs";
import { ZipRegionHint } from "../components/ZipRegionHint";
import workbookExample from "./fixtures/recalculationWorkbookExample.json";

const RESULT = workbookExample as unknown as Recalculation;

describe("grid region from a ZIP code", () => {
  it("reads the ZIP code of an address", () => {
    expect(zipFromAddress("15 State Street, Albany, NY 12207")).toBe("12207");
    expect(zipFromAddress("12345 Main St, Austin TX 78701-1234")).toBe("78701");
    expect(zipFromAddress("Albany, NY")).toBeNull();
    expect(zipFromAddress(null)).toBeNull();
  });

  it("offers the single subregion of a ZIP code and sets it", async () => {
    const onUse = vi.fn();
    const lookup = vi.fn().mockResolvedValue(["NYUP"]);
    render(<ZipRegionHint address="15 State Street, Albany, NY 12207" region={undefined} lookup={lookup} onUse={onUse} />);
    fireEvent.click(await screen.findByRole("button", { name: "Use NYUP" }, { timeout: 2000 }));
    expect(lookup).toHaveBeenCalledWith("12207");
    expect(onUse).toHaveBeenCalledWith("NYUP");
  });

  it("says when a ZIP code is served by several subregions and lets the reviewer pick", async () => {
    const lookup = vi.fn().mockResolvedValue(["NYCW", "NYUP"]);
    render(<ZipRegionHint address="1 Main St, Ardsley, NY 10501" region={undefined} lookup={lookup} onUse={vi.fn()} />);
    expect(await screen.findByText(/served by NYCW or NYUP/, undefined, { timeout: 2000 })).toBeTruthy();
    expect(screen.getAllByRole("button").map((b) => b.textContent)).toEqual(["Use NYCW", "Use NYUP"]);
  });

  it("narrows the grid-region choice to the ZIP code's subregions", () => {
    const result: Recalculation = {
      ...RESULT,
      needs_input: [{ kind: "grid_region", key: "Facility C", options: ["NYCW", "NYUP"],
        message: "Choose the eGRID subregion for Facility C: ZIP 10501 is served by NYCW or NYUP." }],
    };
    const reference: RecalculationReference = {
      dataset: "EPA GHG Emission Factors Hub 2025", gwp_sets: ["AR5"], default_gwp_set: "AR5",
      egrid_subregions: [{ egrid_subregion: "NYCW", name: "NPCC NYC/Westchester" },
        { egrid_subregion: "NYUP", name: "NPCC Upstate NY" }, { egrid_subregion: "RFCE", name: "RFC East" }],
      stationary_fuels: [], mobile_fuels: [], reported_data_points: [],
    };
    render(<RecalculationInputs result={result} reference={reference} settings={{}} saving={false} error={null}
      onSave={vi.fn()} />);
    const field = screen.getByText("Facility C").closest("label")!;
    const options = Array.from(within(field).getByRole("combobox").querySelectorAll("option")).map((o) => o.value);
    expect(options).toEqual(["", "NYCW", "NYUP"]);
  });

  it("names the subregion and its ZIP code in the working", () => {
    const location = RESULT.categories.purchased_electricity_location_based!;
    const withZip: Recalculation = {
      ...RESULT,
      categories: {
        ...RESULT.categories,
        purchased_electricity_location_based: {
          ...location,
          details: { ...location.details, inputs: (location.details.inputs ?? []).map((i) => ({
            ...i, grid_region: "NYUP", grid_region_source: "ZIP 12207 (EPA Power Profiler ZIP Code Tool v14.2 (eGRID2023 rev 1))",
          })) },
        },
      },
    };
    const row = recalculationRows(withZip).find((r) => r.methodologyFieldId === "scope2_location_total")!;
    expect(row.working!.inputs.some((i) => i.source?.endsWith("· subregion NYUP from ZIP 12207"))).toBe(true);
  });
});
