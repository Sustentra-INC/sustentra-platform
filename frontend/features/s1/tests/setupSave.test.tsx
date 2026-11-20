/* @vitest-environment jsdom */
import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { VehicleTypeOption } from "../api/recalculation";
import { setupSavePayload } from "../api/engagements";
import { SetupScreen } from "../components/SetupScreen";
import type { SetupSaveInfo } from "../components/SetupSaveStatus";
import { forgetKeptVehicleDrafts } from "../components/SetupVehicleGroups";
import { draftsFrom, settingsFrom } from "../components/VehicleGroupsFieldset";
import { engagementConfig } from "../fixtures/engagementConfig";
import type { EngagementConfig, VehicleGroupSetting } from "../types";

const TYPES: VehicleTypeOption[] = [
  { vehicle_type: "Medium- and Heavy-Duty Vehicles", fuel_type: "Diesel", on_road: true, by_model_year: true, first_model_year: 2007, last_model_year: 2022 },
  { vehicle_type: "Light-Duty Vehicles", fuel_type: "Gasoline", on_road: true, by_model_year: false, first_model_year: null, last_model_year: null },
  { vehicle_type: "Industrial/Commercial Equipment", fuel_type: "LPG", on_road: false, by_model_year: false, first_model_year: null, last_model_year: null },
];
const REFERENCE = { fuels: ["Diesel Fuel", "Motor Gasoline", "Propane"], types: TYPES };

const saved = (over: Partial<VehicleGroupSetting> = {}): VehicleGroupSetting => ({
  group_id: "vgid-aaaaaaaaaaaa",
  fuel: "Diesel Fuel",
  vehicle_type: "Medium- and Heavy-Duty Vehicles",
  factor_fuel_type: "Diesel",
  on_road: true,
  model_year: 2015,
  distance: 1000.5,
  distance_unit: "km",
  label: "Delivery trucks",
  ...over,
});

function Harness({
  groups = [],
  onChange = vi.fn(),
  save,
  team,
}: {
  groups?: VehicleGroupSetting[];
  onChange?: (next: EngagementConfig) => void;
  save?: SetupSaveInfo;
  team?: EngagementConfig["engagementTeam"];
}) {
  const [engagement, setEngagement] = useState<EngagementConfig>({
    ...engagementConfig,
    ...(team ? { engagementTeam: team } : {}),
    recalculation: { vehicle_groups: groups },
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
      vehicleReference={REFERENCE}
      save={save}
    />
  );
}

const last = (onChange: ReturnType<typeof vi.fn>) => onChange.mock.calls.at(-1)?.[0] as EngagementConfig;

beforeEach(() => forgetKeptVehicleDrafts());

describe("Setup save: blank vehicle rows", () => {
  it("ignores two untouched rows: no duplicate-name message, no problem, and a facility edit still saves", () => {
    const onChange = vi.fn();
    render(<Harness onChange={onChange} />);
    fireEvent.click(screen.getByRole("button", { name: "Add vehicle group" }));
    fireEvent.click(screen.getByRole("button", { name: "Add vehicle group" }));
    expect(screen.queryByText(/More than one group/)).toBeNull();
    expect(screen.queryByText(/Not saved/)).toBeNull();
    expect(onChange).not.toHaveBeenCalled(); // nothing to save yet, nothing blocked

    fireEvent.change(screen.getAllByLabelText("Facility name")[0], { target: { value: "Kent Plant" } });
    expect(last(onChange).facilities[0].name).toBe("Kent Plant");
    expect(last(onChange).recalculation?.vehicle_groups).toEqual([]);
  });

  it("never shows an empty name in the duplicate message", () => {
    render(<Harness />);
    fireEvent.click(screen.getByRole("button", { name: "Add vehicle group" }));
    fireEvent.click(screen.getByRole("button", { name: "Add vehicle group" }));
    // Both rows are touched (a distance) but unnamed and untyped: they have no name to compare.
    for (const n of [1, 2]) {
      fireEvent.change(within(screen.getByRole("group", { name: `Vehicle group ${n}` })).getByLabelText("Distance driven"), { target: { value: "5" } });
    }
    expect(screen.queryByText(/More than one group is called/)).toBeNull();
    expect(document.body.textContent).not.toContain(" ()");
  });
});

describe("Setup save: sections save independently", () => {
  it("saves facilities and account numbers while a vehicle group is incomplete", () => {
    const onChange = vi.fn();
    render(<Harness onChange={onChange} />);
    fireEvent.click(screen.getByRole("button", { name: "Add vehicle group" }));
    fireEvent.change(within(screen.getByRole("group", { name: "Vehicle group 1" })).getByLabelText("Group"), { target: { value: "Vans" } });
    expect(screen.getByText(/1 vehicle group is unfinished/)).toBeInTheDocument();

    const account = screen.getAllByLabelText("Add account number")[0];
    fireEvent.change(account, { target: { value: "ACC-1001" } });
    fireEvent.keyDown(account, { key: "Enter" });
    expect(last(onChange).facilities[0].accountNumbers).toContain("ACC-1001");
    expect(last(onChange).recalculation?.vehicle_groups).toEqual([]); // the unfinished group is left out, not blocking
  });

  it("keeps a saved group's last complete settings while it is half edited", () => {
    const onChange = vi.fn();
    render(<Harness onChange={onChange} groups={[saved()]} />);
    const g = screen.getByRole("group", { name: "Vehicle group 1" });
    fireEvent.change(within(g).getByLabelText("Distance driven"), { target: { value: "" } });
    expect(screen.getByText(/1 vehicle group is unfinished/)).toBeInTheDocument();
    fireEvent.change(screen.getAllByLabelText("Facility name")[0], { target: { value: "Renamed" } });
    expect(last(onChange).recalculation?.vehicle_groups).toEqual([saved()]); // not dropped, not changed
  });

  it("holds back only a reporting period that ends before it starts", () => {
    const config: EngagementConfig = { ...engagementConfig, reportingPeriod: { start: "2025-12-31", end: "2025-01-01" }, clientName: "New name" };
    const server: EngagementConfig = { ...engagementConfig, reportingPeriod: { start: "2025-01-01", end: "2025-12-31" } };
    const { payload, problems } = setupSavePayload(config, server);
    expect(payload.clientName).toBe("New name");
    expect(payload.reportingPeriod).toEqual(server.reportingPeriod);
    expect(problems.company).toMatch(/ends before it starts/);
    expect(setupSavePayload(server, server).problems).toEqual({});
  });
});

describe("Setup save: vehicle groups round-trip", () => {
  it("settingsFrom(draftsFrom(x)) returns every field, including km, exactly", () => {
    const groups = [
      saved(),
      saved({ group_id: "vgid-bbbbbbbbbbbb", label: "Yard", on_road: false, vehicle_type: "Industrial/Commercial Equipment", factor_fuel_type: "LPG", fuel: "Propane", distance: undefined, distance_unit: undefined, model_year: undefined, fuel_quantity: 12.25, fuel_unit: "L" }),
      saved({ group_id: "vgid-cccccccccccc", label: undefined, vehicle_type: "Light-Duty Vehicles", factor_fuel_type: "Gasoline", fuel: "Motor Gasoline", model_year: undefined, distance: 0, distance_unit: "mi" }),
    ].map((g) => JSON.parse(JSON.stringify(g)) as VehicleGroupSetting);
    expect(settingsFrom(draftsFrom(groups), TYPES)).toEqual(groups);
    // Before the vehicle types have loaded, a saved group still comes back whole.
    expect(settingsFrom(draftsFrom(groups), [])).toEqual(groups);
  });

  it("save, reload from the API answer, and compare: nothing changes", () => {
    const onChange = vi.fn();
    const { unmount } = render(<Harness onChange={onChange} groups={[saved()]} />);
    fireEvent.change(screen.getByLabelText("Group"), { target: { value: "Delivery trucks (north)" } });
    const afterSave = JSON.parse(JSON.stringify(last(onChange).recalculation?.vehicle_groups)) as VehicleGroupSetting[];
    expect(afterSave).toEqual([saved({ label: "Delivery trucks (north)" })]);
    unmount();

    // "Reload": a fresh page built only from what the API returned.
    forgetKeptVehicleDrafts();
    const onChange2 = vi.fn();
    render(<Harness onChange={onChange2} groups={afterSave} />);
    const g = screen.getByRole("group", { name: "Vehicle group 1" });
    expect(within(g).getByLabelText("Group")).toHaveValue("Delivery trucks (north)");
    expect(within(g).getByLabelText("Distance driven")).toHaveValue("1000.5");
    expect(within(g).getByLabelText("Distance unit")).toHaveValue("km");
    expect(within(g).getByLabelText("Model year")).toHaveValue("2015");
    fireEvent.change(within(g).getByLabelText("Distance unit"), { target: { value: "mi" } });
    fireEvent.change(within(g).getByLabelText("Distance unit"), { target: { value: "km" } });
    expect(last(onChange2).recalculation?.vehicle_groups).toEqual(afterSave);
  });

  it("a group still being filled in is there when the user comes back to Setup", () => {
    const { unmount } = render(<Harness groups={[saved()]} />);
    fireEvent.click(screen.getByRole("button", { name: "Add vehicle group" }));
    fireEvent.change(within(screen.getByRole("group", { name: "Vehicle group 2" })).getByLabelText("Group"), { target: { value: "Vans" } });
    unmount(); // the user goes to another page
    render(<Harness groups={[saved()]} />);
    expect(within(screen.getByRole("group", { name: "Vehicle group 2" })).getByLabelText("Group")).toHaveValue("Vans");
  });
});

describe("Setup: inputs keep focus while typing", () => {
  it("the engagement team's login keeps focus across several keystrokes", async () => {
    const user = userEvent.setup();
    render(<Harness team={[{ name: "Ada", login: "ada@x.org" }, { name: "Bo", login: "bo@x.org" }]} />);
    const login = screen.getAllByLabelText("Login")[0];
    await user.click(login);
    await user.type(login, "abc");
    expect(screen.getAllByLabelText("Login")[0]).toBe(login); // the same element, never re-created
    expect(login).toHaveFocus();
    expect(login).toHaveValue("ada@x.orgabc");
  });

  it("the team's name, a facility's name and a vehicle group's name keep focus too", async () => {
    const user = userEvent.setup();
    render(<Harness team={[{ name: "Ada", login: "ada@x.org" }]} groups={[saved()]} />);
    for (const input of [
      within(screen.getByText("Engagement team").closest(".s1-setup-card") as HTMLElement).getByLabelText("Name"),
      screen.getAllByLabelText("Facility name")[0],
      screen.getByLabelText("Group"),
    ]) {
      await user.click(input);
      await user.type(input, "xyz");
      expect(input).toHaveFocus();
      expect(input.isConnected).toBe(true); // the element typed into is still the one on the page
    }
  });

  it("a removed member does not hand its row to the next", () => {
    render(<Harness team={[{ name: "Ada", login: "ada@x.org" }, { name: "Bo", login: "bo@x.org" }]} />);
    fireEvent.click(screen.getByRole("button", { name: "Remove Ada" }));
    expect(screen.getAllByLabelText("Login")).toHaveLength(1);
    expect(screen.getByLabelText("Login")).toHaveValue("bo@x.org");
  });
});

describe("Setup save: the save state", () => {
  const info = (over: Partial<SetupSaveInfo> = {}): SetupSaveInfo => ({ state: "idle", savedAt: null, problems: {}, message: null, onSaveNow: vi.fn(), ...over });

  it("says nothing before a change, and nothing at all outside backend mode", () => {
    const { unmount } = render(<Harness save={info()} />);
    expect(screen.queryByText(/Saving…|Saved ·|Not saved/)).toBeNull();
    expect(screen.getByRole("button", { name: "Save changes" })).toBeInTheDocument();
    unmount();
    render(<Harness />);
    expect(screen.queryByRole("button", { name: "Save changes" })).toBeNull();
  });

  it("shows Saving… at the top and on every section", () => {
    render(<Harness save={info({ state: "saving" })} />);
    expect(screen.getAllByText("Saving…")).toHaveLength(5); // top, details, facilities, vehicle groups, team
    expect(screen.getByRole("button", { name: "Save changes" })).toBeDisabled();
  });

  it("shows Saved with the time", () => {
    render(<Harness save={info({ state: "saved", savedAt: new Date(2026, 10, 20, 14, 41) })} />);
    expect(screen.getAllByText("Saved · 2:41 PM")).toHaveLength(5);
  });

  it("shows the reason on the section that failed, with Retry, while the others say Saved", () => {
    const onSaveNow = vi.fn();
    render(
      <Harness
        save={info({ state: "saved", savedAt: new Date(2026, 10, 20, 9, 5), problems: { company: "The reporting period ends before it starts." }, onSaveNow })}
      />
    );
    expect(screen.getAllByText(/Not saved: The reporting period ends before it starts\./)).toHaveLength(2); // top + details
    expect(screen.getAllByText("Saved · 9:05 AM")).toHaveLength(3);
    fireEvent.click(screen.getAllByRole("button", { name: "Retry" })[0]);
    expect(onSaveNow).toHaveBeenCalledTimes(1);
  });

  it("shows an unfinished vehicle group at the top and on its section", () => {
    render(<Harness save={info({ state: "saved", savedAt: new Date(2026, 10, 20, 14, 41) })} />);
    fireEvent.click(screen.getByRole("button", { name: "Add vehicle group" }));
    fireEvent.change(screen.getByLabelText("Group"), { target: { value: "Vans" } });
    expect(screen.getAllByText(/Not saved: 1 vehicle group is unfinished/)).toHaveLength(2);
  });

  it("Save changes calls the save at once", () => {
    const onSaveNow = vi.fn();
    render(<Harness save={info({ onSaveNow })} />);
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
    expect(onSaveNow).toHaveBeenCalledTimes(1);
  });
});
