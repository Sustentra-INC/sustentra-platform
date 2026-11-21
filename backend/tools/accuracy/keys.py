"""Answer-key loading and field-label parsing.

The three keys name fields differently and put the record a value belongs to inside the label:

    ``supplier``                              a document-level value
    ``[Apr 2031] service period start``       a statement inside a bundle
    ``[row 2 03/05/2031] fuel added``         a row of a log
    ``[VEH-9 Jan-31] distance``              a vehicle and a month
    ``on_peak_kwh [MTR-70]``              a meter
    ``January activity_quantity``             a month, NPL style
    ``run 03/05/2031 run_hours``              a date, NPL style
    ``activity quantity (total electricity)`` a qualifier in brackets

``parse_label`` splits a label into a ``Selector`` (which record), a base name and a qualifier; the
mapping table (``mapping.py``) then decides which field family the base name belongs to.
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from backend.tools.accuracy.normalize import MONTHS, _MONTH_NAMES, norm_id, parse_date


@dataclass(frozen=True)
class Selector:
    """Which record of a multi-record document a key cell is about (all parts optional)."""

    dates: tuple[date, ...] = ()
    month: int | None = None
    year: int | None = None
    ids: tuple[str, ...] = ()  # normalised with ``norm_id``
    row: int | None = None  # the record's ordinal (1-based), from the key's page_or_row column

    @property
    def empty(self) -> bool:
        return not (self.dates or self.month or self.ids or self.row)


@dataclass(frozen=True)
class KeyCell:
    set_name: str
    filename: str
    facility: str
    document_type: str
    category: str
    label: str  # the key's field name, as written
    expected: str
    unit: str
    location: str  # page_or_row / page
    extra: dict[str, str] = field(default_factory=dict, hash=False, compare=False)  # NPL: in_reporting_year, trap


@dataclass(frozen=True)
class ParsedLabel:
    selector: Selector
    base: str  # lower-case, words separated by single spaces, selector and qualifier removed
    qualifier: str  # the text of the last "(...)" group, lower-case, or ""


_BRACKET = re.compile(r"\[([^\]]*)\]")
_PAREN = re.compile(r"\(([^)]*)\)")
_ID = re.compile(r"\b([A-Za-z]{1,6}(?:-[A-Za-z0-9]+)+)\b")


def find_ids(text: str) -> list[str]:
    """Dash-joined ids with at least one digit ("VEH-9", "ABC-DE-01"); month-year ("Jan-31") is not an id."""

    return [i for i in _ID.findall(text) if any(c.isdigit() for c in i) and not _MON_YY.fullmatch(i)]


_MON_YY = re.compile(rf"\b({_MONTH_NAMES})\.?[- ](\d{{4}}|\d{{2}})\b", re.I)
_MON_ONLY = re.compile(rf"\b({_MONTH_NAMES})\b", re.I)
_SLASH_DATE = re.compile(r"\b\d{1,2}/\d{1,2}/\d{2,4}\b")
_ORDINAL = re.compile(r"\b(row|line|txn|transaction|entry)\s+\d+\b", re.I)
_DATE_WORD = re.compile(r"\b(?:run|service|txn|transaction|entry|row|line)\s+(?:\d+\s+)?(?=\d{1,2}/\d{1,2}/\d{2,4})", re.I)
_YEAR_MONTH = re.compile(r"\b(20\d{2})-(0[1-9]|1[0-2])\b")


def read_key(path: Path, set_name: str) -> list[KeyCell]:
    """The key's rows. Accepts the STG, NPL and LHF layouts (extra columns are kept in ``extra``)."""

    cells: list[KeyCell] = []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            known = {"filename", "facility", "document_type", "category", "field", "expected_value", "unit",
                     "page_or_row", "page"}
            cells.append(KeyCell(
                set_name=set_name,
                filename=(row.get("filename") or "").strip(),
                facility=(row.get("facility") or "").strip(),
                document_type=(row.get("document_type") or "").strip(),
                category=(row.get("category") or "").strip(),
                label=(row.get("field") or "").strip(),
                expected=(row.get("expected_value") or "").strip(),
                unit=(row.get("unit") or "").strip(),
                location=(row.get("page_or_row") or row.get("page") or "").strip(),
                extra={k: (v or "").strip() for k, v in row.items() if k and k not in known},
            ))
    return [c for c in cells if c.filename]


_ROW = re.compile(r"\b(?:row|line)\s+(\d+)\b", re.I)
_TABULAR = (".csv", ".xls", ".xlsx")


def record_ordinal(location: str, filename: str) -> int | None:
    """The 1-based record a ``page_or_row`` such as "row 3" or "line 2" names.

    In a spreadsheet or CSV the header is row 1, so "row 2" is the first record; in a PDF table
    ("p1 row 2") the rows are counted from the first record. A plural ("rows 2-4") names no record."""

    m = _ROW.search(location)
    if not m:
        return None
    n = int(m.group(1))
    return n - 1 if filename.lower().endswith(_TABULAR) else n


def parse_label(label: str) -> ParsedLabel:
    """Split a key field name into selector, base name and qualifier."""

    text = label.strip()
    brackets = _BRACKET.findall(text)
    text = _BRACKET.sub(" ", text)
    parens = _PAREN.findall(text)
    text = _PAREN.sub(" ", text)
    # Qualifiers that name a record (a vehicle and a date) rather than a measure: NPL/LHF "gallons (VEH-9 ...)".
    record_parens = [p for p in parens if find_ids(p) or _SLASH_DATE.search(p)]
    measure_parens = [p for p in parens if p not in record_parens]
    selector_text = " ".join([*brackets, *record_parens, text])

    dates = tuple(d for d in (parse_date(m) for m in _SLASH_DATE.findall(selector_text)) if d)
    month: int | None = None
    year: int | None = None
    m = _MON_YY.search(selector_text)
    ym = _YEAR_MONTH.search(selector_text)
    if ym:
        year, month = int(ym.group(1)), int(ym.group(2))
    elif m:
        month = MONTHS[m.group(1).lower()]
        y = int(m.group(2))
        year = y + 2000 if y < 100 else y
    else:
        m = _MON_ONLY.search(" ".join([*brackets, text]))
        if m:
            month = MONTHS[m.group(1).lower()]
    ids = tuple(dict.fromkeys(norm_id(i) for i in find_ids(selector_text)))

    base = text
    base = _DATE_WORD.sub(" ", base)
    for remove in (_SLASH_DATE, _MON_YY, _YEAR_MONTH, _ORDINAL):
        base = remove.sub(" ", base)
    if month is not None:
        base = re.sub(rf"\b{_MONTH_NAMES}\b", " ", base, flags=re.I)
    for i in find_ids(text):
        base = base.replace(i, " ")
    base = re.sub(r"[_\s]+", " ", base).strip().lower()
    return ParsedLabel(Selector(dates, month, year, ids), base, (measure_parens[-1].strip().lower() if measure_parens else ""))
