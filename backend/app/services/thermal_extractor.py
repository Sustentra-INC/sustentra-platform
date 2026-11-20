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
so a bill for steam and chilled water keeps both. When the label is generic, the nearest evidence decides:
the unit (ton-hours are chilled water, pounds are steam), the heading just above the table, then a bill that
names one type only. A bill that names several ("Steam & chilled water utility") with nothing near the
quantity gets no energy type and a warning, never a guess; demand (per hour) and condensate-return
lines are not consumption.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
import calendar
from dataclasses import dataclass
from datetime import date
from typing import Any

from backend.app.domain import fuel_units
from backend.app.services.electricity_extractor import ElectricityExtractor, detect_electricity
from backend.app.services.mobile_combustion_extractor import normalize_mobile_fuel
from backend.app.services.stationary_combustion_extractor import (
    _ALL_LABELS as _BASE_LABELS,
)
from backend.app.services.stationary_combustion_extractor import (
    _PRODUCT_HEADERS,
    CONF_DOCUMENT_SCAN,
    CONF_MISSING,
    HALT_UNREADABLE,
    HALT_UNSUPPORTED,
    ExtractionOutcome,
    Located,
    Row,
    StationaryCombustionExtractor,
    UsageRecord,
    _norm,
    detect_fuel,
    parse_date,
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


def thermal_kinds(text: str) -> set[str]:
    """Every energy type ``text`` names. A line naming two ("Steam & chilled water utility")
    decides neither."""

    normalized = _norm(text)
    return {kind for kind, pattern in _CUES if pattern.search(normalized)}


def _single_kind(text: str) -> str | None:
    kinds = thermal_kinds(text)
    return next(iter(kinds)) if len(kinds) == 1 else None


# How far above a usage line a heading ("Steam Consumption") still belongs to it.
_HEADING_REACH = 6
AMBIGUOUS_ENERGY_NOTE = (
    "The energy type (steam, hot water or chilled water) could not be told from the usage line, so it was left "
    "empty: the bill names more than one, or none, next to the quantity. Choose it before the figure is used."
)


@dataclass
class UsageTable:
    header: Row
    records: list[UsageRecord]
    history: bool


# A header row that calls its table a history or a comparison; "previous" and "prior" are left out here
# because "Previous Read" is an ordinary column of a current table.
_HISTORY_HEADER_RE = re.compile(
    r"(?<![a-z])(history|historical|last \d+ months?|\d+[- ]months?|year ago|comparison|compared|average|avg|trend)"
    r"(?![a-z])")
# A heading over the table ("Usage history", "Prior year", "Last 13 months", "Past usage").
_HISTORY_HEADING_RE = re.compile(
    r"(?<![a-z])(history|historical|prior|previous|past|last \d+ months?|\d+[- ]months?|year ago|comparison|"
    r"compared|average|avg|trend)(?![a-z])")
_MONTH_NAME_RE = re.compile(
    r"(?<![a-z])(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sep(?:t(?:ember)?)?|"
    r"oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)(?![a-z])")


_MONTH_NUMBERS = {m: i for i, m in enumerate(
    ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"), start=1)}


def _unread_table_note(page: int | None) -> str:
    where = f"on page {page}" if page else "in this document"
    return (f"A usage table {where} could not be read (its lines had no number in a thermal unit), so its "
            "figures are not in the values below. Check that table in the document.")


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
    HEADLINE_QUANTITY = False  # only the natural gas reader reads a number in large type over a unit
    INLINE_TOTAL_QUANTITY = False  # ... or "TOTAL 1,273.1 THERMS" inside a line of a statement
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

    def _record_kind(self, record: UsageRecord, rows: Sequence[Row], unit_hint: Located | None,
                     doc_kinds: set[str]) -> tuple[str, Located] | None:
        """The usage line's own energy type, from the nearest evidence first and never from a stray
        word elsewhere: its label, its unit (ton-hours are chilled water, pounds are steam), the heading
        just above its table, a labelled "Energy type" field, and last a bill that names one type only.
        None (with no guess) when the bill names several and nothing near the quantity chooses."""

        label = record.quantity.label_cell
        for located in (record.fuel, Located(label.text, [label], record.quantity.row, record.quantity.confidence)
                        if label is not None else None):
            kind = _single_kind(located.raw) if located is not None else None
            if kind and located is not None:
                return kind, located
        unit = self._record_unit(record, unit_hint)
        unit_located = record.unit_located or record.quantity
        if unit == "ton_hour":
            return CHILLED_WATER, unit_located
        if unit in STEAM_MASS_UNITS:
            return STEAM, unit_located
        heading = self._heading_above(record, rows)
        if heading is not None:
            return heading
        if len(doc_kinds) == 1:
            kind = next(iter(doc_kinds))
            for row in rows:
                for cell in row.cells:
                    if _single_kind(cell.text) == kind:
                        return kind, Located(cell.text, [cell], row, CONF_DOCUMENT_SCAN)
        return None

    @staticmethod
    def _heading_above(record: UsageRecord, rows: Sequence[Row]) -> tuple[str, Located] | None:
        row = record.quantity.row
        if row is None:
            return None
        positions = {id(r): i for i, r in enumerate(rows)}
        at = positions.get(id(row))
        if at is None:
            return None
        for above in range(at, max(at - _HEADING_REACH, -1) - 1, -1):
            candidate = rows[above]
            if candidate.page != row.page:
                break
            for cell in candidate.cells:
                kind = _single_kind(cell.text)
                if kind:
                    return kind, Located(cell.text, [cell], candidate, CONF_DOCUMENT_SCAN)
        return None

    def _is_consumption(self, record: UsageRecord) -> bool:
        """Whether this line is energy consumed. A table line is judged by its own quantity column's header
        and its own row, never by the other columns' headers: "Peak Demand (Mlb/hr)" beside "Steam Used (Mlb)"
        makes the demand column demand, not the usage column."""

        if record.quantity_header is not None:
            row_text = record.quantity.row.text if record.quantity.row is not None else ""
            texts = [record.quantity_header, row_text, record.unit_raw or ""]
        else:
            texts = [record.quantity.context or "", record.unit_raw or ""]
        if record.quantity.label_cell is not None:
            texts.append(record.quantity.label_cell.text)
        return not any(_NOT_CONSUMPTION_RE.search(_norm(t)) for t in texts)

    def _counts(self, unit: str | None, energy: str | None) -> bool:
        return unit in THERMAL_ENERGY_UNITS or (energy == STEAM and unit in STEAM_MASS_UNITS)

    def _usage_tables(self, rows: Sequence[Row]) -> tuple[list[UsageTable], list[Row]]:
        """Every usage table on the bill, not only the first: each table that reads (with its header row,
        its records and whether it is a history table), and the header rows of those that do not. A table
        continued under a repeated header, on the next page, is one table (``_table_records`` follows it),
        so a header inside a table already read is not a new table."""

        tables: list[UsageTable] = []
        unread: list[Row] = []
        covered = -1
        period_start = self._period_start(rows)
        for row in rows:
            if row.index <= covered:
                continue
            header = self._usage_header(row)
            if header is None:
                continue
            records = self._table_records(rows, row, header)
            if not records:
                unread.append(row)
                continue
            tables.append(UsageTable(row, records, self._is_history(rows, row, records, period_start)))
            covered = max((r.quantity.row.index for r in records if r.quantity.row is not None), default=row.index)
        return tables, unread

    def _period_start(self, rows: Sequence[Row]) -> date | None:
        """The first day of the bill's own service period, when one was read."""

        start, _ = self._document_period(rows)
        found = parse_date(start.raw) if start is not None else None
        return date.fromisoformat(found[0]) if found else None

    @staticmethod
    def _headings(rows: Sequence[Row], header: Row) -> list[Row]:
        """The short lines just above a table (its heading), on the same page."""

        return [r for r in rows[max(header.index - 2, 0):header.index]
                if r.page == header.page and len(r.cells) <= 2]

    @classmethod
    def _names_history(cls, rows: Sequence[Row], header: Row) -> bool:
        """The table's header row, or the heading over it, calls it history or a comparison."""

        if _HISTORY_HEADER_RE.search(_norm(header.text)):
            return True
        return any(_HISTORY_HEADING_RE.search(_norm(r.text)) for r in cls._headings(rows, header))

    def _is_history(self, rows: Sequence[Row], header: Row, records: Sequence[UsageRecord],
                    period_start: date | None) -> bool:
        """A usage history ("Last 13 months", "Prior year"). It shows past use, not this bill's reading, so
        it is never counted: adding it would count a year of use again on every bill.

        Its own header or heading calling it a history decides. Otherwise its content does, but only on
        evidence that cannot catch a current quarterly bill (Jan, Feb, Mar as three current lines): with the
        bill's period read, a month or date wholly before that period's start; with no period read, six or
        more distinct months (a real history runs 12 or 13, a current bill rarely past a quarter)."""

        if self._names_history(rows, header):
            return True
        months: set[tuple[int | None, int]] = set()
        before = False
        for record in records:
            row = record.quantity.row
            if row is None:
                continue
            for cell in row.cells:
                if cell in record.quantity.cells:
                    continue
                dated = parse_date(cell.text)
                if dated is not None:
                    when = date.fromisoformat(dated[0])
                    months.add((when.year, when.month))
                    last_day = date(when.year, when.month, calendar.monthrange(when.year, when.month)[1])
                    before = before or (period_start is not None and last_day < period_start)
                    continue
                name = _MONTH_NAME_RE.search(_norm(cell.text))
                if name:
                    month = _MONTH_NUMBERS[name.group(0)[:3]]
                    months.add((None, month))
                    # a month with no year is read in the year the bill's period starts
                    before = before or (period_start is not None and month < period_start.month)
        if period_start is not None:
            return before
        return len(months) >= 6

    @staticmethod
    def _share_type_within_table(table: Sequence[UsageRecord]) -> None:
        """A table is one commodity. A line the evidence did not type (the part of a table continued on the
        next page, away from its heading) takes the type its sibling lines agree on."""

        typed = {r.energy for r in table if r.energy}
        if len(typed) != 1:
            return
        donor = next(r for r in table if r.energy)
        for record in table:
            if not record.energy and record.fuel is None:
                record.energy, record.fuel = donor.energy, donor.fuel

    def _usable(self, rows: Sequence[Row], unit_hint: Located | None, doc_kinds: set[str],
                records: Sequence[UsageRecord]) -> list[UsageRecord]:
        """The lines of one table (or the labeled quantities) that are energy consumed. Each is typed
        from its own evidence, then an untyped line takes its table's agreed type, and only then is the
        unit checked: a continued steam table in Mlb has lines that count only once they are known to be steam."""

        typed: list[UsageRecord] = []
        for record in records:
            if not self._is_consumption(record):
                continue
            found = self._record_kind(record, rows, unit_hint, doc_kinds)
            if found is not None:
                record.energy, record.fuel = found
            typed.append(record)
        self._share_type_within_table(typed)
        return [r for r in typed if self._counts(self._record_unit(r, unit_hint), r.energy)]

    def _read_tables(self, rows: Sequence[Row], unit_hint: Located | None,
                     doc_kinds: set[str]) -> tuple[list[UsageRecord], list[Row]]:
        """The bill's usable lines, and the header rows of usage tables that could not be read.

        History tables are skipped (and never reported: a history is not a missed reading). If every table
        that reads is a history, the first is used as before. After the first table counted, another counts
        only when it is a commodity not yet counted or carries a meter or account id not yet seen: a second
        table of the same commodity with no new meter is not a new reading."""

        tables, unread = self._usage_tables(rows)
        unread = [h for h in unread if not self._names_history(rows, h)]
        if not tables:
            return self._usable(rows, unit_hint, doc_kinds, self._labeled_quantity_records(rows)), unread
        chosen = [t for t in tables if not t.history] or tables[:1]
        usable: list[UsageRecord] = []
        kinds: set[str] = set()
        ids: set[str] = set()
        problems = list(unread)
        for table in chosen:
            mine = self._usable(rows, unit_hint, doc_kinds, table.records)
            if not mine:
                problems.append(table.header)
                continue
            mine_kinds = {r.energy for r in mine if r.energy}
            mine_ids = {_norm(r.hint) for r in mine if r.hint and r.hint.strip()}
            if usable and not (mine_kinds - kinds) and not (mine_ids - ids):
                continue
            usable.extend(mine)
            kinds |= mine_kinds
            ids |= mine_ids
        return usable, sorted(problems, key=lambda h: h.index)

    @staticmethod
    def _document_kinds(rows: Sequence[Row]) -> set[str]:
        return {kind for row in rows for cell in row.cells for kind in thermal_kinds(cell.text)}

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
        return bool(self._read_tables(rows, self._document_unit(rows), self._document_kinds(rows))[0])

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
        records, notes = self._part_records(rows, unit_hint)
        if not records:
            return ExtractionOutcome(candidates=[], halt_reason={
                "code": HALT_UNSUPPORTED,
                "message": "No steam, hot water or chilled water quantity in a thermal unit (MMBtu, therms, "
                "kBtu, GJ, MWh, ton-hours, or pounds of steam) was found, so this is not purchased steam, heat "
                "or cooling evidence.",
            })
        # Each record carries its own energy type; the placeholder only stands in where none was told.
        placeholder = Located("", [], None, CONF_MISSING)
        outcome = self._statement_bundle(rows, parser_output, targets, evidence_id, document_id, unit_hint,
                                         placeholder, notes)
        if outcome is None:
            outcome = self._records_to_candidates(rows, parser_output, targets, evidence_id, document_id, records,
                                                  placeholder, unit_hint)
            outcome.notes.extend(notes)
        return outcome

    # --- the readings of one statement (the hooks of the electricity extractor's bundle reader) -------------
    def _part_records(self, rows: Sequence[Row], unit_hint: Located | None) -> tuple[list[UsageRecord], list[str]]:
        records, unread = self._read_tables(rows, unit_hint, self._document_kinds(rows))
        records, summary_notes = self._without_account_summaries(rows, records)
        notes = [AMBIGUOUS_ENERGY_NOTE] if any(r.fuel is None for r in records) else []
        notes.extend(summary_notes)
        # Nothing drops silently: a table whose header was found but whose lines gave no usable thermal
        # quantity is named by its page. (A history table is not a missed reading and is not named.)
        notes.extend(_unread_table_note(header.page) for header in unread)
        return records, notes

    def _part_energy(self, rows: Sequence[Row]) -> Located | None:
        return Located("", [], None, CONF_MISSING)  # the energy type is each record's own

    # ---------------------------------------------------------------------------------
    def _record_values(self, record: UsageRecord | None, period: tuple[Located | None, Located | None],
                       doc_fuel: Located, unit_hint: Located | None) -> dict[str, Any]:
        values = StationaryCombustionExtractor._record_values(self, record, period, doc_fuel, unit_hint)
        if record is not None:  # the energy type is the line's own: a bill-wide word never fills it in
            values["fuel_type"] = (record.fuel or doc_fuel, record.energy)
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
