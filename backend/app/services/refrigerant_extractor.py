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
from dataclasses import dataclass, field
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

SERVICE = "service"
INSTALLATION = "installation"
DISPOSAL = "disposal"
SERVICE_TYPES = (SERVICE, INSTALLATION, DISPOSAL)

RECORD_FIELDS = ("service_date", "refrigerant_type", "refrigerant_added", "refrigerant_recovered",
                 "equipment_id", "equipment_capacity", "service_type", "facility_name")
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
     "refrigerant removed", "amount removed", "recovered", "removed", "reclaimed", "evacuated"),
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
     "visit date", "date performed", "date"),
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
               "amount")),
    ("recovered", ("recovered", "amount recovered", "qty recovered", "refrigerant recovered", "lbs recovered",
                   "kg recovered", "removed", "reclaimed")),
    ("capacity", ("full charge", "nameplate charge", "system charge", "capacity", "charge capacity", "total charge",
                  "design charge")),
    ("date", ("date", "service date", "date of service", "work date", "date serviced", "visit date")),
    ("equipment", ("equipment", "equipment id", "equipment #", "unit", "unit id", "unit #", "asset", "asset id",
                   "asset #", "system", "equipment/unit")),
    ("site", ("site", "facility", "location", "building", "store")),
    ("provider", ("technician", "contractor", "vendor", "service provider", "serviced by", "tech")),
    ("unit", ("uom", "unit of measure", "units")),
)

_INSTALL_RE = re.compile(
    r"\b(?:new (?:equipment|unit|system)|install(?:ation|ed)?|(?<!de)commission(?:ing|ed)?|initial charge|"
    r"start[- ]?up)\b", re.I)
_DISPOSAL_RE = re.compile(
    r"\b(?:decommission(?:ing|ed)?|retire(?:d|ment)?|dispos(?:al|ed)|scrap(?:ped)?|removed from service|"
    r"end of life)\b", re.I)
_SERVICE_RE = re.compile(r"\b(?:leak|recharge|top[- ]?(?:off|up)|repair|maintenance|service call|preventive)\b",
                         re.I)
# Scanning free text (technician notes) needs stronger phrases: "Install date: 2015" on a
# work order is the equipment's age, not a new installation.
_NOTE_INSTALL_RE = re.compile(r"\b(?:new (?:equipment|unit|system) install(?:ed|ation)?|installed (?:a )?new|"
                              r"initial charge|commissioning of (?:the )?new)\b", re.I)
_NOTE_DISPOSAL_RE = re.compile(r"\b(?:decommission(?:ed|ing)?|removed from service|(?:unit|equipment|system) "
                               r"retired|disposal of|scrapped)\b", re.I)
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
    service_type: tuple[Located, str] | None = None
    unit_missing: set[str] = field(default_factory=set)


def classify_service(text: str, notes: bool = False) -> str | None:
    """service / installation / disposal named in ``text``, or None. ``notes``: free text,
    where only explicit phrases count."""

    if notes:
        if _NOTE_DISPOSAL_RE.search(text):
            return DISPOSAL
        if _NOTE_INSTALL_RE.search(text):
            return INSTALLATION
        return SERVICE if _SERVICE_RE.search(text) else None
    if _DISPOSAL_RE.search(text):
        return DISPOSAL
    if _INSTALL_RE.search(text):
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
        records = [r for r in self._records(rows) if r.refrigerant is not None or r.added or r.recovered]
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
                                 or self._letterhead(rows)),
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
        return ExtractionOutcome(candidates=candidates, records=len(records))

    # =================================================================================
    # Records
    # =================================================================================
    def _records(self, rows: Sequence[Row]) -> list[ServiceRecord]:
        document_unit = self._document_mass_unit(rows)
        table = self._service_table_records(rows, document_unit)
        if table:
            self._fill_from_document(table, rows)
            return table
        single = self._labeled_record(rows, document_unit)
        return [single] if single is not None else []

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

    def _service_table_records(self, rows: Sequence[Row], document_unit: str | None) -> list[ServiceRecord]:
        records: list[ServiceRecord] = []
        position = 0
        while position < len(rows):
            header = self._header(rows[position])
            if header is None:
                position += 1
                continue
            columns, units = header
            header_row = rows[position]
            position += 1
            misses = 0
            while position < len(rows) and misses < 3:
                row = rows[position]
                if self._header(row) is not None:
                    break
                record = self._service_table_record(row, header_row, columns, units, document_unit)
                if record is None:
                    misses += 1
                else:
                    misses = 0
                    records.append(record)
                position += 1
        return records

    def _service_table_record(self, row: Row, header_row: Row, columns: dict[str, int], units: dict[str, str],
                      document_unit: str | None) -> ServiceRecord | None:
        if any(_norm(c.text).startswith(_TOTAL_ROW_WORDS) for c in row.cells[:2]):
            return None  # totals repeat the lines above
        assigned = self._assign_columns(row, header_row.cells)
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
        record = ServiceRecord(refrigerant=(located(gas_cell), gas))
        for name in ("added", "recovered", "capacity"):
            c = cell(name)
            if c is None or not c.text.strip():
                continue
            # A materials line names its unit in the description: "R-410A refrigerant (lbs)".
            line_unit = mass_unit(gas_cell.text) if name == "added" else None
            default = units.get(name) or row_unit or line_unit or document_unit
            mass = parse_mass(c.text, default)
            if mass is None and re.fullmatch(r"\s*\d[\d,]*(?:\.\d+)?\s*", c.text):
                mass = parse_mass(c.text, "lb")
                if mass is not None:
                    record.unit_missing.add(name)
            if mass is not None:
                setattr(record, name, (located(c), mass))
        if record.added is None and record.recovered is None:
            return None
        date_cell = cell("date")
        if date_cell is not None and (hit := parse_date(date_cell.text)):
            record.date = (located(date_cell), hit[0])
        for name, attr in (("equipment", "equipment"), ("site", "site"), ("provider", "provider")):
            c = cell(name)
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
        for record in records:
            if date is not None and parsed is not None:
                record.date = (date, parsed[0])
            if equipment is not None:
                record.equipment = equipment
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
        if found is None:
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
        return self._find_labeled(rows, EQUIPMENT_LABELS,
                                  accept=lambda v: bool(re.search(r"[A-Za-z0-9]", v)) and parse_date(v) is None)

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
            if hit is None:
                return self._missing(target, *args)
            located, mass = hit
            flags = []
            if mass.converted:
                flags.append("unit_converted")
            name = {"refrigerant_added": "added", "refrigerant_recovered": "recovered",
                    "equipment_capacity": "capacity"}[field_id]
            if name in record.unit_missing:
                flags.append("unit_missing")
                return self._candidate(target, located, mass.raw, self._clean_number(mass.value), None, *args,
                                       parser_output, flags)
            return self._candidate(target, located, mass.raw, self._clean_number(mass.value), mass.unit, *args,
                                   parser_output, flags)
        if field_id == "service_date":
            if record.date is None:
                return self._missing(target, *args)
            located, iso = record.date
            return self._candidate(target, located, located.raw, iso, None, *args, parser_output, [])
        if field_id == "service_type":
            if record.service_type is None:
                return self._missing(target, *args)
            located, kind = record.service_type
            return self._candidate(target, located, located.raw, kind, None, *args, parser_output, [])
        if field_id == "equipment_id":
            return self._candidate_for_text(target, record.equipment, *args, parser_output, field_id)
        if field_id == "facility_name":
            return self._candidate_for_text(target, record.site or document.get("facility_name"), *args,
                                            parser_output, field_id)
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
