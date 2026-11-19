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
# The facility is the place the fuel or gas was used: a labelled facility or site, else the name in a
# labelled service / delivery / ship-to block. The company that is billed (bill to, sold to, customer) is
# only a last resort: a ship-to block that repeats it names the site on its next line.
FACILITY_LABELS: tuple[tuple[str, ...], ...] = (
    ("facility name", "facility", "site name", "site", "premises name", "premises", "plant", "location name"),
)
SITE_LOCATION_LABELS: tuple[tuple[str, ...], ...] = (
    ("service location", "service site", "delivery location", "delivery site", "site location",
     "ship to name", "ship to", "deliver to", "delivered to", "service at"),
)
BILL_TO_LABELS: tuple[tuple[str, ...], ...] = (
    ("customer name", "customer", "sold to", "bill to", "billed to", "invoice to", "account name",
     "account holder", "service name"),
)
# Who a bill asks to be paid: the organisation named there is a candidate for the supplier, after the
# letterhead and the labelled reads. (Not a bank, a lockbox or a PO box: those are where, not who.)
REMIT_LABELS: tuple[tuple[str, ...], ...] = (
    ("remit payment to", "remit to", "make checks payable to", "payable to"),
)
# When a document names no site at all, the company on the bill is the facility, as on a utility bill to a
# single plant (the golden set's SC-03 and SC-05). Set False to leave such a document with no facility,
# so it waits in Unassigned supporting evidence until a reviewer picks one.
BILL_TO_NAME_IS_LAST_RESORT_FACILITY = True
ADDRESS_LABELS: tuple[tuple[str, ...], ...] = (
    ("service address", "service location", "premises address", "site address", "facility address",
     "delivery address", "delivered to", "deliver to", "ship to", "service at"),
    ("location", "account address"),
)
# A block under one of these headings names the site the bill is for, as lines in the column below it:
# the customer, then the site name (optional), the street, and the city / postal code. A "MAILING ADDRESS"
# block beside it is never read.
SERVICE_BLOCK_HEADINGS = ("service for", "service to", "service site", "service premise", "service premises")
_STREET_LINE_RE = re.compile(r"^\d+[\w/-]*\s+\S")
_POSTAL_LINE_RE = re.compile(r"(?:^\d{4,6}\s+\S|\d{4,6}(?:-\d{4})?\s*$)")  # "Tacoma, WA 98421" or "8001 Zürich"
_BLOCK_LINES = 6
_BLOCK_COLUMN_TOLERANCE = 0.02


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
DOCUMENT_TITLE_WORDS = ("invoice", "statement", "bill", "ticket", "receipt", "notice", "summary", "report",
                        "usage", "record", "overview", "delivery", "history")
# The last word of a first-line letterhead when nothing else marks it (no larger type)
LETTERHEAD_END_WORDS = frozenset({
    "inc", "llc", "ltd", "limited", "co", "corp", "corporation", "company", "utility", "utilities", "power",
    "energy", "electric", "gas", "water", "department", "authority", "cooperative", "co-op", "district",
    "board"})
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
_START_HEADERS = ("from", "start", "previous read date", "prev read date", "start date", "period start",
                  "cycle start", "service start", "from date")
_END_HEADERS = ("to", "end", "current read date", "pres read date", "end date", "period end", "through",
                "cycle end", "service end", "to date")
_RANGE_HEADERS = ("service period", "period", "billing period", "service dates")
_DATE_HEADERS = ("date", "delivery date", "read date", "invoice date", "date posted", "posting date",
                 "transaction date", "date delivered")
# A usage table ends at its summary row: "Total", or a yearly roll-up such as "Annual quantity" /
# "Year to date", which would double count the rows above it if read as one more record.
_TOTAL_ROW_WORDS = ("total", "totals", "subtotal", "grand total", "annual", "year to date", "ytd", "year total")

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
_MONTHS_BUT_MAY = "|".join(name for name in sorted(_MONTHS, key=len, reverse=True) if name != "may")
# How a line without geometry splits into parts (tabs, 2+ spaces, pipes); the source pane
# splits lines the same way (frontend utils/sourceAnchor.ts).
_LINE_PARTS_RE = re.compile(r"\t+|\s{2,}|\s*\|\s*")
_CSV_BLOCK_PREFIX = "csv_parser-"

_DATE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?P<y>\d{4})-(?P<m>\d{1,2})-(?P<d>\d{1,2})"),
    re.compile(r"(?P<m>\d{1,2})/(?P<d>\d{1,2})/(?P<y>\d{4}|\d{2})(?!\d)"),
    re.compile(rf"(?P<mon>{_MONTH_RE})\.?\s+(?P<d>\d{{1,2}}),?\s+(?P<y>\d{{4}})", re.IGNORECASE),
    re.compile(rf"(?P<d>\d{{1,2}})[\s-](?P<mon>{_MONTH_RE})\.?[\s-],?(?P<y>\d{{4}}|\d{{2}})(?!\d)", re.IGNORECASE),
    # 14.03.2026 - dotted dates are day-first wherever they are used
    re.compile(r"(?<![\d.])(?P<d>\d{1,2})\.(?P<m>\d{1,2})\.(?P<y>\d{4}|\d{2})(?![\d.])"),
    # Jan-2025 - a month column in a monthly log: the first day of that month
    re.compile(rf"(?<![\w-])(?P<mon>{_MONTH_RE})-(?P<y>\d{{4}})(?![\w-])", re.IGNORECASE),
)
# "October 1 - 31, 2025", "Oct 1 \u2013 31, 2025", "September 28 - October 27, 2025", "Dec 16 - Jan 15, 2026":
# a range whose first date has no year of its own. The year is the end date's; a first month after the
# last month ("Dec 16 - Jan 15") is the year before. English month names only: another language's
# names do not match, so such a range simply is not read.
_SHORT_RANGE_RE = re.compile(
    rf"(?<![\w])(?P<m1>{_MONTH_RE})\.?\s+(?P<d1>\d{{1,2}})\s*[-\u2013\u2014]\s*"
    rf"(?:(?P<m2>{_MONTH_RE})\.?\s+)?(?P<d2>\d{{1,2}}),?\s+(?P<y>\d{{4}})(?!\d)", re.IGNORECASE)
_NUMBER_RE = re.compile(
    r"(?P<open>\()?(?P<sign>-)?(?<![\w.,])"
    r"(?P<num>\d{1,3}(?:[,.]\d{3})+(?:[.,]\d+)?|\d+(?:[.,]\d+)?)"
    r"(?!\d)(?P<close>\))?(?P<trail>-(?![\w\d])|\s?CR\b)?"
)
_EXPORTED_FROM_RE = re.compile(
    r"\bexported (?:from|by)\s+(.+?)(?:\s+(?:business |customer |online |web )?(?:portal|account|website)\b|\s+on\s|\s+\d{1,2}/\d{1,2}/\d{2,4}|$)",
    re.IGNORECASE)
_SLASH_DATE_RE = re.compile(r"(?<!\d)(\d{1,2})/(\d{1,2})/(\d{2}|\d{4})(?!\d)")


# =========================================================================================
# Layout model
# =========================================================================================
def _column_letters(column: int) -> str:
    letters = ""
    while column > 0:
        column, rest = divmod(column - 1, 26)
        letters = chr(65 + rest) + letters
    return letters


@dataclass
class Cell:
    text: str
    page: int | None
    box: dict[str, float] | None  # parser box {left, top, width, height}
    block_id: str | None
    source_reference_id: str | None
    confidence: float | None
    order: int
    column: int | None = None  # spreadsheet column (A = 1), when the cell came from a sheet
    # Lines without geometry (CSV rows, Word/text lines): which part of the line this cell is
    # (1 = first), so the source pane can mark the exact spot. For a CSV row it is the column.
    part: int | None = None
    # The line as the parser gave it, before runs of spaces were collapsed (boxed lines only)
    raw_text: str | None = None

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
    extra: dict[str, Located] = field(default_factory=dict)  # subclass EXTRA_COLUMNS values
    energy: str | None = None  # thermal bills: the energy type told from this line (steam / hot_water / chilled_water)


@dataclass
class ExtractionOutcome:
    candidates: list[dict]
    halt_reason: dict[str, str] | None = None
    records: int = 0
    notes: list[str] = field(default_factory=list)


def _blank_dates(text: str) -> str:
    for pattern in _DATE_PATTERNS:
        text = pattern.sub(" ", text)
    return text


# Words in the label above or beside a date that say it is not the service period.
_NOT_A_SERVICE_PERIOD = ("next", "due", "pay by", "statement", "bill date", "billing date", "issued")
_RANGE_SEPARATOR = re.compile(r"^\s*(?:[-\u2013\u2014]|to|through)\s*", re.IGNORECASE)


def _only_a_date_range(text: str) -> bool:
    """Whether ``text`` is exactly a date, a dash (or "to", "through") and a date, 20 to 100 days long. The
    first date may leave its year to the second ("October 1 - 31, 2025"). Anything else in it, two dates with
    no dash between them included, is not a range."""

    if _SHORT_RANGE_RE.fullmatch(text):
        dates = parse_dates(text)
    elif (first := parse_date(text)) is not None and first[1] == 0 and (gap := _RANGE_SEPARATOR.match(text[first[2]:])):
        tail = text[first[2] + gap.end():]
        second = parse_date(tail)
        if second is None or second[1] != 0 or tail[second[2]:].strip():
            return False
        dates = [first[0], second[0]]
    else:
        return False
    return len(dates) == 2 and 20 <= (date.fromisoformat(dates[1]) - date.fromisoformat(dates[0])).days <= 100


def _labelled_as(rows: Sequence[Row], cell: Cell, words: Sequence[str]) -> bool:
    """Whether the text directly above ``cell`` or just to its left contains one of ``words`` (a label such
    as "Next scheduled meter read" or "Current reading"). Cells without geometry have no neighbours."""

    box = cell.box
    if box is None:
        return False
    above: tuple[float, str] | None = None
    left: tuple[float, str] | None = None
    for row in rows:
        if row.page != cell.page:
            continue
        for other in row.cells:
            if other is cell or other.box is None:
                continue
            bottom = other.box["top"] + other.box["height"]
            rise = box["top"] - bottom
            if -0.005 <= rise <= max(cell.height, 0.03) and other.left < cell.right and other.right > cell.left:
                if above is None or rise < above[0]:
                    above = (rise, other.text)
            beside = cell.left - other.right
            if -0.005 <= beside <= 0.15 and abs(other.center_y - cell.center_y) <= max(cell.height, other.height) / 2:
                if left is None or beside < left[0]:
                    left = (beside, other.text)
    return any(_has_word(found[1], word) for found in (above, left) if found for word in words)


def _names_a_month(text: str) -> bool:
    """Whether ``text`` names a month. "May" counts only beside a day number or a year ("you may pay online" is
    a sentence)."""

    if re.search(rf"\b(?:{_MONTHS_BUT_MAY})\b", text, re.IGNORECASE):
        return True
    return re.search(r"\bmay\s+\d{1,2}\b|\b\d{1,2}\s+may\b|\bmay,?\s+(?:19|20)\d{2}\b", text, re.IGNORECASE) is not None


def _has_word(text: str, word: str) -> bool:
    """Whether ``word`` is in ``text`` as a whole word or phrase ("rate" is not in "Corporate"), ignoring a
    parenthesis that holds a number: "Your usage (31 days)" is a heading about usage, "Days in period" is about
    days. A parenthesis with only words in it ("Same month (last year)", "Tank (capacity)") says what the
    figure is, so it counts. A word with no letter or digit in it ("$") is looked for as it is."""

    low = re.sub(r"\([^)]*\d[^)]*\)", " ", text.lower())
    if not any(char.isalnum() for char in word):
        return word in low
    return re.search(rf"(?<!\w){re.escape(word)}(?!\w)", low) is not None


def _third_band_floor(heights: Sequence[float]) -> float | None:
    """The smallest text height among the three tallest sizes on a page, where heights within 10% of the tallest
    of their size are one size (OCR reports a size as 0.0599, 0.0601 and 0.0602)."""

    bands: list[float] = []  # the smallest height of each band, tallest band first
    top = 0.0
    for height in sorted(set(heights), reverse=True):
        if bands and height >= 0.9 * top:
            bands[-1] = height
            continue
        bands.append(height)
        top = height
        if len(bands) > 3:
            bands.pop()
            break
    return bands[-1] if bands else None


_LEGAL_SUFFIXES = frozenset({"inc", "incorporated", "llc", "co", "company", "corp", "corporation", "ltd", "limited",
                             "gmbh", "ag", "sa", "plc"})
_UTILITY_WORDS = frozenset({"gas", "energy", "electric", "electricity", "power", "utility", "utilities", "water", "fuel",
                            "fuels", "propane", "oil", "petroleum", "heating", "cooperative", "coop", "authority",
                            "district", "light", "natural", "steam"})
# What a supplier's name ends in. A name that ends in anything else on a Remit To line is a person, a bank or a
# department, not the company.
_ORGANISATION_WORDS = frozenset({"co", "company", "inc", "llc", "ltd", "corp", "corporation", "energy", "gas", "power",
                                 "utilities", "utility", "electric", "district", "authority", "cooperative"})
_NOT_A_PAYEE = re.compile(
    r"\b(?:c/o|attn|dept|department|cent(?:er|re)|processing|payments?|lock\s?box|bank|n\.?a\.?|services?|billing|"
    r"remittance|p\.?\s?o\.?\s*box)(?!\w)", re.IGNORECASE)


def _company_words(name: str) -> list[str]:
    """A company name as comparable words: lower case, no punctuation, bracketed text or branch after a spaced
    dash ("Northgate Provisions Inc - Plant 4"), and no legal suffix (Inc, LLC, Co, Corp, Ltd...)."""

    low = re.sub(r"\([^)]*\)|\[[^\]]*\]", " ", re.split(r"\s+[-\u2013\u2014]\s+", name.casefold())[0])
    return [word for word in re.sub(r"[\W_]+", " ", low).split() if word not in _LEGAL_SUFFIXES]


def _same_company(first: str, second: str) -> bool:
    """Whether two names are one company: equal as words once case, punctuation, legal suffixes, brackets and a
    branch after a dash are gone ("Northgate Provisions Inc - Plant 4" and "NORTHGATE PROVISIONS INC"). "Sierra Basin
    Co" and "Sierra Basin Foods Inc", or "City of Lodi" and "City of Lodi Utilities", are two companies."""

    a, b = _company_words(first), _company_words(second)
    return bool(a) and a == b


def _names_a_utility(name: str) -> bool:
    return any(word in _UTILITY_WORDS for word in _company_words(name))


def _is_customer(name: str, customers: Sequence[str]) -> bool:
    """Whether ``name`` (a letterhead or a payee; a labelled supplier is only compared with ``_same_company``) is
    one of the customers or the customer's parent: the same company, one name starting with the other (the
    shorter has two words or more), the same first two words, or the same first word (four letters or more) in a
    name that says nothing about being a utility."""

    words = _company_words(name)
    for customer in customers:
        theirs = _company_words(customer)
        if _same_company(name, customer):
            return True
        short, long = sorted((words, theirs), key=len)
        if len(short) >= 2 and long[:len(short)] == short:  # "NORTHGATE ENERGY PARTNERS FRESNO CO" is the customer's
            return True
        if len(words) >= 2 and len(theirs) >= 2 and words[:2] == theirs[:2] and not _names_a_utility(name):
            return True
        if words and theirs and words[0] == theirs[0] and len(words[0]) >= 4 and not _names_a_utility(name):
            return True
    return False


def _has_letters(value: str) -> bool:
    return bool(re.search(r"[^\W\d_]{2}", value))


def _name_key(text: str) -> str:
    """A name compared ignoring case, punctuation and spacing."""

    return " ".join(re.sub(r"[\W_]+", " ", text.casefold()).split())


def _is_attention_line(text: str) -> bool:
    return bool(re.match(r"^(attn|attention|c/o|care of)\b", text.strip(), re.I))


_CITY_STATE_ZIP = re.compile(r"^[^\d,]+,\s*[A-Z]{2}\s+\d{5}(-\d{4})?\s*$")


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
                    month, day = _MONTHS[parts["mon"].lower().rstrip(".")], int(parts.get("d") or 1)
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


def _short_range(match: re.Match[str]) -> tuple[str, str] | None:
    parts = match.groupdict()
    try:
        year = int(parts["y"])
        end_month = _MONTHS[(parts["m2"] or parts["m1"]).lower().rstrip(".")]
        start_month = _MONTHS[parts["m1"].lower().rstrip(".")]
        start_year = year - 1 if start_month > end_month else year
        start = date(start_year, start_month, int(parts["d1"]))
        end = date(year, end_month, int(parts["d2"]))
    except (KeyError, ValueError):
        return None
    return (start.isoformat(), end.isoformat()) if start <= end else None


def parse_dates(text: str, day_first: bool | None = None) -> list[str]:
    short = _SHORT_RANGE_RE.search(text)
    if short is not None and (pair := _short_range(short)) is not None:
        return [*parse_dates(text[:short.start()], day_first), *pair, *parse_dates(text[short.end():], day_first)]
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
    """Builds CT-S1-FUELQTY candidates (possibly several records) from parser_output.

    The layout engine (visual rows, label/value lookup, usage tables, traceability) is
    shared with other fuel types: subclasses override the class-level vocabularies,
    ``EXTRA_COLUMNS`` and ``_fuel`` (see MobileCombustionExtractor).
    """

    CANONICAL_TYPE_ID: str = CANONICAL_TYPE_ID
    FUEL_LABEL_GROUPS: tuple[tuple[str, ...], ...] = FUEL_LABELS
    QUANTITY_LABEL_GROUPS: tuple[tuple[str, ...], ...] = QUANTITY_LABELS
    ID_HEADERS: tuple[str, ...] = _ID_HEADERS
    PRODUCT_HEADERS: tuple[str, ...] = _PRODUCT_HEADERS
    DATE_HEADERS: tuple[str, ...] = _DATE_HEADERS
    UNIT_HEADERS: tuple[str, ...] = _UNIT_HEADERS
    QTY_EXCLUDE: tuple[str, ...] = _QTY_EXCLUDE
    # Whether a bill that leads with its quantity in large type ("1,486" over "therms used") is read. Only the
    # natural gas reader reads it: the others look for other units and layouts, and a number above a unit word
    # is too weak a sign for them.
    HEADLINE_QUANTITY = True
    # Whether "TOTAL 1,273.1 THERMS" inside a line of a dense statement is read as the quantity (the gas reader
    # only, like the headline read).
    INLINE_TOTAL_QUANTITY = True
    # Additional table columns kept on each record: key -> header names (normalized).
    # A fuel log's "Site" / "Facility" column: each line's facility (a log can cover several).
    EXTRA_COLUMNS: dict[str, tuple[str, ...]] = {
        "site": ("site", "site name", "facility", "facility name", "plant", "building", "premises"),
        # A portal export repeats the account on every row.
        "account": ("account", "account number", "account no", "account #", "acct", "acct no", "customer account"),
    }
    ALL_LABELS: tuple[str, ...] = ()  # filled after the module-level label groups

    def handles(self, targets: Sequence[dict]) -> bool:
        return bool(targets) and all(t.get("canonical_type_id") == self.CANONICAL_TYPE_ID for t in targets)

    def _fuel(self, text: str) -> tuple[str, str] | None:
        """(fuel_type, matched keyword) for a fuel this extractor accepts."""

        return detect_fuel(text)

    def confirms(self, parser_output: dict) -> bool:
        """Content check used when the classifier is unsure: the document names a
        combusted fuel *and* states a quantity in a fuel unit (kWh/MWh do not count:
        electricity is Scope 2)."""

        rows = self._rows(parser_output)
        token = _DAY_FIRST.set(slash_dates_are_day_first([c.text for r in rows for c in r.cells]))
        try:
            if self._document_fuel(rows) is None:
                return False
            records = self._quantity_records(rows)
            unit_hint = self._document_unit(rows)
            for record in records:
                unit_text = record.unit_raw or (unit_hint.raw if unit_hint else None)
                unit = self._find_unit(unit_text) if unit_text else None
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

        records = self._quantity_records(rows)
        if not records and self.HEADLINE_QUANTITY:  # extraction only: classification (confirms) never reads these
            records = self._headline_quantity_records(rows)
        if not records and self.INLINE_TOTAL_QUANTITY:  # the weakest read, so it runs only when nothing else found one
            records = self._inline_total_records(rows, doc_fuel)
        period = self._document_period(rows)
        unit_hint = self._document_unit(rows)

        units = {self._find_unit(r.unit_raw or (unit_hint.raw if unit_hint else "")) for r in records}
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
                    located = document_values.get(field_id)
                    if field_id == "facility_name" and record is not None and record.extra.get("site") is not None:
                        located = record.extra["site"]
                    if field_id == "account_number" and located is None and record is not None:
                        located = record.extra.get("account")
                    record_candidates.append(self._candidate_for_text(
                        target, located, document_id, evidence_id, record_key,
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
        sheet_positions = self._sheet_positions(parser_output)
        sheet_rows: dict[tuple[str | None, int], list[Cell]] = {}
        for block in parser_output.get("text_blocks", []) or []:
            if not isinstance(block, dict):
                continue
            text = str(block.get("text") or "")
            position = sheet_positions.get(str(block.get("source_reference_id") or ""))
            if position is not None:
                # A spreadsheet cell: one visual row per sheet row, columns by letter.
                if text.strip():
                    order += 1
                    sheet_rows.setdefault((position[0], position[1]), []).append(Cell(
                        text=" ".join(text.split()), page=block.get("page_number"), box=None,
                        block_id=block.get("block_id"), source_reference_id=block.get("source_reference_id"),
                        confidence=self._as_conf(block.get("confidence")), order=order, column=position[2],
                    ))
                continue
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
                    raw_text=line.strip() if box is not None else None,
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
        # Lines without geometry: split columns on runs of 2+ spaces, tabs or pipes. A CSV row
        # is split exactly as the CSV parser joined it (" | "), so each part keeps its column.
        for cell in (c for c in cells if not c.box):
            if str(cell.block_id or "").startswith(_CSV_BLOCK_PREFIX):
                numbered = [(i, " ".join(p.split())) for i, p in enumerate(cell.text.split(" | "), start=1)]
            else:
                numbered = list(enumerate((" ".join(p.split()) for p in _LINE_PARTS_RE.split(cell.text)), start=1))
            parts = [(i, p) for i, p in numbered if p]
            rows.append(Row(
                cells=[Cell(p, cell.page, None, cell.block_id, cell.source_reference_id, cell.confidence, cell.order,
                            part=i) for i, p in parts] or [cell],
                page=cell.page,
            ))
        for sheet_cells in sheet_rows.values():
            sheet_cells.sort(key=lambda c: c.column or 0)
            rows.append(Row(cells=sheet_cells, page=sheet_cells[0].page))
        rows.extend(self._table_rows(parser_output, order))
        rows.sort(key=lambda r: (r.page or 0, r.top if r.cells[0].box else 0, r.cells[0].order))
        for index, row in enumerate(rows):
            row.index = index
        return rows

    @staticmethod
    def _sheet_positions(parser_output: dict) -> dict[str, tuple[str | None, int, int]]:
        """source_reference_id -> (sheet, row, column) for spreadsheet cells ("B12" -> 12, 2)."""

        positions: dict[str, tuple[str | None, int, int]] = {}
        for reference in parser_output.get("source_references", []) or []:
            if not isinstance(reference, dict):
                continue
            match = re.fullmatch(r"([A-Za-z]{1,3})(\d+)", str(reference.get("cell_or_range") or ""))
            if match is None or not reference.get("source_reference_id"):
                continue
            column = 0
            for letter in match.group(1).upper():
                column = column * 26 + ord(letter) - 64
            positions[str(reference["source_reference_id"])] = (reference.get("sheet_name"), int(match.group(2)),
                                                                column)
        return positions

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
        inline: bool = False,
        inline_gap: bool = False,
        inline_only: bool = False,
    ) -> Located | None:
        """First value for the highest-priority label group.

        With ``inline``, when no cell starts with a label, a label that follows other text
        in a cell ("Total kWh Used: 41,200 kWh Service Period: 05/01/2025 to 05/31/2025",
        which OCR returns as one line) is also read; see ``_find_inline``.

        ``accept`` validates a candidate value. ``accept_bare`` (stricter) allows
        "Label value" with no delimiter, e.g. "Account Number 1234-5678"; without it
        such text is treated as a phrase ("Customer charge"), not a label.
        """
        if inline_only:
            return self._find_inline(rows, groups, accept, stop_at_gap=inline_gap)
        for labels in groups:
            for row in rows:
                for position, cell in enumerate(row.cells):
                    prefix = self._label_prefix(cell.text, labels)
                    if prefix is None:
                        continue
                    if inline_gap and cell.raw_text:
                        # a text value ends at a column gap (2+ spaces as the parser gave the line)
                        prefix = self._label_prefix(self._cut_at_gap(cell.raw_text, prefix[0]), labels) or prefix
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
                        is_label = self._label_prefix(nxt.text, self.ALL_LABELS) is not None
                        far = cell.box is not None and nxt.box is not None and nxt.left - cell.right > 0.25
                        if not is_label and not far:
                            after = row.cells[position + 2] if position + 2 < len(row.cells) else None
                            lines = self._wrapped_value(rows, row, cell, after.left if after and after.box else 1.0)
                            lines = lines if nxt in lines else [nxt]
                            value = self._trim_value(" ".join(line.text for line in lines))
                            if value and (accept is None or accept(value)):
                                return Located(value, lines, row, CONF_NEXT_CELL, label_cell=cell,
                                               context=f"{cell.text} {value}")
                            if re.search(r"\d", nxt.text):
                                continue
                            # The neighbour is another column heading ("Invoice Date | PO Number" over a
                            # row of values): the value is below, under its own heading.
                    # 2b) a wrapped value centered on its label: no line of it is on the label's row
                    if cell.box is not None:
                        after = next((c for c in row.cells[position + 1:] if c.box is not None), None)
                        lines = self._wrapped_value(rows, row, cell, after.left if after else 1.0)
                        value = self._trim_value(" ".join(line.text for line in lines))
                        if value and (accept is None or accept(value)):
                            return Located(value, lines, row, CONF_NEXT_CELL, label_cell=cell,
                                           context=f"{cell.text} {value}")
                    # 3) label alone on its row: value directly below, left-aligned
                    if allow_next_row and cell.box is not None:
                        below = self._cell_below(rows, row, cell)
                        if below is not None:
                            value = self._trim_value(below[1].text)
                            if value and (accept is None or accept(value)):
                                return Located(value, [below[1]], below[0], CONF_NEXT_ROW, label_cell=cell,
                                               context=f"{cell.text} {below[1].text}")
        if inline:
            return self._find_inline(rows, groups, accept, stop_at_gap=inline_gap)
        return None

    @staticmethod
    def _cut_at_gap(raw: str, label: str) -> str:
        """``raw`` with its value cut at the first gap of 2+ spaces or a tab. Whitespace between
        the label and its value (or its colon) is not a gap: "Facility:  Main Plant  Meter 9"
        gives "Facility: Main Plant"."""

        head = re.match(r"\s*" + r"\s+".join(re.escape(word) for word in label.split()) + r"\s*", raw,
                        re.IGNORECASE)
        if head is None:
            return raw
        rest = raw[head.end():]
        delimiter = re.match(r"([:#=])?\s*", rest)
        assert delimiter is not None
        value = re.split(r" {2,}|\t+", rest[delimiter.end():])[0]
        return f"{raw[:head.end()].strip()}{delimiter.group(1) or ''} {value}".strip()

    # A short label ("from", "to", "period", "site") inside running text is a common word, so a
    # mid-cell label is only trusted with a colon, or (longer labels only) directly before dates.
    _INLINE_BARE_DATE_MIN_LABEL = 6

    def _find_inline(self, rows: Sequence[Row], groups: Sequence[Sequence[str]], accept: Any,
                     stop_at_gap: bool = False) -> Located | None:
        """A label that follows other text in a cell, e.g. the ``Service Period`` of
        "Total kWh Used: 41,200 kWh Service Period: 05/01/2025 to 05/31/2025".

        The label must start a word and be followed by a colon, or directly by a date when
        it is at least ``_INLINE_BARE_DATE_MIN_LABEL`` characters. The value runs to the
        next "label:" pair, if any. With ``stop_at_gap`` (text values: facility, address, account)
        it also stops at a run of 2+ spaces in the cell as the parser gave it, which separates columns.
        """

        next_label = re.compile(
            r"\s(?:" + "|".join(re.escape(label) for label in sorted(_ALL_LABELS, key=len, reverse=True))
            + r")\s*:", re.IGNORECASE)
        for labels in groups:
            pattern = re.compile(
                r"(?<![A-Za-z0-9])(?:" + "|".join(re.escape(label) for label in sorted(labels, key=len, reverse=True))
                + r")(?![A-Za-z0-9])", re.IGNORECASE)
            for row in rows:
                for cell in row.cells:
                    # column gaps (runs of spaces) become \x00 markers until the value is cut
                    text = (re.sub(r" {2,}|\t+", "\x00", (cell.raw_text or cell.text).strip()) if stop_at_gap
                            else " ".join(cell.text.split()))
                    for match in pattern.finditer(text):
                        if match.start() == 0:
                            continue  # a label at the start of the cell is the ordinary case
                        rest = text[match.end():].lstrip()
                        colon = rest.startswith(":")
                        if colon:
                            value = rest[1:]
                        elif len(match.group(0)) >= self._INLINE_BARE_DATE_MIN_LABEL and (
                                (hit := parse_date(rest)) is not None and hit[1] == 0):
                            value = rest
                        else:
                            continue
                        if colon and match.group(0).lower() in ("to", "from") and (parse_date(value.strip()) or ("", 1))[1] != 0:
                            continue  # "to:" / "from:" are ordinary words unless a date follows
                        stop = next_label.search(value.replace("\x00", " "))
                        value = value[:stop.start()] if stop else value
                        if stop_at_gap:
                            value = value.lstrip("\x00").split("\x00")[0]
                        value = self._trim_value(value.replace("\x00", " "))
                        if value and (accept is None or accept(value)):
                            return Located(value, [cell], row, CONF_SAME_CELL - 0.04, label_cell=cell,
                                           context=text.replace("\x00", " "))
        return None

    @staticmethod
    def _wrapped_value(rows: Sequence[Row], row: Row, label: Cell, column_end: float) -> list[Cell]:
        """The lines of one value in a label/value table, top to bottom: the cells right of
        ``label`` and left of ``column_end`` that together span the label's height.

        A value that wraps in a table cell sits vertically centered on its label
        ("Anheuser-Busch Baldwinsville" above "Customer", "Brewery" below it), so it
        straddles visual rows. A row with a cell under the label is the next field, and a
        line nearer another field's label belongs to that field.
        """

        if label.box is None:
            return []
        nearby = [r for r in rows if r.page == row.page and abs(r.top - row.top) <= 0.1]

        def in_label_column(c: Cell) -> bool:
            return c.box is not None and c.left < label.right and c.right > label.left - 0.01

        others = [c for r in nearby if r is not row for c in r.cells if in_label_column(c)]
        lines: list[Cell] = []
        for other in nearby:
            if other is not row and any(in_label_column(c) for c in other.cells):
                continue
            for c in other.cells:
                distance = abs(c.center_y - label.center_y)
                if (c.box is not None and c is not label and label.right <= c.left < column_end
                        and distance <= 1.5 * max(label.height, c.height)
                        and all(abs(c.center_y - o.center_y) >= distance for o in others)):
                    lines.append(c)
        if not lines:
            return []
        top = min(c.box["top"] for c in lines if c.box)
        bottom = max(c.box["top"] + c.box["height"] for c in lines if c.box)
        if not top <= label.center_y <= bottom:
            return []
        return sorted(lines, key=lambda c: c.center_y)

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
    def _service_block(self, rows: Sequence[Row]) -> tuple[Located | None, Located | None]:
        """(site name, address) from a "SERVICE FOR" block: the lines in the column under the heading.
        The first line is the customer, so a site name is only a line between it and the street."""

        for at, row in enumerate(rows):
            for head in row.cells:
                if not head.box or _norm(head.text) not in SERVICE_BLOCK_HEADINGS:
                    continue
                lines: list[tuple[Cell, Row]] = []
                for below in rows[at + 1: at + 1 + _BLOCK_LINES]:
                    cell = next((c for c in below.cells if c.box and below.page == row.page
                                 and abs(c.left - head.left) <= _BLOCK_COLUMN_TOLERANCE), None)
                    if cell is None:
                        break
                    lines.append((cell, below))
                    if _POSTAL_LINE_RE.search(cell.text) and any(_STREET_LINE_RE.match(c.text) for c, _ in lines):
                        break
                street = next((i for i, (c, _) in enumerate(lines) if _STREET_LINE_RE.match(c.text)), None)
                if street is None:
                    continue
                parts = [lines[street]]
                if street + 1 < len(lines) and _POSTAL_LINE_RE.search(lines[street + 1][0].text):
                    parts.append(lines[street + 1])
                address = Located(", ".join(c.text.strip(" ,") for c, _ in parts), [c for c, _ in parts],
                                  parts[0][1], CONF_DOCUMENT_SCAN)
                name = None
                if street >= 2 and not re.search(r"\d", lines[street - 1][0].text):
                    cell, name_row = lines[street - 1]
                    name = Located(cell.text.strip(), [cell], name_row, CONF_DOCUMENT_SCAN)
                return name, address
        return None, None

    def _facility(self, rows: Sequence[Row]) -> tuple[Located | None, Located | None]:
        """The place the fuel or gas was used, and its street address when the same block gives one.

        In order: a labelled facility or site; the name in a labelled service / delivery / ship-to
        block (its company line, which repeats the bill-to, and its "Attn" line are skipped); else
        the company on the bill (see ``BILL_TO_NAME_IS_LAST_RESORT_FACILITY``). A name that only repeats the
        bill-to, as a ship-to block's company line does, is never taken for the site.
        """

        bill_to = self._party_key(rows, BILL_TO_LABELS)
        located = self._find_labeled(rows, FACILITY_LABELS, accept=_has_letters, inline=True, inline_gap=True)
        if located is not None and _name_key(located.raw.split(",")[0]) != bill_to:
            return self._split_name_address(located)
        for label_cell, row, lines in self._label_blocks(rows, SITE_LOCATION_LABELS):
            name, address = self._site_in_block(lines, bill_to)
            if name is None:
                continue
            cell, text = name
            site = Located(text, [cell], row, CONF_NEXT_CELL, label_cell=label_cell, context=f"{label_cell.text} {text}")
            split, split_address = self._split_name_address(site)
            if split_address is None and address is not None:
                split_address = Located(address, [cell], row, CONF_NEXT_CELL - 0.05, label_cell=label_cell,
                                        context=f"{label_cell.text} {address}")
            return split, split_address
        block_name, block_address = self._service_block(rows)  # a two-column SERVICE FOR / MAILING ADDRESS block
        if block_name is not None or block_address is not None:
            return block_name, block_address
        if BILL_TO_NAME_IS_LAST_RESORT_FACILITY:
            billed = self._find_labeled(rows, BILL_TO_LABELS, accept=_has_letters, inline=True, inline_gap=True)
            if billed is not None:
                return self._split_name_address(billed)
        return None, None

    @staticmethod
    def _split_name_address(located: Located) -> tuple[Located, Located | None]:
        # "Site: Standby Generator Plant, 77 Weir Lane, Lodi, CA" -> name + address
        split = re.match(r"^(?P<name>[^,\d][^,]*?),\s*(?P<addr>\d+\s+\S.*)$", located.raw)
        if split:
            name = Located(split.group("name").strip(), located.cells, located.row, located.confidence,
                           located.label_cell, located.context)
            address = Located(split.group("addr").strip(), located.cells, located.row, located.confidence - 0.05,
                              located.label_cell, located.context)
            return name, address
        return located, None

    def _party_key(self, rows: Sequence[Row], groups: Sequence[Sequence[str]]) -> str:
        """The name a billing-party label gives, as a comparison key ("" when the document has none)."""

        for _, _, lines in self._label_blocks(rows, groups):
            for _, text in lines:
                if not _is_attention_line(text) and _has_letters(text):
                    return _name_key(text.split(",")[0])
        return ""

    def _label_blocks(self, rows: Sequence[Row], groups: Sequence[Sequence[str]]) -> list[tuple[Cell, Row, list[tuple[Cell, str]]]]:
        """Each label of ``groups`` with the text lines of the block that follows it: the value on the
        label's own line, then the lines beneath it (same column, tightly spaced) or, in plain text,
        the single-cell lines after it. A line that is itself a label ends the block."""

        found: list[tuple[Cell, Row, list[tuple[Cell, str]]]] = []
        for labels in groups:
            for row in rows:
                for cell in row.cells:
                    prefix = self._label_prefix(cell.text, labels)
                    if prefix is None:
                        continue
                    lines: list[tuple[Cell, str]] = []
                    if prefix[1]:
                        lines.append((cell, self._trim_value(prefix[1])))
                    lines.extend(self._lines_below(rows, row, cell))
                    found.append((cell, row, lines))
        return found

    def _lines_below(self, rows: Sequence[Row], row: Row, cell: Cell) -> list[tuple[Cell, str]]:
        out: list[tuple[Cell, str]] = []
        previous = cell
        for following in rows[row.index + 1:row.index + 12]:
            if following.page != row.page or len(out) >= 6:
                break
            if cell.box is not None:
                nxt = next((c for c in following.cells if c.box and abs(c.left - cell.left) < 0.02), None)
                if nxt is None or previous.box is None:
                    break
                gap = nxt.box["top"] - (previous.box["top"] + previous.box["height"])  # type: ignore[index]
                if gap > 1.5 * max(previous.height, nxt.height):
                    break
            else:
                nxt = following.cells[0] if len(following.cells) == 1 else None
                if nxt is None:
                    break
            if not nxt.text.strip() or self._label_prefix(nxt.text, self.ALL_LABELS) is not None:
                break
            out.append((nxt, self._trim_value(nxt.text)))
            previous = nxt
        return out

    @staticmethod
    def _site_in_block(lines: list[tuple[Cell, str]], bill_to: str) -> tuple[tuple[Cell, str] | None, str | None]:
        """The site name in a ship-to block, and its street address. The company line (the bill-to
        repeated), "Attn:" lines, PO boxes, street lines and "City, ST 12345" lines are not names."""

        name: tuple[Cell, str] | None = None
        street: str | None = None
        city: str | None = None
        for cell, text in lines:
            if not text or _is_attention_line(text) or _name_key(text.split(",")[0]) == bill_to:
                continue
            if re.match(r"^p\.?\s?o\.?\s*box\b", text, re.I):
                continue
            if _CITY_STATE_ZIP.match(text):
                city = city or text
                continue
            if text[:1].isdigit():
                street = street or text
                continue
            if name is None and _has_letters(text):
                name = (cell, text)
        address = ", ".join(part for part in (street, city) if part) if street else None
        return name, address

    def _address(self, rows: Sequence[Row]) -> Located | None:
        return self._find_labeled(rows, ADDRESS_LABELS, accept=lambda v: bool(re.search(r"\d", v)),
                                  accept_bare=lambda v: bool(re.match(r"\d+\s+\S", v)), inline=True,
                                  inline_gap=True) or self._service_block(rows)[1]

    def _account(self, rows: Sequence[Row]) -> Located | None:
        def accept(value: str) -> bool:
            # an identifier has a token with digits in it ("Your last 6 months" is a heading, not an account)
            return (any(len(t) >= 3 and re.search(r"\d", t) for t in value.split())
                    and parse_date(value) is None and not value.startswith("$"))

        def accept_bare(value: str) -> bool:  # first token must look like an identifier
            return accept(value) and bool(re.match(r"[A-Za-z0-9#-]*\d[\w-]*", value))

        return self._find_labeled(rows, ACCOUNT_LABELS, accept=accept, accept_bare=accept_bare, inline=True,
                                  inline_gap=True)

    def _supplier(self, rows: Sequence[Row]) -> Located | None:
        """The company that issued the bill. Never the customer: the name a Bill To, Sold To, Customer or Service For
        label gives is the other party, whether the name repeats it exactly, with a suffix or branch added
        ("Northgate Provisions Inc - Plant 4"), or is its parent. In order: a labelled supplier, an "Exported from"
        footer, the letterhead, then the organisation on a Remit To or Payable To line."""

        # A "Service For" block is the site's (``SERVICE_BLOCK_HEADINGS``), but the first line in it that is not a
        # site is still a customer, so its name is the other party too.
        customers = [name for name in (self._party_name(rows, BILL_TO_LABELS),
                                       self._party_name(rows, (SERVICE_BLOCK_HEADINGS[:1],))) if name]

        def other_party(found: Located | None) -> Located | None:
            return None if found is not None and _is_customer(found.raw.split(",")[0], customers) else found

        labeled = self._find_labeled(rows, SUPPLIER_LABELS, accept=self._looks_like_org_name, allow_next_row=False,
                                     inline=True)
        if labeled is not None and any(_same_company(labeled.raw.split(",")[0], name) for name in customers):
            labeled = None  # a labelled supplier is out only when it is the customer itself, never a "parent"
        if labeled is None and (exported := self._exported_from(rows)) is not None:
            return exported  # an explicit "Exported from <supplier>" beats a guess at the letterhead
        letterhead = other_party(self._letterhead(rows))
        if (letterhead is not None and letterhead.confidence < CONF_LETTERHEAD  # a guess at line one, not the largest text
                and not _names_a_utility(letterhead.raw) and self._is_addressee_block(rows, letterhead)):
            letterhead = None  # the block a statement is addressed with, and nothing in the name says utility
        if letterhead is not None and (labeled is None or labeled.row is None or labeled.row.index > 2):
            return letterhead
        if labeled is not None:
            labeled.raw = re.split(r"\s{2,}|\s+(?:GST|HST|VAT|Tax ID|EIN)\b", labeled.raw)[0].strip()
            return labeled
        return self._exported_from(rows) or other_party(self._remit_to(rows))

    def _party_name(self, rows: Sequence[Row], groups: Sequence[Sequence[str]]) -> str:
        """The name a billing-party label gives, as written ("" when the document has none)."""

        for _, _, lines in self._label_blocks(rows, groups):
            for _, text in lines:
                if not _is_attention_line(text) and _has_letters(text):
                    return text.split(",")[0].strip()
        return ""

    def _remit_to(self, rows: Sequence[Row]) -> Located | None:
        """The organisation a bill asks to be paid ("REMIT TO: SIERRA BASIN ENERGY CO, PO BOX 618"): the name
        before the first comma or dash, or after "on behalf of". It must end in an organisation word (Co, Inc,
        Energy, Gas, Utilities...) and must not be where or through whom to pay: a bank, lockbox, remittance or
        payment-processing centre, a department, an "in care of" or "attention" line, a billing or services
        company, a PO box or a street. Those name no supplier."""

        for label_cell, row, lines in self._label_blocks(rows, REMIT_LABELS):
            for cell, text in lines[:1]:
                behalf = re.search(r"\bon behalf of\s+(.+)$", text, re.IGNORECASE)
                name = re.split(r"\s{2,}|,|\s+[-\u2013\u2014|]\s+", behalf.group(1) if behalf else text)[0].strip()
                name = name.rstrip(".")
                words = re.sub(r"[^\w ]+", " ", name.casefold()).split()
                if (name and not name[0].isdigit() and self._looks_like_org_name(name)
                        and words and words[-1] in _ORGANISATION_WORDS
                        and not _NOT_A_PAYEE.search(name)):
                    return Located(name, [cell], row, CONF_LETTERHEAD - 0.1, label_cell=label_cell, context=text)
        return None

    @staticmethod
    def _is_addressee_block(rows: Sequence[Row], found: Located) -> bool:
        """Whether the line a name was found on opens an address block (a street or PO box line, then a city,
        state and ZIP line) that a statement header ("ACCOUNT NO", "STMT DATE", "INVOICE") follows: the block
        a statement is addressed with, whose first line is the customer."""

        if found.row is None:
            return False
        following = [r.cells[0].text.strip() for r in rows[found.row.index + 1:found.row.index + 5] if len(r.cells) == 1]
        if len(following) < 3:
            return False
        street, city, header = following[:3]
        return (bool(re.match(r"^(?:\d|p\.?\s?o\.?\s*box\b)", street, re.I))
                and bool(re.match(r"^[^\d]+?,?\s+[A-Za-z]{2}\s+\d{5}(?:-\d{4})?$", city))
                and bool(re.match(r"^(?:account|acct|stmt|statement|invoice|bill)\b", header, re.I)))

    @staticmethod
    def _exported_from(rows: Sequence[Row]) -> Located | None:
        """A portal export's footer names the supplier: "Exported from Mill Creek Natural Gas Co. Business Portal 07/08/2025"."""

        for row in rows:
            for cell in row.cells:
                match = _EXPORTED_FROM_RE.search(cell.text)
                if match:
                    return Located(match.group(1).strip(), [cell], row, CONF_LETTERHEAD - 0.05, context=cell.text)
        return None

    def _letterhead(self, rows: Sequence[Row]) -> Located | None:
        """The largest text near the top of page 1, when it reads like an organization.

        Without geometry (plain text), the first of the top lines naming a company.
        """

        first_page = [r for r in rows if (r.page or 1) == (rows[0].page or 1)][:6] if rows else []
        cells = [c for r in first_page for c in r.cells if c.box and c.box["top"] < 0.2]
        if not cells:
            for row in first_page[:4]:
                text = row.cells[0].text
                if len(row.cells) == 1 and re.search(r"(?<!\w)(company|co\.?|inc\.?|llc|ltd\.?|corp\.?|utilities)(?!\w)", text, re.I):
                    name = re.split(r"\s+[-\u2013\u2014|]\s+", text)[0].strip()
                    if self._looks_like_org_name(name):
                        return Located(name, [row.cells[0]], row, CONF_LETTERHEAD - 0.05, context=text)
            return None
        cell = max(cells, key=lambda c: (c.height, -c.order))
        if len(cells) < 2 or cell.height < 1.25 * min(c.height for c in cells):
            # No cell stands out by size (a lone line near the top, or all the same height, as
            # OCR often returns): fall back to the first line of the page, if it names an organization.
            return self._first_line_letterhead(first_page)
        text = cell.text
        prefix = self._label_prefix(text, SUPPLIER_LABELS[0])
        if prefix is not None and prefix[1]:
            text = prefix[1]
        if not self._looks_like_org_name(text):
            return None
        row = next(r for r in first_page if cell in r.cells)
        return Located(self._trim_value(text), [cell], row, CONF_LETTERHEAD)

    def _first_line_letterhead(self, first_page: Sequence[Row]) -> Located | None:
        """The first line of the page when it is alone on its row and its last word is an
        organization word (``LETTERHEAD_END_WORDS``: "City Water Department", "Pacific Electric");
        stricter than ``_looks_like_org_name``, since size is no evidence."""

        row = first_page[0] if first_page else None
        if row is None or len(row.cells) != 1:
            return None
        cell = row.cells[0]
        # "Shell Energy UK Limited, Elder House, 586-592 Elder Gate" -> the name before the address
        name = re.split(r"\s+[-\u2013\u2014|]\s+|,", cell.text)[0].strip()
        low = f" {_norm(name)}"
        titled = re.search(r"\b(?:" + "|".join(DOCUMENT_TITLE_WORDS) + r")\b", low)  # "Natural Gas Utility Bill"
        last = re.sub(r"[^\w-]", "", low.split()[-1]) if low.split() else ""  # "Ltd." -> "ltd"
        if ":" in name or titled or last not in LETTERHEAD_END_WORDS or not self._looks_like_org_name(name):
            return None
        return Located(self._trim_value(name), [cell], row, CONF_LETTERHEAD - 0.05, context=cell.text)

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
        labeled = self._find_labeled(rows, self.FUEL_LABEL_GROUPS, accept=lambda v: self._fuel(v) is not None,
                                     accept_bare=lambda v: self._fuel(v) is not None)
        if labeled is not None:
            return labeled
        for row in rows:
            for cell in row.cells:
                if self._fuel(cell.text) is not None:
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

        # every cell-start pass first, then the mid-cell ones in the same priority order
        for inline in (False, True):
            delivery = self._find_labeled(rows, DELIVERY_DATE_LABELS, accept=lambda v: parse_date(v) is not None,
                                          accept_bare=starts_with_date, inline=inline, inline_only=inline)
            if delivery is not None:
                return delivery, delivery
            ranged = self._find_labeled(rows, RANGE_PERIOD_LABELS, accept=lambda v: len(parse_dates(v)) >= 2,
                                        accept_bare=starts_with_range, inline=inline, inline_only=inline)
            if ranged is not None:
                return ranged, ranged
            start = self._find_labeled(rows, START_LABELS, accept=lambda v: parse_date(v) is not None,
                                       accept_bare=starts_with_date, inline=inline, inline_only=inline)
            end = self._find_labeled(rows, END_LABELS, accept=lambda v: parse_date(v) is not None,
                                     accept_bare=starts_with_date, inline=inline, inline_only=inline)
            if start is not None or end is not None:
                # "Service from January 1, 2025 through January 31, 2025": one value holds both dates
                if end is None and start is not None and len(parse_dates(start.raw)) >= 2:
                    return start, start
                if start is None and end is not None and len(parse_dates(end.raw)) >= 2:
                    return end, end
                return start, end
        alone = self._standalone_range(rows)
        return (alone, alone) if alone is not None else (None, None)

    @staticmethod
    def _standalone_range(rows: Sequence[Row]) -> Located | None:
        """A period with no label, as a consumer-style bill prints it ("October 1 - 31, 2025"): a cell that
        is exactly a date, a dash (or "to", "through") and a date, 20 to 100 days long, and not labelled as a
        due, statement or next-read date. Only when the document has exactly one such range (a bill that
        also prints last year's, or a chart's, is ambiguous)."""

        found: list[tuple[Row, Cell]] = []
        for row in rows:
            for cell in row.cells:
                text = cell.text.strip().rstrip(".")
                if _only_a_date_range(text) and not _labelled_as(rows, cell, _NOT_A_SERVICE_PERIOD):
                    found.append((row, cell))
        if len(found) != 1:
            return None
        row, cell = found[0]
        return Located(cell.text.strip(), [cell], row, CONF_LETTERHEAD, context=cell.text)

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
        # "Read on January 1, 2025" is a label that names a date, not a value: blank dates first.
        undated = [_blank_dates(t) for t in texts]
        if any(re.search(r"\d{3}|\d,\d|\d\.\d|\d/\d", t) for t in undated):
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
            extra = next(
                (key for key, names in self.EXTRA_COLUMNS.items()
                 if key not in columns and any(text == n or bare == n or text.startswith(n + " ") for n in names)),
                None,
            )
            if extra is not None:
                columns[extra] = index
            elif "unit" not in columns and bare in self.UNIT_HEADERS:
                columns["unit"] = index
            elif "id" not in columns and any(bare == h or bare.startswith(h + " ") for h in self.ID_HEADERS):
                columns["id"] = index
            elif "product" not in columns and bare in self.PRODUCT_HEADERS:
                columns["product"] = index
            elif "range" not in columns and bare in _RANGE_HEADERS:
                columns["range"] = index
            elif "start" not in columns and bare in _START_HEADERS:
                columns["start"] = index
            elif "end" not in columns and bare in _END_HEADERS:
                columns["end"] = index
            elif "date" not in columns and bare in self.DATE_HEADERS:
                columns["date"] = index
        return columns

    # Unit lookups, so a subclass can know units the others must not (the thermal
    # extractor's kBtu, ton-hours and Mlb of steam).
    def _find_unit(self, text: str | None) -> str | None:
        return fuel_units.find_unit(text)

    def _canonical_unit(self, text: str | None) -> str | None:
        return fuel_units.canonical_unit(text)

    def _quantity_header_score(self, text: str) -> int:
        bare = text.strip(" :#")
        if any(word in text for word in self.QTY_EXCLUDE) or bare in self.UNIT_HEADERS or bare.endswith(" unit"):
            return 0
        unit = self._canonical_unit(text) or self._find_unit(text)
        score = 0
        if any(w in text for w in ("usage", "consumption", "consumed", "delivered", "billed", "used", "issued")):
            score += 4
        if any(w in text for w in ("qty", "quantity")):
            score += 3
        if "volume" in text:
            score += 1
        if unit is not None:
            score += 2 + (1 if fuel_units.dimension_of(unit) == fuel_units.ENERGY else 0)
            if self._canonical_unit(text) is not None:
                score += 1  # the whole header is a unit, e.g. "Dth", "Gallons"
        if "difference" in text:
            score = min(score, 1)
        return score

    def _table_records(self, rows: Sequence[Row], header_row: Row, columns: dict[str, int]) -> list[UsageRecord]:
        header_cells = header_row.cells
        header_text = header_cells[columns["quantity"]].text
        paren = re.search(r"\(([^()]{1,20})\)", header_text)
        # "Volume (L)": a unit in parentheses may be a single letter
        header_unit_text = paren.group(1) if paren and self._canonical_unit(paren.group(1)) else header_text
        header_unit = self._canonical_unit(header_unit_text) or self._find_unit(header_text)
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
                if self._canonical_unit(unit_cell.text) is None:
                    continue  # e.g. "EA" for a tank rental line: not a fuel quantity
                unit_raw = unit_cell.text
                unit_located = Located(unit_cell.text, [unit_cell], row, CONF_TABLE)
            elif self._find_unit(qty_cell.text):
                unit_raw = qty_cell.text
            elif header_unit is not None:
                unit_raw = header_unit_text
                unit_located = Located(header_cells[columns["quantity"]].text, [header_cells[columns["quantity"]]],
                                       header_row, CONF_TABLE)
            product_cell = assigned.get(columns["product"]) if "product" in columns else None
            fuel = None
            if product_cell is not None:
                if self._fuel(product_cell.text) is None:
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
            for key in self.EXTRA_COLUMNS:
                cell = assigned.get(columns[key]) if key in columns else None
                if cell is not None and cell.text.strip():
                    record.extra[key] = Located(cell.text, [cell], row, CONF_TABLE,
                                                context=self._row_context(header_row, row))
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
        if all(c.column for c in row.cells) and all(h.column for h in header_cells):
            by_column = {h.column: index for index, h in enumerate(header_cells)}
            return {by_column[c.column]: c for c in row.cells if c.column in by_column}
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

    def _quantity_records(self, rows: Sequence[Row]) -> list[UsageRecord]:
        """Usage table rows, else a labeled quantity (subclasses add more layouts)."""

        return self._usage_table_records(rows) or self._labeled_quantity_records(rows)

    # "TOTAL 1,273.1 THERMS" in the middle of a line: TOTAL directly before the number, the unit directly after
    # it. "TOTAL AMOUNT DUE $1,474.33" and "TOTAL CHARGES 1,474.33" have a word where the number should be, a
    # "$" or no unit; "PREV 40,211 CURR 41,447" has no TOTAL.
    _INLINE_TOTAL = re.compile(
        r"(?<![\w$])total\s+(?P<num>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)\s+(?P<unit>[^\W\d_]+)(?=\s|$)",
        re.IGNORECASE)
    # A line that is about a period other than the bill's own ("YEAR TO DATE TOTAL 14,200 THERMS", "SAME MONTH
    # LAST YEAR TOTAL 1,190 THERMS", "AVG DAILY TOTAL 41"), a year, or a month name is not the bill's usage.
    _NOT_THIS_PERIOD = re.compile(
        r"\b(?:ytd|years?|annual|months?|last|prior|previous|avg|average|daily|day|budget|estimated|est|history)\b"
        r"|\bto date\b|\b(?:19|20)\d{2}\b", re.IGNORECASE)

    _LIQUID_FUELS = frozenset({"propane", "diesel", "fuel_oil", "kerosene", "biodiesel"})  # where gallons are an activity unit
    # Words in the row above that make the row a column of another period ("Year to date", "Aug 2024"); a bare
    # year does not count there, because the line above a total is often the bill's own period.
    _NOT_THIS_PERIOD_ABOVE = re.compile(
        r"\b(?:ytd|years?|annual|months?|last|prior|previous|avg|average|daily|budget|estimated|est|history)\b|\bto date\b",
        re.IGNORECASE)

    def _period_header_above(self, rows: Sequence[Row], position: int, cell: Cell) -> bool:
        """Whether one of the three rows above holds, in the column of ``cell``, a period word or a month name
        ("YEAR TO DATE" over a units line over "TOTAL 14,200 THERMS"). Cells with no geometry count as the same
        column. A bare year does not count here: the line above a total is often the bill's own period."""

        for above in rows[max(0, position - 3):position]:
            if above.page != rows[position].page:
                continue
            for other in above.cells:
                if other.box is not None and cell.box is not None and not (other.left < cell.right and other.right > cell.left):
                    continue
                if self._NOT_THIS_PERIOD_ABOVE.search(other.text) or _names_a_month(other.text):
                    return True
        return False

    def _inline_total_records(self, rows: Sequence[Row], doc_fuel: Located | None = None) -> list[UsageRecord]:
        """A dense statement that states its usage inside a line: "THERM FACTOR 1.030 TOTAL 1,273.1 THERMS".
        It runs last: the labelled reads, the usage table and the headline read are tried first. Money is never
        taken (a "$", or a TOTAL that is followed by a word), nor a line about another period (year to date,
        last year, a daily average, a budget plan, an estimate, a month or a year). When the document says it
        more than once with different numbers or units, nothing is guessed."""

        fuel = (self._fuel(doc_fuel.raw) or (None,))[0] if doc_fuel is not None else None
        found: dict[tuple[float, str], tuple[Row, Cell, re.Match[str]]] = {}
        for position, row in enumerate(rows):
            # The whole row (a PDF reader puts "Year to date" and "TOTAL 14,200 THERMS" in separate cells of one
            # row) and the row directly above (column headers) say which period the total is for.
            line = " ".join(cell.text for cell in row.cells)
            if self._NOT_THIS_PERIOD.search(line) or _names_a_month(line):
                continue
            for cell in row.cells:
                if not self._INLINE_TOTAL.search(cell.text) or self._period_header_above(rows, position, cell):
                    continue
                for match in self._INLINE_TOTAL.finditer(cell.text):
                    unit = match.group("unit")
                    canonical = self._canonical_unit(unit)
                    if canonical is None or canonical in ELECTRIC_UNITS or fuel_units.is_ambiguous_in_text(unit):
                        continue
                    if fuel_units.dimension_of(canonical) == fuel_units.LIQUID_VOLUME and fuel not in self._LIQUID_FUELS:
                        continue  # "TOTAL 500 GALLONS" on a natural gas bill is not its usage
                    number = parse_number(match.group("num"))
                    if number is None or ("," not in match.group("num") and "." not in match.group("num")
                                          and 1990 <= number[0] <= 2100):
                        continue  # a bare year is not a quantity
                    found.setdefault((number[0], canonical), (row, cell, match))  # THERMS and THM are one unit
        if len(found) != 1:
            return []
        row, cell, match = next(iter(found.values()))
        quantity = Located(match.group("num"), [cell], row, CONF_NEXT_CELL - 0.1, context=cell.text)
        return [UsageRecord(quantity=quantity, unit_raw=match.group("unit"),
                            unit_located=Located(match.group("unit"), [cell], row, CONF_NEXT_CELL - 0.1), hint=None)]

    _BARE_NUMBER = re.compile(r"^\d{1,3}(?:,\d{3})+(?:\.\d+)?$|^\d+(?:\.\d+)?$")
    _USAGE_WORDS = frozenset({"used", "billed", "consumed", "delivered", "usage"})
    # Words in the text above or beside a number that say it is not the quantity of the bill.
    _NOT_A_QUANTITY = ("reading", "capacity", "days", "year", "rate", "average", "avg", "daily", "per day", "last",
                       "previous", "prior")
    # Words in the line right under the unit line that say the pair is not the bill's quantity ("therms" over
    # "per day", "gallons" over "tank capacity", "CCF" over "current meter reading").
    _NOT_UNDER_A_UNIT = ("per", "daily", "average", "avg", "tank", "capacity", "meter", "reading", "last", "previous",
                         "prior")

    def _headline_quantity_records(self, rows: Sequence[Row]) -> list[UsageRecord]:
        """A bill that leads with the quantity: "1,486" in large type with "therms used" directly below it.

        Only a laid-out page counts (a line of plain text carries no sign of size), and only when:
        - the number stands alone (no "$", no ID) and is at least twice as tall as the unit line under
          it, and among the three tallest sizes of text on its page (sizes within 10% of each other are
          one size, so OCR jitter does not push it out);
        - the unit line has no digit, starts with a unit that is not one of the short aliases that are
          ambiguous in free text (St, T, L, CF, Ton), and goes on with nothing or a usage word
          ("therms used"; not "therms per day", "gallons capacity", "kWh actual" or "St. Louis, MO"), and
          the line under the unit line is not a qualifier ("per day", "tank capacity", "current meter
          reading") or a date ("October 2024"; the bill's own period, a lone date range, is fine);
        - the text just above or beside the number is not a label that excludes it (a reading, a
          capacity, days, a year, a rate, an amount).
        When the document has two such pairs, nothing is guessed."""

        sizes: dict[int | None, list[float]] = {}
        for row in rows:
            for cell in row.cells:
                if cell.box is not None:
                    sizes.setdefault(row.page, []).append(cell.height)
        smallest_large = {page: _third_band_floor(heights) for page, heights in sizes.items()}
        pairs: list[tuple[Row, Cell, Row, Cell]] = []
        for position, row in enumerate(rows):
            floor = smallest_large.get(row.page)
            for cell in row.cells:
                if cell.box is None or not self._BARE_NUMBER.match(cell.text.strip()):
                    continue
                if floor is None or cell.height < floor - 1e-9:
                    continue
                below = self._unit_line_below(rows, position, cell)
                if below is not None and not _labelled_as(rows, cell, (*self.QTY_EXCLUDE, *self._NOT_A_QUANTITY)):
                    pairs.append((row, cell, *below))
        if len(pairs) != 1:
            return []
        row, number, unit_row, unit_cell = pairs[0]
        parsed = parse_number(number.text)
        if parsed is None:
            return []
        unit_word = unit_cell.text.split()[0]
        quantity = Located(parsed[1], [number], row, CONF_DOCUMENT_SCAN, context=f"{number.text} {unit_cell.text}")
        return [UsageRecord(quantity=quantity, unit_raw=unit_word,
                            unit_located=Located(unit_cell.text, [unit_cell], unit_row, CONF_NEXT_CELL), hint=None)]

    def _unit_line_below(self, rows: Sequence[Row], position: int, number: Cell) -> tuple[Row, Cell] | None:
        def is_unit_line(cell: Cell) -> bool:
            words = [word.strip(".,:;") for word in cell.text.split()]
            if not words or re.search(r"\d", cell.text) or number.height < 2 * cell.height:
                return False
            first = words[0].lower()
            return (self._canonical_unit(words[0]) is not None and not fuel_units.is_ambiguous_in_text(first)
                    and all(word.lower() in self._USAGE_WORDS for word in words[1:]) and len(words) <= 2)

        if number.box is None:
            return None
        bottom = number.box["top"] + number.box["height"]
        best: tuple[float, Row, Cell] | None = None
        for other in rows[position + 1:position + 40]:
            if other.page != rows[position].page:
                break
            for cell in other.cells:
                if cell.box is None or abs(cell.left - number.left) > 0.02:
                    continue
                gap = cell.box["top"] - bottom
                if -0.005 <= gap <= max(0.5 * number.height, 0.02) and (best is None or gap < best[0]):
                    best = (gap, other, cell)
        if best is not None and is_unit_line(best[2]) and not self._qualified_below(rows, position, best[2]):
            return best[1], best[2]
        return None

    def _qualified_below(self, rows: Sequence[Row], position: int, unit: Cell) -> bool:
        """Whether the line directly under the unit line (same column, within about a line) says the pair is not
        the bill's quantity: a qualifier word, or a date, a month and year or a year (last year's figure). A
        date range that is exactly what ``_standalone_range`` accepts is the bill's period and does not count."""

        if unit.box is None:
            return False
        bottom = unit.box["top"] + unit.box["height"]
        for other in rows[position + 1:position + 40]:
            for cell in other.cells:
                if cell is unit or cell.box is None or abs(cell.left - unit.left) > 0.02:
                    continue
                gap = cell.box["top"] - bottom
                if not -0.005 <= gap <= 1.2 * unit.height:
                    continue
                text = cell.text.strip().rstrip(".")
                if _only_a_date_range(text):
                    return False
                return (any(_has_word(text, word) for word in self._NOT_UNDER_A_UNIT)
                        or parse_date(text) is not None or _names_a_month(text)
                        or re.search(r"\b(?:19|20)\d{2}\b", text) is not None)
        return False

    def _labeled_quantity_records(self, rows: Sequence[Row],
                                  label_groups: tuple[tuple[str, ...], ...] | None = None) -> list[UsageRecord]:
        def accept(value: str) -> bool:
            return parse_number(value) is not None and not value.strip().startswith("$")

        located = self._find_labeled(rows, label_groups or self.QUANTITY_LABEL_GROUPS, accept=accept,
                                     accept_bare=lambda v: bool(re.match(r"\(?-?\d", v)))
        if located is None:
            return []
        number = parse_number(located.raw)
        assert number is not None
        unit_raw = located.raw if self._find_unit(located.raw) else None
        if unit_raw is None:
            # "182.40 L": a whole-word unit right after the number (single letters included)
            after = located.raw.split(number[1], 1)[-1].strip().split()
            if after and self._canonical_unit(after[0]) is not None:
                unit_raw = after[0]
        if unit_raw is None and located.label_cell is not None:
            # "Total Usage (Therms): 1,234" - the unit is in the label
            label_paren = re.search(r"\(([^()]{1,30})\)", located.label_cell.text)
            if label_paren and self._find_unit(label_paren.group(1)):
                unit_raw = label_paren.group(1)
            elif self._find_unit(located.label_cell.text.split(":")[0]):
                unit_raw = located.label_cell.text.split(":")[0]  # "Gallons Delivered: 742.6"
        unit_located = None
        if unit_raw is None and located.row is not None:
            for cell in located.row.cells:
                if cell not in located.cells and self._canonical_unit(cell.text):
                    unit_raw, unit_located = cell.text, Located(cell.text, [cell], located.row, CONF_NEXT_CELL)
                    break
        quantity = Located(number[1], located.cells, located.row, located.confidence, located.label_cell,
                           context=located.row.text if located.row else located.raw)
        return [UsageRecord(quantity=quantity, unit_raw=unit_raw, unit_located=unit_located, hint=None)]

    def _document_unit(self, rows: Sequence[Row]) -> Located | None:
        located = self._find_labeled(rows, (("usage unit", "unit of measure", "unit", "units", "uom"),),
                                     accept=lambda v: self._canonical_unit(v) is not None)
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
        detected = self._fuel(fuel_loc.raw)
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
            raw_unit = self._find_unit(unit_text) or unit_text
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
        if cell is not None and cell.part is not None and cell.box is None:
            row = re.fullmatch(r"row (\d+)", str(reference.get("cell_or_range") or ""))
            if str(cell.block_id or "").startswith(_CSV_BLOCK_PREFIX) and row:
                reference["cell_or_range"] = f"{_column_letters(cell.part)}{row.group(1)}"  # "row 2", part 5 -> "E2"
            elif reference.get("cell_or_range") is None:
                reference["cell_or_range"] = f"part {cell.part}"
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
    FACILITY_LABELS + SITE_LOCATION_LABELS + BILL_TO_LABELS + ADDRESS_LABELS + ACCOUNT_LABELS + SUPPLIER_LABELS + FUEL_LABELS + RANGE_PERIOD_LABELS
    + START_LABELS + END_LABELS + DELIVERY_DATE_LABELS + QUANTITY_LABELS
)
_ALL_LABELS: tuple[str, ...] = tuple(label for group in ALL_LABEL_GROUPS for label in group)
StationaryCombustionExtractor.ALL_LABELS = _ALL_LABELS
