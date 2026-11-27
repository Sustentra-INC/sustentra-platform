"""Score extractor output against answer-key cells.

Pure functions over ``ExtractedDoc`` and ``KeyCell``: no pipeline, no files. Rules:

* **match / wrong / missed** only for a key cell whose family the extractor reads. ``wrong`` needs a
  value that differs from the key; ``missed`` is no value (or no such record).
* A value the key does not cover is **never wrong**: it is counted as extracted-but-unscored.
* **not_targeted** when the extractor has no field for the family (meter reads, demand, amounts...).
* **unscored** for key cells that are not a reading (notes, reporting set, non-evidence documents,
  records that cannot be resolved, unmapped fields).
* A **silent error** is a ``wrong`` whose candidate carried no warning flag and was not low confidence.

Number tolerance: a value read as printed must match exactly; a value that went through a unit
conversion, and every total, may differ by 0.1% relative (``REL_TOL``). ``exact`` records which.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal

from backend.tools.accuracy.keys import KeyCell, ParsedLabel, Selector, parse_label, record_ordinal
from backend.tools.accuracy.mapping import FAMILIES, META, REPORTING, UNMAPPED, family_of, total_fuel_filter
from backend.tools.accuracy.model import (
    MATCH, MISSED, NOT_TARGETED, UNSCORED, WRONG, ExtractedDoc, Item, Outcome,
)
from backend.tools.accuracy.normalize import (
    convert, is_exact, norm_id, norm_name, norm_refrigerant, norm_unit, numbers_equal, parse_date, parse_number,
)

REL_TOL = Decimal("0.001")

NON_EVIDENCE_TYPES = re.compile(r"not source evidence|client note|client free-text|inventory summary|supply contract|unstructured",
                                re.I)
NON_EVIDENCE_TRAPS = re.compile(r"not source evidence|unstructured|not evidence of consumption", re.I)
# A key facility that says the platform must NOT place the document (an annex, no address).
DOCUMENT_LEVEL = frozenset({"supplier", "account", "statement_date", "meter"})
UNPLACED = re.compile(r"\s*(unmatched|unassigned)", re.I)
REPORTING_TYPES = re.compile(r"ghg statement|ghg workbook|rec retirement|expected recalculation|^comparison$", re.I)
QUANTITY_FIELDS = ("activity_quantity", "refrigerant_added", "distance")
ID_FIELDS = ("vehicle_or_equipment_id", "equipment_id", "meter_number", "refrigerant_type", "account_number")
DATE_FIELDS = ("service_period_start", "service_period_end", "transaction_date", "service_date")


def doc_role(cells: list[KeyCell]) -> str:
    """"evidence", "non_evidence" (a company inventory, a client note, a contract) or "reporting"."""

    doc_type = cells[0].document_type
    if NON_EVIDENCE_TYPES.search(doc_type) or any(NON_EVIDENCE_TRAPS.search(c.extra.get("trap", "")) for c in cells):
        return "non_evidence"
    if REPORTING_TYPES.search(doc_type):
        return "reporting"
    return "evidence"


@dataclass
class Record:
    index: int
    items: dict[str, Item]
    nulls: dict[str, Item]

    def get(self, fields: tuple[str, ...]) -> Item | None:
        for name in fields:
            if name in self.items:
                return self.items[name]
        return None

    def null_item(self, fields: tuple[str, ...]) -> Item | None:
        for name in fields:
            if name in self.nulls:
                return self.nulls[name]
        return None

    def day(self, name: str) -> date | None:
        item = self.items.get(name)
        return parse_date(item.value if item and item.value is not None else (item.raw if item else None))

    @property
    def dates(self) -> set[date]:
        return {d for d in (self.day(n) for n in DATE_FIELDS) if d}

    @property
    def id_tokens(self) -> set[str]:
        tokens = {norm_id(self.items[f].value if self.items[f].value is not None else self.items[f].raw)
                  for f in ID_FIELDS if f in self.items}
        keys = {norm_id(i.record_key) for i in self.items.values() if i.record_key}
        gas = {norm_refrigerant(self.items["refrigerant_type"].value)} if "refrigerant_type" in self.items else set()
        return {t for t in tokens if t} | keys | gas


def records_of(doc: ExtractedDoc) -> list[Record]:
    grouped: dict[int, list[Item]] = defaultdict(list)
    for item in doc.items:
        grouped[item.record if item.record is not None else 0].append(item)
    out: list[Record] = []
    for index in sorted(grouped):
        items: dict[str, Item] = {}
        nulls: dict[str, Item] = {}
        for item in grouped[index]:
            if item.has_value:
                best = items.get(item.field)
                if best is None or (item.confidence or 0) > (best.confidence or 0):
                    items[item.field] = item
            else:
                nulls.setdefault(item.field, item)
        out.append(Record(index, items, nulls))
    return out


def _unit_of(record: Record, item: Item) -> str:
    """The unit printed for a quantity: the record's activity_unit raw value, else the item's own."""

    unit_item = record.items.get("activity_unit")
    if item.field == "activity_quantity" and unit_item is not None and unit_item.raw:
        return str(unit_item.raw)
    return item.unit or ""


def select_records(records: list[Record], selector: Selector, anchor: tuple[date | None, date | None] | None) -> list[Record]:
    """The records a key cell is about. An empty selector (and no anchor) selects every record."""

    chosen = records
    if selector.row:
        chosen = [r for r in chosen if r.index == selector.row]
    if anchor and (anchor[0] or anchor[1]):
        chosen = [r for r in chosen if (not anchor[0] or r.day("service_period_start") == anchor[0])
                  and (not anchor[1] or r.day("service_period_end") == anchor[1])]
    if selector.ids:
        chosen = [r for r in chosen if all(any(i in t for t in r.id_tokens) for i in selector.ids)]
    if selector.dates:
        chosen = [r for r in chosen if any(d in r.dates for d in selector.dates)]
    if selector.month and not anchor:
        def hit(r: Record, name: str) -> bool:
            d = r.day(name)
            return bool(d and d.month == selector.month and (selector.year is None or d.year == selector.year))
        by_start = [r for r in chosen if hit(r, "service_period_start") or hit(r, "transaction_date")
                    or hit(r, "service_date")]
        chosen = by_start or [r for r in chosen if hit(r, "service_period_end")]
    return chosen


def is_silent(item: Item | None) -> bool:
    return item is not None and not item.flagged


def _name_equal(expected: str, actual: str, *, contains: bool) -> bool:
    e, a = norm_name(expected), norm_name(actual)
    if not e or not a:
        return False
    if e == a:
        return True
    return contains and len(min(e, a, key=len)) >= 3 and (e in a or a in e)


def _address_equal(expected: str, actual: str) -> bool:
    """Same street number and, when both have one, the same ZIP. Abbreviations differ, so words are not compared."""

    def parts(text: str) -> tuple[str | None, str | None]:
        text = re.sub(r"\([^)]*\)", " ", text)
        number = re.match(r"\s*(\d+)", text)
        zip_code = re.findall(r"\b(\d{5})(?:-\d{4})?\b", text)
        return (number.group(1) if number else None, zip_code[-1] if zip_code else None)

    (en, ez), (an, az) = parts(expected), parts(actual)
    if not en or not an or en != an:
        return False
    return not (ez and az and ez != az)


def _show(item: Item) -> str:
    return f"{item.value if item.value is not None else item.raw}{(' ' + item.unit) if item.unit else ''}"


class SetScorer:
    """Scores one test set: its key cells against what the pipeline read."""

    def __init__(self, set_name: str, cells: list[KeyCell], docs: dict[str, ExtractedDoc]) -> None:
        self.set_name = set_name
        self.cells = cells
        self.docs = docs
        self.outcomes: list[Outcome] = []
        self.extracted_unscored: dict[str, int] = defaultdict(int)  # extractor field -> values no key cell covered
        self.unmapped_labels: dict[str, int] = defaultdict(int)

    # -- helpers --------------------------------------------------------------------------
    def _out(self, cell: KeyCell, family: str, status: str, *, reason: str = "", actual: str = "",
             exact: bool = False, item: Item | None = None, expected: str | None = None,
             label: str | None = None, record: int | None = None) -> Outcome:
        outcome = Outcome(
            self.set_name, cell.filename, family, status, reason=reason, label=cell.label if label is None else label,
            expected=cell.expected if expected is None else expected, actual=actual, exact=exact,
            silent=status == WRONG and is_silent(item), flags=item.flags if item else (),
            confidence=item.confidence if item else None, record=record,
        )
        self.outcomes.append(outcome)
        return outcome

    # -- the run --------------------------------------------------------------------------
    def score(self) -> list[Outcome]:
        by_file: dict[str, list[KeyCell]] = defaultdict(list)
        for cell in self.cells:
            by_file[cell.filename].append(cell)
        for filename, cells in by_file.items():
            self._score_document(filename, cells)
        return self.outcomes

    def _score_document(self, filename: str, cells: list[KeyCell]) -> None:
        doc = self.docs.get(filename)
        role = doc_role(cells)
        parsed = [(c, self._parse(c)) for c in cells]
        if doc is None:
            for cell, p in parsed:
                self._out(cell, family_of(p.base, p.qualifier), UNSCORED, reason="document_not_in_folder")
            return
        used: set[int] = set()
        if role == "non_evidence":
            self._recognition(cells[0], doc, evidence=False)
            for cell, p in parsed:
                self._out(cell, family_of(p.base, p.qualifier), UNSCORED, reason="non_evidence_document")
            return
        if role == "reporting":
            for cell, p in parsed:
                self._out(cell, family_of(p.base, p.qualifier), UNSCORED, reason="reporting_document")
            return
        self._recognition(cells[0], doc, evidence=True)
        records = records_of(doc)
        families = [family_of(p.base, p.qualifier) for _, p in parsed]
        anchors = self._anchors(parsed, families)
        facility_cell = next((c for c, _ in parsed if c.facility and not UNPLACED.match(c.facility)), None)
        if facility_cell is not None:
            self._facility(facility_cell, doc, records, used)
        for (cell, p), family in zip(parsed, families, strict=True):
            self._score_cell(cell, p, family, doc, records, anchors.get(p.selector), used)
        for item in doc.items:
            if item.has_value and id(item) not in used and item.field not in ("activity_unit",):
                self.extracted_unscored[item.field] += 1

    @staticmethod
    def _parse(cell: KeyCell) -> ParsedLabel:
        """The label's parts; a label with no record of its own takes the row its page_or_row column names."""

        p = parse_label(cell.label)
        row = record_ordinal(cell.location, cell.filename)
        if row and p.selector.empty:
            return replace(p, selector=replace(p.selector, row=row))
        return p

    @staticmethod
    def _anchors(parsed: list[tuple[KeyCell, ParsedLabel]], families: list[str]) -> dict[Selector, tuple[date | None, date | None]]:
        """For a group of cells about one record, the period the key itself gives: it names the record."""

        starts: dict[Selector, date] = {}
        ends: dict[Selector, date] = {}
        for (cell, p), family in zip(parsed, families, strict=True):
            if p.selector.empty:
                continue
            if family == "period_start" and (d := parse_date(cell.expected)):
                starts[p.selector] = d
            if family == "period_end" and (d := parse_date(cell.expected)):
                ends[p.selector] = d
        return {s: (starts.get(s), ends.get(s)) for s in {*starts, *ends}}

    def _recognition(self, cell: KeyCell, doc: ExtractedDoc, *, evidence: bool) -> None:
        if evidence:
            if doc.read:
                self._out(cell, "document_recognition", MATCH, label="(document)", expected="typed", actual=doc.canonical_type_id or "")
            else:
                self._out(cell, "document_recognition", MISSED, label="(document)", expected="typed",
                          actual=doc.halt_code or doc.error or "no type")
            return
        quantities = [i for i in doc.items if i.field in QUANTITY_FIELDS and i.has_value]
        if doc.read and quantities:
            flagged = any(i.flagged for i in quantities)
            self.outcomes.append(Outcome(self.set_name, cell.filename, "non_evidence_rejected", WRONG, label="(document)",
                                         expected="not evidence", actual=f"typed {doc.canonical_type_id}, {len(quantities)} values",
                                         silent=not flagged))
        else:
            self._out(cell, "non_evidence_rejected", MATCH, label="(document)", expected="not evidence", actual="no evidence values")

    def _facility(self, cell: KeyCell, doc: ExtractedDoc, records: list[Record], used: set[int]) -> None:
        if "facility_name" not in doc.targets and doc.read:
            self._out(cell, "facility", NOT_TARGETED, label="(facility)", expected=cell.facility)
            return
        expected = re.sub(r"^\s*facility\s+\w+\s*:\s*", "", cell.facility, flags=re.I)
        name = next((r.items["facility_name"] for r in records if "facility_name" in r.items), None)
        addr = next((r.items["service_address"] for r in records if "service_address" in r.items), None)
        if name is not None:
            used.add(id(name))
            ok = _name_equal(expected, str(name.value), contains=True) or (
                addr is not None and norm_name(expected) in norm_name(addr.value))
            if not ok and addr is not None:
                # The name read is not the facility's (often the customer's), but placement goes by address,
                # which needs the engagement's facility book: not scored here.
                used.add(id(addr))
                self._out(cell, "facility", UNSCORED, reason="address_only_needs_facility_book", label="(facility)", expected=expected)
                return
            self._out(cell, "facility", MATCH if ok else WRONG, label="(facility)", expected=expected, actual=str(name.value), item=name)
        elif addr is not None:
            used.add(id(addr))
            if norm_name(expected) in norm_name(addr.value):
                self._out(cell, "facility", MATCH, label="(facility)", expected=expected, actual=str(addr.value), item=addr)
            else:
                self._out(cell, "facility", UNSCORED, reason="address_only_needs_facility_book", label="(facility)", expected=expected)
        else:
            self._out(cell, "facility", MISSED, label="(facility)", expected=expected, actual="none read")

    # -- one cell -------------------------------------------------------------------------
    def _score_cell(self, cell: KeyCell, p: ParsedLabel, family: str, doc: ExtractedDoc, records: list[Record],
                    anchor: tuple[date | None, date | None] | None, used: set[int]) -> None:
        if family == META:
            self._out(cell, family, UNSCORED, reason="not_an_extraction_field")
            return
        if family == REPORTING:
            self._out(cell, family, UNSCORED, reason="reporting_set_not_in_harness_v1")
            return
        if family == UNMAPPED:
            self.unmapped_labels[p.base] += 1
            self._out(cell, family, UNSCORED, reason="no_mapping")
            return
        spec = FAMILIES[family]
        fields = tuple(f for f in spec.fields if f in doc.targets)
        if not spec.fields or (doc.read and not fields):
            reason = ""
            if family in ("period_start", "period_end") and "transaction_date" in doc.targets:
                reason = "fleet_card_transaction_dates_are_not_a_service_period"
            self._out(cell, family, NOT_TARGETED, reason=reason)
            return
        if not doc.read:
            self._out(cell, family, MISSED, reason="document_not_read", actual=doc.halt_code or doc.error or "no type")
            return
        if spec.kind == "date" and not parse_date(cell.expected):
            self._out(cell, family, UNSCORED, reason="expected_not_parseable")
            return
        selector = replace(p.selector, row=None) if spec.aggregate else p.selector
        chosen = select_records(records, selector, anchor)
        if not chosen and (selector.row or anchor) and family in DOCUMENT_LEVEL:
            # A header or footer value: the row and period that locate a record do not apply to it.
            chosen = select_records(records, replace(selector, row=None), None)
        if not chosen:
            self._out(cell, family, MISSED, reason="record_not_found")
            return
        if spec.aggregate or (family == "activity_quantity" and p.selector.empty and len(records) > 1):
            self._aggregate(cell, p, family, spec.kind, fields, chosen, used)
            return
        if p.selector.empty and len(chosen) > 1 and family in ("period_start", "period_end"):
            days = [d for d in (r.day(fields[0]) for r in chosen) if d]
            if not days:
                self._out(cell, family, MISSED, reason="no_value")
                return
            day = min(days) if family == "period_start" else max(days)
            item = next(r.items[fields[0]] for r in chosen if r.day(fields[0]) == day)
            used.add(id(item))
            self._compare(cell, family, spec.kind, item, chosen[0], used)
            return
        invariant = family in ("supplier", "account", "meter", "statement_date", "fuel_type", "vehicle_type", "model_year",
                               "refrigerant_type", "service_address", "equipment_id", "heat_content")
        if len(chosen) > 1 and not invariant and not (p.selector.dates or anchor):
            if p.selector.ids and family in ("activity_quantity", "distance", "refrigerant_recovered"):
                # A vehicle or unit named with no date: the key gives its total over the document's records.
                self._aggregate(cell, p, family, spec.kind, fields, chosen, used)
            else:
                self._out(cell, family, UNSCORED, reason="ambiguous_record")
            return
        record = chosen[0]
        for r in chosen:
            if r.get(fields) is not None:
                record = r
                break
        found = record.get(fields)
        if found is None:
            self._out(cell, family, MISSED, reason="no_value", item=record.null_item(fields), record=record.index)
            return
        used.add(id(found))
        self._compare(cell, family, spec.kind, found, record, used)

    def _compare(self, cell: KeyCell, family: str, kind: str, item: Item, record: Record, used: set[int]) -> None:
        shown = _show(item)
        actual_text = str(item.value if item.value is not None else item.raw)
        if kind == "date":
            e, a = parse_date(cell.expected), parse_date(item.value if item.value is not None else item.raw)
            ok = e is not None and a is not None and e == a
            self._out(cell, family, MATCH if ok else WRONG, actual=actual_text, item=item, exact=ok)
        elif kind == "id":
            ok = norm_id(cell.expected) == norm_id(actual_text)
            self._out(cell, family, MATCH if ok else WRONG, actual=actual_text, item=item, exact=ok)
        elif kind == "name":
            ok = _name_equal(cell.expected, actual_text, contains=False)
            self._out(cell, family, MATCH if ok else WRONG, actual=actual_text, item=item, exact=ok)
        elif kind == "text":
            ok = (norm_refrigerant(cell.expected) == norm_refrigerant(actual_text) if family == "refrigerant_type"
                  else _name_equal(cell.expected, actual_text, contains=True))
            self._out(cell, family, MATCH if ok else WRONG, actual=actual_text, item=item, exact=ok)
        elif kind == "address":
            ok = _address_equal(cell.expected, actual_text)
            self._out(cell, family, MATCH if ok else WRONG, actual=actual_text, item=item, exact=ok)
        elif kind == "year":
            year_e, year_a = parse_number(cell.expected), parse_number(actual_text)
            ok = year_e is not None and year_a is not None and year_e == year_a
            self._out(cell, family, MATCH if ok else WRONG, actual=actual_text, item=item, exact=ok)
        else:
            self._compare_number(cell, family, item, record, shown)

    def _candidates(self, item: Item, record: Record) -> list[tuple[Decimal, str, bool]]:
        """(number, unit, as_printed) readings of a quantity: the normalised value and the printed one."""

        out: list[tuple[Decimal, str, bool]] = []
        if (v := parse_number(item.value)) is not None:
            out.append((v, item.unit or "", False))
        if (r := parse_number(item.raw)) is not None:
            out.append((r, _unit_of(record, item), True))
        return out

    def _compare_number(self, cell: KeyCell, family: str, item: Item, record: Record, shown: str) -> None:
        expected = parse_number(cell.expected)
        if expected is None:
            self._out(cell, family, UNSCORED, reason="expected_not_parseable")
            return
        e_unit = norm_unit(cell.unit)
        best: tuple[bool, bool] | None = None
        for number, unit, printed in self._candidates(item, record):
            a_unit = norm_unit(unit)
            if e_unit and a_unit and e_unit != a_unit:
                converted = convert(number, a_unit, e_unit)
                if converted is None:
                    continue  # not comparable: the units differ and no conversion is defined
                number, converted_flag = converted, True
            else:
                converted_flag = False
            # Tolerance only where a conversion happened (ours, or the reader's: unit_converted); a number as
            # printed must be the same number.
            tol = REL_TOL if (converted_flag or (not printed and "unit_converted" in item.flags)) else Decimal(0)
            if numbers_equal(expected, number, rel_tol=tol):
                exact = is_exact(expected, number)
                if best is None or (exact and not best[1]):
                    best = (True, exact)
        ok = best is not None
        self._out(cell, family, MATCH if ok else WRONG, actual=shown, item=item, exact=bool(best and best[1]))
        if family == "activity_quantity" and e_unit:
            self._unit(cell, item, record, e_unit)

    def _unit(self, cell: KeyCell, item: Item, record: Record, e_unit: str) -> None:
        printed = _unit_of(record, item)
        stored = item.unit or ""
        if not printed and not stored:
            self._out(cell, "activity_unit", MISSED, expected=cell.unit, reason="no_unit", item=item)
            return
        # The unit may be the one printed or the one the reader converted the value to: either is a unit read.
        ok = e_unit in (norm_unit(printed), norm_unit(stored))
        unit_item = record.items.get("activity_unit", item)
        self._out(cell, "activity_unit", MATCH if ok else WRONG, expected=cell.unit, actual=printed or stored, item=unit_item, exact=ok)

    def _aggregate(self, cell: KeyCell, p: ParsedLabel, family: str, kind: str, fields: tuple[str, ...],
                   chosen: list[Record], used: set[int]) -> None:
        expected = parse_number(cell.expected)
        if expected is None:
            self._out(cell, family, UNSCORED, reason="expected_not_parseable")
            return
        fuel = total_fuel_filter(p.base, p.qualifier)
        e_unit = norm_unit(cell.unit)
        total = Decimal(0)
        contributing: list[Item] = []
        for record in chosen:
            if fuel:
                fuel_item = record.items.get("fuel_type")
                if fuel_item is None or fuel not in norm_name(fuel_item.value or fuel_item.raw):
                    continue
            item = record.get(fields)
            if item is None:
                continue
            value = None
            for number, unit, _printed in self._candidates(item, record):
                a_unit = norm_unit(unit)
                value = number if not (e_unit and a_unit) else convert(number, a_unit, e_unit)
                if value is not None:
                    break
            if value is None:
                continue
            total += value
            contributing.append(item)
            used.add(id(item))
        if not contributing:
            self._out(cell, family, MISSED, reason="no_value")
            return
        ok = numbers_equal(expected, total, rel_tol=REL_TOL)
        flagged = any(i.flagged for i in contributing)
        stand_in = next((i for i in contributing if i.flagged), contributing[0]) if flagged else contributing[0]
        self._out(cell, family, MATCH if ok else WRONG, actual=f"{total.normalize():f} (sum of {len(contributing)})",
                  item=stand_in, exact=ok and is_exact(expected, total))
