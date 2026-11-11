/* @vitest-environment jsdom */
import { fireEvent, render, renderHook, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

const responses = vi.hoisted(() => ({ byPath: {} as Record<string, unknown> }));
vi.mock("../../../lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../../../lib/api")>()),
  api: vi.fn((path: string) => Promise.resolve(responses.byPath[path])),
}));

import { api } from "../../../lib/api";
import type { CalculationLine, Recalculation, RecalculationReference } from "../api/recalculation";
import { BackendVerificationResults } from "../components/BackendVerificationResults";
import { engagementConfig } from "../fixtures/engagementConfig";
import type { EngagementConfig } from "../types";
import { examinationKey } from "../utils/verificationTable";
import { useVerificationStore } from "../verification/verificationStore";
import calcLines from "./fixtures/calculationLines.json";
import liveExample from "./fixtures/recalculationLive.json";

/*
 * The backend's calculation_lines (Task 2) are mocked: a stationary line with a company side
 * (650,000 therms → 65,000 MMBtu), a mobile diesel group with distance rows, and a purchased
 * electricity line at a 60% consolidated share. Every number below is read off the response.
 */
const LINES = calcLines as unknown as CalculationLine[];
const STATIONARY = "s1:stationary:natural-gas:fac-kc01";
const MOBILE = "s1:mobile:diesel-fuel:vg-diesel-trucks";
const ELECTRICITY = "s2:purchased_energy:electricity:fac-kc01";

const RESULT = { ...(liveExample as unknown as Recalculation), engagement_id: "ENG-1", calculation_lines: LINES } as Recalculation;
const REFERENCE: RecalculationReference = {
  dataset: "EPA GHG Emission Factors Hub 2025",
  gwp_sets: ["AR4", "AR5", "AR6"],
  default_gwp_set: "AR5",
  egrid_subregions: [{ egrid_subregion: "NYUP", name: "NPCC Upstate NY" }],
  stationary_fuels: ["Natural Gas"],
  mobile_fuels: ["Diesel Fuel"],
  reported_data_points: [{ key: "scope1_total", label: "Scope 1 (Total)", workbook_row: 22, unit: "t CO2e" }],
};
const ENGAGEMENT: EngagementConfig = {
  ...engagementConfig,
  engagementId: "ENG-1",
  engagementTeam: [{ name: "Dana", login: "dana@verifier.test" }],
  signedInLogin: "dana@verifier.test",
  signedInName: "Dana",
};

const recalcCalls = () => vi.mocked(api).mock.calls.filter(([path]) => path === "/engagements/ENG-1/recalculation").length;

function renderScreen(props: Partial<React.ComponentProps<typeof BackendVerificationResults>> = {}, engagement = ENGAGEMENT) {
  responses.byPath["/engagements/ENG-1/recalculation"] = RESULT;
  responses.byPath["/reference/recalculation"] = REFERENCE;
  const store = renderHook(() => useVerificationStore()).result;
  const view = render(
    <BackendVerificationResults
      engagement={engagement}
      store={store.current}
      onSaveInputs={async () => {}}
      onError={() => false}
      {...props}
    />
  );
  return { store, view };
}

async function panel(name: RegExp) {
  const region = await screen.findByRole("region", { name: "Calculation by line" });
  return within(region).getByRole("button", { name });
}

describe("calculation panels in Verification results", () => {
  it("renders the stationary panel from the response: header, lines table and total", async () => {
    renderScreen();
    const head = await panel(/Scope 1 › Stationary combustion/);
    // The header takes its figures from the live results line, not a sum made here.
    expect(head.textContent).toContain("1,250.0");
    expect(head.textContent).toContain("1,274.7");
    const region = screen.getByRole("region", { name: "Calculation by line" });
    const row = within(region).getByRole("button", { name: "Kent Cannery · MMBtu" }).closest("tr")!;
    expect(row.textContent).toContain("Natural gas");
    expect(row.textContent).toContain("100%");
    expect(row.textContent).toContain("3,300.0");
    expect(row.textContent).toContain("3,452.4");
    expect(row.textContent).toContain("+152.4");
    expect(row.textContent).toContain("Not examined");
    expect(within(region).getByText("Total").closest("tr")).toBeTruthy();
  });

  it("shows each step's numbers exactly as the response gives them, one step at a time", async () => {
    renderScreen();
    await panel(/Scope 1 › Stationary combustion/);
    fireEvent.click(screen.getByRole("button", { name: "Kent Cannery · MMBtu" }));
    expect(screen.getByText("Energy content × per-MMBtu factor (Eq. 1)")).toBeTruthy();

    // Step 1: periods, evidence and the total; the company side is its annual figure.
    let tab = screen.getByRole("tabpanel");
    expect(within(tab).getByText("2025-01-01 to 2025-01-31")).toBeTruthy();
    expect(within(tab).getByText("Edited by reviewer")).toBeTruthy();
    expect(within(tab).getByText("650,000 therms")).toBeTruthy();

    // Step 2: therms → MMBtu at 0.1 for the company, ×1 for the evidence.
    fireEvent.click(screen.getByRole("tab", { name: /Step 2/ }));
    tab = screen.getByRole("tabpanel");
    const company = within(tab).getByText("Company").closest("tr")!;
    expect(company.textContent).toContain("therms → MMBtu");
    expect(company.textContent).toContain("×0.1");
    expect(within(tab).getByText("Recomputed").closest("tr")!.textContent).toContain("×1");

    // Step 3: one row per gas, mass and CO₂e as given.
    fireEvent.click(screen.getByRole("tab", { name: /Step 3/ }));
    tab = screen.getByRole("tabpanel");
    const co2 = within(tab).getAllByText(/^CO₂/)[0].closest("tr")!;
    expect(co2.textContent).toContain("65,000 MMBtu");
    expect(co2.textContent).toContain("53.06 kg CO₂/MMBtu");
    expect(co2.textContent).toContain("×0.001");
    expect(co2.textContent).toContain("3,448.9");
    expect(within(tab).getAllByRole("row").length).toBeGreaterThanOrEqual(1 + 3);

    // Results: sum, share and total.
    fireEvent.click(screen.getByRole("tab", { name: "Results" }));
    tab = screen.getByRole("tabpanel");
    expect(within(tab).getByText("Total CO₂e (t)").closest("tr")!.textContent).toContain("3,452.4");
    expect(within(tab).getByText("× Consolidated share").closest("tr")!.textContent).toContain("100%");
  });

  it("opens a factor's source in a popover and a document row at its value", async () => {
    const opened: [string, string | undefined][] = [];
    renderScreen({ onOpenDocument: (id, valueId) => opened.push([id, valueId]) });
    await panel(/Scope 1 › Stationary combustion/);
    fireEvent.click(screen.getByRole("button", { name: "Kent Cannery · MMBtu" }));
    fireEvent.click(within(screen.getByRole("tabpanel")).getByRole("button", { name: "GAS-JAN.pdf" }));
    expect(opened).toEqual([["GAS-JAN", "cand-jan"]]);

    fireEvent.click(screen.getByRole("tab", { name: /Step 3/ }));
    fireEvent.click(within(screen.getByRole("tabpanel")).getAllByRole("button", { name: "53.06 kg CO₂/MMBtu" })[0]);
    expect(screen.getByText("Source: EPA GHG Emission Factors Hub 2025, Table 1")).toBeTruthy();
  });

  it("saves a GWP set change through the existing save path and refetches", async () => {
    const saved: unknown[] = [];
    renderScreen({ onSaveInputs: async (next) => void saved.push(next) });
    await panel(/Scope 1 › Stationary combustion/);
    fireEvent.click(screen.getByRole("button", { name: "Kent Cannery · MMBtu" }));
    fireEvent.click(screen.getByRole("tab", { name: /Step 3/ }));
    const before = recalcCalls();
    fireEvent.change(within(screen.getByRole("tabpanel")).getByRole("combobox", { name: "GWP set" }), { target: { value: "AR6" } });
    await waitFor(() => expect(saved).toEqual([expect.objectContaining({ gwp_set: "AR6" })]));
    await waitFor(() => expect(recalcCalls()).toBe(before + 1));
  });

  it("saves company figures for the line, and says in words what is wrong", async () => {
    const saved: Record<string, unknown>[] = [];
    renderScreen({ onSaveInputs: async (next) => void saved.push(next as Record<string, unknown>) });
    await panel(/Scope 1 › Stationary combustion/);
    fireEvent.click(screen.getByRole("button", { name: "Kent Cannery · MMBtu" }));
    fireEvent.click(screen.getByRole("button", { name: "Edit company figures" }));
    const form = screen.getByRole("group", { name: "Company figures · Kent Cannery" });

    fireEvent.change(within(form).getByLabelText("Company total (t CO₂e)"), { target: { value: "abc" } });
    fireEvent.click(within(form).getByRole("button", { name: "Save company figures" }));
    expect(within(form).getByRole("alert").textContent).toContain("Enter the company's total as a number");
    expect(saved).toEqual([]);

    fireEvent.change(within(form).getByLabelText("Company total (t CO₂e)"), { target: { value: "3,300" } });
    fireEvent.change(within(form).getByLabelText("Company annual activity"), { target: { value: "650000" } });
    fireEvent.change(within(form).getByLabelText("Activity unit"), { target: { value: "therms" } });
    fireEvent.click(within(form).getByRole("button", { name: "Save company figures" }));
    await waitFor(() => expect(saved).toHaveLength(1));
    expect(saved[0]).toMatchObject({
      reported_lines: { [STATIONARY]: 3300 },
      reported_activity: { [STATIONARY]: { quantity: 650000, unit: "therms" } },
    });
  });

  it("records examinations and notes against the line key", async () => {
    const { store, view } = renderScreen();
    await panel(/Scope 1 › Stationary combustion/);
    fireEvent.click(screen.getByRole("button", { name: "Kent Cannery · MMBtu" }));
    fireEvent.click(screen.getByRole("button", { name: "Record examination" }));
    fireEvent.click(screen.getByRole("button", { name: /Dana/ }));
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    // The store lives in the test's hook: read it back by the line's key.
    expect(store.current.examinations[examinationKey("calc", STATIONARY)]?.examinedBy).toBe("Dana");
    view.rerender(
      <BackendVerificationResults engagement={ENGAGEMENT} store={store.current} onSaveInputs={async () => {}} onError={() => false} />
    );
    expect(screen.getByText("Examined by Dana")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Add notes" }));
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "Bills match the meter." } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(store.current.examinations[examinationKey("calc", STATIONARY)]?.notes?.[0]?.text).toBe("Bills match the meter.");
  });

  it("shows a mobile group's distance rows for CH₄ and N₂O", async () => {
    renderScreen();
    fireEvent.click(await panel(/Scope 1 › Mobile combustion/));
    fireEvent.click(screen.getByRole("button", { name: "Diesel trucks · gal" }));
    fireEvent.click(screen.getByRole("tab", { name: /Step 3/ }));
    const tab = screen.getByRole("tabpanel");
    expect(within(tab).getAllByText(/90,000 mi/)).toHaveLength(2);
    expect(within(tab).getAllByText(/12,000 gal/)).toHaveLength(1);
    // No company side entered: the Results tab says so.
    fireEvent.click(screen.getByRole("tab", { name: "Results" }));
    expect(within(screen.getByRole("tabpanel")).getAllByText("Not entered").length).toBeGreaterThan(0);
  });

  it("renders an electricity line with its consolidated share", async () => {
    renderScreen();
    fireEvent.click(await panel(/Scope 2 › Purchased electricity/));
    const row = screen.getByRole("button", { name: "Kent Cannery · MWh" }).closest("tr")!;
    expect(row.textContent).toContain("60%");
    expect(row.textContent).toContain("218.8");
    fireEvent.click(screen.getByRole("button", { name: "Kent Cannery · MWh" }));
    fireEvent.click(screen.getByRole("tab", { name: "Results" }));
    expect(within(screen.getByRole("tabpanel")).getByText("× Consolidated share").closest("tr")!.textContent).toContain("60%");
  });

  it("opens Verification focused on a line key, and offers Open in Evidence when wired", async () => {
    const opened: string[] = [];
    renderScreen({ focusLineKey: ELECTRICITY, onOpenEvidence: (key) => opened.push(key) });
    // The electricity panel is open with its line expanded, with no click.
    const row = await screen.findByRole("button", { name: "Kent Cannery · MWh" });
    expect(row.getAttribute("aria-expanded")).toBe("true");
    fireEvent.click(screen.getByRole("button", { name: "Open in Evidence" }));
    expect(opened).toEqual([ELECTRICITY]);
    expect(MOBILE).toContain("mobile");
  });

  it("leaves the page as it was when the response carries no calculation lines", async () => {
    responses.byPath["/engagements/ENG-1/recalculation"] = { ...RESULT, calculation_lines: undefined };
    responses.byPath["/reference/recalculation"] = REFERENCE;
    const store = renderHook(() => useVerificationStore()).result;
    render(<BackendVerificationResults engagement={ENGAGEMENT} store={store.current} onSaveInputs={async () => {}} onError={() => false} />);
    await screen.findByRole("region", { name: "Reported vs recomputed" });
    expect(screen.queryByRole("region", { name: "Calculation by line" })).toBeNull();
  });
});
