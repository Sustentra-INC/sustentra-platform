"""The emissions a company reports in its own summary document (Block 1), read as values to review.

A published GHG statement, a management assertion or the inventory workbook prints the company's
reported emissions: Scope 1, Scope 2 (location- and market-based) and Scope 3 totals, often as a table of
scope rows by gas columns ("Scope 1 | CO2 | CH4 | N2O | HFC | Total CO2e"). They are the company's CLAIMS, not
source evidence: once a reviewer accepts them they feed only the "Reported" side of Verification results
(``document_reported``), never a recalculated number, and never the evidence that counts.

Reading is rules first (``ReportedTotalsExtractor``):

* PDF text blocks carry their boxes, so a table is rebuilt from geometry: numeric cells are put in rows, the row
  label (a two-line "Scope 2" + "(location-based)" is joined) is the text left of them, the column header is the
  text above the same column. A cell is read only when its row label names a scope exactly and its column header
  names a gas or "Total"; a row with a bare "Scope 2" (no basis) is left alone.
* Workbook and Textract tables are read the same way from their rows.
* A figure is never added up, worked out or taken from a sentence by the rules. What the rules leave empty is
  offered to Sustentra's AI (``ai_extraction``), which must quote the line that states it.
* "N/A" and dashes are "not reported" (kept as printed, never 0). A unit is read only when it is printed
  (the table's header or caption) and is exactly one known unit; otherwise the value is kept with no unit and
  is never converted.

Units: ``parse_unit`` knows tCO2e, MTCO2e (metric tons), ktCO2e, MtCO2e / MMTCO2e (million tonnes), kgCO2e and
the plain mass units for a single gas. ``to_tonnes`` normalises to tonnes; the printed unit stays on the value.
"""

from __future__ import annotations

import math
import re
import unicodedata
from collections import defaultdict
from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from backend.app.services import emissions_rollup as rollup
from backend.app.services.extraction_candidate_service import ExtractionCandidateService
from backend.app.services.reviewed_evidence import AI_SUGGESTED
from backend.app.services.stationary_combustion_extractor import ExtractionOutcome

WORKBOOK_TYPE_ID = "CT-GHG-WORKBOOK"
METHODDOC_TYPE_ID = "CT-S1-METHODDOC"
REPORTED_TYPES = frozenset({WORKBOOK_TYPE_ID, METHODDOC_TYPE_ID})
REVIEWED = ("accepted", "edited")
YEAR_FLAG = "year:"  # validation flag of a figure: the one year its table names

GASES = ("co2", "ch4", "n2o", "hfcs", "pfcs", "sf6", "nf3")
# (row prefix, key of the row's total). Scope 3 is reported only: no recalculation compares it.
SCOPE_ROWS: dict[str, tuple[str, str]] = {
    "s1": ("scope1", "scope1_total"),
    "s2_location": ("scope2", "scope2_location_total"),
    "s2_market": ("scope2_market", "scope2_market_total"),
    "s3": ("scope3", "scope3_total"),
}
REPORTED_ONLY_PREFIX = "scope3"


def is_reported_only(field_id: str) -> bool:
    """Reported, never compared: Scope 3 is not recalculated."""

    return field_id.startswith(REPORTED_ONLY_PREFIX)


# =========================================================================================
# Units
# =========================================================================================
@dataclass(frozen=True)
class Unit:
    label: str  # the unit as a value carries it: "tCO2e", "MtCO2e", "t"
    factor: float  # to tonnes
    co2e: bool  # tonnes of CO2e, as against tonnes of one gas


UNITS: dict[str, Unit] = {u.label: u for u in (
    Unit("tCO2e", 1.0, True), Unit("ktCO2e", 1e3, True), Unit("MtCO2e", 1e6, True), Unit("kgCO2e", 1e-3, True),
    Unit("t", 1.0, False), Unit("kt", 1e3, False), Unit("Mt", 1e6, False))}
CO2E_UNITS = ["tCO2e", "ktCO2e", "MtCO2e", "kgCO2e"]
MASS_UNITS = ["t", "kt", "Mt"]

_E = r"(?:co2\s?-?\s?e(?:q(?:uivalents?)?)?|carbon\s+dioxide\s+equivalents?)"
# Case matters for "Mt" (million tonnes) against "MT" (metric tons): a lowercase "mt" is not read at all.
_RULES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"(?<![A-Za-z])(?:Mt|MMT)\s?CO2\s?-?\s?e(?:q)?(?![A-Za-z])"), "MtCO2e"),
    (re.compile(rf"(?i:(?<![a-z])million\s+(?:metric\s+)?(?:tons?|tonnes?)\s+(?:of\s+)?{_E})"), "MtCO2e"),
    (re.compile(r"(?<![A-Za-z])kt\s?CO2\s?-?\s?e(?:q)?(?![A-Za-z])"), "ktCO2e"),
    (re.compile(rf"(?i:(?<![a-z])(?:thousand|kilo)\s*(?:metric\s+)?(?:tons?|tonnes?)\s+(?:of\s+)?{_E})"), "ktCO2e"),
    (re.compile(rf"(?i:(?<![a-z])kg\s?{_E})"), "kgCO2e"),
    (re.compile(rf"(?:(?i:(?<![a-z])(?:t|tonnes?|metric\s+tons?|metric\s+tonnes?)\s?(?:of\s+)?)|(?<![A-Za-z])(?:MT|mT)\s?(?:of\s+)?)"
                rf"(?i:{_E})(?![a-z])"), "tCO2e"),
)
_MASS_FULL: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"Mt|million\s+(?:metric\s+)?(?:tons?|tonnes?)", re.I), "Mt"),
    (re.compile(r"kt|(?:thousand|kilo)\s*(?:metric\s+)?(?:tons?|tonnes?)", re.I), "kt"),
    (re.compile(r"t|tonnes?|metric\s+tons?|metric\s+tonnes?", re.I), "t"),
)


def _text(value: Any) -> str:
    return " ".join(unicodedata.normalize("NFKC", str(value or "")).replace(" ", " ").split())


def _scan_units(text: str) -> tuple[set[str], str]:
    """The CO2e units printed in ``text`` and what is left of it once they are taken out. A longer unit
    ("million metric tons CO2e") hides the shorter one inside it ("metric tons CO2e")."""

    clean = _text(text)
    found: set[str] = set()
    for pattern, label in _RULES:
        if pattern.search(clean):
            found.add(label)
            clean = pattern.sub(" \x00 ", clean)  # where a unit was: a scale word is read beside it
    return found, clean


def find_units(text: str) -> set[str]:
    """Every CO2e unit printed inside ``text`` (a header or caption: "Emissions MTCO2e")."""

    return _scan_units(text)[0]


# A scale printed beside a unit: "thousand tCO2e", "tCO2e (in thousands)", "'000 tCO2e", "m tCO2e", "MM tCO2e".
_SCALES: tuple[tuple[re.Pattern[str], float], ...] = (
    (re.compile(r"(?i:\b(?:in\s+)?thousands?\b)|['\u2019]000s?|\(\s*000s?\s*\)|\b000s\b"
                r"|(?<![A-Za-z])k\s+(?=\x00)"), 1e3),
    (re.compile(r"(?i:\b(?:in\s+)?millions?\b)|\bMM\b|(?<![A-Za-z])m\s+(?=\x00)"), 1e6),
)
# A measure that is not an amount of emissions: an intensity ("tCO2e / $M revenue"), a ratio, "per" anything.
_BAD_MEASURE = re.compile(r"(?i)intensity|\bper\b|revenue|/")
# Reasons a column is some other measure than the emissions total.
_NOT_A_TOTAL = re.compile(r"(?i)intensity|\bper\b|revenue|/|biogenic|%|percent|change|target|baseline|reduction|share|ratio|yoy")
_NAMES_TOTAL = re.compile(r"(?i)\btotal\b|\bemissions?\b")
# Unit-like words that are not unambiguous: a lowercase "mt", "tons" (short tons?), "short tons".
_UNCLEAR = re.compile(r"(?i)(?<![a-z])(?:mt|tons?|short\s+tons?)\s?(?:of\s+)?(?:co2|carbon\s+dioxide)")
SCALED_LABEL = {1e3: "ktCO2e", 1e6: "MtCO2e"}


def read_unit(texts: Sequence[str]) -> tuple[str | None, str | None, str | None]:
    """(unit, the words it was read from, problem) from the header and caption texts around a table, nearest first.

    The unit is one CO2e unit, with a printed scale applied ("thousand tCO2e" is ktCO2e). A problem says why there is
    none: "measure" (a header with a "/" denominator, "intensity", "per" or "revenue": the table is about something
    other than an amount of emissions and is not read at all), "scale" (several scales, or a scale printed beside a unit
    that is already scaled), "units" (several units), "unclear" (a unit that could mean two things)."""

    labels: set[str] = set()
    scales: set[float] = set()
    unclear = False
    source: str | None = None
    for raw in texts:
        text = _text(raw)
        found, rest = _scan_units(text)
        factors = {f for pattern, f in _SCALES if pattern.search(rest)}
        if not found:
            if factors and len(text) <= 80:  # a short caption of its own: "(in thousands)"
                scales |= factors
            elif _UNCLEAR.search(text):
                unclear = True
                source = source or text
            continue
        if _BAD_MEASURE.search(text):
            return None, text, "measure"
        labels |= found
        scales |= factors
        source = source or text
    if len(scales) > 1:
        return None, source, "scale"
    if len(labels) > 1:
        return None, source, "units"
    if not labels:
        return None, source, "unclear" if unclear else None
    label = next(iter(labels))
    if scales:
        factor = next(iter(scales))
        return (SCALED_LABEL[factor], source, None) if label == "tCO2e" else (None, source, "scale")
    return label, source, None


def parse_unit(text: Any, *, mass: bool = False) -> Unit | None:
    """The unit a whole cell or string names, or None. ``mass``: plain tonnes of one gas are accepted too."""

    clean = _text(text).rstrip(".")
    if not clean:
        return None
    found = find_units(clean)
    if len(found) == 1:
        label = next(iter(found))
        # the whole text is the unit: "thousand tCO2e of" or "Emissions MTCO2e" is a caption, not a unit cell
        if any(pattern.fullmatch(clean) for pattern, name in _RULES if name == label):
            return UNITS[label]
        return None
    if mass and not found:
        for pattern, label in _MASS_FULL:
            if pattern.fullmatch(clean) and not (label == "Mt" and clean == "mt"):
                return UNITS[label]
    return None


def to_tonnes(value: float, unit: Unit) -> float:
    return value * unit.factor


# =========================================================================================
# Cells
# =========================================================================================
_NUMBER = re.compile(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?")
_NOT_REPORTED = {"n/a", "na", "n.a.", "not available", "not reported", "nr", "-", "–", "—", "--"}
_YEAR = re.compile(r"(?:19|20)\d\d")


def number_of(text: Any) -> float | None:
    """A printed number with thousands separators ("34,128", "1.2"); nothing else (no units, signs or ranges)."""

    clean = _text(text)
    return float(clean.replace(",", "")) if _NUMBER.fullmatch(clean) else None


def is_not_reported(text: Any) -> bool:
    return _text(text).casefold() in _NOT_REPORTED


def _is_year(text: Any) -> bool:
    return _YEAR.fullmatch(_text(text)) is not None


def _value_cell(text: Any) -> bool:
    return (number_of(text) is not None and not _is_year(text)) or is_not_reported(text)


_ROW = re.compile(r"scope\s*([123])\s*(?:[-:,]\s*)?(?:\(?\s*(location|market)[\s-]*based\s*\)?)?(?:\s+(?:total|emissions?))?")


def scope_row(label: str) -> str | None:
    """The row a label names ("Scope 2 (location-based)" -> "s2_location"); None for anything else, and for a
    "Scope 2" that does not say its basis (it could be either)."""

    clean = _text(label).casefold()
    match = _ROW.fullmatch(clean)
    if match is None:
        return None
    scope, basis = match.group(1), match.group(2)
    if scope == "1":
        return "s1" if basis is None else None
    if scope == "2":
        return {"location": "s2_location", "market": "s2_market"}.get(basis or "")
    return "s3"


_COLUMNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"total(?:\s+(?:co2e|co2\s?-?\s?e(?:q)?|ghg|emissions?))*"), "total"),
    (re.compile(r"co2"), "co2"), (re.compile(r"ch4"), "ch4"), (re.compile(r"n2o"), "n2o"),
    (re.compile(r"hfcs?"), "hfcs"), (re.compile(r"pfcs?"), "pfcs"), (re.compile(r"sf6"), "sf6"),
    (re.compile(r"nf3"), "nf3"))


def column_of(header: str) -> str | None:
    """"CO2" -> co2, "HFC" -> hfcs, "Total CO2e" -> total; None for a header that names no gas."""

    clean = _text(header).casefold().strip(" ()")
    return next((key for pattern, key in _COLUMNS if pattern.fullmatch(clean)), None)


def field_for(row: str, column: str) -> str:
    prefix, total = SCOPE_ROWS[row]
    return total if column == "total" else f"{prefix}_{column}"


# =========================================================================================
# What was read
# =========================================================================================
@dataclass
class Hit:
    field_id: str
    raw: str  # the cell as printed ("34,128", "N/A")
    number: float | None  # None: not reported
    unit: str | None  # a label of UNITS, None when no single unit is printed
    unit_text: str | None  # the words the unit was read from
    reference: dict[str, Any]
    context: dict[str, Any] = field(default_factory=dict)
    year: int | None = None  # the one year the table's header or caption names
    unit_problem: str | None = None  # why there is no unit: see read_unit


@dataclass
class _Cell:
    text: str
    page: int | None
    x0: float
    y0: float
    x1: float
    y1: float
    block: dict[str, Any]

    @property
    def cx(self) -> float:
        return (self.x0 + self.x1) / 2

    @property
    def cy(self) -> float:
        return (self.y0 + self.y1) / 2

    @property
    def h(self) -> float:
        return max(self.y1 - self.y0, 1e-6)


def _cells(parser_output: Mapping[str, Any]) -> dict[int | None, list[_Cell]]:
    pages: dict[int | None, list[_Cell]] = defaultdict(list)
    for block in parser_output.get("text_blocks") or []:
        box = block.get("bounding_box") if isinstance(block, dict) else None
        text = _text(block.get("text")) if isinstance(block, dict) else ""
        if not text or not isinstance(box, dict):
            continue
        try:
            x0, y0 = float(box["left"]), float(box["top"])
            x1, y1 = x0 + float(box["width"]), y0 + float(box["height"])
        except (KeyError, TypeError, ValueError):
            continue
        pages[block.get("page_number")].append(_Cell(text, block.get("page_number"), x0, y0, x1, y1, block))
    return pages


def _median(values: Sequence[float]) -> float:
    ordered = sorted(values)
    return ordered[len(ordered) // 2] if ordered else 0.0


_YEAR_IN = re.compile(r"(?<![\d,.])(?:19|20)\d\d(?![\d,])")


def years_in(texts: Iterable[str]) -> set[int]:
    return {int(y) for t in texts for y in _YEAR_IN.findall(_text(t))}


def _numeric_rows(cells: Sequence[_Cell]) -> list[list[_Cell]]:
    """Value cells put in rows by the height of their centre."""

    values = sorted((c for c in cells if _value_cell(c.text)), key=lambda c: c.cy)
    tolerance = 0.6 * _median([c.h for c in values])
    rows: list[list[_Cell]] = []
    for cell in values:
        if rows and abs(cell.cy - sum(c.cy for c in rows[-1]) / len(rows[-1])) <= tolerance:
            rows[-1].append(cell)
        else:
            rows.append([cell])
    return [sorted(r, key=lambda c: c.x0) for r in rows]


def _total_ok(context: Sequence[str], unit: str | None) -> bool:
    """A lone value column is read as the row's Total only when its header or caption names a total or emissions, the
    unit is one of CO2e, and nothing there says it is another measure (intensity, biogenic, a change, a target...)."""

    joined = " ".join(context)
    return bool(unit in CO2E_UNITS and _NAMES_TOTAL.search(joined) and not _NOT_A_TOTAL.search(joined))


def _segment(matched: list[tuple[list[_Cell], str]], texts: Sequence[_Cell], row_h: float
             ) -> list[list[tuple[list[_Cell], str]]]:
    """Scope rows put into tables: a new table starts after a vertical gap of more than a couple of rows, or where
    a column header (a gas, a year) is printed again between two rows."""

    groups: list[list[tuple[list[_Cell], str]]] = []
    tops = [min(c.y0 for c in row) for row, _ in matched]
    pitch = _median([b - a for a, b in zip(tops, tops[1:])])
    limit = max(4 * row_h, 2.2 * pitch)  # rows of one table are about a pitch apart, whatever their height
    for row, key in matched:
        top = min(c.y0 for c in row)
        if groups:
            above = max(c.y1 for c in groups[-1][-1][0])
            header_between = any(above - 1e-4 <= t.cy <= top + 1e-4 and (column_of(t.text) or _is_year(t.text)) for t in texts)
            if top - above > limit or header_between:
                groups.append([])
        else:
            groups.append([])
        groups[-1].append((row, key))
    return groups


def read_page_cells(cells: Sequence[_Cell]) -> tuple[list[Hit], list[str]]:
    """The scope rows of every table on one page. A table is a run of value rows whose labels name scopes; its
    columns are named by the text above it, and only by that (two tables stacked on a page do not share a header)."""

    hits: list[Hit] = []
    notes: list[str] = []
    rows = [r for r in _numeric_rows(cells) if r]
    if not rows:
        return hits, notes
    value_ids = {id(c) for r in rows for c in r}
    texts = [c for c in cells if id(c) not in value_ids]
    row_h = _median([c.h for r in rows for c in r])
    # Each text cell left of a row belongs to the row whose centre is nearest (a two-line label shares one row).
    labels: dict[int, list[_Cell]] = defaultdict(list)
    for text in texts:
        best: int | None = None
        gap = 1.7 * row_h
        for index, row in enumerate(rows):
            apart = abs(text.cy - sum(c.cy for c in row) / len(row))
            if text.x1 <= row[0].x0 + 1e-4 and apart <= gap:
                best, gap = index, apart
        if best is not None:
            labels[best].append(text)
    matched: list[tuple[list[_Cell], str]] = []
    for index, row in enumerate(rows):
        pieces = sorted(labels.get(index, []), key=lambda c: (c.cy, c.x0))
        key = scope_row(" ".join(c.text for c in pieces)) if pieces else None
        if key is not None:
            matched.append((row, key))
    groups = _segment(matched, texts, row_h)
    spans = [(min(c.y0 for r, _ in g for c in r), max(c.y1 for r, _ in g for c in r)) for g in groups]
    for index, group in enumerate(groups):
        previous = spans[index - 1][1] if index else 0.0
        following = spans[index + 1][0] if index + 1 < len(groups) else 1.0
        found, more = _read_table_cells(group, texts, value_ids, cells, previous, following)
        hits.extend(found)
        notes.extend(more)
    return hits, notes


def _read_table_cells(group: list[tuple[list[_Cell], str]], texts: Sequence[_Cell], value_ids: set[int],
                      cells: Sequence[_Cell], previous: float, following: float) -> tuple[list[Hit], list[str]]:
    """One table of scope rows, read through its own header and caption."""

    hits: list[Hit] = []
    notes: list[str] = []
    top = min(c.y0 for row, _ in group for c in row)
    bottom = max(c.y1 for row, _ in group for c in row)
    reference = max((row for row, _ in group), key=len)
    pitch = min((b.cx - a.cx for a, b in zip(reference, reference[1:])), default=0.1) or 0.1
    floor = max(previous, top - 0.2)

    def column_cells(centre: float, within: float) -> list[_Cell]:
        # a header sits over its own column: a title or caption spanning several columns names none of them
        return [c for c in texts if floor < c.y1 <= top + 1e-4 and abs(c.cx - centre) <= within
                and c.x1 - c.x0 <= 2.4 * within]

    headers = {id(cell): " ".join(c.text for c in sorted(column_cells(cell.cx, 0.5 * pitch), key=lambda c: c.cy))
               for cell in reference}
    # a column about another measure ("tCO2e / $M revenue") names nothing, and takes no part in the unit
    named = {id(cell): (None if _BAD_MEASURE.search(headers[id(cell)]) else column_of(headers[id(cell)])) for cell in reference}
    band = [c for c in texts if floor < c.y1 <= top + 1e-4]
    if sum(1 for c in band if _is_year(c.text)) >= 2:
        return [], ["A table here has several year columns, so none of its figures were read: the document would "
                    "have to say which year is the reporting year."]
    years = years_in(c.text for c in band)
    year = next(iter(years)) if len(years) == 1 else None
    year_cell = next((c for c in band if year is not None and year in years_in([c.text])), None)

    def near(c: _Cell) -> float:
        return top - c.y1 if c.y1 <= top else max(c.y0 - bottom, 0.0)

    bad_headers = {id(c) for cell in reference for c in column_cells(cell.cx, 0.5 * pitch) if _BAD_MEASURE.search(headers[id(cell)])}
    context = sorted((c for c in cells if id(c) not in value_ids and id(c) not in bad_headers
                      and max(previous, top - 0.3) <= c.y1 <= min(bottom + 0.05, following - 0.005)), key=near)
    unit, unit_text, problem = read_unit([c.text for c in context])
    if problem == "measure":
        return [], ["A table here is about another measure (an intensity or a ratio), so none of its figures were read."]
    single = not any(named.values()) and all(len(row) == 1 for row, _ in group)
    if single and not _total_ok([c.text for c in band], unit):
        return [], ["A table here has one value column that is not named as a total in a CO2e unit, so it was not read."]
    for row, key in group:
        for cell in row:
            column = "total" if single else None
            if not single:
                nearest = min(reference, key=lambda r: abs(r.cx - cell.cx))
                if abs(nearest.cx - cell.cx) <= 0.5 * pitch:
                    column = named.get(id(nearest))
            if column is None:
                continue
            number = number_of(cell.text)
            hits.append(Hit(field_for(key, column), cell.text, number, unit if number is not None else None,
                            unit_text if number is not None else None, {}, {"block": cell.block, "page_number": cell.page},
                            year if number is not None else None, problem if number is not None else None))
    if hits and year_cell is not None and year is not None:
        hits.append(Hit("reporting_year", str(year), float(year), None, None, {},
                        {"block": year_cell.block, "page_number": year_cell.page}, year))
    return hits, notes


@dataclass
class TableRead:
    cells: list[tuple[str, str, str]]  # (row, column, the cell as printed)
    unit: str | None
    unit_text: str | None
    problem: str | None
    year: int | None
    notes: list[str]


def _segments(grid: list[list[str]]) -> list[tuple[list[list[str]], list[list[str]]]]:
    """(header rows, scope rows) per table: a table ends where a row that is not a scope row follows its scope rows."""

    out: list[tuple[list[list[str]], list[list[str]]]] = []
    header: list[list[str]] = []
    body: list[list[str]] = []
    for row in grid:
        lead = next((c for c in row if c), "")
        if not any(row):
            continue
        if scope_row(lead) is not None:
            body.append(row)
            continue
        if body:
            out.append((header, body))
            header, body = [], []
        header.append(row)
    if body:
        out.append((header, body))
    return out


def read_tables(rows: Sequence[Sequence[Any]]) -> list[TableRead]:
    """The tables in a grid of rows (a workbook sheet, a Textract table): each is read through its own header, and the
    columns are the same position in every row."""

    grid = [[_text(c) for c in row] for row in rows]
    reads: list[TableRead] = []
    for header, body in _segments(grid):
        notes: list[str] = []
        width = max(len(r) for r in [*header, *body])
        names: dict[int, str | None] = {}
        other_measure: set[int] = set()  # a column about an intensity, a ratio, "per ...": it names nothing
        label_column = min((next((i for i, c in enumerate(r) if c), width) for r in body), default=0)
        for index in range(width):
            text = " ".join(row[index] for row in header[-4:] if index < len(row) and row[index])
            if _BAD_MEASURE.search(text) and index != label_column:  # the label column's header is the caption
                other_measure.add(index)
            names[index] = None if index in other_measure else column_of(text)
        header_texts = [c for row in header for c in row if c]
        year_cells = [c for c in header_texts if _is_year(c)]
        if len(year_cells) >= 2 and not any(names.values()):
            reads.append(TableRead([], None, None, None, None,
                                   ["A table here has several year columns, so none of its figures were read."]))
            continue
        years = years_in(header_texts)
        year = next(iter(years)) if len(years) == 1 else None
        # nearest the rows first; a column about another measure takes no part in the unit
        unit, unit_text, problem = read_unit([row[i] for row in reversed(header) for i in range(len(row))
                                              if row[i] and i not in other_measure])
        if problem == "measure":
            reads.append(TableRead([], None, None, "measure", None,
                                   ["A table here is about another measure (an intensity or a ratio), so none of its figures were read."]))
            continue
        out: list[tuple[str, str, str]] = []
        single_ok = _total_ok(header_texts, unit)
        refused = False
        for row in body:
            label_at = next((i for i, c in enumerate(row) if c), None)
            key = scope_row(row[label_at]) if label_at is not None else None
            if key is None or label_at is None:
                continue
            numbers = [i for i, c in enumerate(row) if i > label_at and _value_cell(c)]
            single = not any(names.values()) and len(numbers) == 1
            if single and not single_ok:
                refused = True
                continue
            for index in numbers:
                column = "total" if single else names.get(index)
                if column is not None:
                    out.append((key, column, row[index]))
        if refused:
            notes.append("A table here has one value column that is not named as a total in a CO2e unit, so it was not read.")
        reads.append(TableRead(out, unit, unit_text, problem, year, notes))
    return reads


# =========================================================================================
# The extractor
# =========================================================================================
CONFIDENCE = 0.8  # a figure read from a printed table cell; a reviewer still accepts it


class ReportedTotalsExtractor:
    """Rule reader for the reported-emissions targets of a company summary document."""

    def __init__(self) -> None:
        self._service = ExtractionCandidateService()

    def handles(self, targets: Sequence[dict]) -> bool:
        return bool(targets) and all(t.get("canonical_type_id") in REPORTED_TYPES for t in targets)

    def extract(self, parser_output: dict, targets: Sequence[dict], evidence_id: str) -> ExtractionOutcome:
        document_id = str(parser_output.get("document_id") or "")
        hits, notes = self._hits(parser_output, document_id)
        by_field: dict[str, Hit] = {}
        clashes: set[str] = set()
        for hit in hits:  # the first printed place wins; two different figures for one field read nothing
            if hit.field_id in by_field:
                if by_field[hit.field_id].raw != hit.raw:
                    clashes.add(hit.field_id)
                continue
            by_field[hit.field_id] = hit
        if clashes:
            notes.append("A figure is printed twice with different values, so it was not read; check the document.")
        candidates = []
        for target in targets:
            name = str(target["field_id"])
            found_hit = None if name in clashes else by_field.get(name)
            candidates.append(self._candidate(target, found_hit, evidence_id, document_id, parser_output))
        return ExtractionOutcome(candidates=candidates, notes=notes)

    # --- finding the figures -------------------------------------------------------------------
    def _hits(self, parser_output: dict, document_id: str) -> tuple[list[Hit], list[str]]:
        hits: list[Hit] = []
        notes: list[str] = []
        for _page, cells in _cells(parser_output).items():
            found, more = read_page_cells(cells)
            for hit in found:
                block = hit.context["block"]
                hit.reference = self._service._source_reference_for_block(parser_output, block, document_id)
            hits.extend(found)
            notes.extend(more)
        for table in parser_output.get("tables") or []:
            if not isinstance(table, dict):
                continue
            reference = self._service._source_reference_for_table(parser_output, table, document_id)
            for read in read_tables(table.get("rows") or []):
                notes.extend(read.notes)
                for row, column, raw in read.cells:
                    number = number_of(raw)
                    located = self._service._with_position(parser_output, reference, raw, {"row_text": raw})
                    hits.append(Hit(field_for(row, column), raw, number, read.unit if number is not None else None,
                                    read.unit_text if number is not None else None, located,
                                    {"page_number": table.get("page_number")}, read.year if number is not None else None,
                                    read.problem if number is not None else None))
                if read.cells and read.year is not None:
                    hits.append(Hit("reporting_year", str(read.year), float(read.year), None, None, reference,
                                    {"page_number": table.get("page_number")}, read.year))
        return hits, list(dict.fromkeys(notes))

    # --- candidates ----------------------------------------------------------------------------
    def _candidate(self, target: dict, hit: Hit | None, evidence_id: str, document_id: str,
                   parser_output: dict) -> dict:
        name = str(target["field_id"])
        label = str(target.get("field_label") or name)
        build = self._service._build_candidate
        if hit is None:
            return build(evidence_id=evidence_id, document_id=document_id, field_id=name, display_label=label,
                         raw_value=None, normalized_value=None, unit=None, confidence=0.0,
                         source_reference=self._service._missing_source_reference(document_id, name),
                         validation_flags=[])
        reference = hit.reference
        flags: list[str] = []
        if hit.number is None:  # "N/A": not reported, kept as printed, never 0
            flags.append("not_reported")
            return build(evidence_id=evidence_id, document_id=document_id, field_id=name, display_label=label,
                         raw_value=hit.raw, normalized_value=None, unit=None, confidence=CONFIDENCE,
                         source_reference=reference, validation_flags=flags)
        allowed = [str(u) for u in target.get("expected_units") or ()]
        unit = hit.unit if hit.unit in allowed else None
        if target.get("value_type") == "quantity":
            if hit.unit is None:
                flags.append("unit_unclear" if hit.unit_problem else "unit_missing")
            elif unit is None:
                flags.append("unit_not_expected")
            else:
                flags.append(f"unit_as_printed:{hit.unit_text or unit}"[:120])
        if hit.year is not None and name != "reporting_year":
            flags.append(f"{YEAR_FLAG}{hit.year}")
        number: float | int = int(hit.number) if float(hit.number).is_integer() else hit.number
        return build(evidence_id=evidence_id, document_id=document_id, field_id=name, display_label=label,
                     raw_value=hit.raw, normalized_value=number, unit=unit, confidence=CONFIDENCE,
                     source_reference=reference, validation_flags=flags)


# =========================================================================================
# What an accepted figure feeds: the Reported side of Verification results
# =========================================================================================
@dataclass(frozen=True)
class DocumentFigure:
    key: str
    value_t: float  # in tonnes (of CO2e, or of the one gas)
    unit_choice: str  # "t CO2e" or "t": how a per-gas figure was reported
    document_id: str
    file_name: str
    page: int | None
    printed: str  # "34,128 tCO2e" / "1.2 MtCO2e", as the reviewer accepted it
    label: str
    year: int | None = None  # the year its table names, else the document's accepted reporting year

    def public(self) -> dict[str, Any]:
        return {"value": self.value_t, "unit": self.unit_choice, "document_id": self.document_id,
                "file_name": self.file_name, "page": self.page, "printed": self.printed, "label": self.label,
                "year": self.year}


def document_year(items: Sequence[Mapping[str, Any]], reviews: Sequence[Mapping[str, Any] | None]) -> int | None:
    """The reporting year the reviewer accepted (or typed) for the document, if any."""

    for item, review in zip(items, reviews):
        if item.get("field_name") != "reporting_year" or not review or str(review.get("decision")) not in REVIEWED:
            continue
        value = review.get("reviewed_value") if str(review.get("decision")) == "edited" else item.get("normalized_value")
        year = number_of(value) if not isinstance(value, (int, float)) or isinstance(value, bool) else float(value)
        if year is not None and float(year).is_integer() and 1900 <= year <= 2100:
            return int(year)
    return None


def _year_flag(item: Mapping[str, Any]) -> int | None:
    for flag in item.get("validation_flags") or []:
        if isinstance(flag, str) and flag.startswith(YEAR_FLAG) and flag[len(YEAR_FLAG):].isdigit():
            return int(flag[len(YEAR_FLAG):])
    return None


def figure_of(item: Mapping[str, Any], review: Mapping[str, Any] | None, document: Mapping[str, Any],
              doc_year: int | None = None) -> DocumentFigure | None:
    """The reviewer-accepted (or corrected) figure of one extracted item, in tonnes. None for anything not
    accepted, not a number, with no single known unit, or not a data point of the roll-up (Scope 3 is returned
    by ``reported_only_figure``)."""

    name = str(item.get("field_name") or "")
    if not review or str(review.get("decision")) not in REVIEWED:
        return None  # only accepted values count: a suggestion, a rejection or no decision feeds nothing
    if AI_SUGGESTED in (item.get("validation_flags") or []) and str(review.get("decision")) not in REVIEWED:
        return None
    if name not in rollup.FINAL_OUTPUT_KEYS and not is_reported_only(name):
        return None
    value = review.get("reviewed_value") if str(review.get("decision")) == "edited" else item.get("normalized_value")
    number = value if isinstance(value, (int, float)) and not isinstance(value, bool) else number_of(value)
    if number is None or not math.isfinite(number) or number < 0:
        return None
    given = review.get("reviewed_unit") or item.get("unit")
    gas = name in rollup.UNIT_KEYS
    unit = parse_unit(given, mass=gas) or (UNITS.get(str(given)) if given else None)
    if unit is None or (not unit.co2e and not gas and not is_reported_only(name)):
        return None  # no single known unit, or tonnes of "a gas" against a total: never guessed
    reference = item.get("source_reference") or {}
    page = reference.get("page_number")
    return DocumentFigure(
        key=name, value_t=to_tonnes(float(number), unit), unit_choice="t CO2e" if unit.co2e else "t",
        document_id=str(document.get("document_id")), file_name=str(document.get("file_name") or ""),
        page=page if isinstance(page, int) else None, printed=f"{_trim(float(number))} {unit.label}",
        label=str(item.get("display_label") or name), year=_year_flag(item) or doc_year)


def _trim(number: float) -> str:
    return f"{number:,.0f}" if float(number).is_integer() else f"{number:,}"


def year_problem(figure: DocumentFigure, years: Collection[int] | None) -> str | None:
    """Why a figure is not compared: its year is not the engagement's, or not stated, or the period is not set."""

    if figure.year is None:
        return "Year not stated"
    if years is None:
        return "Reporting period not set, so the year was not compared"
    return None if figure.year in years else f"Different year ({figure.year}) \u2014 not compared"


def period_years(start: Any, end: Any) -> set[int] | None:
    """The year a figure for the engagement's reporting period carries: the year it ends in (a fiscal year is named by
    the year it ends), or its own year when it is one calendar year. None when the period is not set."""

    if end is None:
        return None
    years = {end.year}
    if start is not None and start.year == end.year:
        years.add(start.year)
    return years


def overlay(manual: Mapping[str, float], manual_units: Mapping[str, str], figures: Iterable[DocumentFigure],
            years: Collection[int] | None = None
            ) -> tuple[dict[str, float], dict[str, str], dict[str, dict[str, Any]], list[dict[str, Any]]]:
    """The reported values the comparison uses, the units of its per-gas rows, what each came from, and the
    figures that are reported only (Scope 3).

    A manual entry always wins and is never changed; the document's figure is shown beside it and flagged when it
    differs. Two accepted figures for one data point that disagree feed nothing (listed as a conflict). A figure of
    another year than the engagement's, or of no stated year, is never fed: it is listed as not compared."""

    by_key: dict[str, list[DocumentFigure]] = defaultdict(list)
    reported_only: list[dict[str, Any]] = []
    for figure in figures:
        if is_reported_only(figure.key):
            reported_only.append({**figure.public(), "key": figure.key, "excluded": year_problem(figure, years)})
        else:
            by_key[figure.key].append(figure)
    reported, units = dict(manual), dict(manual_units)
    sources: dict[str, dict[str, Any]] = {}
    for key, every in by_key.items():
        found = [f for f in every if year_problem(f, years) is None]
        if not found:
            first = every[0]
            sources[key] = {"document": first.public(), "manual": manual.get(key), "used": "manual" if key in manual else None,
                            "differs": False, "excluded": year_problem(first, years)}
            continue
        agreed = [f for f in found if math.isclose(f.value_t, found[0].value_t, rel_tol=1e-9, abs_tol=1e-9)
                  and f.unit_choice == found[0].unit_choice]
        figure = found[0]
        if len(agreed) != len(found):
            sources[key] = {"document": None, "manual": manual.get(key), "used": "manual" if key in manual else None,
                            "differs": False, "conflict": [f.public() for f in found]}
            continue
        if key in manual:
            differs = (not math.isclose(manual[key], figure.value_t, rel_tol=1e-6, abs_tol=0.5)
                       or (key in rollup.UNIT_KEYS and manual_units.get(key, "t") != figure.unit_choice))
            sources[key] = {"document": figure.public(), "manual": manual[key], "used": "manual", "differs": differs}
            continue
        reported[key] = figure.value_t
        if key in rollup.UNIT_KEYS:
            units[key] = figure.unit_choice
        sources[key] = {"document": figure.public(), "manual": None, "used": "document", "differs": False}
    return reported, units, sources, reported_only
