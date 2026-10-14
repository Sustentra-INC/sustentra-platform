"""Scope 2 purchased steam, heat and cooling: deterministic extraction for CT-S2-THERMAL.

Reads district energy and steam bills for the inputs of workbook rows 48-50 (indirect
emissions from purchased steam, heating and cooling), the same fields as purchased
electricity:

    determinant  facility_name, service_address, supplier_name
    matching key account_number
    prorate      service_period_start, service_period_end
    input        energy_type (steam / hot_water / chilled_water), activity_quantity, activity_unit

The layout engine is the EXT-001 one; this module swaps the vocabulary. A quantity counts
when it is thermal energy (MMBtu, therms, dekatherms, kBtu, GJ, kWh or MWh), normalized to
MMBtu because the EPA steam and heat factor (Hub Table 7) is per MMBtu. Steam billed by
weight (lb, Mlb) is read as written: its energy needs the steam's heat content, which the
reviewer gives, so it is never guessed here.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any

from backend.app.domain import fuel_units
from backend.app.services.electricity_extractor import ElectricityExtractor
from backend.app.services.stationary_combustion_extractor import (
    _ALL_LABELS as _BASE_LABELS,
)
from backend.app.services.stationary_combustion_extractor import (
    HALT_UNREADABLE,
    HALT_UNSUPPORTED,
    ExtractionOutcome,
    Located,
    Row,
    StationaryCombustionExtractor,
    UsageRecord,
    _norm,
)

CANONICAL_TYPE_ID = "CT-S2-THERMAL"
TARGET_UNIT = "MMBtu"
STEAM, HOT_WATER, CHILLED_WATER = "steam", "hot_water", "chilled_water"
# Energy units a thermal bill states, and steam's weight units (energy needs a heat content).
THERMAL_ENERGY_UNITS = frozenset({"MMBtu", "Dth", "therm", "kBtu", "Btu", "GJ", "kWh", "MWh", "ton_hour"})
STEAM_MASS_UNITS = frozenset({"lb", "klb"})

# Strict cues only: "heat" alone also appears on gas bills ("heat content", "heating
# degree days"), so a hot-water service must be named as such.
_CUES: tuple[tuple[str, re.Pattern[str]], ...] = (
    (CHILLED_WATER, re.compile(r"(?<![a-z])(chilled water|district cooling|cooling services?|ton[- ]hours?)(?![a-z])")),
    (STEAM, re.compile(r"(?<![a-z])(steam)(?![a-z])")),
    (HOT_WATER, re.compile(r"(?<![a-z])(hot water|heating hot water|district heating|district heat|"
                           r"thermal energy|heating services?)(?![a-z])")),
)

ENERGY_TYPE_LABELS: tuple[tuple[str, ...], ...] = (
    ("energy type", "service type", "commodity", "product", "service"),
)
QUANTITY_LABELS: tuple[tuple[str, ...], ...] = (
    ("total steam usage", "total steam delivered", "steam usage", "steam delivered", "steam consumption",
     "total steam", "steam used",
     "hot water usage", "heating usage", "heat delivered", "energy delivered", "thermal energy delivered",
     "chilled water usage", "cooling usage", "cooling delivered",
     "total usage", "total consumption", "billed usage", "usage", "consumption", "mmbtu", "therms"),
)


def detect_thermal(text: str) -> tuple[str, str] | None:
    """(energy type, matched cue) when ``text`` names steam, hot water or chilled water."""

    normalized = _norm(text)
    for kind, pattern in _CUES:
        match = pattern.search(normalized)
        if match:
            return kind, match.group(0)
    return None


class ThermalExtractor(ElectricityExtractor):
    """Builds CT-S2-THERMAL candidates: one record per usage line (or one per bill)."""

    CANONICAL_TYPE_ID = CANONICAL_TYPE_ID
    FUEL_LABEL_GROUPS = ENERGY_TYPE_LABELS
    QUANTITY_LABEL_GROUPS = QUANTITY_LABELS
    QTY_EXCLUDE = StationaryCombustionExtractor.QTY_EXCLUDE + ("demand", "peak", "rate", "per ")
    ALL_LABELS = _BASE_LABELS + tuple(label for group in (ENERGY_TYPE_LABELS + QUANTITY_LABELS) for label in group)

    def _fuel(self, text: str) -> tuple[str, str] | None:
        return detect_thermal(text)

    def _quantity_header_score(self, text: str) -> int:
        score = StationaryCombustionExtractor._quantity_header_score(self, text)
        if score and "total" in text:
            score += 1
        return score

    def _counts(self, unit: str | None, energy: str | None) -> bool:
        return unit in THERMAL_ENERGY_UNITS or (energy == STEAM and unit in STEAM_MASS_UNITS)

    def confirms(self, parser_output: dict) -> bool:
        """Content check: the document names steam, hot water or chilled water, states a
        thermal quantity, and names no combusted fuel (a gas bill is fuel, not steam)."""

        rows = self._rows(parser_output)
        found = next((detect_thermal(c.text) for r in rows for c in r.cells if detect_thermal(c.text)), None)
        if found is None or StationaryCombustionExtractor().confirms(parser_output):
            return False
        unit_hint = self._document_unit(rows)
        return any(self._counts(self._record_unit(r, unit_hint), found[0]) for r in self._quantity_records(rows))

    # ---------------------------------------------------------------------------------
    def _extract(self, rows: list[Row], parser_output: dict, targets: Sequence[dict], evidence_id: str,
                 document_id: str) -> ExtractionOutcome:
        if not any(cell.text.strip() for row in rows for cell in row.cells):
            return ExtractionOutcome(candidates=[], halt_reason={
                "code": HALT_UNREADABLE,
                "message": "No readable text was found in the document (for example a scan without a text "
                "layer while OCR is off, or an empty file). Upload a text-based PDF or enable OCR.",
            })
        doc_energy = self._document_fuel(rows)
        energy = doc_energy.raw if doc_energy is not None else None
        kind = detect_thermal(energy or "")
        unit_hint = self._document_unit(rows)
        records = [r for r in self._quantity_records(rows)
                   if self._counts(self._record_unit(r, unit_hint), kind[0] if kind else None)]
        if not records or doc_energy is None:
            return ExtractionOutcome(candidates=[], halt_reason={
                "code": HALT_UNSUPPORTED,
                "message": "No steam, hot water or chilled water quantity in a thermal unit (MMBtu, therms, "
                "kBtu, GJ, MWh, or pounds of steam) was found, so this is not purchased steam, heat or "
                "cooling evidence.",
            })
        return self._records_to_candidates(rows, parser_output, targets, evidence_id, document_id, records,
                                           doc_energy, unit_hint)

    # ---------------------------------------------------------------------------------
    def _record_values(self, record: UsageRecord | None, period: tuple[Located | None, Located | None],
                       doc_fuel: Located, unit_hint: Located | None) -> dict[str, Any]:
        values = StationaryCombustionExtractor._record_values(self, record, period, doc_fuel, unit_hint)
        quantity = values.get("activity_quantity")
        if record is None or quantity is None:
            return values
        located, number, _ = quantity
        normalized = self._to_mmbtu(number, self._record_unit(record, unit_hint))
        values["activity_quantity"] = (located, number, normalized)
        unit = values.get("activity_unit")
        if unit is not None:
            values["activity_unit"] = (unit[0], unit[1], normalized)
        return values

    @staticmethod
    def _to_mmbtu(number: tuple[float, str] | None, unit: str | None) -> fuel_units.NormalizedQuantity | None:
        """Thermal energy -> MMBtu. Steam by weight stays as written (its heat content is asked)."""

        if number is None or unit is None:
            return None
        if unit in STEAM_MASS_UNITS:
            return fuel_units.NormalizedQuantity(value=float(number[0]), unit=unit, dimension=fuel_units.MASS,
                                                 original_value=float(number[0]), original_unit=unit,
                                                 converted=False)
        if unit not in THERMAL_ENERGY_UNITS:
            return None
        value = float(number[0]) if unit == TARGET_UNIT else fuel_units.convert(number[0], unit, TARGET_UNIT)
        return fuel_units.NormalizedQuantity(value=value, unit=TARGET_UNIT, dimension=fuel_units.ENERGY,
                                             original_value=float(number[0]), original_unit=unit,
                                             converted=unit != TARGET_UNIT)
