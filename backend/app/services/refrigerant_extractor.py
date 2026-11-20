"""Scope 1 fugitive refrigerants: deterministic extraction for CT-S1-REFRSVC.

Reads refrigerant service work orders and refrigerant logs (also fire-suppression
recharge records) for the Simplified Material Balance inputs in "Data from Evidence
(Scope 1)" of the GHG Required Data workbook:

    each refrigerant emissions = (P_N - C_N) + P_S + (C_D - R_D), once per refrigerant type

    service       refrigerant added to existing equipment            -> P_S
    installation  refrigerant charged into new equipment, its charge  -> P_N, C_N
    disposal      charge of retired equipment, refrigerant recovered  -> C_D, R_D

Fields, one record per service line (a log or a work order's materials table) or one
per work order:

    core         service_date, refrigerant_type, refrigerant_added, equipment_id
    conditional  refrigerant_recovered, service_type, facility_name
    optional     equipment_capacity, service_address, service_provider

Refrigerant names are normalized to the EPA Hub's names ("R410A" -> "R-410A",
"R-134a" -> "HFC-134a", "FM-200" -> "HFC-227ea"); amounts to lb or kg (ounces and grams
are converted). The service type is read from the record ("leak repair" -> service,
"new unit installed" -> installation, "unit decommissioned" -> disposal).

The layout engine (visual rows, label/value lookup, bounding boxes) is the EXT-001 one.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from typing import Any

from backend.app.domain.refrigerants import Mass, Refrigerant, find_refrigerant, mass_unit, parse_mass
from backend.app.services.stationary_combustion_extractor import (
    _ALL_LABELS as _BASE_LABELS,
)
from backend.app.services.stationary_combustion_extractor import (
    _TOTAL_ROW_WORDS,
    CONF_DOCUMENT_SCAN,
    CONF_TABLE,
    HALT_UNREADABLE,
    HALT_UNSUPPORTED,
    Cell,
    ExtractionOutcome,
    Located,
    Row,
    StationaryCombustionExtractor,
    _norm,
    parse_date,
)

CANONICAL_TYPE_ID = "CT-S1-REFRSVC"

# A priced line counted in cylinders on a supplier's invoice is refrigerant bought, not refrigerant added to
# equipment. The material balance counts what is charged into equipment (P_S, P_N); a purchase is not an
# emission until then, so the reader names it as a purchase and flags it for the reviewer.
PURCHASE_FLAG = "purchase_not_equipment_charge"
PURCHASE_LABEL = "Refrigerant purchased"
POSSIBLE_SUMMARY_FLAG = "possible_summary_or_continuation"
POSSIBLE_SUMMARY_NOTE = ("This line has no date or equipment. It may be a total or a continuation. Accept it only if it is "
                         "a separate service.")
TOTALS_NOTE = ("Rows under a totals heading (Total, Summary, Subtotal) were not read as service lines.")
PURCHASE_NOTE = ("This document is a supplier invoice: the refrigerant was bought, not recorded as added to equipment. "
                 "A purchase is not an emission until it is charged into equipment, so accept these amounts only if "
                 "the refrigerant went into equipment, and check them against the service records.")

SERVICE = "service"
INSTALLATION = "installation"
DISPOSAL = "disposal"
SERVICE_TYPES = (SERVICE, INSTALLATION, DISPOSAL)

RECORD_FIELDS = ("service_date", "refrigerant_type", "refrigerant_added", "refrigerant_recovered",
                 "equipment_id", "equipment_capacity", "service_type", "facility_name", "technician")
DOCUMENT_FIELDS = ("service_address", "service_provider")
MASS_FIELDS = ("refrigerant_added", "refrigerant_recovered", "equipment_capacity")

# --- labels (single work orders) ------------------------------------------------------
REFRIGERANT_LABELS: tuple[tuple[str, ...], ...] = (
    ("refrigerant type", "type of refrigerant", "refrigerant used", "refrigerant", "gas type", "suppression agent",
     "agent type", "agent", "gas"),
)
ADDED_LABELS: tuple[tuple[str, ...], ...] = (
    ("refrigerant added", "amount added", "quantity added", "qty added", "total added", "lbs added", "lb added",
     "kg added", "charge added", "amount charged", "refrigerant charged", "recharge amount", "top-off amount",
     "added", "charged"),
)
RECOVERED_LABELS: tuple[tuple[str, ...], ...] = (
    ("refrigerant recovered", "amount recovered", "quantity recovered", "qty recovered", "lbs recovered",
     "refrigerant removed", "amount removed", "qty removed", "quantity removed",
     "refrigerant reclaimed", "amount reclaimed", "recovered", "removed", "reclaimed", "evacuated"),
)
CAPACITY_LABELS: tuple[tuple[str, ...], ...] = (
    ("full charge", "nameplate charge", "system charge", "factory charge", "design charge", "operating charge",
     "total charge", "charge capacity", "equipment capacity", "refrigerant capacity", "capacity"),
)
EQUIPMENT_LABELS: tuple[tuple[str, ...], ...] = (
    ("equipment id", "equipment #", "equipment no", "equipment number", "asset id", "asset #", "asset tag",
     "asset no", "unit id", "unit #", "unit no", "unit number", "system id"),
    ("equipment", "system", "unit"),
)
DATE_LABELS: tuple[tuple[str, ...], ...] = (
    ("service date", "date of service", "date serviced", "work date", "date completed", "completion date",
     "visit date", "date performed", "invoice date", "date"),
)
SERVICE_TYPE_LABELS: tuple[tuple[str, ...], ...] = (
    ("service type", "type of service", "work type", "work performed", "reason for service", "reason for visit",
     "service performed", "description of work", "work description", "reason", "activity"),
)
PROVIDER_LABELS: tuple[tuple[str, ...], ...] = (
    ("service provider", "service company", "serviced by", "contractor", "vendor", "company"),
)

# --- columns (logs and materials tables) ----------------------------------------------
# Header text is matched after removing a unit in parentheses ("Added (lbs)" -> "added").
COLUMNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("service_type", ("service type", "type of service", "work type", "activity", "reason", "event", "action",
                      "work performed")),
    ("refrigerant", ("refrigerant", "refrigerant type", "gas", "gas type", "agent", "type", "product", "material",
                     "description", "item")),
    ("added", ("added", "amount added", "qty added", "quantity added", "refrigerant added", "lbs added",
               "lb added", "kg added", "oz added", "charged", "charge added", "amount charged", "quantity", "qty",
               "total", "total qty", "total quantity", "net weight", "amount")),
    ("recovered", ("recovered", "amount recovered", "qty recovered", "quantity recovered", "refrigerant recovered",
                   "lbs recovered", "kg recovered", "removed", "reclaimed", "amount removed", "qty removed",
                   "quantity removed", "refrigerant removed", "amount reclaimed", "qty reclaimed",
                   "quantity reclaimed", "refrigerant reclaimed", "amount evacuated", "evacuated")),
    ("capacity", ("full charge", "nameplate charge", "system charge", "capacity", "charge capacity", "total charge",
                  "design charge")),
    ("date", ("date", "service date", "date of service", "work date", "date serviced", "visit date")),
    ("equipment", ("equipment", "equipment id", "equipment #", "unit", "unit id", "unit #", "asset", "asset id",
                   "asset #", "system", "equipment/unit")),
    ("site", ("site", "facility", "location", "building", "store")),
    ("provider", ("contractor", "vendor", "service provider", "serviced by")),
    ("technician", ("technician", "technician name", "tech", "tech name")),
    ("unit", ("uom", "unit of measure", "units")),
)

# Installation and disposal change the material balance (P_N - C_N, C_D - R_D), so they are
# only read when the equipment itself is the subject: "new rooftop unit installed", "chiller
# decommissioned". A part ("installed new filter drier", "old valve disposed") or a vague word
# ("start-up", "commissioning check") is ordinary service (P_S), the default.
_EQUIPMENT = (r"(?:units?|equipment|system|chiller|rtu|rooftop unit|condenser|condensing unit|compressor rack|rack|"
              r"walk-in(?: cooler| freezer)?|cooler|freezer|air handler|heat pump|a/?c unit|split system|"
              r"package unit|ice machine|refrigerator|suppression system|fm-?200 system)"
              r"(?:[\s#-]*[\w#-]*\d[\w#-]*)?")  # optionally followed by its ID: "chiller CH-2", "RTU-12"
_DISPOSAL_RE = re.compile(
    r"\bdecommission(?:ed|ing)?\b|\bend of life\b|\b(?:removed|taken) (?:from|out of) service\b"
    rf"|\b{_EQUIPMENT}\s+(?:was\s+|has been\s+)?(?:retired|scrapped|disposed(?: of)?)\b"
    rf"|\b(?:retired|scrapped|disposed of)\s+(?:the\s+)?(?:old\s+)?{_EQUIPMENT}\b"
    rf"|\b(?:equipment|unit) (?:disposal|retirement)\b", re.I)
_INSTALL_RE = re.compile(
    rf"\b(?:new|replacement)\s+{_EQUIPMENT}\s+(?:was\s+)?(?:installed|install(?:ation)?|commissioned|charged)\b"
    rf"|\binstall(?:ed|ation of)?\s+(?:a |an |the )?(?:new|replacement)\s+{_EQUIPMENT}\b"
    r"|\binitial charge\b|\bnew install(?:ation)?\b", re.I)
_SERVICE_RE = re.compile(r"\b(?:leak|recharge[ds]?|top[- ]?(?:off|up)|repair(?:ed)?|maintenance|service call|preventive|"
                         r"replaced|evacuat\w*)\b", re.I)
# A short Service Type cell may hold just the word.
_SHORT_DISPOSAL = {"disposal", "disposed", "retired", "retirement", "decommissioned", "decommission", "scrapped"}
_SHORT_INSTALL = {"installation", "install", "installed", "new install", "new installation", "new unit"}
# A bare unit in a cell is a unit of measure, never an equipment ID: a mass ("LB", "oz") or a package an
# invoice counts in ("cyl", "drum", "ea").
_UNIT_ONLY_RE = re.compile(
    r"\s*(?:lbs?|pounds?|oz|ounces?|kgs?|kilograms?|g|grams?|cyls?|cylinders?|drums?|bottles?|pails?|"
    r"cases?|ea|each|pcs?|pieces?)\.?\s*", re.I)
_KNOWN_HEADERS = frozenset(name for _, options in COLUMNS for name in options)
# The headers that name the gas. A run-together header is cut only where exactly one side is one of these (the
# real case: "Refrigerant" beside a right-aligned "Full Charge"); two amount columns are never cut apart.
_GAS_HEADERS = frozenset({"refrigerant", "refrigerant type", "gas", "gas type", "agent", "agent type"})
# A column that prices the line ("Unit Price", "Price / Lb", "Rate"): the table is an invoice, not a log of work.
_PRICE_HEADER_RE = re.compile(r"\bprice\b|\bcost\b|\brate\b|\bext\b\.?|\$\s*/|/\s*\$", re.I)
# A supplier, not a contractor: only the letterhead says so ("Refrigerant Supply", "Wholesale"). "Supply" alone is
# in contractors' names ("HVAC Service & Supply") and a "Ship To" block is on every invoice.
_SUPPLIER_RE = re.compile(r"\b(?:refrigerant supply|refrigerants? (?:supplier|distribut\w+)|wholesale|distributors?)\b", re.I)
# Work done, anywhere on the document: "Leak repair labor", "Recharged system", "Adjusted charge per superheat". A tool
# or a product ("leak detector") is not work, so "leak" alone is not a word here, only "leak check".
_WORK_DONE_RE = re.compile(
    r"\b(?:repair\w*|recharg\w+|charged|adjust\w*|leak[- ]?check\w*|serviced|servicing|service (?:call|performed|work|"
    r"provided|rendered)|labou?r)\b", re.I)
# A phone number: "service call (800) 555-0100" is a contact line, not work done.
_PHONE_RE = re.compile(r"\(?\b\d{3}\)?[\s.-]\d{3}[\s.-]\d{4}\b")
# A heading that starts a block of totals: the rows under it are sums, not services.
_TOTALS_TITLE_RE = re.compile(r"^\W*(?:grand\s+total|sub-?total|totals?|summary)\b", re.I)
# A blank amount: a dash or "n/a" is "none", not a note.
_NO_AMOUNT_RE = re.compile(r"\s*(?:[-\u2013\u2014]+|n/?a|none|nil)?\s*", re.I)
# Cooling capacity, airflow and fuel units: a "Capacity: 5 tons" is tonnage, not a refrigerant charge.
_NOT_A_CHARGE_RE = re.compile(r"\b(?:tons?|btu\w*|mbh|kw|hp|cfm|gallons?|gal)\b", re.I)
# An approximate amount: "~3", "approx. 3", "3 (est.)", "3*" is read as 3 and flagged.
_APPROX_RE = re.compile(r"[~\u2248*]|\bapprox(?:imately|imate)?\b\.?|\(\s*est(?:imated|\.)?\s*\)|\bestimated\b|\best\.", re.I)
_TOTAL_KEYS = ("total", "total qty", "total quantity")
_BUSINESS_WORD_RE = re.compile(
    r"\b(?:supply|supplies|services?|mechanical|refrigeration|company|co\.?|inc\.?|llc|ltd\.?|corp\.?|systems|"
    r"solutions|distribut\w+|hvac|gases|wholesale)\b", re.I)
_DOCUMENT_UNIT_RE = re.compile(r"(?:all )?(?:quantities|amounts|weights?) (?:are )?(?:in|shown in) ([a-z]+)", re.I)


@dataclass
class ServiceRecord:
    refrigerant: tuple[Located, Refrigerant] | None
    added: tuple[Located, Mass] | None = None
    recovered: tuple[Located, Mass] | None = None
    capacity: tuple[Located, Mass] | None = None
    date: tuple[Located, str] | None = None
    equipment: Located | None = None
    site: Located | None = None
    provider: Located | None = None
    technician: Located | None = None  # the person who did the work (a log's Technician column)
    service_type: tuple[Located, str] | None = None
    # A line on a supplier's invoice (priced, counted in cylinders): refrigerant bought, not yet added to equipment.
    possible_summary: bool = False  # an amount with no date and no equipment: a total or a continuation, or a service
    priced: bool = False  # the table has a price column
    packaged: bool = False  # counted in cylinders or named by a package size
    purchase: bool = False
    unit_missing: set[str] = field(default_factory=set)
    flags: dict[str, list[str]] = field(default_factory=dict)  # field -> extra validation flags
    not_a_number: set[str] = field(default_factory=set)  # amount cells holding words ("TBD"), left empty


def classify_service(text: str, notes: bool = False) -> str | None:
    """service / installation / disposal named in ``text``, or None (read as service).

    ``notes``: free text such as technician notes; otherwise a Service Type cell or label,
    where a single word ("Disposal", "Installation") is enough on its own.
    """

    if _DISPOSAL_RE.search(text):
        return DISPOSAL
    if _INSTALL_RE.search(text):
        return INSTALLATION
    if not notes:
        words = " ".join(re.sub(r"[^a-z/ -]", " ", text.lower()).split())
        if words in _SHORT_DISPOSAL:
            return DISPOSAL
        if words in _SHORT_INSTALL:
            return INSTALLATION
    if _SERVICE_RE.search(text):
        return SERVICE
    return None


def _header_key(text: str) -> tuple[str, str | None]:
    """(header without its unit, unit named in it): "Added (lbs)" and "Lbs Added" -> ("added", "lb")."""

    low = _norm(re.sub(r"\([^()]*\)", " ", text))
    words = [w for w in low.split() if not re.fullmatch(r"(?:lbs?|kgs?|oz|grams?|pounds?)\.?", w)]
    return " ".join(words).strip(" :#"), mass_unit(text)


class RefrigerantServiceExtractor(StationaryCombustionExtractor):
    """Builds CT-S1-REFRSVC candidates: one record per refrigerant service line."""

    CANONICAL_TYPE_ID = CANONICAL_TYPE_ID
    HEADLINE_QUANTITY = False  # only the natural gas reader reads a number in large type over a unit
    INLINE_TOTAL_QUANTITY = False  # ... or "TOTAL 1,273.1 THERMS" inside a line of a statement
    ALL_LABELS = _BASE_LABELS + tuple(
        label
        for group in (REFRIGERANT_LABELS + ADDED_LABELS + RECOVERED_LABELS + CAPACITY_LABELS + EQUIPMENT_LABELS
                      + DATE_LABELS + SERVICE_TYPE_LABELS + PROVIDER_LABELS)
        for label in group
    )

    def confirms(self, parser_output: dict) -> bool:
        """Content check: the document names a refrigerant and an amount in lb, oz, kg or g."""

        rows = self._rows(parser_output)
        records = self._records(rows)
        return any(r.refrigerant is not None and (r.added or r.recovered) for r in records)

    # ---------------------------------------------------------------------------------
    def _extract(self, rows: list[Row], parser_output: dict, targets: Sequence[dict], evidence_id: str,
                 document_id: str) -> ExtractionOutcome:
        if not any(cell.text.strip() for row in rows for cell in row.cells):
            return ExtractionOutcome(candidates=[], halt_reason={
                "code": HALT_UNREADABLE,
                "message": "No readable text was found in the document (for example a scan without a text layer "
                "while OCR is off, or an empty file). Upload a text-based PDF or enable OCR.",
            })
        found, notes = self._records_and_notes(rows)
        records = [r for r in found if r.refrigerant is not None or r.added or r.recovered]
        if not any(r.refrigerant is not None for r in records):
            return ExtractionOutcome(candidates=[], halt_reason={
                "code": HALT_UNSUPPORTED,
                "message": "No refrigerant or fire-suppression gas (for example R-410A, R-134a, HFC-227ea or SF6) "
                "is named in the document, so it is not a refrigerant service record.",
            })

        facility, address_from_facility = self._facility(rows)
        document: dict[str, Located | None] = {
            "facility_name": facility,
            "service_address": self._address(rows) or address_from_facility,
            "service_provider": (self._find_labeled(rows, PROVIDER_LABELS, accept=self._looks_like_org_name,
                                                    allow_next_row=False)
                                 or self._letterhead_name(rows)),
        }

        candidates: list[dict] = []
        multi = len(records) > 1
        for index, record in enumerate(records, start=1):
            record_index = index if multi else None
            record_key = self._service_key(index, record) if multi else None
            record_candidates = [
                self._service_candidate(target, record, document, document_id, evidence_id, record_key,
                                        record_index, parser_output)
                for target in targets
            ]
            if multi:
                label = self._service_display(index, record)
                for candidate in record_candidates:
                    candidate["display_label"] = f"{candidate['display_label']} ({label})"
                    candidate["source_reference"]["record_key"] = record_key
            candidates.extend(record_candidates)
        return ExtractionOutcome(candidates=candidates, records=len(records), notes=notes)

    def _letterhead_name(self, rows: Sequence[Row]) -> Located | None:
        """The letterhead, joined with a short second line that completes the name
        ("POLAR RIDGE" over "Refrigerant Supply")."""

        head = self._letterhead(rows)
        if head is None or head.row is None:
            return head
        nxt = next((r for r in rows if r.index == head.row.index + 1), None)
        second = nxt.cells[0] if nxt is not None and nxt.cells else None
        if (second is not None and nxt is not None and nxt.page == head.row.page and len(head.cells) == 1
                and len(second.text.split()) <= 4 and not re.search(r"\d", second.text)
                and _BUSINESS_WORD_RE.search(second.text)
                and (head.cells[0].box is None or second.box is None
                     or abs(second.left - head.cells[0].left) < 0.03)):
            name = f"{head.raw} {second.text.strip()}"
            return Located(name, [*head.cells, second], head.row, head.confidence, context=name)
        return head

    # =================================================================================
    # Records
    # =================================================================================
    def _records(self, rows: Sequence[Row]) -> list[ServiceRecord]:
        return self._records_and_notes(rows)[0]

    def _records_and_notes(self, rows: Sequence[Row]) -> tuple[list[ServiceRecord], list[str]]:
        document_unit = self._document_mass_unit(rows)
        groups, skipped = self._service_table_groups(rows, document_unit)
        notes: list[str] = []
        table = [r for group in groups for r in group]
        if skipped:
            notes.append(TOTALS_NOTE)
        if table:
            self._fill_from_document(table, rows)
            # No date and no equipment even from the document: it may be a total or a continuation, so it is flagged
            # for the reviewer (it counts only if accepted); the date and equipment are never filled in by guessing.
            for r in table:
                r.possible_summary = r.date is None and r.equipment is None
            if any(r.possible_summary for r in table):
                notes.append(POSSIBLE_SUMMARY_NOTE)
            self._decide_purchase(table, rows)
            if any(r.purchase for r in table):
                notes.append(PURCHASE_NOTE)
            return table, notes
        single = self._labeled_record(rows, document_unit)
        return ([single] if single is not None else []), notes

    def _decide_purchase(self, table: list[ServiceRecord], rows: Sequence[Row]) -> None:
        """Priced lines counted in cylinders, or a supplier's price list, are refrigerant bought. Not when
        the document names the equipment or the work done (a work order or a contractor's invoice)."""

        priced = [r for r in table if r.priced]
        if not priced:
            return
        supplier = any(_SUPPLIER_RE.search(row.text) for row in rows[:3])  # the letterhead
        for r in priced:
            r.purchase = r.packaged or supplier
        work = (self._equipment(rows) is not None
                or self._find_labeled(rows, SERVICE_TYPE_LABELS, accept=lambda v: classify_service(v) is not None)
                is not None
                or any(_WORK_DONE_RE.search(c.text) and not _PHONE_RE.search(c.text)
                       for row in rows for c in row.cells))
        if work:
            for r in priced:
                r.purchase = False

    def _document_mass_unit(self, rows: Sequence[Row]) -> str | None:
        for row in rows:
            match = _DOCUMENT_UNIT_RE.search(row.text)
            if match and mass_unit(match.group(1)):
                return mass_unit(match.group(1))
        return None

    # --- logs and materials tables ------------------------------------------------------
    def _header(self, row: Row) -> tuple[dict[str, int], dict[str, str]] | None:
        """Column positions of a refrigerant log header. Each column takes the cell that
        matches its most specific name ("Refrigerant" beats a generic "Type")."""

        keys = [_header_key(cell.text) for cell in row.cells]
        columns: dict[str, int] = {}
        units: dict[str, str] = {}
        used: set[int] = set()
        for name, options in COLUMNS:
            best: tuple[int, int, str | None] | None = None
            for position, (key, unit) in enumerate(keys):
                if position in used or key not in options:
                    continue
                if key in _TOTAL_KEYS and unit is None:
                    continue  # a bare "Total" is a money column; "Total Lbs" is a mass
                rank = options.index(key)
                if best is None or rank < best[0]:
                    best = (rank, position, unit)
            if best is not None:
                columns[name] = best[1]
                used.add(best[1])
                if best[2]:
                    units[name] = best[2]
        if "refrigerant" not in columns or not ({"added", "recovered"} & columns.keys()):
            return None
        return columns, units

    @staticmethod
    def _split_glued_headers(row: Row) -> Row:
        """A header whose neighbours the parser read as one cell: "RefrigerantFull Charge (lb)" or
        "Refrigerant Full Charge (kg)" is the "Refrigerant" and "Full Charge" columns (the data rows have a
        cell for each). A cell is cut only when it is not a header as a whole, both sides are headers this
        reader knows, and exactly one side is the refrigerant column: two amount columns ("Amount Removed")
        are never cut apart, and an ordinary heading is never split. The box is shared out by text length, so
        each part sits over the data cells under it."""

        known = _KNOWN_HEADERS
        cells: list[Cell] = []
        changed = False
        for cell in row.cells:
            parts: tuple[str, str] | None = None
            if cell.column is None and _header_key(cell.text)[0] not in known:
                for boundary in re.finditer(r"(?<=[a-z])(?=[A-Z])|\s+", cell.text):
                    left, right = cell.text[:boundary.start()], cell.text[boundary.end():]
                    keys = (_header_key(left)[0], _header_key(right)[0])
                    if (left and right and all(k in known for k in keys)
                            and sum(k in _GAS_HEADERS for k in keys) == 1):
                        parts = (left, right)
                        break
            if parts is None:
                cells.append(cell)
                continue
            changed = True
            share = len(parts[0]) / (len(parts[0]) + len(parts[1]))
            box = cell.box
            first_box = second_box = box
            if box is not None:
                width = box["width"]
                first_box = {**box, "width": width * share}
                second_box = {**box, "left": box["left"] + width * share, "width": width * (1 - share)}
            cells.append(replace(cell, text=parts[0], box=first_box))
            cells.append(replace(cell, text=parts[1], box=second_box))
        return Row(cells, row.page, row.index) if changed else row

    def _service_table_groups(self, rows: Sequence[Row], document_unit: str | None
                              ) -> tuple[list[list[ServiceRecord]], int]:
        """The records under each header, one list per header, and how many rows were left out. Rows are left out
        only under an explicit totals heading (a row reading Total, Totals, Summary, Grand total or Subtotal): the
        undated, equipment-less rows right under it. Nothing else is guessed: a line with an amount is a record."""

        groups: list[list[ServiceRecord]] = []
        skipped = 0
        under_totals = False
        position = 0
        while position < len(rows):
            header_row = rows[position]
            header = self._header(header_row)
            if header is None:  # a header the parser ran together: try it cut where two known headers meet
                split = self._split_glued_headers(header_row)
                header = self._header(split) if split is not header_row else None
                if header is not None:
                    header_row = split
            if header is None:
                if header_row.cells and _TOTALS_TITLE_RE.match(header_row.cells[0].text):
                    under_totals = True
                position += 1
                continue
            columns, units = header
            position += 1
            misses = 0
            group: list[ServiceRecord] = []
            groups.append(group)
            while position < len(rows) and misses < 3:
                row = rows[position]
                if self._header(row) is not None:
                    break
                record = self._service_table_record(row, header_row, columns, units, document_unit)
                if record is None:
                    if row.cells and _TOTALS_TITLE_RE.match(row.cells[0].text):
                        under_totals = True
                    misses += 1
                elif under_totals and record.date is None and record.equipment is None:
                    skipped += 1  # a row under a totals heading
                    misses = 0
                else:
                    under_totals = False
                    misses = 0
                    group.append(record)
                position += 1
        return [g for g in groups if g], skipped

    def _service_table_record(self, row: Row, header_row: Row, columns: dict[str, int], units: dict[str, str],
                      document_unit: str | None) -> ServiceRecord | None:
        if any(_norm(c.text).startswith(_TOTAL_ROW_WORDS) for c in row.cells[:2]):
            return None  # totals repeat the lines above
        assigned = self._assign_columns(row, header_row.cells)
        gas_at = columns.get("refrigerant")
        shift = len(header_row.cells) - len(row.cells)
        if (gas_at is not None and shift > 0 and not any(c.box for c in row.cells)
                and find_refrigerant(assigned[gas_at].text if gas_at in assigned else "") is None
                and gas_at - shift >= 0 and find_refrigerant(row.cells[gas_at - shift].text) is not None):
            # text with no positions and the leading cells (date, equipment) left blank: the cells are the last columns
            assigned = {i + shift: c for i, c in enumerate(row.cells)}
        context = f"{header_row.text} | {row.text}"

        def cell(name: str) -> Cell | None:
            index = columns.get(name)
            return assigned.get(index) if index is not None else None

        def located(c: Cell, raw: str | None = None) -> Located:
            return Located(raw or c.text, [c], row, CONF_TABLE, context=context)

        gas_cell = cell("refrigerant")
        if gas_cell is None:
            return None
        gas = find_refrigerant(gas_cell.text)
        if gas is None:
            return None
        unit_cell = cell("unit")
        row_unit = mass_unit(unit_cell.text) if unit_cell is not None else None
        # An invoice's "Unit" column (lb, oz, cyl) can land under the equipment heading: a unit of
        # measure is never an equipment ID.
        equipment_cell = cell("equipment")
        unit_words = [unit_cell.text] if unit_cell is not None else []
        if equipment_cell is not None and _UNIT_ONLY_RE.fullmatch(equipment_cell.text):
            row_unit = row_unit or mass_unit(equipment_cell.text)
            unit_words.append(equipment_cell.text)
            equipment_cell = None
        record = ServiceRecord(refrigerant=(located(gas_cell), gas))
        priced = any(_PRICE_HEADER_RE.search(c.text) for c in header_row.cells)
        in_packages = any(_UNIT_ONLY_RE.fullmatch(w) and mass_unit(w) is None for w in unit_words)
        # "R-410A refrigerant 25 lb cylinder" names a package size; "R-410A refrigerant (lbs)" a unit.
        package = parse_mass(gas_cell.text)
        for name in ("added", "recovered", "capacity"):
            c = cell(name)
            if c is None or not c.text.strip() or _NOT_A_CHARGE_RE.search(c.text):
                continue
            text = _APPROX_RE.sub(" ", c.text).strip()
            approximate = text != c.text.strip()
            bare = re.fullmatch(r"\s*(\d[\d,]*(?:\.\d+)?)\s*", text)
            # A header that names the unit ("Total Lbs") says the cell is already a mass, not a count of packages.
            if name == "added" and package is not None and bare and name not in units:
                count = float(bare.group(1).replace(",", ""))
                packaged = Mass(count * package.value, package.unit, f"{bare.group(1)} x {package.raw}",
                                converted=package.converted)
                record.flags.setdefault(name, []).append("quantity_times_package_size")
                if approximate:
                    record.flags[name].append("approximate")
                setattr(record, name, (located(c), packaged))
                continue
            line_unit = mass_unit(gas_cell.text) if name == "added" and package is None else None
            default = units.get(name) or row_unit or line_unit or document_unit
            mass = parse_mass(text, default)
            if mass is None and bare:
                mass = parse_mass(text, "lb")
                if mass is not None:
                    record.unit_missing.add(name)
            if mass is not None:
                if approximate:
                    mass = replace(mass, raw=c.text.strip())
                    record.flags.setdefault(name, []).append("approximate")
                setattr(record, name, (located(c), mass))
        # An amount cell holding words ("TBD", "2 trips") is not read; it stays empty and is flagged. A row whose
        # amounts are all words (or zero beside words) is a note, not a line; one amount that reads as a number keeps it.
        for name in ("added", "recovered"):
            c = cell(name)
            if c is not None and getattr(record, name) is None and c.text.strip() and not _NO_AMOUNT_RE.fullmatch(c.text):
                record.not_a_number.add(name)
        numbers = [m.value for m in (record.added and record.added[1], record.recovered and record.recovered[1]) if m]
        if not any(numbers) and record.not_a_number:
            return None
        if record.added is None and record.recovered is None:
            return None
        record.priced = priced
        record.packaged = in_packages or package is not None
        date_cell = cell("date")
        if date_cell is not None and (hit := parse_date(date_cell.text)):
            record.date = (located(date_cell), hit[0])
        for name, attr in (("equipment", "equipment"), ("site", "site"), ("provider", "provider"),
                           ("technician", "technician")):
            c = equipment_cell if name == "equipment" else cell(name)
            if c is not None and c.text.strip():
                setattr(record, attr, located(c))
        type_cell = cell("service_type")
        if type_cell is not None and (kind := classify_service(type_cell.text)):
            record.service_type = (located(type_cell), kind)
        else:
            kind = classify_service(row.text, notes=True)
            if kind is not None:
                record.service_type = (Located(row.text, list(row.cells), row, CONF_DOCUMENT_SCAN,
                                               context=context), kind)
        return record

    def _fill_from_document(self, records: list[ServiceRecord], rows: Sequence[Row]) -> None:
        """A work order's materials table: date, equipment and service type are on the
        order itself, not on each line."""

        # Only when no line has its own value: a log's lines each carry their date and unit.
        date = None if any(r.date for r in records) else self._find_labeled(
            rows, DATE_LABELS, accept=lambda v: parse_date(v) is not None)
        parsed = parse_date(date.raw) if date is not None else None
        equipment = None if any(r.equipment for r in records) else self._equipment(rows)
        service = None if any(r.service_type for r in records) else self._service_type(rows)
        shared = len(records) > 1  # one order's lines share its date and unit; a table of many lines is to be checked
        for record in records:
            if date is not None and parsed is not None:
                record.date = (date, parsed[0])
                if shared:
                    record.flags.setdefault("date", []).append("filled_from_document")
            if equipment is not None:
                record.equipment = equipment
                if shared:
                    record.flags.setdefault("equipment", []).append("filled_from_document")
            if service is not None:
                record.service_type = service

    # --- single work orders -----------------------------------------------------------
    def _labeled_record(self, rows: Sequence[Row], document_unit: str | None) -> ServiceRecord | None:
        gas_loc = self._find_labeled(rows, REFRIGERANT_LABELS, accept=lambda v: find_refrigerant(v) is not None)
        if gas_loc is None:
            for row in rows:
                for c in row.cells:
                    if find_refrigerant(c.text) is not None:
                        gas_loc = Located(c.text, [c], row, CONF_DOCUMENT_SCAN)
                        break
                if gas_loc is not None:
                    break
        record = ServiceRecord(refrigerant=None)
        if gas_loc is not None:
            found_gas = find_refrigerant(gas_loc.raw)
            record.refrigerant = (gas_loc, found_gas) if found_gas is not None else None
        for name, groups in (("added", ADDED_LABELS), ("recovered", RECOVERED_LABELS),
                             ("capacity", CAPACITY_LABELS)):
            hit = self._labeled_mass(rows, groups, document_unit)
            if hit is not None:
                found, mass, unit_missing = hit
                setattr(record, name, (found, mass))
                if unit_missing:
                    record.unit_missing.add(name)
        if record.refrigerant is None and record.added is None and record.recovered is None:
            return None
        date = self._find_labeled(rows, DATE_LABELS, accept=lambda v: parse_date(v) is not None)
        if date is not None and (parsed := parse_date(date.raw)):
            record.date = (date, parsed[0])
        record.equipment = self._equipment(rows)
        record.service_type = self._service_type(rows)
        return record

    def _labeled_mass(self, rows: Sequence[Row], groups: Sequence[Sequence[str]], document_unit: str | None
                      ) -> tuple[Located, Mass, bool] | None:
        found = self._find_labeled(rows, groups,
                                   accept=lambda v: bool(re.match(r"\(?\s*\d|\.\d", v)), allow_next_row=True)
        if found is None or _NOT_A_CHARGE_RE.search(found.raw):
            return None
        label_unit = mass_unit(found.label_cell.text if found.label_cell is not None else None)
        mass = parse_mass(found.raw, label_unit or document_unit)
        if mass is not None:
            return found, mass, False
        number = re.match(r"\s*(\d[\d,]*(?:\.\d+)?)", found.raw)
        if number is None:
            return None
        bare = parse_mass(number.group(1), "lb")
        return (found, bare, True) if bare is not None else None

    def _equipment(self, rows: Sequence[Row]) -> Located | None:
        # "Equipment ID: Rooftop unit" is trusted; a bare "Unit" / "System" label only with an
        # ID-like value ("RTU-3"), so a table header ("Unit  Price") is not read as one.
        explicit, generic = EQUIPMENT_LABELS[0], EQUIPMENT_LABELS[1]
        return (self._find_labeled(rows, (explicit,),
                                   accept=lambda v: bool(re.search(r"[A-Za-z0-9]", v)) and parse_date(v) is None)
                or self._find_labeled(rows, (generic,),
                                      accept=lambda v: bool(re.search(r"\d", v)) and parse_date(v) is None
                                      and _UNIT_ONLY_RE.fullmatch(v) is None))

    def _service_type(self, rows: Sequence[Row]) -> tuple[Located, str] | None:
        labeled = self._find_labeled(rows, SERVICE_TYPE_LABELS, accept=lambda v: classify_service(v) is not None)
        if labeled is not None:
            return labeled, classify_service(labeled.raw) or SERVICE
        for row in rows:  # "Leak found on compressor; recharged" in the technician's notes
            for c in row.cells:
                kind = classify_service(c.text, notes=True)
                if kind is not None:
                    return Located(c.text, [c], row, CONF_DOCUMENT_SCAN), kind
        return None

    # =================================================================================
    # Candidates
    # =================================================================================
    def _service_candidate(self, target: dict, record: ServiceRecord, document: dict[str, Located | None],
                           document_id: str, evidence_id: str, record_key: str | None, record_index: int | None,
                           parser_output: dict) -> dict:
        args = (document_id, evidence_id, record_key, record_index)
        field_id = str(target.get("field_id") or "")
        if field_id == "refrigerant_type":
            if record.refrigerant is None:
                return self._missing(target, *args)
            located, gas = record.refrigerant
            flags = ["montreal_protocol_gas"] if gas.montreal else []
            return self._candidate(target, located, gas.raw, gas.name, None, *args, parser_output, flags)
        if field_id in MASS_FIELDS:
            hit = {"refrigerant_added": record.added, "refrigerant_recovered": record.recovered,
                   "equipment_capacity": record.capacity}[field_id]
            name = {"refrigerant_added": "added", "refrigerant_recovered": "recovered",
                    "equipment_capacity": "capacity"}[field_id]
            if hit is None:
                if name not in record.not_a_number:
                    return self._missing(target, *args)
                required = target.get("required_status") in {"core", "conditional"}
                return self._missing(target, *args, [*(["field_not_found"] if required else []), "amount_not_a_number"])
            located, mass = hit
            flags = []
            if mass.converted:
                flags.append("unit_converted")
            flags.extend(record.flags.get(name, []))
            if name == "added" and record.purchase:
                flags.append(PURCHASE_FLAG)
            if name in ("added", "recovered") and record.possible_summary:
                flags.append(POSSIBLE_SUMMARY_FLAG)
            unit = None if name in record.unit_missing else mass.unit
            if name in record.unit_missing:
                flags.append("unit_missing")
            candidate = self._candidate(target, located, mass.raw, self._clean_number(mass.value), unit, *args,
                                        parser_output, flags)
            if name == "added" and record.purchase:
                candidate["display_label"] = PURCHASE_LABEL  # bought from a supplier, not added to equipment
            return candidate
        if field_id == "service_date":
            if record.date is None:
                return self._missing(target, *args)
            located, iso = record.date
            return self._candidate(target, located, located.raw, iso, None, *args, parser_output,
                                   record.flags.get("date", []))
        if field_id == "service_type":
            if record.service_type is None:
                return self._missing(target, *args)
            located, kind = record.service_type
            return self._candidate(target, located, located.raw, kind, None, *args, parser_output, [])
        if field_id == "equipment_id":
            candidate = self._candidate_for_text(target, record.equipment, *args, parser_output, field_id)
            candidate["validation_flags"].extend(record.flags.get("equipment", []))
            return candidate
        if field_id == "facility_name":
            return self._candidate_for_text(target, record.site or document.get("facility_name"), *args,
                                            parser_output, field_id)
        if field_id == "technician":
            return self._candidate_for_text(target, record.technician, *args, parser_output, field_id)
        if field_id == "service_provider":
            return self._candidate_for_text(target, record.provider or document.get("service_provider"), *args,
                                            parser_output, field_id)
        if field_id in DOCUMENT_FIELDS:
            return self._candidate_for_text(target, document.get(field_id), *args, parser_output, field_id)
        return self._missing(target, *args, ["unsupported_extraction_method"])

    @staticmethod
    def _service_display(index: int, record: ServiceRecord) -> str:
        parts = [f"record {index}"]
        if record.date is not None:
            parts.append(record.date[1])
        if record.equipment is not None:
            parts.append(record.equipment.raw.strip())
        if record.refrigerant is not None:
            parts.append(record.refrigerant[1].name)
        return " · ".join(parts)

    @staticmethod
    def _service_key(index: int, record: ServiceRecord) -> str:
        parts = [f"r{index}"]
        if record.date is not None:
            parts.append(record.date[1])
        if record.equipment is not None:
            parts.append(re.sub(r"\s+", "_", record.equipment.raw.strip()))
        return ":".join(parts)


def service_type_of(value: Any) -> str:
    """The reviewed service type, defaulting to a service (refrigerant added to existing equipment)."""

    text = str(value or "").strip().lower()
    return text if text in SERVICE_TYPES else SERVICE
