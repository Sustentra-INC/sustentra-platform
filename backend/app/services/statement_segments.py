"""Where one statement ends and the next begins, in a file that holds several (EXT-015).

A utility sends an annual package, or a client scans a stack of bills into one PDF: twelve monthly
statements in one file. Read as a single bill it gives one record, for the first statement only.
Here the rows (as the extractors build them, with their pages) are cut into one part per statement,
and each part is then read like the single bill it is. A wrong cut is worse than no cut (a quantity
paired with another month's period, or one bill counted twice), so the rules are strict and a cut that
is not clean is not made:

- A statement's period is a labelled period line ("Billing Period: 12/16/2024 - 01/15/2025") whose value
  begins with its first date. When a file prints several names for it (a billing period, a meter-read
  period a few days apart), only the name most lines carry counts. A line under an adjustment,
  restatement, prior-period, correction, history or summary heading is not a statement's period.
- Periods that overlap (two days or more), or start within a few days of each other, are the same
  statement: a summary page and its detail page state their periods a day apart.
- A new statement starts at the top of a page. The one exception is a page that also holds the earlier
  statement's usage table: there the new one must start at a title line that repeats the first
  statement's title ("Electric Service Statement"; a title line may have several cells).
- If the file holds two or more statements by those periods but a cut would not be clean, nothing is
  split: ``Split.note`` says so, and the caller reads the file whole and passes the note on.

Pure and layout-only: it reads no values. Each part's rows are renumbered from 0.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import date

from backend.app.domain import fuel_units
from backend.app.services.stationary_combustion_extractor import (
    RANGE_PERIOD_LABELS,
    Row,
    _norm,
    parse_date,
    parse_dates,
)

# "period" alone also heads columns and sentences ("reporting period"); a statement's period is named.
_PERIOD_LABELS = tuple(sorted(
    {label for group in RANGE_PERIOD_LABELS for label in group if label != "period"},
    key=lambda label: (-len(label), label)))  # longest first, then by name: the same order in every process
_TITLE_RE = re.compile(r"\b(?:statement|invoice|bill)\b")
_TITLE_MAX_WORDS = 8
_TITLE_REACH = 14  # how far above its period line a statement's title can sit
_HEADING_REACH = 8  # how far above a period line its heading is looked for
# A period under one of these headings restates or lists periods; it does not start a statement.
_NOT_A_STATEMENT_RE = re.compile(
    r"\b(adjustment|adjustments|restatement|restated|prior[- ]period|previous period|correction|corrected|"
    r"history|summary of accounts|account summary|summary)\b")
SAME_STATEMENT_OVERLAP_DAYS = 2  # periods sharing this many days or more are one statement
SAME_STATEMENT_START_DAYS = 5  # periods starting this close are one statement

SPLIT_NOTE = ("This file may hold more than one statement, but it was read as one. "
              "Check the billing periods.")


@dataclass(frozen=True)
class Split:
    """``parts``: one row list per statement; None when the file is read whole. ``note``: to tell the
    reviewer when the file may hold more statements than were told apart (it was not cut, or periods that
    differ were taken for one statement); None when the periods leave no doubt."""

    parts: list[list[Row]] | None
    note: str | None = None


def _labelled_period(row: Row) -> tuple[str, tuple[str, str]] | None:
    """(label, (start, end)) when the row is a labelled billing-period line, else None. The value must
    begin with its first date, so "Billing period adjustment: ..." or "Next read date" are not periods."""

    for at, cell in enumerate(row.cells):
        text = _norm(cell.text)
        for label in _PERIOD_LABELS:
            if text.startswith(label) and (len(text) == len(label) or text[len(label)] in ": "):
                after = cell.text[len(label):].lstrip(" :")
                value = after if after.strip() else " ".join(c.text for c in row.cells[at + 1: at + 2])
                first = parse_date(value)
                dates = parse_dates(value)
                if first is not None and first[1] == 0 and len(dates) >= 2:
                    return label, (dates[0], dates[1])
                break
    return None


def statement_period(row: Row) -> tuple[str, str] | None:
    """(start, end) ISO dates when the row is a labelled billing-period line, else None."""

    found = _labelled_period(row)
    return found[1] if found else None


def _is_heading(row: Row) -> bool:
    """A short line of words with no figures: a section heading, not a value line."""

    text = " ".join(_norm(c.text) for c in row.cells)
    return bool(text) and len(row.cells) <= 2 and len(text.split()) <= 8 and not re.search(r"\d|\$", text) \
        and ":" not in text


def _under_a_restating_heading(rows: Sequence[Row], at: int) -> bool:
    """True when the nearest heading above the period line, on its page, restates or lists periods."""

    for above in range(at - 1, max(at - _HEADING_REACH, -1) - 1, -1):
        if rows[above].page != rows[at].page:
            return False
        if _is_heading(rows[above]):
            return _NOT_A_STATEMENT_RE.search(" ".join(_norm(c.text) for c in rows[above].cells)) is not None
    return False


def _days(iso: str) -> date:
    return date.fromisoformat(iso)


def _same_statement(first: tuple[str, str], other: tuple[str, str]) -> bool:
    """Periods that overlap, or start within a few days of each other, belong to one statement."""

    try:
        start_a, end_a, start_b, end_b = _days(first[0]), _days(first[1]), _days(other[0]), _days(other[1])
    except ValueError:
        return True  # an unreadable date is never grounds for a cut
    overlap = (min(end_a, end_b) - max(start_a, start_b)).days + 1
    return overlap >= SAME_STATEMENT_OVERLAP_DAYS or abs((start_a - start_b).days) <= SAME_STATEMENT_START_DAYS


def _title_text(row: Row) -> str | None:
    """The statement title a row carries ("Your Electric Service Statement"), whatever else is on the row."""

    for cell in row.cells:
        text = _norm(cell.text)
        if _TITLE_RE.search(text) and len(text.split()) <= _TITLE_MAX_WORDS and not re.search(r"\d", text):
            return text
    return None


def _has_usage_table_row(row: Row) -> bool:
    """A table row with a figure and its unit ("WEC-1  Total kWh  1,000  2,000  1,000 kWh")."""

    return len(row.cells) >= 3 and any(
        re.search(r"\d", cell.text) and fuel_units.find_unit(cell.text) is not None for cell in row.cells)


def split_statements(rows: Sequence[Row]) -> Split:
    """The rows cut into one list per statement, or ``Split(None)`` (with a note when the file looks like
    several statements but could not be cut cleanly)."""

    labelled = [(at, found) for at, row in enumerate(rows)
                if (found := _labelled_period(row)) is not None and not _under_a_restating_heading(rows, at)]
    if not labelled:
        return Split(None)
    counts: dict[str, int] = {}
    for _, (name, _) in labelled:
        counts[name] = counts.get(name, 0) + 1
    label = max(counts, key=lambda name: (counts[name], -_PERIOD_LABELS.index(name)))
    periods = [(at, period) for at, (name, period) in labelled if name == label]

    # where each new statement's period line sits (a period the current statement already states is not new)
    firsts = [periods[0]]
    merged = False  # a period that differs from its statement's but was taken for the same statement
    for at, period in periods[1:]:
        if not _same_statement(firsts[-1][1], period):
            firsts.append((at, period))
        elif period != firsts[-1][1]:
            merged = True
    note = SPLIT_NOTE if merged else None  # two real statements can overlap or start days apart: say so
    if len(firsts) < 2:
        return Split(None, note)

    title = next((t for i in range(firsts[0][0], max(firsts[0][0] - _TITLE_REACH, -1) - 1, -1)
                  if (t := _title_text(rows[i])) is not None), None)
    starts = [0]
    for number, (at, _) in enumerate(firsts[1:], start=1):
        row = rows[at]
        page_first = next(i for i, r in enumerate(rows) if r.page == row.page)
        previous_at = firsts[number - 1][0]
        fresh_page = rows[previous_at].page != row.page and not any(_has_usage_table_row(r) for r in
                                                                       rows[page_first:at])
        if fresh_page:
            starts.append(page_first)  # the new statement starts at the top of a page
            continue
        floor = max(previous_at + 1, page_first, at - _TITLE_REACH)
        start = next((i for i in range(at - 1, floor - 1, -1)
                      if title is not None and _title_text(rows[i]) == title), None)
        if start is None:
            return Split(None, SPLIT_NOTE)  # two statements share the page and nothing marks where one ends
        starts.append(start)
    bounds = [*starts, len(rows)]
    # The readers address rows by ``row.index`` as a position in the list they are given, so each part's
    # rows are renumbered from 0 (the cells are shared, nothing is copied).
    parts = [[replace(row, index=n) for n, row in enumerate(rows[bounds[i]:bounds[i + 1]])]
             for i in range(len(starts)) if bounds[i] < bounds[i + 1]]
    return Split(parts, note)
