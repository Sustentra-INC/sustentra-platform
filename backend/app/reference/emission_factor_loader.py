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
