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
from backend.app.services.statement_segments import SPLIT_NOTE, split_statements
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
    parse_number,
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


# Time-of-use lines that are parts of a total ("On-Peak kWh", "Off-Peak kWh", "Part-Peak", "Shoulder").
_COMPONENT_RE = re.compile(
    r"(?<![a-z])(?:(?:on|off|mid|part|super[- ]?off)[- ]?peak|shoulder|peak)(?![a-z])")
_TOTAL_RE = re.compile(r"^total(?![a-z])")
TOU_TOLERANCE = 0.005  # parts add up to their total within half a percent
TOU_NOTE = ("Time-of-use lines (on-peak, off-peak) were read as separate records because no total line adds "
            "up to them. Check that none of them is counted twice.")
# The header text of a table row's context ("Meter | Register | Usage | <row text>"), the row's own cells excluded.
_HEADER_SEPARATOR = " | "


def _labels(record: UsageRecord) -> list[str]:
    """The text cells of the record's row (the quantity cell and bare numbers left out)."""

    row = record.quantity.row
    if row is None:
        return []
    return [_norm(cell.text) for cell in row.cells
            if cell not in record.quantity.cells and re.search(r"[a-z]", _norm(cell.text))]


def _is_part(record: UsageRecord) -> bool:
    """A time-of-use line: the peak label can sit in any text cell of the row (the register or the
    description, not only the first), and a row that is a part is never also a total."""

    return any(_COMPONENT_RE.search(label) for label in _labels(record))


def _is_total(record: UsageRecord) -> bool:
    return not _is_part(record) and any(_TOTAL_RE.match(label) for label in _labels(record))


def _block_key(record: UsageRecord) -> str:
    context = record.quantity.context or ""
    return context.split(_HEADER_SEPARATOR, 1)[0]


def _blocks(records: list[UsageRecord]) -> list[list[UsageRecord]]:
    """Records grouped by table and meter: a new block starts when the table header changes or a different
    meter id begins (a line with no meter id belongs to the meter above it)."""

    blocks: list[list[UsageRecord]] = []
    meter: str | None = None
    for record in records:
        hint = _norm(record.hint) if record.hint else None
        if hint is not None and (_COMPONENT_RE.search(hint) or _TOTAL_RE.match(hint)):
            hint = None  # a peak or total label in the meter column is a line, not another meter
        new = (not blocks or _block_key(blocks[-1][0]) != _block_key(record)
               or (hint is not None and meter is not None and hint != meter)
               or (_is_total(record) and any(_is_total(r) for r in blocks[-1])))  # a second total: a table again
        if new:
            blocks.append([])
            meter = None
        blocks[-1].append(record)
        if hint is not None:
            meter = hint
    return blocks


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
        doc_energy = self._document_fuel(rows)
        records, notes = self._part_records(rows, unit_hint)
        if not records or doc_energy is None:
            return ExtractionOutcome(candidates=[], halt_reason={
                "code": HALT_UNSUPPORTED,
                "message": "No electricity quantity in kWh or MWh was found, so this is not purchased-"
                "electricity evidence (for example a gas, fuel or water bill).",
            })
        outcome = self._statement_bundle(rows, parser_output, targets, evidence_id, document_id, unit_hint,
                                         doc_energy, notes)
        if outcome is None:
            outcome = self._records_to_candidates(rows, parser_output, targets, evidence_id, document_id, records,
                                                  doc_energy, unit_hint)
            outcome.notes.extend(notes)
        return outcome

    # --- the readings of one statement (hooks the thermal extractor overrides) ---------------------------
    def _part_records(self, rows: Sequence[Row], unit_hint: Located | None) -> tuple[list[UsageRecord], list[str]]:
        """The metered usage lines of ``rows`` in kWh or MWh, with a note for anything the reviewer should
        check. A time-of-use table lists on-peak and off-peak lines beside the total."""

        records = [r for r in self._quantity_records(rows) if self._record_unit(r, unit_hint) in ELECTRIC_UNITS]
        return self._collapse_time_of_use(records, rows, unit_hint)

    def _part_energy(self, rows: Sequence[Row]) -> Located | None:
        return self._document_fuel(rows)

    def _mwh(self, record: UsageRecord, unit_hint: Located | None) -> float | None:
        number = parse_number(record.quantity.raw)
        normalized = self._to_mwh(number, self._record_unit(record, unit_hint))
        return normalized.value if normalized is not None else None

    def _collapse_time_of_use(self, records: list[UsageRecord], rows: Sequence[Row],
                              unit_hint: Located | None) -> tuple[list[UsageRecord], list[str]]:
        """Per meter or table block: when the on-peak, off-peak and similar lines add up to the block's own
        total (a line labelled total, or the Total row right under the table) within half a percent, the total
        is the record and the parts are not. Parts that do not add up, or have no total, are all kept and
        the reviewer is told: dropping a meter's real usage would be silent, keeping it is visible."""

        out: list[UsageRecord] = []
        notes: list[str] = []
        for block in _blocks(records):
            parts = [r for r in block if _is_part(r)]
            if not parts:
                out.extend(block)
                continue
            values = [self._mwh(r, unit_hint) for r in parts]
            total_record = next((r for r in block if _is_total(r)), None)
            if total_record is None:
                total_record = self._total_row_under(parts, rows, unit_hint)
            total = self._mwh(total_record, unit_hint) if total_record is not None else None
            if (total_record is None or total is None or None in values
                    or abs(sum(v for v in values if v is not None) - total) > TOU_TOLERANCE * abs(total)):
                out.extend(block)
                if TOU_NOTE not in notes:
                    notes.append(TOU_NOTE)
                continue
            out.extend(r for r in block if r not in parts)
            if total_record not in block:  # the Total row under the table, read as a record of its own
                out.append(total_record)
        return out, notes

    def _total_row_under(self, parts: list[UsageRecord], rows: Sequence[Row],
                         unit_hint: Located | None) -> UsageRecord | None:
        """A "Total" row right under the time-of-use lines, as a record of its own (the table reader stops at
        it): its figure is the cell nearest the parts' sum."""

        last = parts[-1].quantity.row
        if last is None or last.index + 1 >= len(rows):
            return None
        under = rows[last.index + 1]
        if not under.cells or _TOTAL_RE.match(_norm(under.cells[0].text)) is None:
            return None
        wanted = sum(v for v in (self._mwh(r, unit_hint) for r in parts) if v is not None)
        best: tuple[float, Any, Any] | None = None
        for cell in under.cells[1:]:
            number = parse_number(cell.text)
            if number is None:
                continue
            probe = UsageRecord(quantity=Located(number[1], [cell], under, parts[-1].quantity.confidence),
                                unit_raw=parts[-1].unit_raw, unit_located=parts[-1].unit_located, hint=None)
            value = self._mwh(probe, unit_hint)
            if value is not None and (best is None or abs(value - wanted) < best[0]):
                best = (abs(value - wanted), cell, number)
        if best is None:
            return None
        _, cell, number = best
        header = (parts[-1].quantity.context or "").split(_HEADER_SEPARATOR, 1)[0]
        quantity = Located(number[1], [cell], under, parts[-1].quantity.confidence,
                           context=f"{header}{_HEADER_SEPARATOR}{under.text}")
        return UsageRecord(quantity=quantity, unit_raw=parts[-1].unit_raw, unit_located=parts[-1].unit_located,
                           hint=None)

    def _statement_bundle(self, rows: list[Row], parser_output: dict, targets: Sequence[dict], evidence_id: str,
                          document_id: str, unit_hint: Located | None, doc_energy: Located,
                          notes: list[str]) -> ExtractionOutcome | None:
        """One record per statement for a file holding several (EXT-015), numbered in file order and
        read from each statement's own pages. None when the file is read whole: it is a single statement,
        a clean cut is not possible, or fewer than two of its parts hold a reading. A file that looks like
        several statements but is read whole says so in ``notes``."""

        split = split_statements(rows)
        if split.parts is None:
            if split.note:
                notes.append(split.note)
            return None
        bundle_notes = [split.note] if split.note else []
        found: list[tuple[list[Row], Located | None, list[UsageRecord]]] = []
        part_notes: list[str] = []
        for part in split.parts:
            part_hint = self._document_unit(part) or unit_hint
            records, more = self._part_records(part, part_hint)
            if records:
                found.append((part, part_hint, records))
                part_notes.extend(n for n in more if n not in part_notes)
        if len(found) < 2:
            notes.append(SPLIT_NOTE)
            return None
        candidates: list[dict] = []
        first_index = 1
        for part, part_hint, records in found:
            energy = self._part_energy(part) or doc_energy
            outcome = self._records_to_candidates(part, parser_output, targets, evidence_id, document_id, records,
                                                  energy, part_hint, first_index=first_index, multi=True)
            candidates.extend(outcome.candidates)
            first_index += len(records)
        return ExtractionOutcome(candidates=candidates, records=first_index - 1,
                                 notes=[*bundle_notes, *(n for n in part_notes if n not in bundle_notes)])

    def _records_to_candidates(self, rows: list[Row], parser_output: dict, targets: Sequence[dict],
                               evidence_id: str, document_id: str, records: list[UsageRecord],
                               doc_energy: Located, unit_hint: Located | None, *, first_index: int = 1,
                               multi: bool | None = None) -> ExtractionOutcome:
        """One candidate per target for each usage record; the bill's own fields (facility,
        address, supplier, account) are shared by its records. A statement of a bundle is numbered
        on from the statements before it (``first_index``, ``multi``)."""

        facility, address_from_facility = self._facility(rows)
        document_values: dict[str, Located | None] = {
            "facility_name": facility,
            "service_address": self._address(rows) or address_from_facility,
            "supplier_name": self._supplier(rows),
            "account_number": self._account(rows),
        }
        period = self._document_period(rows)

        candidates: list[dict] = []
        multi = len(records) > 1 if multi is None else multi
        for index, record in enumerate(records, start=first_index):
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
