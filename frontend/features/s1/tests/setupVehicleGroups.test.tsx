/* @vitest-environment jsdom */
import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { useState } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { VehicleTypeOption } from "../api/recalculation";
import { SetupScreen } from "../components/SetupScreen";
import { forgetKeptVehicleDrafts } from "../components/SetupVehicleGroups";
import { engagementConfig } from "../fixtures/engagementConfig";
import type { EngagementConfig, VehicleGroupSetting } from "../types";

const TYPES: VehicleTypeOption[] = [
  { vehicle_type: "Medium- and Heavy-Duty Vehicles", fuel_type: "Diesel", on_road: true, by_model_year: true, first_model_year: 2007, last_model_year: 2022 },
  { vehicle_type: "Industrial/Commercial Equipment", fuel_type: "LPG", on_road: false, by_model_year: false, first_model_year: null, last_model_year: null },
];
const REFERENCE = { fuels: ["Diesel Fuel", "Motor Gasoline"], types: TYPES };

const group = (label: string, over: Partial<VehicleGroupSetting> = {}): VehicleGroupSetting => ({
  fuel: "Diesel Fuel",
  vehicle_type: "Medium- and Heavy-Duty Vehicles",
  factor_fuel_type: "Diesel",
  on_road: true,
  model_year: 2015,
  distance: 1000,
  distance_unit: "mi",
  label,
  ...over,
});

function Harness({
  groups = [],
  onChange = vi.fn(),
  reference = REFERENCE,
}: {
  groups?: VehicleGroupSetting[];
  onChange?: (next: EngagementConfig) => void;
  reference?: typeof REFERENCE | null;
}) {
  const [engagement, setEngagement] = useState<EngagementConfig>({
    ...engagementConfig,
    recalculation: { grid_regions: { "Kent Cannery": "NWPP" }, vehicle_groups: groups },
  });
  return (
    <SetupScreen
      engagement={engagement}
      onChange={(next) => {
        setEngagement(next);
        onChange(next);
      }}
      inScopeFields={[]}
      onInScopeChange={vi.fn()}
      vehicleReference={reference ?? undefined}
    />
  );
}

const lastGroups = (onChange: ReturnType<typeof vi.fn>) =>
  (onChange.mock.calls.at(-1)?.[0] as EngagementConfig | undefined)?.recalculation?.vehicle_groups;

function fillFirstGroup(label: string) {
  const g = screen.getByRole("group", { name: "Vehicle group 1" });
  fireEvent.change(within(g).getByLabelText("Group"), { target: { value: label } });
  fireEvent.change(within(g).getByLabelText("Fuel (from the evidence)"), { target: { value: "Diesel Fuel" } });
  fireEvent.change(within(g).getByLabelText("Vehicle type (EPA)"), { target: { value: "Medium- and Heavy-Duty Vehicles" } });
  return g;
}

function fillFirstGroupAt(n: number, label: string) {
  const g = screen.getByRole("group", { name: `Vehicle group ${n}` });
  fireEvent.change(within(g).getByLabelText("Group"), { target: { value: label } });
}

describe("Setup: vehicle groups", () => {
  beforeEach(() => forgetKeptVehicleDrafts());

  it("shows the section only when the fuels and vehicle types are known", () => {
    const { unmount } = render(<Harness reference={null} />);
    expect(screen.queryByRole("heading", { name: /Vehicle groups/ })).toBeNull();
    unmount();
    render(<Harness />);
    expect(screen.getByRole("heading", { name: /Vehicle groups/ })).toBeInTheDocument();
  });

  it("loads the groups already saved on the engagement (the same data as Recalculation inputs)", () => {
    render(<Harness groups={[group("Delivery trucks"), group("Yard equipment")]} />);
    expect(within(screen.getByRole("group", { name: "Vehicle group 1" })).getByLabelText("Group")).toHaveValue("Delivery trucks");
    expect(within(screen.getByRole("group", { name: "Vehicle group 2" })).getByLabelText("Group")).toHaveValue("Yard equipment");
  });

  it("does not save a group until it is complete, then saves it beside the other recalculation inputs", () => {
    const onChange = vi.fn();
    render(<Harness onChange={onChange} />);
    fireEvent.click(screen.getByRole("button", { name: "Add vehicle group" }));
    const g = fillFirstGroup("Delivery trucks");
    expect(screen.getByText(/Not saved: 1 vehicle group is unfinished\. Finish or remove it/)).toBeInTheDocument();
    expect(onChange).not.toHaveBeenCalled();
    fireEvent.change(within(g).getByLabelText("Model year"), { target: { value: "2015" } });
    fireEvent.change(within(g).getByLabelText("Distance driven"), { target: { value: "12000" } });
    expect(screen.queryByText(/Not saved/)).toBeNull();
    const saved = onChange.mock.calls.at(-1)?.[0] as EngagementConfig;
    expect(saved.recalculation?.grid_regions).toEqual({ "Kent Cannery": "NWPP" }); // nothing else is lost
    expect(saved.recalculation?.vehicle_groups).toEqual([
      { fuel: "Diesel Fuel", vehicle_type: "Medium- and Heavy-Duty Vehicles", factor_fuel_type: "Diesel", on_road: true, label: "Delivery trucks", distance: 12000, distance_unit: "mi", model_year: 2015 },
    ]);
  });

  it("keeps a non-ASCII or CJK name as typed", () => {
    const onChange = vi.fn();
    render(<Harness onChange={onChange} groups={[group("Delivery trucks")]} />);
    for (const name of ["Lieferwagen – Zürich", "配送トラック"]) {
      fireEvent.change(within(screen.getByRole("group", { name: "Vehicle group 1" })).getByLabelText("Group"), { target: { value: name } });
      expect(lastGroups(onChange)?.[0].label).toBe(name);
    }
  });

  it("says when two groups share a name, however they are spaced or cased, and stops saying it once they differ", () => {
    render(<Harness groups={[group("Delivery  trucks"), group("delivery trucks"), group("Yard equipment")]} />);
    expect(screen.getAllByText(/More than one group is called/)).toHaveLength(1);
    expect(screen.getByText(/More than one group is called "Delivery {1,2}trucks"/)).toBeInTheDocument();
    fireEvent.change(within(screen.getByRole("group", { name: "Vehicle group 2" })).getByLabelText("Group"), { target: { value: "Vans" } });
    expect(screen.queryByText(/More than one group is called/)).toBeNull();
  });

  it("asks before removing, saying the documents fall to Unassigned supporting evidence, and removes only on confirm", () => {
    const onChange = vi.fn();
    render(<Harness onChange={onChange} groups={[group("Delivery trucks"), group("Yard equipment")]} />);
    const first = screen.getByRole("group", { name: "Vehicle group 1" });
    fireEvent.click(within(first).getByRole("button", { name: "Remove group" }));
    expect(within(first).getByRole("alert")).toHaveTextContent("move to Unassigned supporting evidence");
    expect(onChange).not.toHaveBeenCalled();
    fireEvent.click(within(first).getByRole("button", { name: "Keep group" }));
    expect(onChange).not.toHaveBeenCalled();
    expect(screen.getAllByRole("group", { name: /Vehicle group \d/ })).toHaveLength(2);
    fireEvent.click(within(screen.getByRole("group", { name: "Vehicle group 1" })).getByRole("button", { name: "Remove group" }));
    fireEvent.click(screen.getByRole("button", { name: "Confirm remove" }));
    expect(lastGroups(onChange)?.map((x) => x.label)).toEqual(["Yard equipment"]);
  });

  it("can remove the last group, saving an empty list", () => {
    const onChange = vi.fn();
    render(<Harness onChange={onChange} groups={[group("Delivery trucks")]} />);
    fireEvent.click(screen.getByRole("button", { name: "Remove group" }));
    fireEvent.click(screen.getByRole("button", { name: "Confirm remove" }));
    expect(lastGroups(onChange)).toEqual([]);
  });

  it("removing the unfinished group lets the rest save", () => {
    const onChange = vi.fn();
    render(<Harness onChange={onChange} groups={[group("Delivery trucks")]} />);
    fireEvent.click(screen.getByRole("button", { name: "Add vehicle group" }));
    fillFirstGroupAt(2, "Vans");
    expect(screen.getByText(/Not saved: 1 vehicle group is unfinished/)).toBeInTheDocument();
    fireEvent.click(within(screen.getByRole("group", { name: "Vehicle group 2" })).getByRole("button", { name: "Remove group" }));
    fireEvent.click(screen.getByRole("button", { name: "Confirm remove" }));
    expect(screen.queryByText(/Not saved/)).toBeNull();
    expect(onChange).not.toHaveBeenCalled(); // the saved group never changed: nothing to save
    expect(screen.getAllByRole("group", { name: /Vehicle group \d/ })).toHaveLength(1);
  });

  it("lists 50 groups, and stops adding at the API's limit of 200", () => {
    const fifty = Array.from({ length: 50 }, (_, i) => group(`Fleet ${i + 1}`));
    const { unmount } = render(<Harness groups={fifty} />);
    expect(screen.getAllByRole("group", { name: /Vehicle group \d/ })).toHaveLength(50);
    expect(screen.getByRole("button", { name: "Add vehicle group" })).toBeEnabled();
    unmount();
    render(<Harness groups={Array.from({ length: 200 }, (_, i) => group(`Fleet ${i + 1}`))} />);
    expect(screen.getByRole("button", { name: "Add vehicle group" })).toBeDisabled();
    expect(screen.getByText("A company can have at most 200 vehicle groups.")).toBeInTheDocument();
  }, 30_000); // renders 250 groups inside the whole Setup screen; slow on a busy machine

  it("offers only the fuels the recalculation accepts", () => {
    render(<Harness groups={[group("Delivery trucks")]} />);
    const select = within(screen.getByRole("group", { name: "Vehicle group 1" })).getByLabelText("Fuel (from the evidence)") as HTMLSelectElement;
    expect(Array.from(select.options).map((o) => o.value)).toEqual(["", "Diesel Fuel", "Motor Gasoline"]);
  });
});
