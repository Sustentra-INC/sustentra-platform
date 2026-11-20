/* @vitest-environment jsdom */
import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { reportedSourceWords, type Recalculation, type RecalculationReference, type ReportedSource } from "../api/recalculation";
import { RecalculationInputs } from "../components/RecalculationInputs";
import workbookExample from "./fixtures/recalculationWorkbookExample.json";

afterEach(cleanup);

const REFERENCE: RecalculationReference = {
  dataset: "EPA GHG Emission Factors Hub 2025",
  gwp_sets: ["AR5", "AR6"],
  default_gwp_set: "AR5",
  egrid_subregions: [{ egrid_subregion: "NYUP", name: "NPCC Upstate NY" }],
  stationary_fuels: ["Natural Gas"],
  mobile_fuels: ["Diesel Fuel"],
  reported_data_points: [
    { key: "scope1_total", label: "Scope 1 (Total)", workbook_row: 22, unit: "t CO2e" },
    { key: "scope2_location_total", label: "Scope 2 (Total), location-based", workbook_row: 30, unit: "t CO2e" },
  ],
};

const figure = (value: number, printed: string) => ({
  value,
  unit: "t CO2e" as const,
  document_id: "d1",
  file_name: "2023-Statement-of-GHG-Emissions.pdf",
  page: 3,
  printed,
  label: "Scope 1 total",
});

function show(sources: Record<string, ReportedSource>, only: Recalculation["reported_only"] = []) {
  const result = { ...(workbookExample as unknown as Recalculation), reported_sources: sources, reported_only: only };
  render(<RecalculationInputs result={result} reference={REFERENCE} settings={{}} saving={false} error={null} onSave={vi.fn()} />);
  // the section opens from its header
  fireEvent.click(screen.getByRole("button", { name: /Recalculation inputs/ }));
}

describe("Reported values read from accepted summary documents", () => {
  it("says where a figure came from: file and page, as accepted", () => {
    expect(reportedSourceWords(figure(1, "1"))).toBe("From 2023-Statement-of-GHG-Emissions.pdf, page 3");
    show({ scope1_total: { document: figure(1_200_000, "1.2 MtCO2e"), manual: null, used: "document", differs: false } });
    const row = screen.getByText(/Scope 1 \(Total\)/).closest("label") as HTMLElement;
    expect(within(row).getByRole("note")).toHaveTextContent("From 2023-Statement-of-GHG-Emissions.pdf, page 3 · 1.2 MtCO2e · used as reported");
  });

  it("shows both a typed figure and the document's, and flags a difference", () => {
    show({ scope1_total: { document: figure(38922, "38,922 tCO2e"), manual: 40000, used: "manual", differs: true } });
    const row = screen.getByText(/Scope 1 \(Total\)/).closest("label") as HTMLElement;
    expect(within(row).getByRole("note")).toHaveTextContent("differs from the figure entered here, which is used");
  });

  it("says when two documents disagree and none is used", () => {
    show({
      scope1_total: { document: null, manual: null, used: null, differs: false, conflict: [figure(1, "1 tCO2e"), figure(2, "2 tCO2e")] },
    });
    expect(screen.getByRole("note")).toHaveTextContent("Two documents give different figures");
  });

  it("lists Scope 3 as reported only, never compared", () => {
    show({}, [{ ...figure(30660751, "30,660,751 tCO2e"), key: "scope3_total", label: "Scope 3 total" }]);
    const note = screen.getByText(/Reported only, not compared/).closest("div") as HTMLElement;
    expect(note).toHaveTextContent("Scope 3 total: 30,660,751 tCO2e");
    expect(screen.queryByText(/Scope 3.*location-based/)).toBeNull();
  });
});
