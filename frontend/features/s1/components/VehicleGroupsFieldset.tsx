"use client";

import type { RecalcNeedsInput, VehicleTypeOption } from "../api/recalculation";
import type { VehicleGroupSetting } from "../types";

/**
 * Vehicle groups for mobile CH₄ and N₂O (workbook Eq 4 / Eq 5). The evidence gives fuel
 * per fuel type; the CH₄ and N₂O factors also depend on the vehicle, so the reviewer says
 * which vehicles used each fuel: on-road groups by distance (and model year where the
 * EPA factor depends on it), non-road groups by the fuel they used.
 */
export interface VehicleGroupDraft {
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

export function draftsFrom(groups: VehicleGroupSetting[] | undefined): VehicleGroupDraft[] {
  return (groups ?? []).map((g) => ({
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

function optionFor(types: VehicleTypeOption[], draft: VehicleGroupDraft): VehicleTypeOption | undefined {
  return types.find(
    (t) => t.on_road === draft.onRoad && t.vehicle_type === draft.vehicleType && t.fuel_type === draft.factorFuel
  );
}

const isNumber = (text: string) => text.trim() !== "" && Number.isFinite(Number(text)) && Number(text) >= 0;

/** What is wrong with a group, in words, or null when it can be saved. */
export function draftProblem(draft: VehicleGroupDraft, types: VehicleTypeOption[]): string | null {
  if (!draft.fuel || !draft.vehicleType || !draft.factorFuel) return "Choose the fuel, vehicle type and EPA fuel.";
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

/** The groups as saved. A model year is sent only where the EPA factor uses one, so a year
 *  typed before switching to a type without one (hidden from then on) is not sent. */
export function settingsFrom(drafts: VehicleGroupDraft[], types: VehicleTypeOption[]): VehicleGroupSetting[] {
  return drafts.map((d) => ({
    fuel: d.fuel,
    vehicle_type: d.vehicleType,
    factor_fuel_type: d.factorFuel,
    on_road: d.onRoad,
    ...(d.label.trim() ? { label: d.label.trim() } : {}),
    ...(d.onRoad
      ? {
          distance: Number(d.distance),
          distance_unit: d.distanceUnit,
          ...(d.modelYear.trim() && optionFor(types, d)?.by_model_year ? { model_year: Number(d.modelYear) } : {}),
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
}: {
  drafts: VehicleGroupDraft[];
  /** EPA Table 2 fuels with reviewed mobile records (each a recalculated line). */
  fuels: string[];
  types: VehicleTypeOption[];
  asks: RecalcNeedsInput[];
  onChange: (next: VehicleGroupDraft[]) => void;
}) {
  const update = (index: number, patch: Partial<VehicleGroupDraft>) =>
    onChange(drafts.map((d, i) => (i === index ? { ...d, ...patch } : d)));
  const vehicleTypes = (onRoad: boolean) =>
    Array.from(new Set(types.filter((t) => t.on_road === onRoad).map((t) => t.vehicle_type)));
  const factorFuels = (onRoad: boolean, vehicleType: string) =>
    types.filter((t) => t.on_road === onRoad && t.vehicle_type === vehicleType).map((t) => t.fuel_type);

  return (
    <fieldset className="s1-rc__group s1-rc__group--wide">
      <legend>Vehicle groups (mobile CH₄ and N₂O)</legend>
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
        const problem = draftProblem(draft, types);
        const option = optionFor(types, draft);
        const fuelChoices = factorFuels(draft.onRoad, draft.vehicleType);
        return (
          <div key={index} className="s1-rc__vg" role="group" aria-label={`Vehicle group ${index + 1}`}>
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
                onChange={(e) => update(index, { onRoad: e.target.value === "on", vehicleType: "", factorFuel: "" })}
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
                  update(index, { vehicleType: e.target.value, factorFuel: choices.length === 1 ? choices[0] : "" });
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
              <button
                className="s1-linklike"
                type="button"
                onClick={() => onChange(drafts.filter((_, i) => i !== index))}
              >
                Remove group
              </button>
            </div>
          </div>
        );
      })}
      <button
        className="s1-linklike"
        type="button"
        onClick={() =>
          onChange([
            ...drafts,
            {
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
    </fieldset>
  );
}
