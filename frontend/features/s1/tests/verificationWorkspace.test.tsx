/* @vitest-environment jsdom */
import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { VerificationWorkspace } from "../components/VerificationWorkspace";
import { engagementConfig } from "../fixtures/engagementConfig";
import { verificationLines } from "../fixtures/verification/resultsDataset";
import type { FacilityResult, ResultLine, SourceRef } from "../types/verificationResults";
import { fuelByEnergy } from "../utils/calculationChains";
import {
  buildResultBoxes,
  formatPercent,
  formatSignedTonnes,
  formatTonnes,
  lineRecomputed,
  lineReported,
} from "../utils/verificationTable";
import { useVerificationStore } from "../verification/verificationStore";

function facility(id: string, reported: number, recomputed: number | null): FacilityResult {
  return { facilityId: id, facility: id, reported, recomputed, steps: [], cause: "" };
}

function line(id: string, activity: string, facilities: FacilityResult[] | null, extra: Partial<ResultLine> = {}): ResultLine {
  return { id, box: "scope2_location", activity, facilities, ...extra };
}

describe("the Reported vs recomputed table", () => {
  it("computes difference, share, % material, the total row and coverage as the spec defines them", () => {
    const [, location] = buildResultBoxes([
      line("elec", "Electricity", [facility("a", 600, 600), facility("b", 200, 200)]),
      line("heat", "Heating", [facility("a", 100, 110)]),
      line("steam", "Steam", [facility("a", 100, 100)]),
    ]);
    const heat = location.rows.find((r) => r.activity === "Heating")!;
    expect(heat.difference).toBeCloseTo(10);
    expect(heat.pctDifference).toBeCloseTo(0.1); // 10 ÷ 100
    expect(heat.share).toBeCloseTo(0.1); // 100 ÷ 1,000
    expect(heat.pctMaterial).toBeCloseTo(0.01); // %Difference × Share
    expect(location.totals).toMatchObject({ reported: 1000, recomputed: 1010, difference: 10, examined: 0, facilities: 4 });
    expect(location.totals.pctDifference).toBeCloseTo(0.01);
    expect(location.totals.pctMaterial).toBeCloseTo(0.01);
    expect(location.totals.share).toBeCloseTo(1); // coverage
    expect(location.normalizedMaterial).toBeNull(); // only below 100% coverage
    // Largest |% material| first; Cooling, not reported, greyed at the bottom.
    expect(location.rows.map((r) => [r.activity, r.notReported])).toEqual([
      ["Heating", false],
      ["Electricity", false],
      ["Steam", false],
      ["Cooling", true],
    ]);
  });

  it("keeps a reported but untested line in the share, so coverage drops and the normalized row appears", () => {
    const [, location] = buildResultBoxes([
      line("elec", "Electricity", [facility("a", 750, 780)]),
      line("steam", "Steam", [facility("a", 250, null)]),
    ]);
    const steam = location.rows.find((r) => r.activity === "Steam")!;
    expect(steam.notTested).toBe(true);
    expect(location.totals.share).toBeCloseTo(0.75);
    expect(location.totals.pctMaterial).toBeCloseTo(0.03); // 30 ÷ 1,000
    expect(location.normalizedMaterial).toBeCloseTo(0.04); // 3% ÷ 75%
  });

  it("orders Scope 1 by category, names each category once, and lists an unreported category last", () => {
    const [scope1] = buildResultBoxes([
      line("ng", "Natural gas", [facility("a", 100, 100)], { box: "scope1", category: "Stationary combustion" }),
      line("pr", "Propane", [facility("a", 50, 60)], { box: "scope1", category: "Stationary combustion" }),
      line("r404", "R-404A", [facility("a", 30, 30)], { box: "scope1", category: "Fugitive emissions" }),
    ]);
    expect(scope1.rows.map((r) => [r.categoryLabel, r.activity || "Not reported"])).toEqual([
      ["Stationary combustion", "Propane"],
      [null, "Natural gas"],
      ["Fugitive emissions", "R-404A"],
      ["Mobile combustion", "Not reported"],
      ["Process emissions", "Not reported"],
    ]);
  });

  it("adds each facility after its consolidated share, and leaves biogenic CO₂ whole", () => {
    const half = { ...facility("jv", 400, 500), consolidatedShare: 0.5 };
    const scope1 = line("ng", "Natural gas", [facility("a", 100, 100), half], { box: "scope1", category: "Stationary combustion" });
    expect([lineReported(scope1), lineRecomputed(scope1)]).toEqual([300, 350]);
    const biogenic = line("bio", "Direct", [half], { box: "biogenic" });
    expect([lineReported(biogenic), lineRecomputed(biogenic)]).toEqual([400, 500]);
  });

  it("formats tonnes and percentages with their signs", () => {
    expect(formatTonnes(9560.61)).toBe("9,561");
    expect(formatSignedTonnes(345.245)).toBe("+345");
    expect(formatSignedTonnes(-205.7)).toBe("−206");
    expect(formatSignedTonnes(0.3)).toBe("0");
    expect(formatPercent(0.03608, true)).toBe("+3.6%");
    expect(formatPercent(-0.012, true)).toBe("−1.2%");
    expect(formatPercent(0.00001, true)).toBe("0.0%");
    expect(formatPercent(0.5435)).toBe("54.4%");
  });
});

describe("the calculation card", () => {
  const gwp = { ch4: { value: 28, unit: "" }, n2o: { value: 265, unit: "" } };
  const naturalGas = { co2: { value: 53.06, unit: "kg/MMBtu" }, ch4: { value: 1.0, text: "1.0", unit: "g/MMBtu" }, n2o: { value: 0.1, text: "0.10", unit: "g/MMBtu" } };

  it("reproduces the wireframe's Facility B: 650,000 against 715,000 therms", () => {
    const chain = fuelByEnergy({
      consumption: { reported: { value: 650_000, unit: "therms" }, recomputed: { value: 715_000, unit: "therms" } },
      heatContent: { value: 0.1, unit: "MMBtu per therm" },
      ...naturalGas,
      gwp,
    });
    expect(chain.steps.map((s) => [s.step, s.reported?.text, s.recomputed?.text])).toEqual([
      ["Annual consumption", "650,000 therms", "715,000 therms"],
      ["Unit conversion", "65,000 MMBtu", "71,500 MMBtu"],
      ["CO₂", "3,448.9 t", "3,793.8 t"],
      ["CH₄", "1.8 t", "2.0 t"],
      ["N₂O", "1.7 t", "1.9 t"],
      ["Total", "3,452 tCO₂e", "3,798 tCO₂e"],
    ]);
    expect(formatSignedTonnes(chain.recomputed - chain.reported)).toBe("+345");
  });

  it("gives a factor the client applied differently its own row", () => {
    const chain = fuelByEnergy({
      consumption: { value: 1_000, unit: "therms" },
      heatContent: { value: 0.1, unit: "MMBtu per therm" },
      ...naturalGas,
      co2: { reported: { value: 50, unit: "kg/MMBtu" }, recomputed: naturalGas.co2 },
      gwp,
    });
    const factorRow = chain.steps.find((s) => s.step === "CO₂ factor");
    expect([factorRow?.reported?.text, factorRow?.recomputed?.text]).toEqual(["50 kg/MMBtu", "53.06 kg/MMBtu"]);
    expect(chain.steps.find((s) => s.step === "CO₂")?.how.map((c) => c.text).join("")).toBe("× CO₂ factor");
    // An agreed factor stays in the How column.
    expect(chain.steps.find((s) => s.step === "CH₄")?.how.map((c) => c.text).join("")).toBe("× 1.0 g/MMBtu × GWP 28");
  });
});

describe("the demo inventory", () => {
  const sources = (l: ResultLine): SourceRef[] =>
    (l.facilities ?? []).flatMap((f) => f.steps.flatMap((s) => [...s.how, s.reported, s.recomputed]).flatMap((c) => (c?.source ? [c.source] : [])));

  it("adds up: Scope 1 and Scope 2 totals from the facility calculations", () => {
    const [scope1, location, market, biogenic] = buildResultBoxes(verificationLines);
    expect([formatTonnes(scope1.totals.reported), formatTonnes(scope1.totals.recomputed), formatSignedTonnes(scope1.totals.difference)]).toEqual([
      "17,589",
      "18,298",
      "+709",
    ]);
    expect([formatTonnes(location.totals.reported), formatTonnes(location.totals.recomputed)]).toEqual(["6,175", "6,182"]);
    expect(formatSignedTonnes(market.totals.difference)).toBe("+295"); // electricity +288, heating +7
    expect(formatSignedTonnes(market.rows[0].difference ?? 0)).toBe("+288");
    expect(formatTonnes(biogenic.totals.reported)).toBe("140");
    const gas = verificationLines.find((l) => l.id === "s1-stationary-natural-gas")!;
    expect([formatTonnes(lineReported(gas)!), formatTonnes(lineRecomputed(gas)!)]).toEqual(["9,561", "9,906"]);
  });

  it("cites a source for every consumption, and a monthly list sums to the recomputed amount", () => {
    for (const l of verificationLines) {
      for (const f of l.facilities ?? []) {
        const first = f.steps[0];
        expect(first.reported?.source?.kind, `${l.id} ${f.facility}`).toBe("workbook");
        expect(["records", "document"]).toContain(first.recomputed?.source?.kind);
      }
      for (const source of sources(l)) {
        if (source.kind === "records") {
          const sum = source.items.reduce((s, i) => s + i.quantity, 0);
          expect(source.items.some((i) => i.lines[i.highlight])).toBe(true);
          expect(sum).toBeGreaterThan(0);
        }
        if (source.kind === "workbook") expect(source.rows[source.target.row][source.target.column]).toBeTruthy();
      }
    }
    const kent = verificationLines.find((l) => l.id === "s1-stationary-natural-gas")!.facilities![1];
    const bills = kent.steps[0].recomputed!.source as Extract<SourceRef, { kind: "records" }>;
    expect(bills.items.reduce((s, i) => s + i.quantity, 0)).toBe(715_000);
    expect(bills.items.find((i) => i.filename === bills.missingFrom)?.quantity).toBe(65_000);
  });
});

function Harness() {
  const store = useVerificationStore({}, [], "M. Osei");
  return (
    <VerificationWorkspace
      lines={verificationLines}
      store={store}
      team={engagementConfig.engagementTeam ?? []}
      signedInLogin={engagementConfig.signedInLogin}
    />
  );
}

describe("the Verification results page", () => {
  it("folds boxes to their summary line and opens a line's calculation in a panel that Esc closes", () => {
    render(<Harness />);
    // Scope 1 starts open; the other boxes show their summary line and fold open on click.
    const boxHead = (name: RegExp) =>
      screen.getAllByRole("button", { name }).find((b) => b.hasAttribute("aria-expanded")) as HTMLElement;
    const location = boxHead(/Scope 2, location-based/);
    expect(location.getAttribute("aria-expanded")).toBe("false");
    expect(location.textContent).toContain("+0.1% material");
    expect(screen.queryByRole("button", { name: "Steam" })).toBeNull();
    fireEvent.click(location);
    expect(location.getAttribute("aria-expanded")).toBe("true");
    expect(screen.getByRole("button", { name: "Steam" })).toBeTruthy();

    // A row opens its line in the panel; Esc closes it.
    fireEvent.click(boxHead(/Scope 2, market-based/));
    const market = boxHead(/Scope 2, market-based/).closest(".s1-vw-box") as HTMLElement;
    fireEvent.click(within(market).getByRole("button", { name: "Electricity" }));
    expect(within(screen.getByRole("region", { name: "Calculation" })).getByRole("heading", { level: 2 }).textContent).toBe(
      "Scope 2, market-based › Electricity"
    );
    fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.queryByRole("region", { name: "Calculation" })).toBeNull();
  });

  it("opens the differing facility's card and its sources, and records the examination", () => {
    render(<Harness />);
    const gasRow = screen.getByRole("button", { name: "Natural gas" }).closest("tr") as HTMLElement;
    expect(within(gasRow).getByText("0 of 3")).toBeTruthy();

    fireEvent.click(within(gasRow).getByRole("button", { name: "Natural gas" }));
    const calc = screen.getByRole("region", { name: "Calculation" });
    expect(within(calc).getByRole("heading", { level: 2 }).textContent).toBe("Scope 1 › Stationary combustion › Natural gas");
    expect(calc.querySelector(".s1-vw-summary")?.textContent).toBe("Reported 9,561Recomputed 9,906Difference +345");
    // Kent Cannery explains the difference, so its card is already open.
    expect(within(calc).getByRole("button", { name: /Kent Cannery/ }).getAttribute("aria-expanded")).toBe("true");
    expect(within(calc).getByText(/the March bill is missing from the reported total/)).toBeTruthy();

    // Underlined inputs open their documents beside the calculation.
    const source = screen.getByRole("region", { name: "Source" });
    fireEvent.click(within(calc).getByRole("button", { name: "650,000 therms" }));
    expect(within(source).getByText(/cell D3/)).toBeTruthy();
    const bills = within(calc).getByRole("button", { name: "715,000 therms" });
    fireEvent.click(bills);
    expect(bills.getAttribute("aria-pressed")).toBe("true");
    expect(within(source).getByText("Not in the reported total")).toBeTruthy();
    fireEvent.click(within(source).getByRole("button", { name: "kent_gas_mar_2025.pdf" }));
    expect(within(source).getByText("65,000 therms").closest("[aria-current]")).toBeTruthy();
    fireEvent.click(within(calc).getByRole("button", { name: "53.06 kg/MMBtu" }));
    expect(within(source).getByText(/Table 1, row 38/)).toBeTruthy();

    // Record examination: the signed-in member is pre-selected; Save recounts the table.
    fireEvent.click(within(calc).getByRole("button", { name: "Record examination" }));
    const box = within(calc).getByRole("group", { name: /Record examination · Kent Cannery · Natural gas/ });
    expect(within(box).getByRole("button", { name: /M\. Osei/ }).getAttribute("aria-pressed")).toBe("true");
    fireEvent.change(within(box).getByRole("textbox"), { target: { value: "Traced to the March bill." } });
    fireEvent.click(within(box).getByRole("button", { name: "Save" }));
    expect(within(gasRow).getByText("1 of 3")).toBeTruthy();
    expect(within(calc).getByText("Examined by M. Osei")).toBeTruthy();

    // Re-opening shows what was stored, with Clear.
    fireEvent.click(within(calc).getByRole("button", { name: "Record examination" }));
    const again = within(calc).getByRole("group", { name: /Record examination/ });
    expect(within(again).getByText(/Examined by M\. Osei,/)).toBeTruthy();
    expect((within(again).getByRole("textbox") as HTMLTextAreaElement).value).toBe("Traced to the March bill.");
    fireEvent.click(within(again).getByRole("button", { name: "Clear examination" }));
    expect(within(gasRow).getByText("0 of 3")).toBeTruthy();

    fireEvent.click(within(calc).getByRole("button", { name: "Close calculation" }));
    expect(screen.queryByRole("region", { name: "Source" })).toBeNull();
  });

  it("shows each facility's consolidated share, closes every card on it, and totals the panel from it", () => {
    render(<Harness />);
    fireEvent.click(screen.getByRole("button", { name: "Natural gas" }));
    const calc = screen.getByRole("region", { name: "Calculation" });
    const table = calc.querySelector(".s1-vw-facilities") as HTMLTableElement;
    const headers = Array.from(table.tHead!.rows[0].cells).map((th) => th.textContent);
    expect(headers.slice(1, 3)).toEqual(["Facility", "Consolidated share"]);
    const facilityRows = Array.from(table.tBodies[0].rows).filter((r) => r.classList.contains("s1-vw-row"));
    expect(facilityRows).toHaveLength(3);
    for (const row of facilityRows) expect(row.cells[2].textContent).toBe("100%");

    // Kent's card: one last row after Total, the total times its share, with the difference.
    const steps = Array.from(calc.querySelectorAll(".s1-vw-steps tbody tr")) as HTMLTableRowElement[];
    const [total, consolidated] = steps.slice(-2);
    expect(total.cells[0].textContent).toBe("Total");
    expect(consolidated.cells[0].textContent).toBe("Consolidated");
    expect(consolidated.cells[1].textContent).toBe("Total × 100% consolidated share");
    expect(consolidated.cells[2].textContent).toBe(total.cells[2].textContent);
    expect(consolidated.cells[3].textContent).toMatch(/^[\d,]+ tCO₂e \(\+\d+\)$/);
    expect(total.cells[3].textContent).not.toMatch(/\(/);

    // The panel's bottom row sums the facilities' consolidated values.
    const bottom = table.querySelector(".s1-vw-total") as HTMLTableRowElement;
    expect(Array.from(bottom.cells).map((c) => c.textContent)).toEqual(["Natural gas", "Total", "", "9,561", "9,906", "+345"]);
  });

  it("leaves biogenic CO₂ without a consolidated share", () => {
    render(<Harness />);
    const head = screen.getAllByRole("button", { name: /Biogenic CO₂/ }).find((b) => b.hasAttribute("aria-expanded")) as HTMLElement;
    fireEvent.click(head);
    fireEvent.click(within(head.closest(".s1-vw-box") as HTMLElement).getByRole("button", { name: "Direct" }));
    const calc = screen.getByRole("region", { name: "Calculation" });
    expect(within(calc).queryByText("Consolidated share")).toBeNull();
    expect(within(calc).queryByText("Consolidated")).toBeNull();
  });

  it("saves a note only with text, and a note is not an examination", () => {
    render(<Harness />);
    fireEvent.click(screen.getByRole("button", { name: "Natural gas" }));
    const calc = screen.getByRole("region", { name: "Calculation" });
    fireEvent.click(within(calc).getByRole("button", { name: /Tualatin Plant/ }));
    fireEvent.click(within(calc).getByRole("button", { name: "Add notes" }));
    const box = within(calc).getByRole("group", { name: /Add notes/ });
    const save = within(box).getByRole("button", { name: "Save" }) as HTMLButtonElement;
    expect(save.disabled).toBe(true);
    fireEvent.change(within(box).getByRole("textbox"), { target: { value: "Ask for the meter photos." } });
    fireEvent.click(save);
    expect(within(calc).getByText("Ask for the meter photos.")).toBeTruthy();
    const gasRow = screen.getByRole("button", { name: "Natural gas" }).closest("tr") as HTMLElement;
    expect(within(gasRow).getByText("0 of 3")).toBeTruthy();
  });
});
