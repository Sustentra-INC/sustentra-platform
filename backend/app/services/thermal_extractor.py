"""Scope 2 purchased steam, heat and cooling: deterministic extraction for CT-S2-THERMAL.

Reads district energy and steam bills for the inputs of workbook rows 48-50 (indirect
emissions from purchased steam, heating and cooling), the same fields as purchased
electricity:

    determinant  facility_name, service_address, supplier_name
    matching key account_number
    prorate      service_period_start, service_period_end
    input        energy_type (steam / hot_water / chilled_water), activity_quantity, activity_unit

The layout engine is the EXT-001 one; this module swaps the vocabulary. A quantity counts
when it is thermal energy (MMBtu, therms, dekatherms, kBtu, GJ, kWh, MWh or ton-hours),
normalized to MMBtu because the EPA steam and heat factor (Hub Table 7) is per MMBtu. Steam
billed by weight (lb, Mlb) is read as written: its energy needs the steam's heat content,
which the reviewer gives, so it is never guessed here.

The district energy units (kBtu, ton-hours, Mlb) are known only here (``fuel_units``
``thermal=True``), so they never change how fuel or electricity documents are read. Each
usage line takes its energy type from its own label ("Steam Usage", "Chilled Water Usage"),
so a bill for steam and chilled water keeps both; demand (per hour) and condensate-return
lines are not consumption.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any

from backend.app.domain import fuel_units
from backend.app.services.electricity_extractor import ElectricityExtractor, detect_electricity
from backend.app.services.mobile_combustion_extractor import normalize_mobile_fuel
from backend.app.services.stationary_combustion_extractor import (
    _ALL_LABELS as _BASE_LABELS,
)
from backend.app.services.stationary_combustion_extractor import (
    _PRODUCT_HEADERS,
    HALT_UNREADABLE,
    HALT_UNSUPPORTED,
    ExtractionOutcome,
    Located,
    Row,
    StationaryCombustionExtractor,
    UsageRecord,
    _norm,
    detect_fuel,
)

CANONICAL_TYPE_ID = "CT-S2-THERMAL"
TARGET_UNIT = "MMBtu"
STEAM, HOT_WATER, CHILLED_WATER = "steam", "hot_water", "chilled_water"
# Energy units a thermal bill states, and steam's weight units (energy needs a heat content).
THERMAL_ENERGY_UNITS = frozenset({"MMBtu", "Dth", "therm", "kBtu", "Btu", "GJ", "kWh", "MWh", "ton_hour"})
STEAM_MASS_UNITS = frozenset({"lb", "klb"})

# Strict cues only: "heat" alone also appears on gas bills ("heat content", "heating
# degree days"), and "thermal energy" names suppliers' businesses ("Thermal Energy
# Corporation"), so a hot-water service must be named as such.
_CUES: tuple[tuple[str, re.Pattern[str]], ...] = (
    (CHILLED_WATER, re.compile(r"(?<![a-z])(chilled water|district cooling|cooling services?|ton[- ]hours?)(?![a-z])")),
    (STEAM, re.compile(r"(?<![a-z])(steam)(?![a-z])")),
    (HOT_WATER, re.compile(r"(?<![a-z])(hot water|heating hot water|district heating|district heat|"
                           r"heating services?)(?![a-z])")),
)

ENERGY_TYPE_LABELS: tuple[tuple[str, ...], ...] = (
    ("energy type", "service type", "commodity", "product", "service"),
)
# One label group per commodity, so a combined bill yields one record each.
COMMODITY_LABELS: tuple[tuple[str, ...], ...] = (
    ("total steam usage", "total steam delivered", "steam usage", "steam delivered", "steam consumption",
     "total steam", "steam used"),
    ("hot water usage", "heating hot water usage", "heating usage", "heat delivered", "district heating usage"),
    ("chilled water usage", "cooling usage", "cooling delivered", "district cooling usage"),
)
GENERIC_LABELS: tuple[str, ...] = (
    "energy delivered", "thermal energy delivered", "total usage", "total consumption", "billed usage", "usage",
    "consumption", "mmbtu", "therms",
)
QUANTITY_LABELS: tuple[tuple[str, ...], ...] = (tuple(label for group in COMMODITY_LABELS for label in group)
                                                + GENERIC_LABELS,)
# Lines that are not energy consumed: demand (per hour) and condensate returned or credited.
_NOT_CONSUMPTION_RE = re.compile(r"(/\s*h(?:r|our)?\b|per\s+hour|\bdemand\b|condensate|\breturn(?:ed)?\b|\bcredit\b)")
# "(1000 lbs)" as a column header means thousands of pounds of steam.
_THOUSAND_LB_RE = re.compile(r"1,?000\s*(?:lbs?|pounds)")


def detect_thermal(text: str) -> tuple[str, str] | None:
    """(energy type, matched cue) when ``text`` names steam, hot water or chilled water."""

    normalized = _norm(text)
    for kind, pattern in _CUES:
        match = pattern.search(normalized)
        if match:
            return kind, match.group(0)
    return None


def thermal_kind(value: Any) -> str | None:
    """steam / hot_water / chilled_water from a stored or reviewer-typed energy type
    ("Chilled water", "hot-water", "Steam"), or None when it names none of them."""

    text = str(value or "").strip().lower()
    key = re.sub(r"[\s-]+", "_", text)
    if key in (STEAM, HOT_WATER, CHILLED_WATER):
        return key
    found = detect_thermal(text)
    return found[0] if found else None


# Unit words detect_fuel also takes as natural gas cues: a steam or hot water bill may be in therms.
_UNIT_ONLY_CUES = frozenset({"therm", "therms", "thm", "dekatherm", "dekatherms", "decatherm", "decatherms", "dth"})
# Unit words detect_electricity takes as electricity cues: district heat may be billed in MWh.
_ELECTRIC_UNIT_CUES = frozenset({"kwh", "mwh", "kilowatt hour", "kilowatt hours", "kilowatt-hour", "kilowatt-hours"})


def _names_fuel(rows: Sequence[Row]) -> bool:
    """True when any line names a combusted fuel (natural gas, oil, propane, diesel...)."""

    for row in rows:
        for cell in row.cells:
            hit = detect_fuel(cell.text)
            if (hit and hit[1].lower() not in _UNIT_ONLY_CUES) or normalize_mobile_fuel(cell.text):
                return True
    return False


def _names_electricity(rows: Sequence[Row]) -> bool:
    """True when any line names electricity in words ("Electric", "Electricity"), not only a unit."""

    for row in rows:
        for cell in row.cells:
            hit = detect_electricity(cell.text)
            if hit and hit[1].lower() not in _ELECTRIC_UNIT_CUES:
                return True
    return False


class ThermalExtractor(ElectricityExtractor):
    """Builds CT-S2-THERMAL candidates: one record per usage line (or one per bill)."""

    CANONICAL_TYPE_ID = CANONICAL_TYPE_ID
    FUEL_LABEL_GROUPS = ENERGY_TYPE_LABELS
    QUANTITY_LABEL_GROUPS = QUANTITY_LABELS
    QTY_EXCLUDE = StationaryCombustionExtractor.QTY_EXCLUDE + (
        "demand", "peak", "rate", "per ", "/hr", "/h", "condensate", "return", "credit")
    PRODUCT_HEADERS = _PRODUCT_HEADERS + ("service", "service type", "energy type")
    ALL_LABELS = _BASE_LABELS + tuple(label for group in (ENERGY_TYPE_LABELS + QUANTITY_LABELS) for label in group)

    # --- units: the district energy units are known here only ------------------------
    def _find_unit(self, text: str | None) -> str | None:
        return fuel_units.find_unit(text, thermal=True)

    def _canonical_unit(self, text: str | None) -> str | None:
        if text is not None and _THOUSAND_LB_RE.fullmatch(" ".join(str(text).strip(" ()").lower().split())):
            return "klb"  # a "(1000 lbs)" header
        return fuel_units.canonical_unit(text, thermal=True)

    def _record_unit(self, record: UsageRecord, unit_hint: Located | None) -> str | None:
        unit_text = record.unit_raw or (unit_hint.raw if unit_hint else None)
        if not unit_text:
            return None
        return self._canonical_unit(unit_text) or self._find_unit(unit_text)

    def _fuel(self, text: str) -> tuple[str, str] | None:
        return detect_thermal(text)

    def _quantity_header_score(self, text: str) -> int:
        score = StationaryCombustionExtractor._quantity_header_score(self, text)
        if score and "total" in text:
            score += 1
        return score

    # --- records ----------------------------------------------------------------------
    def _labeled_quantity_records(self, rows: Sequence[Row],
                                  label_groups: tuple[tuple[str, ...], ...] | None = None) -> list[UsageRecord]:
        """One labeled quantity per commodity ("Steam Usage", "Chilled Water Usage"), each
        typed by its own label; the generic labels ("Total Usage") only when none is named."""

        if label_groups is not None:
            return super()._labeled_quantity_records(rows, label_groups)
        records: list[UsageRecord] = []
        seen: set[int] = set()
        for group in COMMODITY_LABELS:
            for record in super()._labeled_quantity_records(rows, (group,)):
                key = id(record.quantity.cells[0]) if record.quantity.cells else id(record)
                if key in seen:
                    continue
                seen.add(key)
                label = record.quantity.label_cell
                if label is not None and detect_thermal(label.text):
                    record.fuel = Located(label.text, [label], record.quantity.row, record.quantity.confidence)
                records.append(record)
        return records or super()._labeled_quantity_records(rows, (GENERIC_LABELS,))

    def _record_kind(self, record: UsageRecord, document_kind: str | None) -> str | None:
        for text in (record.fuel.raw if record.fuel else None,
                     record.quantity.label_cell.text if record.quantity.label_cell else None):
            found = detect_thermal(text or "")
            if found:
                return found[0]
        return document_kind

    def _is_consumption(self, record: UsageRecord) -> bool:
        texts = [record.quantity.context or "", record.unit_raw or ""]
        if record.quantity.label_cell is not None:
            texts.append(record.quantity.label_cell.text)
        return not any(_NOT_CONSUMPTION_RE.search(_norm(t)) for t in texts)

    def _counts(self, unit: str | None, energy: str | None) -> bool:
        return unit in THERMAL_ENERGY_UNITS or (energy == STEAM and unit in STEAM_MASS_UNITS)

    def _usable(self, rows: Sequence[Row], unit_hint: Located | None, document_kind: str | None) -> list[UsageRecord]:
        return [r for r in self._quantity_records(rows)
                if self._is_consumption(r)
                and self._counts(self._record_unit(r, unit_hint), self._record_kind(r, document_kind))]

    def confirms(self, parser_output: dict) -> bool:
        """Content check: the document names steam, hot water or chilled water, states a
        thermal quantity, and names neither a combusted fuel nor electricity in words. A
        gas bill for a "Steam Boiler House" is the company's own fuel (Scope 1); an electric
        bill with a hot water tip is electricity."""

        rows = self._rows(parser_output)
        found = next((detect_thermal(c.text) for r in rows for c in r.cells if detect_thermal(c.text)), None)
        if found is None or _names_fuel(rows) or _names_electricity(rows):
            return False
        if StationaryCombustionExtractor().confirms(parser_output):
            return False
        return bool(self._usable(rows, self._document_unit(rows), found[0]))

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
        kind = detect_thermal(doc_energy.raw if doc_energy is not None else "")
        unit_hint = self._document_unit(rows)
        records = self._usable(rows, unit_hint, kind[0] if kind else None)
        if not records or doc_energy is None:
            return ExtractionOutcome(candidates=[], halt_reason={
                "code": HALT_UNSUPPORTED,
                "message": "No steam, hot water or chilled water quantity in a thermal unit (MMBtu, therms, "
                "kBtu, GJ, MWh, ton-hours, or pounds of steam) was found, so this is not purchased steam, heat "
                "or cooling evidence.",
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
