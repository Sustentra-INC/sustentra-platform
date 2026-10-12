"""Build reference-data/emission-factors/epa_ghg_emission_factors_hub_2025.json.

Reads the US EPA GHG Emission Factors Hub 2025 workbook (one sheet, Tables 1-12) and
writes a JSON copy of the tables the recalculation uses. Every factor keeps the
EPA table number and the workbook row it came from, so a calculation step can cite
exactly where its factor was read.

Usage:
    python backend/scripts/build_emission_factor_reference.py [path/to/hub.xlsx] [out.json]

Defaults: reference-data/emission-factors/source/ghg-emission-factors-hub-2025.xlsx
       -> reference-data/emission-factors/epa_ghg_emission_factors_hub_2025.json
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

import openpyxl

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SOURCE = REPO_ROOT / "reference-data" / "emission-factors" / "source" / "ghg-emission-factors-hub-2025.xlsx"
DEFAULT_OUT = REPO_ROOT / "reference-data" / "emission-factors" / "epa_ghg_emission_factors_hub_2025.json"
SHEET = "Emission Factors Hub"

Row = tuple[int, list[Any]]  # (1-based workbook row, non-empty cells in order)


def _cells(raw: tuple[Any, ...]) -> list[Any]:
    out: list[Any] = []
    for cell in raw:
        if cell is None:
            continue
        if isinstance(cell, str):
            text = " ".join(cell.split())
            if text:
                out.append(text)
        else:
            out.append(cell)
    return out


def _is_num(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _table_rows(rows: list[Row], number: int) -> list[Row]:
    """Rows from 'Table N' up to (not including) its 'Source:'/'Notes:' footer or the next table."""

    start = next(i for i, (_, c) in enumerate(rows) if c and c[0] == f"Table {number}")
    body: list[Row] = []
    for index in range(start + 1, len(rows)):
        _, cells = rows[index]
        if not cells:
            continue
        head = str(cells[0])
        if re.fullmatch(r"Table \d+", head) or head.startswith(("Source", "Notes")):
            break
        body.append(rows[index])
    return body


def _model_years(text: str) -> tuple[int | None, int | None] | None:
    """'1975' -> (1975, 1975); '1973-1974' -> (1973, 1974); '≤1980' -> (None, 1980); '≥2023' -> (2023, None)."""

    value = str(text).strip()
    open_range = re.fullmatch(r"(≤|<=|≥|>=)\s*(\d{4})", value)
    if open_range:
        year = int(open_range.group(2))
        return (None, year) if open_range.group(1) in ("≤", "<=") else (year, None)
    match = re.fullmatch(r"(\d{4})(?:\s*-\s*(\d{4}))?", value)
    if not match:
        return None
    first = int(match.group(1))
    return first, int(match.group(2) or first)


def _unit_after_per(text: str) -> str:
    return str(text).split(" per ", 1)[1].strip()


# --- Table 1: stationary combustion -----------------------------------------------------
def stationary(rows: list[Row]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    category = None
    physical_unit = None
    for row_no, cells in _table_rows(rows, 1):
        nums = [c for c in cells if _is_num(c)]
        if cells[0] == "Fuel Type":
            continue
        if not nums and str(cells[0]).startswith("mmBtu per"):
            physical_unit = _unit_after_per(cells[0])  # "mmBtu per short ton" -> "short ton"
            continue
        if not nums:
            category = str(cells[0])
            continue
        name = str(cells[0])
        if len(nums) == 7:
            hhv, co2_e, ch4_e, n2o_e, co2_u, ch4_u, n2o_u = nums
            out.append({
                "fuel_type": name, "category": category,
                "heat_content_hhv": {"value": hhv, "unit": f"mmBtu per {physical_unit}"},
                "per_energy": {"co2_kg_per_mmbtu": co2_e, "ch4_g_per_mmbtu": ch4_e, "n2o_g_per_mmbtu": n2o_e},
                "per_unit": {"unit": physical_unit, "co2_kg_per_unit": co2_u, "ch4_g_per_unit": ch4_u,
                             "n2o_g_per_unit": n2o_u},
                "source": {"table": "Table 1", "row": row_no},
            })
        elif len(nums) == 3:  # Kraft pulping liquor: energy basis only
            co2_e, ch4_e, n2o_e = nums
            out.append({
                "fuel_type": name, "category": category, "heat_content_hhv": None,
                "per_energy": {"co2_kg_per_mmbtu": co2_e, "ch4_g_per_mmbtu": ch4_e, "n2o_g_per_mmbtu": n2o_e},
                "per_unit": None, "source": {"table": "Table 1", "row": row_no},
            })
        else:
            raise ValueError(f"Table 1 row {row_no}: unexpected layout {cells}")
    return out


# --- Table 2: mobile CO2 ---------------------------------------------------------------
def mobile_co2(rows: list[Row]) -> list[dict[str, Any]]:
    out = []
    for row_no, cells in _table_rows(rows, 2):
        if cells[0] == "Fuel Type":
            continue
        name, factor, unit = cells
        out.append({"fuel_type": name, "co2_kg_per_unit": factor, "unit": unit,
                    "source": {"table": "Table 2", "row": row_no}})
    return out


# --- Tables 3/4: on-road CH4/N2O per vehicle-mile --------------------------------------
def on_road(rows: list[Row], number: int, fixed_fuel: str | None) -> list[dict[str, Any]]:
    out = []
    vehicle = fuel = None
    for row_no, cells in _table_rows(rows, number):
        if cells[0] == "Vehicle Type":
            continue
        nums = [c for c in cells if _is_num(c)]
        labels = [c for c in cells if not _is_num(c)]
        years = None
        # A single model year is stored as a number (1975); a range as text ("1973-1974").
        if len(nums) == 3 and isinstance(nums[0], int) and 1900 <= nums[0] <= 2100:
            years = (nums[0], nums[0])
            nums = nums[1:]
        if len(nums) != 2:
            raise ValueError(f"Table {number} row {row_no}: unexpected layout {cells}")
        if years is None and labels and _model_years(labels[-1]):
            years = _model_years(labels.pop())
        # "(Vans, Pickup Trucks, SUVs)" describes the vehicle type above it; it is not a new type.
        labels = [label for label in labels if not str(label).startswith("(")]
        if fixed_fuel is not None:  # Table 3: gasoline only, labels = [vehicle]
            if labels:
                vehicle = labels[0]
            fuel = fixed_fuel
        else:  # Table 4: labels = [vehicle, fuel] | [fuel] | []
            if len(labels) == 2:
                vehicle, fuel = labels
            elif len(labels) == 1:
                fuel = labels[0]
        out.append({
            "vehicle_type": vehicle, "fuel_type": fuel,
            "model_year_from": years[0] if years else None, "model_year_to": years[1] if years else None,
            "ch4_g_per_mile": nums[0], "n2o_g_per_mile": nums[1],
            "source": {"table": f"Table {number}", "row": row_no},
        })
    return out


# --- Table 5: non-road CH4/N2O per gallon -----------------------------------------------
def non_road(rows: list[Row]) -> list[dict[str, Any]]:
    out = []
    vehicle = None
    for row_no, cells in _table_rows(rows, 5):
        if cells[0] == "Vehicle Type":
            continue
        nums = [c for c in cells if _is_num(c)]
        labels = [c for c in cells if not _is_num(c)]
        if len(nums) != 2 or not 1 <= len(labels) <= 2:
            raise ValueError(f"Table 5 row {row_no}: unexpected layout {cells}")
        if len(labels) == 2:
            vehicle = re.sub(r"(Equipment)[AB]$", r"\1", labels[0])  # footnote letters "EquipmentA"
        out.append({"vehicle_type": vehicle, "fuel_type": labels[-1], "ch4_g_per_gallon": nums[0],
                    "n2o_g_per_gallon": nums[1], "source": {"table": "Table 5", "row": row_no}})
    return out


# --- Table 6: electricity (eGRID subregions) --------------------------------------------
def electricity(rows: list[Row]) -> list[dict[str, Any]]:
    out = []
    for row_no, cells in _table_rows(rows, 6):
        nums = [c for c in cells if _is_num(c)]
        if len(nums) < 6:
            continue  # header rows
        acronym, name = cells[0], cells[1]
        out.append({
            "egrid_subregion": acronym, "name": name,
            "total_output": {"co2_lb_per_mwh": nums[0], "ch4_lb_per_mwh": nums[1], "n2o_lb_per_mwh": nums[2]},
            "non_baseload": {"co2_lb_per_mwh": nums[3], "ch4_lb_per_mwh": nums[4], "n2o_lb_per_mwh": nums[5]},
            "grid_gross_loss": nums[6] if len(nums) > 6 else None,
            "source": {"table": "Table 6", "row": row_no},
        })
    return out


# --- Table 7: steam and heat ------------------------------------------------------------
def steam_heat(rows: list[Row]) -> list[dict[str, Any]]:
    out = []
    for row_no, cells in _table_rows(rows, 7):
        nums = [c for c in cells if _is_num(c)]
        if len(nums) == 3:
            out.append({"name": cells[0], "co2_kg_per_mmbtu": nums[0], "ch4_g_per_mmbtu": nums[1],
                        "n2o_g_per_mmbtu": nums[2], "source": {"table": "Table 7", "row": row_no}})
    return out


# --- Tables 11/12: GWP ------------------------------------------------------------------
def gwp(rows: list[Row]) -> list[dict[str, Any]]:
    out = []
    for row_no, cells in _table_rows(rows, 11):
        if len(cells) == 3 and _is_num(cells[2]):
            out.append({"name": cells[0], "formula": cells[1], "gwp_100yr": cells[2],
                        "source": {"table": "Table 11", "row": row_no}})
    return out


def gwp_blends(rows: list[Row]) -> list[dict[str, Any]]:
    out = []
    for row_no, cells in _table_rows(rows, 12):
        if len(cells) >= 2 and _is_num(cells[1]):
            out.append({"ashrae": cells[0], "gwp_100yr": cells[1],
                        "composition": cells[2] if len(cells) > 2 else None,
                        "source": {"table": "Table 12", "row": row_no}})
    return out


def build(source: Path) -> dict[str, Any]:
    ws = openpyxl.load_workbook(source, data_only=True, read_only=True)[SHEET]
    rows: list[Row] = [(i, _cells(raw)) for i, raw in enumerate(ws.iter_rows(values_only=True), start=1)]
    gwp_values = gwp(rows)
    by_formula = {g["formula"]: g["gwp_100yr"] for g in gwp_values}
    return {
        "dataset": "EPA GHG Emission Factors Hub 2025",
        "source_file": source.name,
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "sheet": SHEET,
        "gwp_set": "IPCC AR5 100-year" if (by_formula.get("CH4"), by_formula.get("N2O")) == (28, 265) else "unknown",
        "units": {
            "stationary_combustion": "per_energy: kg CO2 / g CH4 / g N2O per mmBtu; per_unit: per physical unit",
            "mobile_co2": "kg CO2 per unit (unit given per row)",
            "mobile_on_road": "g per vehicle-mile",
            "mobile_non_road": "g per gallon",
            "electricity": "lb per MWh (eGRID2023 subregion output rates)",
            "steam_heat": "kg CO2 / g CH4 / g N2O per mmBtu",
        },
        "stationary_combustion": stationary(rows),
        "mobile_co2": mobile_co2(rows),
        "mobile_on_road_gasoline": on_road(rows, 3, fixed_fuel="Gasoline"),
        "mobile_on_road_other": on_road(rows, 4, fixed_fuel=None),
        "mobile_non_road": non_road(rows),
        "electricity": electricity(rows),
        "steam_heat": steam_heat(rows),
        "gwp": gwp_values,
        "gwp_refrigerant_blends": gwp_blends(rows),
    }


def main(argv: list[str]) -> int:
    source = Path(argv[1]) if len(argv) > 1 else DEFAULT_SOURCE
    out = Path(argv[2]) if len(argv) > 2 else DEFAULT_OUT
    data = build(source)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    counts = {k: len(v) for k, v in data.items() if isinstance(v, list)}
    print(f"wrote {out} from {source.name}: {counts}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
