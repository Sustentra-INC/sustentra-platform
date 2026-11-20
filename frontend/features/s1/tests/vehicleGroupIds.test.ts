/* @vitest-environment jsdom */
import { describe, expect, it } from "vitest";

import { assignDemoGroupIds, withDemoGroupIds } from "../demo-backend/groupIds";
import { draftsFrom, settingsFrom, withSavedIds } from "../components/VehicleGroupsFieldset";
import type { VehicleTypeOption } from "../api/recalculation";
import type { EngagementConfig, VehicleGroupSetting } from "../types";
import { adoptGroupIds } from "../utils/vehicleGroupIds";

const group = (label: string, over: Partial<VehicleGroupSetting> = {}): VehicleGroupSetting => ({
  fuel: "Diesel Fuel", vehicle_type: "Medium- and Heavy-Duty Vehicles", factor_fuel_type: "Diesel", on_road: true,
  distance: 1000, distance_unit: "mi", label, ...over,
});
const ids = (groups: VehicleGroupSetting[]) => groups.map((g) => g.group_id);
const TYPES: VehicleTypeOption[] = [
  { vehicle_type: "Medium- and Heavy-Duty Vehicles", fuel_type: "Diesel", on_road: true, by_model_year: false } as VehicleTypeOption,
];

describe("the demo gives vehicle groups ids like the server", () => {
  it("makes distinct ids for new groups, whatever their names", () => {
    const made = assignDemoGroupIds(["配送トラック", "配送トラック", "Lieferwagen – Zürich", ""].map((l) => group(l)), undefined);
    expect(new Set(ids(made)).size).toBe(4);
    expect(ids(made).every((id) => /^vgid-[a-f0-9]{12}$/.test(id ?? ""))).toBe(true); // never an old vg-<slug> anchor
    expect(ids(made).join(" ")).not.toMatch(/none|z-rich/);
  });

  it("keeps ids through a rename, a reorder and a removal, and never reuses a removed id", () => {
    const [a, b, c] = assignDemoGroupIds([group("Trucks"), group("Trucks"), group("Pickups", { fuel: "Motor Gasoline" })], undefined);
    expect(ids(assignDemoGroupIds([{ ...a, label: "Renamed 配送" }, b, c], [a, b, c]))).toEqual([a.group_id, b.group_id, c.group_id]);
    expect(ids(assignDemoGroupIds([c, a, b], [a, b, c]))).toEqual([c.group_id, a.group_id, b.group_id]);
    expect(ids(assignDemoGroupIds([b, c], [a, b, c]))).toEqual([b.group_id, c.group_id]);
    const again = assignDemoGroupIds([b, c, group("Trucks")], assignDemoGroupIds([b, c], [a, b, c]));
    expect(ids(again)).not.toContain(a.group_id);
  });

  it("does not trust an id the engagement never had, and matches unchanged groups for a client that sends none", () => {
    const [a] = assignDemoGroupIds([group("Trucks")], undefined);
    const out = assignDemoGroupIds([a, group("Vans", { group_id: "vg-forgedforged" })], [a]);
    expect(out[0].group_id).toBe(a.group_id);
    expect(out[1].group_id).not.toBe("vg-forgedforged");
    const bare = { ...a };
    delete bare.group_id;
    expect(assignDemoGroupIds([bare], [a])[0].group_id).toBe(a.group_id);
  });

  it("gives groups saved before ids their old anchor as the id", () => {
    const old = [group("配送トラック"), group("配送トラック")];
    expect(ids(assignDemoGroupIds(old, old))).toEqual(["vg-none", "vg-none-2"]);
  });

  it("gives the engagement's groups ids when it is saved", () => {
    const config = { recalculation: { vehicle_groups: [group("Trucks")] } } as unknown as EngagementConfig;
    const saved = withDemoGroupIds(config, null);
    expect(saved.recalculation?.vehicle_groups?.[0].group_id).toMatch(/^vgid-/);
    expect(withDemoGroupIds({} as EngagementConfig, null)).toEqual({});
  });
});

describe("the page keeps the ids the server gave", () => {
  it("sends a saved group's id back, and nothing for a new group", () => {
    const [saved] = [group("Trucks", { group_id: "vg-abc123def456" })];
    const drafts = draftsFrom([saved]);
    expect(drafts[0].groupId).toBe("vg-abc123def456");
    expect(settingsFrom(drafts, TYPES)[0].group_id).toBe("vg-abc123def456");
    const renamed = settingsFrom([{ ...drafts[0], label: "Delivery 配送" }], TYPES)[0];
    expect(renamed).toMatchObject({ group_id: "vg-abc123def456", label: "Delivery 配送" });
    expect("group_id" in settingsFrom([{ ...drafts[0], groupId: undefined }], TYPES)[0]).toBe(false);
  });

  it("shows a group added this session with the id the save answered, whatever the order", () => {
    const typed = draftsFrom([group("Trucks"), group("Vans")]);
    const savedAnswer = [group("Vans", { group_id: "vgid-bbbbbbbbbbbb" }), group("Trucks", { group_id: "vgid-aaaaaaaaaaaa" })];
    expect(withSavedIds(typed, savedAnswer).map((d) => d.groupId)).toEqual(["vgid-aaaaaaaaaaaa", "vgid-bbbbbbbbbbbb"]);
    const edited = [{ ...typed[0], label: "Edited" }, typed[1]];
    expect(withSavedIds(edited, savedAnswer).map((d) => d.groupId)).toEqual([undefined, "vgid-bbbbbbbbbbbb"]);
  });

  it("never gives two drafts the same id, after a removal and a same-named add", () => {
    // saved: Trucks (id A) and Vans (id B). Trucks is removed and a new Trucks added; the saved list is still the old one.
    const saved = [group("Trucks", { group_id: "vgid-aaaaaaaaaaaa" }), group("Vans", { group_id: "vgid-bbbbbbbbbbbb" })];
    const drafts = [...draftsFrom([saved[1]]), ...draftsFrom([group("Trucks")])];
    const shown = withSavedIds(drafts, saved, ["vgid-aaaaaaaaaaaa"]); // A was removed in these drafts
    expect(shown.map((d) => d.groupId)).toEqual(["vgid-bbbbbbbbbbbb", undefined]); // the new group does not inherit A
    const ids = withSavedIds(drafts, saved).map((d) => d.groupId).filter(Boolean);
    expect(new Set(ids).size).toBe(ids.length); // and without the list of removed ones, still no id twice
    // two identical new drafts take two different saved ids, never one id twice
    const twins = draftsFrom([group("Vans"), group("Vans")]);
    const both = [group("Vans", { group_id: "vgid-111111111111" }), group("Vans", { group_id: "vgid-222222222222" })];
    expect(withSavedIds(twins, both).map((d) => d.groupId)).toEqual(["vgid-111111111111", "vgid-222222222222"]);
    expect(withSavedIds(twins, [both[0]]).map((d) => d.groupId)).toEqual(["vgid-111111111111", undefined]);
  });

  it("does not match a group on its place in the list", () => {
    const typed = draftsFrom([group("Trucks", { distance: 5 })]);
    expect(withSavedIds(typed, [group("Trucks", { distance: 6, group_id: "vgid-aaaaaaaaaaaa" })])).toBe(typed); // other figures
    expect(withSavedIds(typed, [group("Vans", { group_id: "vgid-bbbbbbbbbbbb" }), group("Trucks", { distance: 5, group_id: "vgid-cccccccccccc" })])[0].groupId).toBe("vgid-cccccccccccc");
  });

  it("adopts the saved ids into the engagement without touching groups that have one or were edited since", () => {
    const config = { recalculation: { vehicle_groups: [group("Trucks"), group("Trucks"), group("Vans", { group_id: "vg-kept00000000" }), group("Edited later")] } } as unknown as EngagementConfig;
    const saved = [group("Trucks", { group_id: "vg-first0000000" }), group("Trucks", { group_id: "vg-second000000" }),
      group("Vans", { group_id: "vg-kept00000000" }), group("Edited", { group_id: "vg-other0000000" })];
    const out = adoptGroupIds(config, saved);
    expect(out.recalculation?.vehicle_groups?.map((g) => g.group_id)).toEqual(["vg-first0000000", "vg-second000000", "vg-kept00000000", undefined]);
    expect(adoptGroupIds(out, saved).recalculation?.vehicle_groups).toEqual(out.recalculation?.vehicle_groups);
    expect(adoptGroupIds({} as EngagementConfig, saved)).toEqual({});
  });
});

describe("the demo matches groups like the server when no ids are sent", () => {
  const bare = (g: VehicleGroupSetting) => {
    const { group_id: _id, ...rest } = g;
    void _id;
    return rest;
  };

  it("keeps same-named groups' ids when they are reordered", () => {
    const stored = assignDemoGroupIds([group("Trucks", { distance: 1000 }), group("Trucks", { distance: 5000 })], undefined);
    const out = assignDemoGroupIds(stored.map(bare).reverse(), stored);
    expect(out.map((g) => [g.distance, g.group_id])).toEqual([[5000, stored[1].group_id], [1000, stored[0].group_id]]);
  });

  it("never hands a group the id of the group whose name it took in a rename plus a reorder", () => {
    const [trucks, vans] = assignDemoGroupIds([group("Trucks", { distance: 1 }), group("Vans", { distance: 2 })], undefined);
    const out = assignDemoGroupIds([{ ...bare(vans), label: "Lorries" }, { ...bare(trucks), label: "Vans" }], [trucks, vans]);
    expect(out[1].group_id).toBe(trucks.group_id);
    expect([trucks.group_id, vans.group_id]).not.toContain(out[0].group_id);
  });

  it("moves an old anchor on when an id already uses it, like the server", () => {
    const old = [group("Trucks"), { ...group("Trucks"), group_id: "vg-trucks" }];
    const out = assignDemoGroupIds(old.map((g, i) => (i === 0 ? { ...g, group_id: "vg-trucks" } : g)), old);
    expect(out[0].group_id).toBe("vg-trucks");
  });
});
