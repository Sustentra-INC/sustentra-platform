"""EPA GHG Emission Factors Hub 2025: emission factor and GWP lookups.

Reads reference-data/emission-factors/epa_ghg_emission_factors_hub_2025.json, which
``backend/scripts/build_emission_factor_reference.py`` generates from the EPA workbook
(reference-data/emission-factors/source/). Every lookup returns the factor together
with its source (EPA table and workbook row) so a calculation can cite it.

Lookups never guess: an unknown fuel, subregion, vehicle or gas raises
``EmissionFactorNotFoundError`` naming what was asked for.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

DEFAULT_PATH = (
    Path(__file__).resolve().parents[3] / "reference-data" / "emission-factors" / "epa_ghg_emission_factors_hub_2025.json"
)

AR6_LIBRARY_PATH = (
    Path(__file__).resolve().parents[3] / "reference-data" / "config" / "libraries" / "emission_factor_library.json"
)

# EPA physical-unit labels -> canonical units in backend.app.domain.fuel_units.
EPA_UNIT_TO_CANONICAL = {"short ton": "short_ton", "scf": "scf", "gallon": "gal"}

# GWP sets the recalculation can use. AR5 is EPA Hub 2025 Table 11 (the set in the GHG
# Required Data workbook's worked examples); AR6 is the combustion set in
# reference-data/config/libraries/emission_factor_library.json. The engagement chooses.
GWP_SETS = ("AR5", "AR6")
DEFAULT_GWP_SET = "AR5"

# The gas groups reported separately (GHG Protocol / SB 253): CO2, CH4, N2O, HFCs, PFCs, SF6, NF3.
GAS_GROUPS = ("CO2", "CH4", "N2O", "HFCs", "PFCs", "SF6", "NF3")


def gas_group_of(name: str) -> str | None:
    """The reported gas group of a single gas ("HFC-32" -> "HFCs"), or None when it is not one
    of them (HCFCs and CFCs are Montreal Protocol gases; hydrocarbons are not reported)."""

    low = " ".join(str(name).lower().split())
    if low.startswith("hfc-") or low in ("chf3", "ch2f2"):
        return "HFCs"
    if low.startswith("pfc-") or low in ("cf4", "c2f6", "c3f8", "c-c4f8", "c4f10", "c5f12", "c6f14", "c10f18"):
        return "PFCs"
    return {"co2": "CO2", "carbon dioxide": "CO2", "ch4": "CH4", "methane": "CH4", "n2o": "N2O",
            "nitrous oxide": "N2O", "sf6": "SF6", "sulfur hexafluoride": "SF6", "nf3": "NF3",
            "nitrogen trifluoride": "NF3"}.get(low)


class EmissionFactorNotFoundError(LookupError):
    """No factor in the reference data matches the request."""


@dataclass(frozen=True)
class Factor:
    """One numeric factor with its unit and where it was read."""

    value: float
    unit: str
    source: str  # e.g. "EPA GHG Emission Factors Hub 2025, Table 6, row 353"


def _cite(dataset: str, source: dict[str, Any]) -> str:
    return f"{dataset}, {source['table']}, row {source['row']}"


def _norm(text: str) -> str:
    return " ".join(str(text).lower().split())


class EmissionFactorReference:
    def __init__(self, data: dict[str, Any]) -> None:
        self.data = data
        self.dataset: str = data["dataset"]
        self.gwp_set: str = data["gwp_set"]
        self._stationary = {_norm(r["fuel_type"]): r for r in data["stationary_combustion"]}
        self._mobile_co2 = {_norm(r["fuel_type"]): r for r in data["mobile_co2"]}
        self._egrid = {_norm(r["egrid_subregion"]): r for r in data["electricity"]}
        self._gwp: dict[str, dict[str, Any]] = {}
        for row in data["gwp"]:
            self._gwp[_norm(row["formula"])] = row
            self._gwp[_norm(row["name"])] = row
        for row in data["gwp_refrigerant_blends"]:
            self._gwp[_norm(row["ashrae"])] = row

    # --- GWP --------------------------------------------------------------------------
    def gwp(self, gas: str, gwp_set: str = DEFAULT_GWP_SET) -> Factor:
        if gwp_set == "AR6":
            return _ar6_gwp(gas)
        if gwp_set != "AR5":
            raise EmissionFactorNotFoundError(f"Unknown GWP set {gwp_set!r}; use one of {GWP_SETS}.")
        row = self._gwp.get(_norm(gas))
        if row is None:
            raise EmissionFactorNotFoundError(f"No GWP for {gas!r} in {self.dataset} (Tables 11-12).")
        return Factor(float(row["gwp_100yr"]), "kg CO2e per kg", _cite(self.dataset, row["source"]) + " (IPCC AR5)")

    def gas_groups(self, gas: str) -> dict[str, dict[str, float]] | None:
        """Which reported gas groups a gas or refrigerant blend is made of.

        Returns {group: {"mass_fraction": f, "co2e_fraction": g}}: a pure gas is one group at
        1.0; a Table 12 blend splits by its composition, mass by weight percent and CO2e by
        each component's share of the blend's CO2e (weight percent x Table 11 GWP), so the
        groups add up to the blend's own CO2e. Components outside the groups (HCFCs,
        hydrocarbons) carry mass but no CO2e here, as in Table 12. None when the gas is not
        in the Hub (its split is unknown).
        """

        row = self._gwp.get(_norm(gas))
        if row is None:
            group = gas_group_of(gas)
            return {group: {"mass_fraction": 1.0, "co2e_fraction": 1.0}} if group else None
        if "composition" not in row:  # Table 11: a single gas
            group = gas_group_of(row["name"]) or gas_group_of(row["formula"])
            return {group: {"mass_fraction": 1.0, "co2e_fraction": 1.0}} if group else None
        parts: list[tuple[str, float]] = []
        for part in str(row["composition"]).split(","):
            match = re.match(r"\s*([\d.]+)\s*%\s*(.+?)\s*$", part)
            if match:
                parts.append((match.group(2), float(match.group(1)) / 100))
        weights: dict[str, float] = {}
        masses: dict[str, float] = {}
        for component, fraction in parts:
            group = gas_group_of(component)
            if group is None:
                continue
            masses[group] = masses.get(group, 0.0) + fraction
            component_row = self._gwp.get(_norm(component))
            gwp = float(component_row["gwp_100yr"]) if component_row is not None else 0.0
            weights[group] = weights.get(group, 0.0) + fraction * gwp
        total = sum(weights.values())
        return {group: {"mass_fraction": masses[group],
                        "co2e_fraction": (weights[group] / total) if total else 0.0} for group in masses}

    # --- Scope 2 electricity ----------------------------------------------------------
    def egrid_subregions(self) -> list[dict[str, Any]]:
        return [{"egrid_subregion": r["egrid_subregion"], "name": r["name"]} for r in self.data["electricity"]]

    def electricity(self, subregion: str) -> dict[str, Factor]:
        row = self._egrid.get(_norm(subregion))
        if row is None:
            raise EmissionFactorNotFoundError(f"No eGRID subregion {subregion!r} in {self.dataset} (Table 6).")
        cite = _cite(self.dataset, row["source"])
        rates = row["total_output"]
        return {
            "CO2": Factor(float(rates["co2_lb_per_mwh"]), "lb per MWh", cite),
            "CH4": Factor(float(rates["ch4_lb_per_mwh"]), "lb per MWh", cite),
            "N2O": Factor(float(rates["n2o_lb_per_mwh"]), "lb per MWh", cite),
        }

    # --- Scope 1 stationary combustion ------------------------------------------------
    def stationary_fuel(self, fuel_type: str) -> dict[str, Any]:
        row = self._stationary.get(_norm(fuel_type))
        if row is None:
            raise EmissionFactorNotFoundError(
                f"No stationary-combustion fuel {fuel_type!r} in {self.dataset} (Table 1). "
                "Use the EPA fuel name, e.g. 'Natural Gas', 'Distillate Fuel Oil No. 2'."
            )
        return row

    def stationary_fuel_types(self) -> list[str]:
        return [r["fuel_type"] for r in self.data["stationary_combustion"]]

    def cite(self, row: dict[str, Any]) -> str:
        return _cite(self.dataset, row["source"])

    # --- Scope 1 mobile combustion ----------------------------------------------------
    def mobile_co2(self, fuel_type: str) -> dict[str, Any]:
        row = self._mobile_co2.get(_norm(fuel_type))
        if row is None:
            raise EmissionFactorNotFoundError(
                f"No mobile CO2 factor for {fuel_type!r} in {self.dataset} (Table 2)."
            )
        return row

    def on_road(self, vehicle_type: str, fuel_type: str, model_year: int | None) -> dict[str, Any]:
        """Table 3 (gasoline) or Table 4 (other fuels) row for a vehicle, fuel and model year."""

        rows = self.data["mobile_on_road_gasoline"] + self.data["mobile_on_road_other"]
        matches = [
            r for r in rows
            if _norm(r["vehicle_type"]) == _norm(vehicle_type) and _norm(r["fuel_type"]) == _norm(fuel_type)
        ]
        if not matches:
            raise EmissionFactorNotFoundError(
                f"No on-road CH4/N2O factor for {vehicle_type!r} / {fuel_type!r} in {self.dataset} (Tables 3-4)."
            )
        dated = [r for r in matches if r["model_year_from"] is not None or r["model_year_to"] is not None]
        if not dated:
            return matches[0]
        if model_year is None:
            raise EmissionFactorNotFoundError(
                f"{vehicle_type!r} / {fuel_type!r} factors depend on model year; none was given."
            )
        for row in dated:  # an open end ("≤1980") has no bound on that side
            low, high = row["model_year_from"], row["model_year_to"]
            if (low is None or low <= model_year) and (high is None or model_year <= high):
                return row
        raise EmissionFactorNotFoundError(
            f"No {vehicle_type!r} / {fuel_type!r} factor covers model year {model_year} in {self.dataset}."
        )

    def vehicle_types(self) -> list[dict[str, Any]]:
        """Vehicle types with CH4/N2O factors: on-road (Tables 3-4, per mile, some by model
        year) and non-road (Table 5, per gallon), with the fuels each has factors for."""

        grouped: dict[tuple[str, str, bool], list[dict[str, Any]]] = {}
        for row in self.data["mobile_on_road_gasoline"] + self.data["mobile_on_road_other"]:
            grouped.setdefault((row["vehicle_type"], row["fuel_type"], True), []).append(row)
        for row in self.data["mobile_non_road"]:
            grouped.setdefault((row["vehicle_type"], row["fuel_type"], False), []).append(row)
        out = []
        for (vehicle_type, fuel_type, on_road), rows in grouped.items():
            dated = [r for r in rows if r.get("model_year_from") is not None or r.get("model_year_to") is not None]
            starts = [r["model_year_from"] for r in dated if r.get("model_year_from") is not None]
            ends = [r["model_year_to"] for r in dated if r.get("model_year_to") is not None]
            out.append({
                "vehicle_type": vehicle_type, "fuel_type": fuel_type, "on_road": on_road,
                "by_model_year": bool(dated),
                # None when the oldest band is open-ended ("1980 and earlier"), like last_model_year.
                "first_model_year": min(starts) if dated and len(starts) == len(dated) else None,
                # None when the newest band is open-ended ("2021 and later") or nothing is dated.
                "last_model_year": max(ends) if dated and len(ends) == len(dated) else None,
            })
        return out

    def non_road(self, vehicle_type: str, fuel_type: str) -> dict[str, Any]:
        for row in self.data["mobile_non_road"]:
            if _norm(row["vehicle_type"]) == _norm(vehicle_type) and _norm(row["fuel_type"]) == _norm(fuel_type):
                return row
        raise EmissionFactorNotFoundError(
            f"No non-road CH4/N2O factor for {vehicle_type!r} / {fuel_type!r} in {self.dataset} (Table 5)."
        )


@lru_cache(maxsize=1)
def _ar6_values() -> dict[str, tuple[float, str]]:
    """Combustion-default AR6 GWPs from the curated library (CH4 uses its combustion default)."""

    library = json.loads(AR6_LIBRARY_PATH.read_text(encoding="utf-8-sig"))
    out: dict[str, tuple[float, str]] = {}
    for gwp_set in library["gwp_sets"]:
        for value in gwp_set["values"]:
            if not value.get("combustion_default"):
                continue
            cite = f"emission_factor_library.json, {gwp_set['gwp_set_id']}, {value['gwp_key']} (IPCC AR6)"
            out[_norm(value["chemical_formula"])] = (float(value["gwp"]), cite)
    return out


def _ar6_gwp(gas: str) -> Factor:
    hit = _ar6_values().get(_norm(gas))
    if hit is None:
        raise EmissionFactorNotFoundError(
            f"The AR6 set in emission_factor_library.json has no GWP for {gas!r} (it covers CO2, CH4, N2O)."
        )
    return Factor(hit[0], "kg CO2e per kg", hit[1])


def load_emission_factor_reference(path: Path | None = None) -> EmissionFactorReference:
    target = Path(path) if path is not None else DEFAULT_PATH
    return EmissionFactorReference(json.loads(target.read_text(encoding="utf-8")))


@lru_cache(maxsize=1)
def default_emission_factor_reference() -> EmissionFactorReference:
    return load_emission_factor_reference()
