"use client";

import { useState, type ReactNode } from "react";

import type { RecalcNeedsInput, VehicleTypeOption } from "../api/recalculation";
import type { VehicleGroupSetting } from "../types";

/**
 * Vehicle groups for mobile CH₄ and N₂O (workbook Eq 4 / Eq 5). The evidence gives fuel
 * per fuel type; the CH₄ and N₂O factors also depend on the vehicle, so the reviewer says
 * which vehicles used each fuel: on-road groups by distance (and model year where the
 * EPA factor depends on it), non-road groups by the fuel they used.
 */
export interface VehicleGroupDraft {
  /** A stable id for the row on this page (never saved): React keys the row by it, so typing keeps focus. */
  uid?: string;
  /** The server's id for a saved group (absent on a new one): sent back so a rename keeps the group's line. */
  groupId?: string;
  label: string;
  fuel: string;
  onRoad: boolean;
  vehicleType: string;
  factorFuel: string;
  modelYear: string;
  distance: string;
  distanceUnit: "mi" | "km";
  fuelQuantity: string;
  fuelUnit: "gal" | "L";
}

let draftSeq = 0;
/** A new row id: unique on this page. */
export function newDraftUid(): string {
  draftSeq += 1;
  return `vg-${draftSeq}`;
}

export function draftsFrom(groups: VehicleGroupSetting[] | undefined): VehicleGroupDraft[] {
  return (groups ?? []).map((g) => ({
    uid: newDraftUid(),
    ...(g.group_id ? { groupId: g.group_id } : {}),
    label: g.label ?? "",
    fuel: g.fuel,
    onRoad: g.on_road,
    vehicleType: g.vehicle_type,
    factorFuel: g.factor_fuel_type,
    modelYear: g.model_year != null ? String(g.model_year) : "",
    distance: g.distance != null ? String(g.distance) : "",
    distanceUnit: g.distance_unit ?? "mi",
    fuelQuantity: g.fuel_quantity != null ? String(g.fuel_quantity) : "",
    fuelUnit: g.fuel_unit ?? "gal",
  }));
}

const numberOrNone = (text: string): number | undefined => (text.trim() === "" ? undefined : Number(text));

/** Whether a draft is the saved group: the same in every field the group saves. */
function draftIsSaved(d: VehicleGroupDraft, s: VehicleGroupSetting): boolean {
  if (s.fuel !== d.fuel || s.vehicle_type !== d.vehicleType || s.factor_fuel_type !== d.factorFuel || s.on_road !== d.onRoad) return false;
  if ((s.label ?? "") !== d.label.trim()) return false;
  return d.onRoad
    ? numberOrNone(d.distance) === s.distance && (s.distance_unit ?? "mi") === d.distanceUnit && numberOrNone(d.modelYear) === s.model_year
    : numberOrNone(d.fuelQuantity) === s.fuel_quantity && (s.fuel_unit ?? "gal") === d.fuelUnit;
}

/**
 * The ids the server gave groups added in this session. A draft has no id until the save answers. It takes the id of
 * a saved group that is the same group in every field, whatever the order, and only an id no other draft has and
 * that did not belong to a group removed in these drafts (`removed`): so two drafts never share an id, and a new group
 * never inherits the line of one that was removed. Returns the drafts as they were when nothing changed.
 */
export function withSavedIds(
  drafts: VehicleGroupDraft[],
  saved: VehicleGroupSetting[] | undefined,
  removed: readonly string[] = []
): VehicleGroupDraft[] {
  if (!saved) return drafts;
  const taken = new Set([...drafts.map((d) => d.groupId).filter((id): id is string => Boolean(id)), ...removed]);
  let changed = false;
  const next = drafts.map((d) => {
    if (d.groupId) return d;
    const match = saved.find((s) => s.group_id && !taken.has(s.group_id) && draftIsSaved(d, s));
    if (!match?.group_id) return d;
    taken.add(match.group_id);
    changed = true;
    return { ...d, groupId: match.group_id };
  });
  return changed ? next : drafts;
}

/** A row nobody has touched: nothing typed or chosen (a fuel the page filled in alone does not count). */
export function isBlankDraft(d: VehicleGroupDraft, fuels: string[] = []): boolean {
  const defaultFuel = fuels.length === 1 ? fuels[0] : "";
  return (
    !d.groupId &&
    !d.label.trim() &&
    !d.vehicleType &&
    !d.factorFuel &&
    !d.modelYear.trim() &&
    !d.distance.trim() &&
    !d.fuelQuantity.trim() &&
    (d.fuel === "" || d.fuel === defaultFuel)
  );
}

function optionFor(types: VehicleTypeOption[], draft: VehicleGroupDraft): VehicleTypeOption | undefined {
  return types.find(
    (t) => t.on_road === draft.onRoad && t.vehicle_type === draft.vehicleType && t.fuel_type === draft.factorFuel
  );
}

const isNumber = (text: string) => text.trim() !== "" && Number.isFinite(Number(text)) && Number(text) >= 0;

/** What is wrong with a group, in words, or null when it can be saved. */
export function draftProblem(draft: VehicleGroupDraft, types: VehicleTypeOption[]): string | null {
  if (!draft.fuel || !draft.vehicleType || !draft.factorFuel) return "Choose the fuel, vehicle type and EPA fuel.";
  if (draft.label.trim().length > 200) return "The group name is at most 200 characters.";
  const option = optionFor(types, draft);
  if (draft.onRoad) {
    if (!isNumber(draft.distance)) return "On-road groups need the distance driven.";
    const year = Number(draft.modelYear.trim());
    if (option?.by_model_year && !(/^\d{4}$/.test(draft.modelYear.trim()) && year >= 1900 && year <= 2100)) {
      return "This vehicle type needs a model year (four digits).";
    }
  } else if (draft.fuelQuantity.trim() && !isNumber(draft.fuelQuantity)) {
    return "Fuel used must be a number.";
  }
  return null;
}

/** Whether the group's model year is saved: a real year, on a type that uses one (or one not in the loaded list, so a
 *  saved group comes back as it was even before the vehicle types have loaded). */
function keepsModelYear(d: VehicleGroupDraft, types: VehicleTypeOption[]): boolean {
  const text = d.modelYear.trim();
  if (!/^\d{4}$/.test(text) || Number(text) < 1900 || Number(text) > 2100) return false;
  const option = optionFor(types, d);
  return option === undefined || option.by_model_year;
}

/** The groups as saved. A model year is sent only where the EPA factor uses one, so a year typed before switching to
 *  a type without one (hidden from then on) is not sent. */
export function settingsFrom(drafts: VehicleGroupDraft[], types: VehicleTypeOption[]): VehicleGroupSetting[] {
  return drafts.map((d) => ({
    ...(d.groupId ? { group_id: d.groupId } : {}),
    fuel: d.fuel,
    vehicle_type: d.vehicleType,
    factor_fuel_type: d.factorFuel,
    on_road: d.onRoad,
    ...(d.label.trim() ? { label: d.label.trim() } : {}),
    ...(d.onRoad
      ? {
          distance: Number(d.distance),
          distance_unit: d.distanceUnit,
          ...(keepsModelYear(d, types) ? { model_year: Number(d.modelYear) } : {}),
        }
      : d.fuelQuantity.trim()
        ? { fuel_quantity: Number(d.fuelQuantity), fuel_unit: d.fuelUnit }
        : {}),
  }));
}

export function VehicleGroupsFieldset({
  drafts,
  fuels,
  types,
  asks,
  onChange,
  confirmRemove,
  maxGroups,
  heading = true,
}: {
  drafts: VehicleGroupDraft[];
  /** EPA Table 2 fuels with reviewed mobile records (each a recalculated line). */
  fuels: string[];
  types: VehicleTypeOption[];
  asks: RecalcNeedsInput[];
  onChange: (next: VehicleGroupDraft[]) => void;
  /** When set, removing a group first asks, saying this. */
  confirmRemove?: string;
  /** The most groups the API takes; adding stops there. */
  maxGroups?: number;
  /** False where the page already titles the section. */
  heading?: boolean;
}) {
  const [removing, setRemoving] = useState<number | null>(null);
  const update = (index: number, patch: Partial<VehicleGroupDraft>) =>
    onChange(drafts.map((d, i) => (i === index ? { ...d, ...patch } : d)));
  const vehicleTypes = (onRoad: boolean) =>
    Array.from(new Set(types.filter((t) => t.on_road === onRoad).map((t) => t.vehicle_type)));
  const factorFuels = (onRoad: boolean, vehicleType: string) =>
    types.filter((t) => t.on_road === onRoad && t.vehicle_type === vehicleType).map((t) => t.fuel_type);

  return (
    <Wrap heading={heading}>
      <p className="s1-muted s1-rc__hint">
        CH₄ and N₂O depend on the vehicle as well as the fuel. Say which vehicles used each fuel: on-road by
        distance driven, non-road (forklifts, equipment, boats) by the fuel they used.
      </p>
      {asks.map((a) => (
        <p key={a.key} className="s1-rc__error">
          {a.message}
        </p>
      ))}
      {drafts.map((draft, index) => {
        const problem = isBlankDraft(draft, fuels) ? null : draftProblem(draft, types);
        const option = optionFor(types, draft);
        const fuelChoices = factorFuels(draft.onRoad, draft.vehicleType);
        return (
          <div key={draft.uid ?? index} className="s1-rc__vg" role="group" aria-label={`Vehicle group ${index + 1}`}>
            <label className="s1-rc__field">
              <span>Group</span>
              <input
                placeholder="e.g. 4 delivery trucks"
                value={draft.label}
                onChange={(e) => update(index, { label: e.target.value })}
              />
            </label>
            <label className="s1-rc__field">
              <span>Fuel (from the evidence)</span>
              <select value={draft.fuel} onChange={(e) => update(index, { fuel: e.target.value })}>
                <option value="">Choose the fuel</option>
                {Array.from(new Set([...fuels, draft.fuel].filter(Boolean))).map((f) => (
                  <option key={f} value={f}>
                    {f}
                  </option>
                ))}
              </select>
            </label>
            <label className="s1-rc__field">
              <span>Road</span>
              <select
                value={draft.onRoad ? "on" : "off"}
                onChange={(e) => update(index, { onRoad: e.target.value === "on", vehicleType: "", factorFuel: "", modelYear: "" })}
              >
                <option value="on">On-road (by distance)</option>
                <option value="off">Non-road (by fuel used)</option>
              </select>
            </label>
            <label className="s1-rc__field">
              <span>Vehicle type (EPA)</span>
              <select
                value={draft.vehicleType}
                onChange={(e) => {
                  const choices = factorFuels(draft.onRoad, e.target.value);
                  update(index, { vehicleType: e.target.value, factorFuel: choices.length === 1 ? choices[0] : "", modelYear: "" });
                }}
              >
                <option value="">Choose a vehicle type</option>
                {vehicleTypes(draft.onRoad).map((v) => (
                  <option key={v} value={v}>
                    {v}
                  </option>
                ))}
              </select>
            </label>
            <label className="s1-rc__field">
              <span>EPA fuel for CH₄ and N₂O</span>
              <select value={draft.factorFuel} onChange={(e) => update(index, { factorFuel: e.target.value })}>
                <option value="">Choose</option>
                {fuelChoices.map((f) => (
                  <option key={f} value={f}>
                    {f}
                  </option>
                ))}
              </select>
            </label>
            {draft.onRoad ? (
              <>
                {option?.by_model_year ? (
                  <label className="s1-rc__field">
                    <span>Model year</span>
                    <input
                      inputMode="numeric"
                      placeholder={option.first_model_year ? `${option.first_model_year} to ${option.last_model_year ?? "now"}`
                        : `up to ${option.last_model_year ?? "now"}`}
                      value={draft.modelYear}
                      onChange={(e) => update(index, { modelYear: e.target.value })}
                    />
                  </label>
                ) : null}
                <label className="s1-rc__field">
                  <span>Distance driven</span>
                  <span className="s1-rc__num">
                    <input
                      inputMode="decimal"
                      value={draft.distance}
                      onChange={(e) => update(index, { distance: e.target.value })}
                    />
                    <select
                      aria-label="Distance unit"
                      value={draft.distanceUnit}
                      onChange={(e) => update(index, { distanceUnit: e.target.value === "km" ? "km" : "mi" })}
                    >
                      <option value="mi">miles</option>
                      <option value="km">km</option>
                    </select>
                  </span>
                </label>
              </>
            ) : (
              <label className="s1-rc__field">
                <span>Fuel used (blank: all of this fuel, if it is the only group)</span>
                <span className="s1-rc__num">
                  <input
                    inputMode="decimal"
                    value={draft.fuelQuantity}
                    onChange={(e) => update(index, { fuelQuantity: e.target.value })}
                  />
                  <select
                    aria-label="Fuel unit"
                    value={draft.fuelUnit}
                    onChange={(e) => update(index, { fuelUnit: e.target.value === "L" ? "L" : "gal" })}
                  >
                    <option value="gal">gal</option>
                    <option value="L">L</option>
                  </select>
                </span>
              </label>
            )}
            <div className="s1-rc__vg-foot">
              {problem ? <span className="s1-muted">{problem}</span> : null}
              {removing === index ? (
                <span role="alert">
                  <span className="s1-muted">{confirmRemove} </span>
                  <button
                    className="s1-linklike"
                    type="button"
                    onClick={() => {
                      setRemoving(null);
                      onChange(drafts.filter((_, i) => i !== index));
                    }}
                  >
                    Confirm remove
                  </button>{" "}
                  <button className="s1-linklike" type="button" onClick={() => setRemoving(null)}>
                    Keep group
                  </button>
                </span>
              ) : (
                <button
                  className="s1-linklike"
                  type="button"
                  onClick={() => (confirmRemove ? setRemoving(index) : onChange(drafts.filter((_, i) => i !== index)))}
                >
                  Remove group
                </button>
              )}
            </div>
          </div>
        );
      })}
      <button
        className="s1-linklike"
        type="button"
        disabled={maxGroups !== undefined && drafts.length >= maxGroups}
        onClick={() =>
          onChange([
            ...drafts,
            {
              uid: newDraftUid(),
              label: "",
              fuel: fuels.length === 1 ? fuels[0] : "",
              onRoad: true,
              vehicleType: "",
              factorFuel: "",
              modelYear: "",
              distance: "",
              distanceUnit: "mi",
              fuelQuantity: "",
              fuelUnit: "gal",
            },
          ])
        }
      >
        Add vehicle group
      </button>
      {maxGroups !== undefined && drafts.length >= maxGroups ? (
        <span className="s1-muted">A company can have at most {maxGroups} vehicle groups.</span>
      ) : null}
    </Wrap>
  );
}

function Wrap({ heading, children }: { heading: boolean; children: ReactNode }) {
  return heading ? (
    <fieldset className="s1-rc__group s1-rc__group--wide">
      <legend>Vehicle groups (mobile CH₄ and N₂O)</legend>
      {children}
    </fieldset>
  ) : (
    <div className="s1-rc__group s1-rc__group--wide" role="group" aria-label="Vehicle groups">
      {children}
    </div>
  );
}
