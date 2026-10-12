"""Scope 2 purchased electricity: deterministic extraction for CT-S2-ELEC.

Reads utility electricity bills for the location-based inputs listed in "Data from
Evidence (Scope 2)" of the GHG Required Data workbook:

    determinant  facility_name, service_address, supplier_name (the utility)
    matching key account_number
    prorate      service_period_start, service_period_end
    input        energy_type, activity_quantity, activity_unit

Market-based inputs (certificate coverage, REC retirement statements) come from the
company workbook and certificate documents, not the bill, so they are not read here.

The layout engine (visual rows, label/value lookup, usage tables, bounding boxes) is
the EXT-001 one; this module swaps the vocabulary. The energy type is electricity and
a quantity only counts when its unit is kWh or MWh. Quantities are normalized to MWh
because grid emission factors (eGRID, EPA GHG Emission Factors Hub) are per MWh.
Demand (kW), reactive power (kVARh) and power/load factors are never read as
consumption.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any

from backend.app.domain import fuel_units
from backend.app.services.stationary_combustion_extractor import (
    _ALL_LABELS as _BASE_LABELS,
)
from backend.app.services.stationary_combustion_extractor import (
    CONF_LETTERHEAD,
    DOCUMENT_FIELDS,
    DOCUMENT_TITLE_WORDS,
    ELECTRIC_UNITS,
    HALT_UNREADABLE,
    HALT_UNSUPPORTED,
    RECORD_FIELDS,
    ExtractionOutcome,
    Located,
    Row,
    StationaryCombustionExtractor,
    UsageRecord,
    _norm,
)

CANONICAL_TYPE_ID = "CT-S2-ELEC"
ENERGY_TYPE = "electricity"
TARGET_UNIT = "MWh"

# Whole-word electricity cues. "Electric" also covers utility names such as
# "Pacific Gas and Electric", which is fine: on this document type the energy is power.
_ELECTRIC_RE = re.compile(r"(?<![a-z0-9])(electricity|electrical|electric|kwh|mwh|kilowatt[- ]hours?)(?![a-z0-9])")

ENERGY_TYPE_LABELS: tuple[tuple[str, ...], ...] = (
    ("energy type", "service type", "commodity", "utility type", "service"),
)
# The workbook's common labels ("Total kWh", "kWh Used", "Usage (kWh)", "Total Usage",
# "Total Consumption", "Billed kWh", "kWh This Period") plus their usual longer forms, then
# generic fallbacks. The longest label that prefixes a cell wins, so "Total kWh Used" needs
# its own entry: "total kwh" alone would leave "Used" behind and read the cell as a phrase.
QUANTITY_LABELS: tuple[tuple[str, ...], ...] = (
    ("total kwh used", "total kwh billed", "total kwh consumed", "kwh used this period", "kwh this period",
     "total kwh", "kwh used", "kwh consumed", "kwh delivered", "billed kwh", "net kwh",
     "total mwh used", "total mwh", "mwh used",
     "total electricity consumption", "total electricity used", "electricity consumption", "electricity used",
     "total energy used", "energy consumption", "energy used", "energy usage",
     "total usage", "total consumption", "billed usage", "usage", "consumption", "kwh"),
)


# Words that name an electric utility in a plain-text letterhead ("Riverside Electric Utility",
# "Valley Power and Light", "Southern California Edison", "Pedernales Electric Cooperative").
_UTILITY_NAME_RE = re.compile(
    r"\b(company|co\.|inc\.?|llc|ltd\.?|corp\.?|utility|utilities|power|light|electric|energy|edison"
    r"|cooperative|co-op|authority)\b",
    re.I,
)


def detect_electricity(text: str) -> tuple[str, str] | None:
    """(energy_type, matched cue) when ``text`` names electricity, else None."""

    match = _ELECTRIC_RE.search(_norm(text))
    return (ENERGY_TYPE, match.group(0)) if match else None


class ElectricityExtractor(StationaryCombustionExtractor):
    """Builds CT-S2-ELEC candidates: one record per metered usage line (or one per bill)."""

    CANONICAL_TYPE_ID = CANONICAL_TYPE_ID
    FUEL_LABEL_GROUPS = ENERGY_TYPE_LABELS
    QUANTITY_LABEL_GROUPS = QUANTITY_LABELS
    QTY_EXCLUDE = StationaryCombustionExtractor.QTY_EXCLUDE + (
        "demand", "kvar", "power factor", "load factor",
    )
    ALL_LABELS = _BASE_LABELS + tuple(
        label for group in (ENERGY_TYPE_LABELS + QUANTITY_LABELS) for label in group
    )

    def _fuel(self, text: str) -> tuple[str, str] | None:
        return detect_electricity(text)

    def _quantity_header_score(self, text: str) -> int:
        score = super()._quantity_header_score(text)
        # Time-of-use bills list on-peak, off-peak and total kWh: prefer the total.
        if score and "total" in text and fuel_units.find_unit(text) in ELECTRIC_UNITS:
            score += 1
        return score

    def _letterhead(self, rows: Sequence[Row]) -> Located | None:
        """The utility name at the top of the bill.

        Laid-out PDFs use the base rule (largest text near the top). Plain text has no
        geometry, so the first top line that names an electric utility is taken.
        """

        found = super()._letterhead(rows)
        if found is not None or not rows:
            return found
        first_page = [r for r in rows if (r.page or 1) == (rows[0].page or 1)][:4]
        if any(c.box for r in first_page for c in r.cells):
            return None
        for row in first_page:
            if len(row.cells) != 1:
                continue
            text = row.cells[0].text
            name = re.split(r"\s+[-–—|]\s+", text)[0].strip()
            if _norm(name).startswith(DOCUMENT_TITLE_WORDS) or "electricity" in _norm(name):
                continue  # "Electricity Bill", "Statement of Account" are titles, not names
            if _UTILITY_NAME_RE.search(name) and self._looks_like_org_name(name):
                return Located(name, [row.cells[0]], row, CONF_LETTERHEAD - 0.05, context=text)
        return None

    def _record_unit(self, record: UsageRecord, unit_hint: Located | None) -> str | None:
        unit_text = record.unit_raw or (unit_hint.raw if unit_hint else None)
        if not unit_text:
            return None
        return fuel_units.canonical_unit(unit_text) or fuel_units.find_unit(unit_text)

    def confirms(self, parser_output: dict) -> bool:
        """Content check: the document names electricity and states a kWh/MWh quantity."""

        rows = self._rows(parser_output)
        if not any(detect_electricity(cell.text) for row in rows for cell in row.cells):
            return False
        unit_hint = self._document_unit(rows)
        return any(self._record_unit(r, unit_hint) in ELECTRIC_UNITS for r in self._quantity_records(rows))

    # ---------------------------------------------------------------------------------
    def _extract(self, rows: list[Row], parser_output: dict, targets: Sequence[dict], evidence_id: str,
                 document_id: str) -> ExtractionOutcome:
        if not any(cell.text.strip() for row in rows for cell in row.cells):
            return ExtractionOutcome(candidates=[], halt_reason={
                "code": HALT_UNREADABLE,
                "message": "No readable text was found in the document (for example a scan without a text "
                "layer while OCR is off, or an empty file). Upload a text-based PDF or enable OCR.",
            })

        unit_hint = self._document_unit(rows)
        records = [r for r in self._quantity_records(rows) if self._record_unit(r, unit_hint) in ELECTRIC_UNITS]
        doc_energy = self._document_fuel(rows)
        if not records or doc_energy is None:
            return ExtractionOutcome(candidates=[], halt_reason={
                "code": HALT_UNSUPPORTED,
                "message": "No electricity quantity in kWh or MWh was found, so this is not purchased-"
                "electricity evidence (for example a gas, fuel or water bill).",
            })

        facility, address_from_facility = self._facility(rows)
        document_values: dict[str, Located | None] = {
            "facility_name": facility,
            "service_address": self._address(rows) or address_from_facility,
            "supplier_name": self._supplier(rows),
            "account_number": self._account(rows),
        }
        period = self._document_period(rows)

        candidates: list[dict] = []
        multi = len(records) > 1
        for index, record in enumerate(records, start=1):
            values = self._record_values(record, period, doc_energy, unit_hint)
            record_index = index if multi else None
            record_key = self._record_key(index, record, values) if multi else None
            record_candidates: list[dict] = []
            for target in targets:
                field_id = str(target.get("field_id") or "")
                if field_id in DOCUMENT_FIELDS:
                    record_candidates.append(self._candidate_for_text(
                        target, document_values.get(field_id), document_id, evidence_id, record_key,
                        record_index, parser_output, field_id))
                elif field_id == "energy_type" or field_id in RECORD_FIELDS:
                    record_candidates.append(self._record_candidate(
                        target, values, document_id, evidence_id, record_key, record_index, parser_output))
                else:
                    record_candidates.append(self._missing(target, document_id, evidence_id, record_key,
                                                           record_index, ["unsupported_extraction_method"]))
            if multi:
                label = self._record_display(index, record, values)
                for candidate in record_candidates:
                    candidate["display_label"] = f"{candidate['display_label']} ({label})"
                    candidate["source_reference"]["record_key"] = record_key
            candidates.extend(record_candidates)
        return ExtractionOutcome(candidates=candidates, records=len(records))

    # ---------------------------------------------------------------------------------
    def _record_values(self, record: UsageRecord | None, period: tuple[Located | None, Located | None],
                       doc_fuel: Located, unit_hint: Located | None) -> dict[str, Any]:
        values = super()._record_values(record, period, doc_fuel, unit_hint)
        quantity = values.get("activity_quantity")
        if record is None or quantity is None:
            return values
        located, number, _ = quantity
        normalized = self._to_mwh(number, self._record_unit(record, unit_hint))
        values["activity_quantity"] = (located, number, normalized)
        unit = values.get("activity_unit")
        if unit is not None:
            values["activity_unit"] = (unit[0], unit[1], normalized)
        return values

    @staticmethod
    def _to_mwh(number: tuple[float, str] | None, unit: str | None) -> fuel_units.NormalizedQuantity | None:
        """kWh/MWh -> MWh. The shared fuel normalizer would turn kWh into MMBtu."""

        if number is None or unit not in ELECTRIC_UNITS:
            return None
        value = float(number[0]) if unit == TARGET_UNIT else fuel_units.convert(number[0], unit, TARGET_UNIT)
        return fuel_units.NormalizedQuantity(
            value=value,
            unit=TARGET_UNIT,
            dimension=fuel_units.ENERGY,
            original_value=float(number[0]),
            original_unit=unit,
            converted=unit != TARGET_UNIT,
        )

    def _record_candidate(self, target: dict, values: dict[str, Any], document_id: str, evidence_id: str,
                          record_key: str | None, record_index: int | None, parser_output: dict) -> dict:
        if str(target.get("field_id")) != "energy_type":
            return super()._record_candidate(target, values, document_id, evidence_id, record_key, record_index,
                                             parser_output)
        located, energy = values["fuel_type"]
        if energy is None:
            return self._missing(target, document_id, evidence_id, record_key, record_index)
        return self._candidate(target, located, located.raw, energy, None, document_id, evidence_id, record_key,
                               record_index, parser_output, [])
