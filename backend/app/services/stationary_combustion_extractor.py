"""EXT-001 - deterministic extraction for CT-S1-FUELQTY (stationary fuel quantity).

Handles natural gas / heating fuel bills, fuel delivery tickets and bulk fuel
statements. Works from ``parser_output`` lines (PDF text layer or Textract LINEs,
each with a page-normalized bounding box) and rebuilds the page's visual rows so that
label/value pairs and usage tables can be read the way a person reads them.

Output: ``extraction_candidate`` dicts (contracts/extraction_candidate.schema.json).
A bill can contain several meters or service periods; each becomes its own *record*
and every field of a record gets its own candidate, tagged with ``record_key`` /
``record_index`` (single-record documents keep ``record_index`` = None so their
candidate ids are unchanged).

Units follow ``backend.app.domain.fuel_units``: energy is converted to MMBtu; gas,
liquid and mass quantities keep their (canonical) unit because converting them needs
a heating value (Scope 1 schema S1-STC-020), which is not extraction's job.

The extractor halts instead of guessing when the document has no text
(``unreadable_document``) or carries no fuel signal at all (``unsupported_document``,
e.g. a water bill that has meters, CCF and a billing period).
"""

from __future__ import annotations

import copy
import re
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Sequence

from backend.app.domain import fuel_units

CANONICAL_TYPE_ID = "CT-S1-FUELQTY"

HALT_UNREADABLE = "unreadable_document"
HALT_UNSUPPORTED = "unsupported_document"

RECORD_FIELDS = ("fuel_type", "activity_quantity", "activity_unit", "service_period_start", "service_period_end")
DOCUMENT_FIELDS = ("facility_name", "service_address", "supplier_name", "account_number")
KNOWN_FIELDS = RECORD_FIELDS + DOCUMENT_FIELDS

# Confidence by how a value was located (then capped by the parser's own confidence).
CONF_SAME_CELL = 0.92
CONF_NEXT_CELL = 0.9
CONF_TABLE = 0.88
CONF_NEXT_ROW = 0.8
CONF_LETTERHEAD = 0.75
CONF_DOCUMENT_SCAN = 0.7
CONF_INHERITED = 0.85  # record field taken from the document header (e.g. statement period)
CONF_MISSING = 0.2

_MAX_SNIPPET = 240

# --- labels (priority order; earlier groups win) -----------------------------------------
FACILITY_LABELS: tuple[tuple[str, ...], ...] = (
    ("facility name", "facility", "site name", "site", "premises name", "premises", "plant", "location name"),
    ("customer name", "customer", "sold to", "bill to", "ship to name", "account name", "service name"),
)
ADDRESS_LABELS: tuple[tuple[str, ...], ...] = (
    ("service address", "service location", "premises address", "site address", "facility address",
     "delivery address", "delivered to", "deliver to", "ship to", "service at"),
    ("location", "account address"),
)
ACCOUNT_LABELS: tuple[tuple[str, ...], ...] = (
    ("account number", "account no", "account #", "acct number", "acct no", "acct #", "customer account",
     "customer acct", "customer number", "customer no", "account id", "account"),
)
SUPPLIER_LABELS: tuple[tuple[str, ...], ...] = (
    ("supplier", "utility", "provider", "vendor", "issued by", "company", "distributor"),
)
FUEL_LABELS: tuple[tuple[str, ...], ...] = (
    ("fuel type", "fuel", "commodity", "product", "service type"),
)
RANGE_PERIOD_LABELS: tuple[tuple[str, ...], ...] = (
    ("service period", "billing period", "service dates", "billing dates", "period of service",
     "usage period", "read period", "statement period", "period"),
)
START_LABELS: tuple[tuple[str, ...], ...] = (
    ("period start", "service start", "start date", "service from", "from date", "from"),
)
END_LABELS: tuple[tuple[str, ...], ...] = (
    ("period end", "service end", "end date", "service to", "through", "to date", "to"),
)
DELIVERY_DATE_LABELS: tuple[tuple[str, ...], ...] = (("delivery date", "date delivered", "delivered on", "fill date"),)
QUANTITY_LABELS: tuple[tuple[str, ...], ...] = (
    ("total usage", "billed usage", "total consumption", "gas used", "net gallons", "gallons delivered",
     "total gallons", "quantity delivered", "litres delivered", "liters delivered", "usage", "consumption",
     "quantity"),
)
DOCUMENT_TITLE_WORDS = ("invoice", "statement", "bill", "ticket", "receipt", "notice")
ORG_HINTS = (" inc", " llc", " ltd", " co.", " company", " corp", "utilities", " utility", " energy", " gas",
             " fuel", " oil", " propane", " power", " services", " transport")

# --- fuel vocabulary -------------------------------------------------------------------
FUEL_KEYWORDS: tuple[tuple[str, str], ...] = (
    # Biogenic fuels first so "renewable natural gas" / "biodiesel" are not read as fossil.
    # biogas / biodiesel / kerosene are outside the seed's allowed_values and get flagged.
    ("renewable natural gas", "biogas"),
    ("landfill gas", "biogas"),
    ("digester gas", "biogas"),
    ("biogas", "biogas"),
    ("biodiesel", "biodiesel"),
    ("ultra low sulfur diesel", "diesel"),
    ("ulsd", "diesel"),
    ("diesel", "diesel"),
    ("heating oil", "fuel_oil"),
    ("fuel oil", "fuel_oil"),
    ("#2 oil", "fuel_oil"),
    ("no. 2 oil", "fuel_oil"),
    ("residual oil", "fuel_oil"),
    ("distillate", "fuel_oil"),
    ("kerosene", "kerosene"),
    ("propane", "propane"),
    ("lpg", "propane"),
    ("liquefied petroleum gas", "propane"),
    ("hd-5", "propane"),
    ("natural gas", "natural_gas"),
    ("nat gas", "natural_gas"),
    ("gas service", "natural_gas"),
    ("gas supply", "natural_gas"),
    ("gas company", "natural_gas"),
    ("gas utility", "natural_gas"),
    ("gas utilities", "natural_gas"),
    ("gas transport", "natural_gas"),
    ("therm", "natural_gas"),
    ("therms", "natural_gas"),
    ("dekatherm", "natural_gas"),
    ("dekatherms", "natural_gas"),
    ("anthracite", "coal"),
    ("bituminous", "coal"),
    ("coal", "coal"),
    ("wood pellets", "biomass"),
    ("wood pellet", "biomass"),
    ("wood chips", "biomass"),
    ("firewood", "biomass"),
    ("biomass", "biomass"),
)
# Keywords match whole words only: "therm" does not match "thermostat" or "Thermo Fuel".
_FUEL_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = tuple(
    (re.compile(rf"(?<![a-z0-9]){re.escape(keyword)}(?![a-z0-9])"), fuel) for keyword, fuel in FUEL_KEYWORDS
)
# "Coal 20%, Natural Gas 40%": an electricity fuel-mix disclosure, not a combusted fuel.
_PERCENT_NEAR = re.compile(r"\d\s*%")
# Electricity is Scope 2: a kWh/MWh quantity alone never confirms stationary combustion.
ELECTRIC_UNITS = frozenset({"kWh", "MWh"})

# --- usage tables ----------------------------------------------------------------------
_QTY_EXCLUDE = ("read", "factor", "heat value", "heat content", "price", "rate", "amount", "charge", "cost",
                "$", "days", "multiplier", "pressure", "tax", "total amount", "balance")
_ID_HEADERS = ("meter number", "meter id", "meter #", "meter no", "meter", "tank", "invoice", "ticket", "delivery no")
_UNIT_HEADERS = ("unit", "units", "uom", "unit of measure")
_PRODUCT_HEADERS = ("product", "description", "fuel", "commodity", "item")
_START_HEADERS = ("from", "start", "previous read date", "prev read date", "start date", "period start")
_END_HEADERS = ("to", "end", "current read date", "pres read date", "end date", "period end", "through")
_RANGE_HEADERS = ("service period", "period", "billing period", "service dates")
_DATE_HEADERS = ("date", "delivery date", "read date", "invoice date", "date posted", "posting date",
                 "transaction date", "date delivered")
_TOTAL_ROW_WORDS = ("total", "totals", "subtotal", "grand total")

_MONTHS = {
    m: i
    for i, names in enumerate(
        (
            ("jan", "january"), ("feb", "february"), ("mar", "march"), ("apr", "april"), ("may",),
            ("jun", "june"), ("jul", "july"), ("aug", "august"), ("sep", "sept", "september"),
            ("oct", "october"), ("nov", "november"), ("dec", "december"),
        ),
        start=1,
    )
    for m in names
}
_MONTH_RE = "|".join(sorted(_MONTHS, key=len, reverse=True))
_DATE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?P<y>\d{4})-(?P<m>\d{1,2})-(?P<d>\d{1,2})"),
    re.compile(r"(?P<m>\d{1,2})/(?P<d>\d{1,2})/(?P<y>\d{4}|\d{2})(?!\d)"),
    re.compile(rf"(?P<mon>{_MONTH_RE})\.?\s+(?P<d>\d{{1,2}}),?\s+(?P<y>\d{{4}})", re.IGNORECASE),
    re.compile(rf"(?P<d>\d{{1,2}})[\s-](?P<mon>{_MONTH_RE})\.?[\s-],?(?P<y>\d{{4}})", re.IGNORECASE),
)
_NUMBER_RE = re.compile(
    r"(?P<open>\()?(?P<sign>-)?(?<![\w.,])"
    r"(?P<num>\d{1,3}(?:[,.]\d{3})+(?:[.,]\d+)?|\d+(?:[.,]\d+)?)"
    r"(?!\d)(?P<close>\))?(?P<trail>-(?![\w\d])|\s?CR\b)?"
)
_SLASH_DATE_RE = re.compile(r"(?<!\d)(\d{1,2})/(\d{1,2})/(\d{2}|\d{4})(?!\d)")


# =========================================================================================
# Layout model
# =========================================================================================
@dataclass
class Cell:
    text: str
    page: int | None
    box: dict[str, float] | None  # parser box {left, top, width, height}
    block_id: str | None
    source_reference_id: str | None
    confidence: float | None
    order: int

    @property
    def left(self) -> float:
        return self.box["left"] if self.box else 0.0

    @property
    def right(self) -> float:
        return self.box["left"] + self.box["width"] if self.box else 0.0

    @property
    def center_y(self) -> float:
        return self.box["top"] + self.box["height"] / 2 if self.box else 0.0

    @property
    def height(self) -> float:
        return self.box["height"] if self.box else 0.0


@dataclass
class Row:
    cells: list[Cell]
    page: int | None
    index: int = 0

    @property
    def text(self) -> str:
        return "  ".join(cell.text for cell in self.cells)

    @property
    def top(self) -> float:
        return min((c.box["top"] for c in self.cells if c.box), default=0.0)


@dataclass
class Located:
    """A value plus where it came from."""

    raw: str
    cells: list[Cell]  # value cell(s): bounding box + block ids
    row: Row | None
    confidence: float
    label_cell: Cell | None = None
    context: str | None = None  # snippet override


@dataclass
class UsageRecord:
    quantity: Located
    unit_raw: str | None
    unit_located: Located | None
    hint: str | None
    start: Located | None = None
    end: Located | None = None
    fuel: Located | None = None


@dataclass
class ExtractionOutcome:
    candidates: list[dict]
    halt_reason: dict[str, str] | None = None
    records: int = 0
    notes: list[str] = field(default_factory=list)


def _norm(text: str) -> str:
    return " ".join(str(text).lower().replace("–", "-").replace("—", "-").split())


# =========================================================================================
# Value parsing helpers
# =========================================================================================
# Whether the document being extracted writes slash dates day-first (dd/mm/yyyy).
# A ContextVar keeps concurrent extractions (API thread pool) independent.
_DAY_FIRST: ContextVar[bool] = ContextVar("stationary_combustion_day_first", default=False)


def parse_date(text: str, day_first: bool | None = None) -> tuple[str, int, int] | None:
    """First date in ``text`` as (iso, start, end) span.

    Slash dates are month-first unless the document is day-first (or ``day_first``
    is passed) or the first number cannot be a month ("13/01/2024").
    """

    if day_first is None:
        day_first = _DAY_FIRST.get()
    best: tuple[str, int, int] | None = None
    for pattern in _DATE_PATTERNS:
        for match in pattern.finditer(text):
            parts = match.groupdict()
            try:
                year = int(parts["y"])
                if year < 100:
                    year += 2000
                if parts.get("mon"):
                    month, day = _MONTHS[parts["mon"].lower().rstrip(".")], int(parts["d"])
                elif "/" in match.group(0):
                    first, second = int(parts["m"]), int(parts["d"])
                    month, day = (second, first) if day_first or first > 12 else (first, second)
                else:
                    month, day = int(parts["m"]), int(parts["d"])
                value = date(year, month, day).isoformat()
            except (KeyError, ValueError):
                continue
            if best is None or match.start() < best[1]:
                best = (value, match.start(), match.end())
            break
    return best


def parse_dates(text: str, day_first: bool | None = None) -> list[str]:
    found: list[str] = []
    remaining = text
    while True:
        hit = parse_date(remaining, day_first)
        if hit is None:
            return found
        found.append(hit[0])
        remaining = remaining[hit[2]:]


def slash_dates_are_day_first(texts: Sequence[str]) -> bool:
    """True when some dd/mm date has dd > 12 and no mm/dd date has dd > 12."""

    day_first = month_first = False
    for text in texts:
        for match in _SLASH_DATE_RE.finditer(text):
            first, second = int(match.group(1)), int(match.group(2))
            day_first |= first > 12 >= second
            month_first |= second > 12 >= first
    return day_first and not month_first


def parse_number(text: str) -> tuple[float, str] | None:
    """First number in ``text`` as (value, token as written).

    Handles both thousands conventions ("1,234.5" and "1.234,5"), a decimal comma
    ("12,5"), and credits written "(1,234)", "-1,234", "1,234-" or "1,234 CR"
    (returned negative).
    """

    match = _NUMBER_RE.search(text.replace("−", "-"))
    if not match:
        return None
    token = match.group("num")
    if "," in token and "." in token:
        decimal = "," if token.rfind(",") > token.rfind(".") else "."
    elif "," in token:
        decimal = "." if re.fullmatch(r"\d{1,3}(?:,\d{3})+", token) else ","
    elif "." in token:
        decimal = "" if re.fullmatch(r"\d{1,3}(?:\.\d{3}){2,}", token) else "."
    else:
        decimal = "."
    normalized = token.replace({",": ".", ".": ",", "": "."}[decimal], "")
    if decimal == ",":
        normalized = normalized.replace(",", ".")
    try:
        value = float(normalized)
    except ValueError:
        return None
    negative = bool(match.group("open") and match.group("close")) or bool(match.group("sign")) or bool(
        match.group("trail")
    )
    return (-value if negative else value), match.group(0).strip()


def detect_fuel(text: str) -> tuple[str, str] | None:
    """(fuel_type, matched keyword) for the most specific fuel keyword in ``text``.

    Mentions next to a percentage (fuel-mix lines on electricity bills) are ignored.
    """

    low = _norm(text)
    for pattern, fuel in _FUEL_PATTERNS:
        for match in pattern.finditer(low):
            if _PERCENT_NEAR.search(low[max(0, match.start() - 8): match.end() + 10]):
                continue
            return fuel, match.group(0)
    return None


# =========================================================================================
# Extractor
# =========================================================================================
class StationaryCombustionExtractor:
    """Builds CT-S1-FUELQTY candidates (possibly several records) from parser_output."""

    def handles(self, targets: Sequence[dict]) -> bool:
        return bool(targets) and all(t.get("canonical_type_id") == CANONICAL_TYPE_ID for t in targets)

    def confirms(self, parser_output: dict) -> bool:
        """Content check used when the classifier is unsure: the document names a
        combusted fuel *and* states a quantity in a fuel unit (kWh/MWh do not count:
        electricity is Scope 2)."""

        rows = self._rows(parser_output)
        token = _DAY_FIRST.set(slash_dates_are_day_first([c.text for r in rows for c in r.cells]))
        try:
            if self._document_fuel(rows) is None:
                return False
            records = self._usage_table_records(rows) or self._labeled_quantity_records(rows)
            unit_hint = self._document_unit(rows)
            for record in records:
                unit_text = record.unit_raw or (unit_hint.raw if unit_hint else None)
                unit = fuel_units.find_unit(unit_text) if unit_text else None
                if unit is not None and unit not in ELECTRIC_UNITS:
                    return True
            return False
        finally:
            _DAY_FIRST.reset(token)

    # ---------------------------------------------------------------------------------
    def extract(self, parser_output: dict, targets: Sequence[dict], evidence_id: str) -> ExtractionOutcome:
        document_id = str(parser_output.get("document_id") or "")
        if not document_id:
            raise ValueError("parser_output must include a non-empty 'document_id'.")

        rows = self._rows(parser_output)
        token = _DAY_FIRST.set(slash_dates_are_day_first([c.text for r in rows for c in r.cells]))
        try:
            return self._extract(rows, parser_output, targets, evidence_id, document_id)
        finally:
            _DAY_FIRST.reset(token)

    def _extract(self, rows: list[Row], parser_output: dict, targets: Sequence[dict], evidence_id: str,
                 document_id: str) -> ExtractionOutcome:
        if not any(cell.text.strip() for row in rows for cell in row.cells):
            return ExtractionOutcome(
                candidates=[],
                halt_reason={
                    "code": HALT_UNREADABLE,
                    "message": "No readable text was found in the document (for example a scan without a "
                    "text layer while OCR is off, or an empty file). Upload a text-based PDF or enable OCR.",
                },
            )

        doc_fuel = self._document_fuel(rows)
        if doc_fuel is None:
            return ExtractionOutcome(
                candidates=[],
                halt_reason={
                    "code": HALT_UNSUPPORTED,
                    "message": "No combusted fuel (natural gas, fuel oil, propane, diesel, coal or biomass) is "
                    "named anywhere in the document, so it is not stationary-combustion evidence "
                    "(for example a water or electricity bill).",
                },
            )

        document_values: dict[str, Located | None] = {
            "facility_name": None,
            "service_address": None,
            "supplier_name": self._supplier(rows),
            "account_number": self._account(rows),
        }
        facility, address_from_facility = self._facility(rows)
        document_values["facility_name"] = facility
        document_values["service_address"] = self._address(rows) or address_from_facility

        records = self._usage_table_records(rows) or self._labeled_quantity_records(rows)
        period = self._document_period(rows)
        unit_hint = self._document_unit(rows)

        units = {fuel_units.find_unit(r.unit_raw or (unit_hint.raw if unit_hint else "")) for r in records}
        if records and units <= ELECTRIC_UNITS and any("electric" in _norm(r.text) for r in rows):
            return ExtractionOutcome(
                candidates=[],
                halt_reason={
                    "code": HALT_UNSUPPORTED,
                    "message": "The quantities are electricity (kWh/MWh) on an electricity bill; purchased "
                    "electricity is Scope 2, not stationary combustion.",
                },
            )

        candidates: list[dict] = []
        record_list: list[UsageRecord | None] = list(records) if records else [None]
        multi = len(record_list) > 1
        for index, record in enumerate(record_list, start=1):
            record_values = self._record_values(record, period, doc_fuel, unit_hint)
            record_index = index if multi else None
            record_key = self._record_key(index, record, record_values) if multi else None
            record_candidates: list[dict] = []
            for target in targets:
                field_id = str(target.get("field_id") or "")
                if field_id in DOCUMENT_FIELDS:
                    record_candidates.append(self._candidate_for_text(
                        target, document_values.get(field_id), document_id, evidence_id, record_key,
                        record_index, parser_output, field_id))
                elif field_id in RECORD_FIELDS:
                    record_candidates.append(self._record_candidate(
                        target, record_values, document_id, evidence_id, record_key, record_index, parser_output))
                else:
                    record_candidates.append(self._missing(target, document_id, evidence_id, record_key,
                                                           record_index, ["unsupported_extraction_method"]))
            if multi:
                label = self._record_display(index, record, record_values)
                for candidate in record_candidates:
                    candidate["display_label"] = f"{candidate['display_label']} ({label})"
                    # Downstream (approved evidence, methodology values) groups by source_reference.record_key.
                    candidate["source_reference"]["record_key"] = record_key
            candidates.extend(record_candidates)
        return ExtractionOutcome(candidates=candidates, records=len(record_list) if records else 0)

    # =================================================================================
    # Layout
    # =================================================================================
    def _rows(self, parser_output: dict) -> list[Row]:
        cells: list[Cell] = []
        order = 0
        for block in parser_output.get("text_blocks", []) or []:
            if not isinstance(block, dict):
                continue
            text = str(block.get("text") or "")
            box = block.get("bounding_box") if isinstance(block.get("bounding_box"), dict) else None
            lines = [line for line in text.splitlines() if line.strip()]
            if box is not None and len(lines) > 1:
                box = None  # a multi-line block's box does not locate any single line
            for line in lines:
                order += 1
                cells.append(Cell(
                    text=" ".join(line.split()) if box is not None else line.strip(), page=block.get("page_number"), box=box,
                    block_id=block.get("block_id"), source_reference_id=block.get("source_reference_id"),
                    confidence=self._as_conf(block.get("confidence")), order=order,
                ))
        if not cells:
            for page in parser_output.get("pages", []) or []:
                if not isinstance(page, dict):
                    continue
                for line in str(page.get("text") or "").splitlines():
                    if line.strip():
                        order += 1
                        cells.append(Cell(line.strip(), page.get("page_number"), None, None, None, None, order))

        rows: list[Row] = []
        boxed = sorted((c for c in cells if c.box), key=lambda c: (c.page or 0, c.center_y, c.left))
        for cell in boxed:
            current = rows[-1] if rows else None
            if (
                current is not None
                and current.page == cell.page
                and current.cells[-1].box is not None
                and abs(cell.center_y - sum(c.center_y for c in current.cells) / len(current.cells))
                <= 0.6 * max(min(cell.height, current.cells[0].height), 1e-6)
            ):
                current.cells.append(cell)
            else:
                rows.append(Row(cells=[cell], page=cell.page))
        for row in rows:
            row.cells.sort(key=lambda c: c.left)
        # Lines without geometry: split columns on runs of 2+ spaces, tabs or pipes.
        for cell in (c for c in cells if not c.box):
            parts = [" ".join(p.split()) for p in re.split(r"\t+|\s{2,}|\s*\|\s*", cell.text) if p.strip()]
            rows.append(Row(
                cells=[Cell(p, cell.page, None, cell.block_id, cell.source_reference_id, cell.confidence, cell.order)
                       for p in parts] or [cell],
                page=cell.page,
            ))
        rows.extend(self._table_rows(parser_output, order))
        rows.sort(key=lambda r: (r.page or 0, r.top if r.cells[0].box else 0, r.cells[0].order))
        for index, row in enumerate(rows):
            row.index = index
        return rows

    def _table_rows(self, parser_output: dict, order: int) -> list[Row]:
        """Rows of structured parser tables (Textract / spreadsheets) not already in text."""

        if parser_output.get("text_blocks"):
            return []
        rows: list[Row] = []
        for table in parser_output.get("tables", []) or []:
            if not isinstance(table, dict):
                continue
            for raw_row in table.get("rows") or []:
                if not isinstance(raw_row, list):
                    continue
                order += 1
                cells = [Cell(str(v).strip(), table.get("page_number"), None, None, table.get("source_reference_id"),
                              None, order) for v in raw_row if v not in (None, "") and str(v).strip()]
                if cells:
                    rows.append(Row(cells=cells, page=table.get("page_number")))
        return rows

    # =================================================================================
    # Label / value lookup
    # =================================================================================
    @staticmethod
    def _label_prefix(text: str, labels: Sequence[str]) -> tuple[str, str, bool] | None:
        """(label, remainder, had_delimiter) when ``text`` starts with one of ``labels``."""

        low = _norm(text)
        best: tuple[str, str, bool] | None = None
        for label in labels:
            if not low.startswith(label):
                continue
            rest_low = low[len(label):]
            if rest_low and rest_low[0].isalnum():
                continue  # "customer" must not match "customers"
            if best is not None and len(label) <= len(best[0]):
                continue
            raw_rest = " ".join(text.split())[len(label):]
            stripped = raw_rest.lstrip()
            # "Total Usage (Therms): 1,234" - a parenthetical belongs to the label
            paren = re.match(r"\([^()]{1,30}\)\s*", stripped)
            if paren and stripped[paren.end():][:1] in (":", "#", "="):
                stripped = stripped[paren.end():]
            had_delimiter = bool(stripped) and stripped[0] in ":#=" or stripped.lower().startswith(("no.", "no:"))
            remainder = stripped.lstrip(":#=").strip() if had_delimiter else stripped.strip()
            if stripped.lower().startswith(("no.", "no:")) and label.endswith(("number", "no", "#")):
                remainder = stripped[3:].strip()
            best = (label, remainder, had_delimiter)
        return best

    def _find_labeled(
        self,
        rows: Sequence[Row],
        groups: Sequence[Sequence[str]],
        *,
        accept: Any = None,
        allow_next_row: bool = True,
        accept_bare: Any = None,
    ) -> Located | None:
        """First value for the highest-priority label group.

        ``accept`` validates a candidate value. ``accept_bare`` (stricter) allows
        "Label value" with no delimiter, e.g. "Account Number 1234-5678"; without it
        such text is treated as a phrase ("Customer charge"), not a label.
        """
        for labels in groups:
            for row in rows:
                for position, cell in enumerate(row.cells):
                    prefix = self._label_prefix(cell.text, labels)
                    if prefix is None:
                        continue
                    _, remainder, had_delimiter = prefix
                    # 1) "Label: value" in the same cell
                    if remainder and had_delimiter:
                        value = self._trim_value(remainder)
                        if value and (accept is None or accept(value)):
                            return Located(value, [cell], row, CONF_SAME_CELL, label_cell=cell)
                        continue
                    if remainder:  # "Customer charge" - a phrase, not a label, unless strictly valid
                        value = self._trim_value(remainder)
                        if accept_bare is not None and value and accept_bare(value):
                            return Located(value, [cell], row, CONF_SAME_CELL - 0.04, label_cell=cell)
                        continue
                    # 2) value in the next cell of the same visual row (unless that cell is
                    #    another column's label or sits far away, as in a two-column header)
                    if position + 1 < len(row.cells):
                        nxt = row.cells[position + 1]
                        is_label = self._label_prefix(nxt.text, _ALL_LABELS) is not None
                        far = cell.box is not None and nxt.box is not None and nxt.left - cell.right > 0.25
                        if not is_label and not far:
                            value = self._trim_value(nxt.text)
                            if value and (accept is None or accept(value)):
                                return Located(value, [nxt], row, CONF_NEXT_CELL, label_cell=cell,
                                               context=f"{cell.text} {nxt.text}")
                            continue
                    # 3) label alone on its row: value directly below, left-aligned
                    if allow_next_row and cell.box is not None:
                        below = self._cell_below(rows, row, cell)
                        if below is not None:
                            value = self._trim_value(below[1].text)
                            if value and (accept is None or accept(value)):
                                return Located(value, [below[1]], below[0], CONF_NEXT_ROW, label_cell=cell,
                                               context=f"{cell.text} {below[1].text}")
        return None

    @staticmethod
    def _cell_below(rows: Sequence[Row], row: Row, cell: Cell) -> tuple[Row, Cell] | None:
        if row.index + 1 >= len(rows):
            return None
        nxt = rows[row.index + 1]
        if nxt.page != row.page:
            return None
        for candidate in nxt.cells:
            if candidate.box and abs(candidate.left - cell.left) < 0.02:
                if candidate.box["top"] - (cell.box["top"] + cell.box["height"]) < 3 * cell.box["height"]:  # type: ignore[index]
                    return nxt, candidate
        return None

    @staticmethod
    def _trim_value(value: str) -> str:
        return value.strip().strip(",;").strip()

    # =================================================================================
    # Document-level fields
    # =================================================================================
    def _facility(self, rows: Sequence[Row]) -> tuple[Located | None, Located | None]:
        located = self._find_labeled(rows, FACILITY_LABELS, accept=lambda v: bool(re.search(r"[A-Za-z]{2}", v)))
        if located is None:
            return None, None
        # "Site: Standby Generator Plant, 77 Weir Lane, Lodi, CA" -> name + address
        split = re.match(r"^(?P<name>[^,\d][^,]*?),\s*(?P<addr>\d+\s+\S.*)$", located.raw)
        if split:
            name = Located(split.group("name").strip(), located.cells, located.row, located.confidence,
                           located.label_cell, located.context)
            address = Located(split.group("addr").strip(), located.cells, located.row, located.confidence - 0.05,
                              located.label_cell, located.context)
            return name, address
        return located, None

    def _address(self, rows: Sequence[Row]) -> Located | None:
        return self._find_labeled(rows, ADDRESS_LABELS, accept=lambda v: bool(re.search(r"\d", v)),
                                  accept_bare=lambda v: bool(re.match(r"\d+\s+\S", v)))

    def _account(self, rows: Sequence[Row]) -> Located | None:
        def accept(value: str) -> bool:
            return bool(re.search(r"\d", value)) and parse_date(value) is None and not value.startswith("$")

        def accept_bare(value: str) -> bool:  # first token must look like an identifier
            return accept(value) and bool(re.match(r"[A-Za-z0-9#-]*\d[\w-]*", value))

        return self._find_labeled(rows, ACCOUNT_LABELS, accept=accept, accept_bare=accept_bare)

    def _supplier(self, rows: Sequence[Row]) -> Located | None:
        labeled = self._find_labeled(rows, SUPPLIER_LABELS, accept=self._looks_like_org_name, allow_next_row=False)
        letterhead = self._letterhead(rows)
        if letterhead is not None and (labeled is None or labeled.row is None or labeled.row.index > 2):
            return letterhead
        if labeled is not None:
            labeled.raw = re.split(r"\s{2,}|\s+(?:GST|HST|VAT|Tax ID|EIN)\b", labeled.raw)[0].strip()
        return labeled

    def _letterhead(self, rows: Sequence[Row]) -> Located | None:
        """The largest text near the top of page 1, when it reads like an organization.

        Without geometry (plain text), the first of the top lines naming a company.
        """

        first_page = [r for r in rows if (r.page or 1) == (rows[0].page or 1)][:6] if rows else []
        cells = [c for r in first_page for c in r.cells if c.box and c.box["top"] < 0.2]
        if not cells:
            for row in first_page[:4]:
                text = row.cells[0].text
                if len(row.cells) == 1 and re.search(r"\b(company|co\.|inc\.?|llc|ltd\.?|corp\.?|utilities)\b", text, re.I):
                    name = re.split(r"\s+[-\u2013\u2014|]\s+", text)[0].strip()
                    if self._looks_like_org_name(name):
                        return Located(name, [row.cells[0]], row, CONF_LETTERHEAD - 0.05, context=text)
            return None
        cell = max(cells, key=lambda c: (c.height, -c.order))
        if cell.height < 1.25 * min(c.height for c in cells):
            return None
        text = cell.text
        prefix = self._label_prefix(text, SUPPLIER_LABELS[0])
        if prefix is not None and prefix[1]:
            text = prefix[1]
        if not self._looks_like_org_name(text):
            return None
        row = next(r for r in first_page if cell in r.cells)
        return Located(self._trim_value(text), [cell], row, CONF_LETTERHEAD)

    @staticmethod
    def _looks_like_org_name(value: str) -> bool:
        low = f" {_norm(value)}"
        if not re.search(r"[A-Za-z]{3}", value) or re.fullmatch(r"[\d\W]+", value):
            return False
        if any(low.strip().startswith(word) for word in DOCUMENT_TITLE_WORDS) and not any(h in low for h in ORG_HINTS):
            return False
        return any(h in low for h in ORG_HINTS) or value.isupper() or len(value.split()) >= 2

    # =================================================================================
    # Fuel
    # =================================================================================
    def _document_fuel(self, rows: Sequence[Row]) -> Located | None:
        labeled = self._find_labeled(rows, FUEL_LABELS, accept=lambda v: detect_fuel(v) is not None,
                                     accept_bare=lambda v: detect_fuel(v) is not None)
        if labeled is not None:
            return labeled
        for row in rows:
            for cell in row.cells:
                if detect_fuel(cell.text) is not None:
                    return Located(cell.text, [cell], row, CONF_DOCUMENT_SCAN)
        return None

    # =================================================================================
    # Periods
    # =================================================================================
    def _document_period(self, rows: Sequence[Row]) -> tuple[Located | None, Located | None]:
        def starts_with_date(value: str) -> bool:
            hit = parse_date(value)
            return hit is not None and hit[1] == 0

        def starts_with_range(value: str) -> bool:
            return starts_with_date(value) and len(parse_dates(value)) >= 2

        delivery = self._find_labeled(rows, DELIVERY_DATE_LABELS, accept=lambda v: parse_date(v) is not None,
                                      accept_bare=starts_with_date)
        if delivery is not None:
            return delivery, delivery
        ranged = self._find_labeled(rows, RANGE_PERIOD_LABELS, accept=lambda v: len(parse_dates(v)) >= 2,
                                    accept_bare=starts_with_range)
        if ranged is not None:
            return ranged, ranged
        start = self._find_labeled(rows, START_LABELS, accept=lambda v: parse_date(v) is not None,
                                   accept_bare=starts_with_date)
        end = self._find_labeled(rows, END_LABELS, accept=lambda v: parse_date(v) is not None,
                                 accept_bare=starts_with_date)
        return start, end

    # =================================================================================
    # Quantities
    # =================================================================================
    def _usage_table_records(self, rows: Sequence[Row]) -> list[UsageRecord]:
        for row in rows:
            header = self._usage_header(row)
            if header is None:
                continue
            records = self._table_records(rows, row, header)
            if records:
                return records
        return []

    def _usage_header(self, row: Row) -> dict[str, int] | None:
        if len(row.cells) < 3:
            return None
        texts = [_norm(c.text) for c in row.cells]
        if any(re.search(r"\d{3}|\d,\d|\d\.\d|\d/\d", t) for t in texts):
            return None  # header rows carry labels, not values
        scores: list[tuple[int, int]] = []
        for index, text in enumerate(texts):
            score = self._quantity_header_score(text)
            if score > 0:
                scores.append((score, index))
        if not scores:
            return None
        columns: dict[str, int] = {"quantity": max(scores)[1]}
        for index, text in enumerate(texts):
            if index == columns["quantity"]:
                continue
            bare = text.strip(" :#")
            if "unit" not in columns and bare in _UNIT_HEADERS:
                columns["unit"] = index
            elif "id" not in columns and any(bare == h or bare.startswith(h + " ") for h in _ID_HEADERS):
                columns["id"] = index
            elif "product" not in columns and bare in _PRODUCT_HEADERS:
                columns["product"] = index
            elif "range" not in columns and bare in _RANGE_HEADERS:
                columns["range"] = index
            elif "start" not in columns and bare in _START_HEADERS:
                columns["start"] = index
            elif "end" not in columns and bare in _END_HEADERS:
                columns["end"] = index
            elif "date" not in columns and bare in _DATE_HEADERS:
                columns["date"] = index
        return columns

    @staticmethod
    def _quantity_header_score(text: str) -> int:
        bare = text.strip(" :#")
        if any(word in text for word in _QTY_EXCLUDE) or bare in _UNIT_HEADERS or bare.endswith(" unit"):
            return 0
        unit = fuel_units.canonical_unit(text) or fuel_units.find_unit(text)
        score = 0
        if any(w in text for w in ("usage", "consumption", "consumed", "delivered", "billed", "used", "issued")):
            score += 4
        if any(w in text for w in ("qty", "quantity")):
            score += 3
        if "volume" in text:
            score += 1
        if unit is not None:
            score += 2 + (1 if fuel_units.dimension_of(unit) == fuel_units.ENERGY else 0)
            if fuel_units.canonical_unit(text) is not None:
                score += 1  # the whole header is a unit, e.g. "Dth", "Gallons"
        if "difference" in text:
            score = min(score, 1)
        return score

    def _table_records(self, rows: Sequence[Row], header_row: Row, columns: dict[str, int]) -> list[UsageRecord]:
        header_cells = header_row.cells
        header_unit = fuel_units.find_unit(header_cells[columns["quantity"]].text)
        records: list[UsageRecord] = []
        last_top = header_row.top
        header_texts = [_norm(c.text) for c in header_cells]
        current_page = header_row.page
        position = header_row.index + 1
        while position < len(rows):
            row = rows[position]
            position += 1
            if row.page != current_page or (
                row.cells[0].box and header_cells[0].box
                and row.top - last_top > 4 * max(header_cells[0].height, 1e-6)
            ):
                # The table may continue under a repeated header (next page, or after a page footer).
                repeat = next(
                    (r for r in rows[row.index:row.index + 12]
                     if [_norm(c.text) for c in r.cells] == header_texts and r.index != header_row.index),
                    None,
                )
                if repeat is None or not records:
                    break
                header_row, header_cells = repeat, repeat.cells
                current_page, last_top, position = repeat.page, repeat.top, repeat.index + 1
                continue
            assigned = self._assign_columns(row, header_cells)
            first = _norm(row.cells[0].text)
            if any(first == w or first.startswith(w + " ") for w in _TOTAL_ROW_WORDS):
                break
            qty_cell = assigned.get(columns["quantity"])
            number = parse_number(qty_cell.text) if qty_cell is not None else None
            if qty_cell is None or number is None:
                break  # a usage table's data starts right under its header
            last_top = row.top
            unit_cell = assigned.get(columns["unit"]) if "unit" in columns else None
            unit_raw = None
            unit_located = None
            if unit_cell is not None:
                if fuel_units.canonical_unit(unit_cell.text) is None:
                    continue  # e.g. "EA" for a tank rental line: not a fuel quantity
                unit_raw = unit_cell.text
                unit_located = Located(unit_cell.text, [unit_cell], row, CONF_TABLE)
            elif fuel_units.find_unit(qty_cell.text):
                unit_raw = qty_cell.text
            elif header_unit is not None:
                unit_raw = header_cells[columns["quantity"]].text
                unit_located = Located(header_cells[columns["quantity"]].text, [header_cells[columns["quantity"]]],
                                       header_row, CONF_TABLE)
            product_cell = assigned.get(columns["product"]) if "product" in columns else None
            fuel = None
            if product_cell is not None:
                if detect_fuel(product_cell.text) is None:
                    continue  # non-fuel line item
                fuel = Located(product_cell.text, [product_cell], row, CONF_TABLE)
            hint_cell = assigned.get(columns["id"]) if "id" in columns else None
            record = UsageRecord(
                quantity=Located(number[1], [qty_cell], row, CONF_TABLE, context=self._row_context(header_row, row)),
                unit_raw=unit_raw,
                unit_located=unit_located,
                hint=hint_cell.text if hint_cell is not None else None,
                fuel=fuel,
            )
            self._row_dates(record, row, assigned, columns, header_row)
            records.append(record)
        return records

    def _row_dates(self, record: UsageRecord, row: Row, assigned: dict[int, Cell], columns: dict[str, int],
                   header_row: Row) -> None:
        context = self._row_context(header_row, row)
        if "range" in columns and (cell := assigned.get(columns["range"])) is not None and len(parse_dates(cell.text)) >= 2:
            record.start = record.end = Located(cell.text, [cell], row, CONF_TABLE, context=context)
            return
        if "start" in columns and (cell := assigned.get(columns["start"])) is not None and parse_date(cell.text):
            record.start = Located(cell.text, [cell], row, CONF_TABLE, context=context)
        if "end" in columns and (cell := assigned.get(columns["end"])) is not None and parse_date(cell.text):
            record.end = Located(cell.text, [cell], row, CONF_TABLE, context=context)
        if record.start is None and record.end is None and "date" in columns:
            cell = assigned.get(columns["date"])
            if cell is not None and parse_date(cell.text):
                record.start = record.end = Located(cell.text, [cell], row, CONF_TABLE, context=context)

    @staticmethod
    def _assign_columns(row: Row, header_cells: Sequence[Cell]) -> dict[int, Cell]:
        """Map each data cell to the header column it sits under."""

        assigned: dict[int, Cell] = {}
        if not all(c.box for c in row.cells) or not all(h.box for h in header_cells):
            for index, cell in enumerate(row.cells[: len(header_cells)]):
                assigned[index] = cell
            return assigned
        for cell in row.cells:
            best_index, best_score = None, None
            for index, head in enumerate(header_cells):
                overlap = min(cell.right, head.right) - max(cell.left, head.left)
                distance = abs((cell.left + cell.right) / 2 - (head.left + head.right) / 2)
                score = (overlap > 0, overlap if overlap > 0 else -distance)
                if best_score is None or score > best_score:
                    best_index, best_score = index, score
            if best_index is not None and best_index not in assigned:
                assigned[best_index] = cell
        return assigned

    @staticmethod
    def _row_context(header_row: Row, row: Row) -> str:
        return f"{header_row.text} | {row.text}"

    def _labeled_quantity_records(self, rows: Sequence[Row]) -> list[UsageRecord]:
        def accept(value: str) -> bool:
            return parse_number(value) is not None and not value.strip().startswith("$")

        located = self._find_labeled(rows, QUANTITY_LABELS, accept=accept,
                                     accept_bare=lambda v: bool(re.match(r"\(?-?\d", v)))
        if located is None:
            return []
        number = parse_number(located.raw)
        assert number is not None
        unit_raw = located.raw if fuel_units.find_unit(located.raw) else None
        if unit_raw is None and located.label_cell is not None:
            # "Total Usage (Therms): 1,234" - the unit is in the label
            label_paren = re.search(r"\(([^()]{1,30})\)", located.label_cell.text)
            if label_paren and fuel_units.find_unit(label_paren.group(1)):
                unit_raw = label_paren.group(1)
        unit_located = None
        if unit_raw is None and located.row is not None:
            for cell in located.row.cells:
                if cell not in located.cells and fuel_units.canonical_unit(cell.text):
                    unit_raw, unit_located = cell.text, Located(cell.text, [cell], located.row, CONF_NEXT_CELL)
                    break
        quantity = Located(number[1], located.cells, located.row, located.confidence, located.label_cell,
                           context=located.row.text if located.row else located.raw)
        return [UsageRecord(quantity=quantity, unit_raw=unit_raw, unit_located=unit_located, hint=None)]

    def _document_unit(self, rows: Sequence[Row]) -> Located | None:
        located = self._find_labeled(rows, (("usage unit", "unit of measure", "unit", "units", "uom"),),
                                     accept=lambda v: fuel_units.canonical_unit(v) is not None)
        return located

    # =================================================================================
    # Record assembly
    # =================================================================================
    def _record_values(self, record: UsageRecord | None, period: tuple[Located | None, Located | None],
                       doc_fuel: Located, unit_hint: Located | None) -> dict[str, Any]:
        values: dict[str, Any] = {"record": record}
        start_loc = record.start if record and record.start else period[0]
        end_loc = record.end if record and record.end else period[1]
        inherited_period = not (record and (record.start or record.end))
        values["service_period_start"] = self._date_value(start_loc, first=True, inherited=inherited_period and record is not None)
        values["service_period_end"] = self._date_value(end_loc, first=False, inherited=inherited_period and record is not None)

        fuel_loc = record.fuel if record and record.fuel else doc_fuel
        detected = detect_fuel(fuel_loc.raw)
        values["fuel_type"] = (fuel_loc, detected[0] if detected else None)

        values["activity_quantity"] = None
        values["activity_unit"] = None
        if record is None:
            return values
        number = parse_number(record.quantity.raw)
        unit_text = record.unit_raw or (unit_hint.raw if unit_hint else None)
        unit_loc = record.unit_located or (unit_hint if unit_hint and not record.unit_raw else None)
        if unit_loc is None and record.unit_raw:
            unit_loc = Located(record.unit_raw, record.quantity.cells, record.quantity.row,
                               record.quantity.confidence, context=record.quantity.context)
        normalized = None
        if number is not None and unit_text:
            try:
                normalized = fuel_units.normalize_quantity(number[0], unit_text)
            except fuel_units.UnitError:
                normalized = None
        values["activity_quantity"] = (record.quantity, number, normalized)
        values["activity_unit"] = (unit_loc, unit_text, normalized)
        return values

    @staticmethod
    def _date_value(located: Located | None, *, first: bool, inherited: bool) -> tuple[Located, str] | None:
        if located is None:
            return None
        dates = parse_dates(located.raw)
        if not dates:
            return None
        value = dates[0] if first else dates[-1]
        if inherited:
            located = Located(located.raw, located.cells, located.row, min(located.confidence, CONF_INHERITED),
                              located.label_cell, located.context)
        return located, value

    @staticmethod
    def _record_display(index: int, record: UsageRecord | None, values: dict[str, Any]) -> str:
        """Short reviewer-facing record label, e.g. "record 2 · meter PR-A1174 · 2024-01-30 to 2024-02-28"."""

        parts = [f"record {index}"]
        if record is not None and record.hint:
            parts.append(record.hint.strip())
        start, end = values.get("service_period_start"), values.get("service_period_end")
        if start and end and start[1] != end[1]:
            parts.append(f"{start[1]} to {end[1]}")
        elif start or end:
            parts.append((start or end)[1])  # type: ignore[index]
        return " · ".join(parts)

    @staticmethod
    def _record_key(index: int, record: UsageRecord | None, values: dict[str, Any]) -> str:
        start = values.get("service_period_start")
        end = values.get("service_period_end")
        parts = [f"r{index}"]
        if record is not None and record.hint:
            parts.append(re.sub(r"\s+", "_", record.hint.strip()))
        if start or end:
            parts.append(f"{start[1] if start else ''}..{end[1] if end else ''}")
        return ":".join(parts)

    # =================================================================================
    # Candidate building
    # =================================================================================
    def _record_candidate(self, target: dict, values: dict[str, Any], document_id: str, evidence_id: str,
                          record_key: str | None, record_index: int | None, parser_output: dict) -> dict:
        field_id = str(target.get("field_id"))
        if field_id in ("service_period_start", "service_period_end"):
            hit = values.get(field_id)
            if hit is None:
                return self._missing(target, document_id, evidence_id, record_key, record_index)
            located, iso = hit
            start, end = values.get("service_period_start"), values.get("service_period_end")
            flags = ["period_start_after_end"] if start and end and start[1] > end[1] else []
            return self._candidate(target, located, located.raw, iso, None, document_id, evidence_id, record_key,
                                   record_index, parser_output, flags)
        if field_id == "fuel_type":
            located, fuel = values["fuel_type"]
            flags = []
            allowed = (target.get("normalization") or {}).get("allowed_values") or []
            if fuel is None:
                return self._missing(target, document_id, evidence_id, record_key, record_index)
            if allowed and fuel not in allowed:
                flags.append("value_not_in_allowed_values")
            raw = located.raw
            return self._candidate(target, located, raw, fuel, None, document_id, evidence_id, record_key,
                                   record_index, parser_output, flags)
        if field_id == "activity_quantity":
            hit = values.get("activity_quantity")
            if hit is None:
                return self._missing(target, document_id, evidence_id, record_key, record_index)
            located, number, normalized = hit
            if number is None:
                return self._missing(target, document_id, evidence_id, record_key, record_index)
            flags = ["negative_quantity"] if number[0] < 0 else []
            if normalized is None:
                flags.append("unit_missing")
                return self._candidate(target, located, number[1], number[0], None, document_id, evidence_id,
                                       record_key, record_index, parser_output, flags)
            if normalized.converted:
                flags.append("unit_converted")
            return self._candidate(target, located, number[1], self._clean_number(normalized.value), normalized.unit,
                                   document_id, evidence_id, record_key, record_index, parser_output, flags)
        if field_id == "activity_unit":
            hit = values.get("activity_unit")
            if hit is None or hit[0] is None or hit[2] is None:
                return self._missing(target, document_id, evidence_id, record_key, record_index)
            located, unit_text, normalized = hit
            flags = ["unit_converted"] if normalized.converted else []
            raw_unit = fuel_units.find_unit(unit_text) or unit_text
            return self._candidate(target, located, raw_unit, normalized.unit, None, document_id, evidence_id,
                                   record_key, record_index, parser_output, flags)
        return self._missing(target, document_id, evidence_id, record_key, record_index)

    def _candidate_for_text(self, target: dict, located: Located | None, document_id: str, evidence_id: str,
                            record_key: str | None, record_index: int | None, parser_output: dict,
                            field_id: str) -> dict:
        if located is None:
            return self._missing(target, document_id, evidence_id, record_key, record_index)
        value = " ".join(located.raw.split())
        return self._candidate(target, located, located.raw, value, None, document_id, evidence_id, record_key,
                               record_index, parser_output, [])

    @staticmethod
    def _clean_number(value: float) -> int | float:
        return int(value) if float(value).is_integer() else round(value, 6)

    def _candidate(self, target: dict, located: Located, raw: Any, normalized: Any, unit: str | None,
                   document_id: str, evidence_id: str, record_key: str | None, record_index: int | None,
                   parser_output: dict, flags: list[str]) -> dict:
        confidence = located.confidence
        parser_conf = [c.confidence for c in located.cells if c.confidence is not None]
        if parser_conf:
            confidence = min(confidence, min(parser_conf))
        return self._build(target, document_id, evidence_id, record_key, record_index,
                           raw=raw, normalized=normalized, unit=unit, confidence=round(confidence, 4),
                           source_reference=self._source_reference(parser_output, located, document_id),
                           flags=flags)

    def _missing(self, target: dict, document_id: str, evidence_id: str, record_key: str | None,
                 record_index: int | None, flags: list[str] | None = None) -> dict:
        field_id = str(target.get("field_id") or "")
        if flags is None:
            flags = ["field_not_found"] if target.get("required_status") in {"core", "conditional"} else []
        return self._build(target, document_id, evidence_id, record_key, record_index,
                           raw=None, normalized=None, unit=None, confidence=CONF_MISSING,
                           source_reference={
                               "source_reference_id": f"missing::{document_id}::{field_id}",
                               "document_id": document_id, "page_number": None, "sheet_name": None,
                               "cell_or_range": None, "text_snippet": None, "bounding_box": None,
                               "parser_block_ids": [],
                           },
                           flags=flags)

    def _build(self, target: dict, document_id: str, evidence_id: str, record_key: str | None,
               record_index: int | None, *, raw: Any, normalized: Any, unit: str | None, confidence: float,
               source_reference: dict, flags: list[str]) -> dict:
        field_id = str(target.get("field_id") or "")
        suffix = f"::r{record_index}" if record_index is not None else ""
        label = str(target.get("field_label") or field_id)
        return {
            "candidate_id": f"candidate::{evidence_id}::{document_id}::{field_id}{suffix}",
            "evidence_id": evidence_id,
            "document_id": document_id,
            "field_name": field_id,
            "display_label": label,
            "raw_value": raw,
            "normalized_value": normalized,
            "unit": unit,
            "confidence": confidence,
            "source_reference": source_reference,
            "validation_flags": list(flags),
            "record_key": record_key,
            "record_index": record_index,
        }

    def _source_reference(self, parser_output: dict, located: Located, document_id: str) -> dict:
        cell = located.cells[0] if located.cells else None
        resolved = None
        if cell is not None and cell.source_reference_id:
            for reference in parser_output.get("source_references", []) or []:
                if isinstance(reference, dict) and reference.get("source_reference_id") == cell.source_reference_id:
                    resolved = copy.deepcopy(reference)
                    break
        boxes = [c.box for c in located.cells if c.box]
        block_ids = [c.block_id for c in located.cells if c.block_id]
        if located.label_cell is not None and located.label_cell.block_id and located.label_cell.block_id not in block_ids:
            block_ids.append(located.label_cell.block_id)
        # Same-line values keep the parser's own line snippet; values found in another
        # cell/row carry their label or table-header context instead.
        snippet_text = (
            located.context
            or (resolved or {}).get("text_snippet")
            or (located.row.text if located.row else located.raw)
        )
        reference = resolved or {
            "source_reference_id": f"inline::{document_id}::{cell.block_id if cell and cell.block_id else 'text'}",
            "document_id": document_id,
            "page_number": cell.page if cell else None,
            "sheet_name": None,
            "cell_or_range": None,
        }
        reference["page_number"] = reference.get("page_number") or (cell.page if cell else None)
        reference["text_snippet"] = self._snippet(snippet_text)
        reference["bounding_box"] = self._union_box(boxes) if boxes else reference.get("bounding_box")
        reference["parser_block_ids"] = block_ids or list(reference.get("parser_block_ids") or [])
        reference.setdefault("sheet_name", None)
        reference.setdefault("cell_or_range", None)
        reference.pop("source_kind", None)
        return reference

    @staticmethod
    def _union_box(boxes: Sequence[dict[str, float]]) -> dict[str, float]:
        left = min(b["left"] for b in boxes)
        top = min(b["top"] for b in boxes)
        right = max(b["left"] + b["width"] for b in boxes)
        bottom = max(b["top"] + b["height"] for b in boxes)
        return {"x": round(left, 6), "y": round(top, 6), "width": round(right - left, 6), "height": round(bottom - top, 6)}

    @staticmethod
    def _snippet(text: Any) -> str | None:
        if text is None:
            return None
        collapsed = " ".join(str(text).split())
        return collapsed if len(collapsed) <= _MAX_SNIPPET else collapsed[: _MAX_SNIPPET - 1].rstrip() + "…"

    @staticmethod
    def _as_conf(value: Any) -> float | None:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        return number / 100 if number > 1 else number


ALL_LABEL_GROUPS: tuple[tuple[str, ...], ...] = (
    FACILITY_LABELS + ADDRESS_LABELS + ACCOUNT_LABELS + SUPPLIER_LABELS + FUEL_LABELS + RANGE_PERIOD_LABELS
    + START_LABELS + END_LABELS + DELIVERY_DATE_LABELS + QUANTITY_LABELS
)
_ALL_LABELS: tuple[str, ...] = tuple(label for group in ALL_LABEL_GROUPS for label in group)
