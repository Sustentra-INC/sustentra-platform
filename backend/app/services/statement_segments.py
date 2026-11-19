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
- Statements run forward in time: a new period that starts before the previous statement's means the file
  is not read as a bundle (a newest-first bundle is read whole, with the note).
- A new part counts as a statement only when it repeats the first statement's title row or its account
  number; otherwise nothing is split.
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
    ACCOUNT_LABELS,
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
# A period under one of these headings restates, compares or lists periods; it does not start a statement
# ("Your Previous Bill", "Usage Comparison", "Last Year", "Budget Plan Detail", "Prior Period Adjustment").
_NOT_A_STATEMENT_RE = re.compile(
    r"\b(adjustment|adjustments|restatement|restated|correction|corrected|comparison|compare|compared|"
    r"previous|prior|last (?:year|month|bill|period)|budget|plan detail|history|summary)\b")
# Of those, the words that name a restatement outright. "summary" and "budget" alone can head every page of a
# real bundle ("Bill Summary", "Budget Billing Plan Customer"): see ``_statement_headings``.
_STRONG_RE = re.compile(
    r"\b(adjustment|adjustments|restatement|restated|correction|corrected|comparison|compare|compared|"
    r"previous|prior|last (?:year|month|bill|period)|plan detail|history|summary of accounts)\b")
_PAGE_HEADING_ROWS = 5  # a page's heading is among its first rows
SAME_STATEMENT_OVERLAP_DAYS = 2  # periods sharing this many days or more are one statement
SAME_STATEMENT_START_DAYS = 5  # periods starting this close are one statement

SPLIT_NOTE = ("This file may hold more than one statement, but it was read as one. "
              "Check the billing periods.")


@dataclass(frozen=True)
class Split:
    """``parts``: one row list per statement; None when the file is read whole. ``note``: to tell the
    reviewer when the file may hold more statements than were told apart (it was not cut, periods that
    differ were taken for one statement, or period lines were left out as restatements); None when the
    periods leave no doubt."""

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


def _row_text(row: Row) -> str:
    return " ".join(_norm(c.text) for c in row.cells)


def _restates(row: Row) -> bool:
    return _NOT_A_STATEMENT_RE.search(_row_text(row)) is not None


def _restating_heading(rows: Sequence[Row], at: int) -> tuple[str, bool] | None:
    """(heading text, whether it names a restatement outright) when the period line sits under a heading that
    restates, compares or lists periods: the nearest heading above it on its page, or any cell of the page's
    first rows (a heading can sit in a logo | utility | heading row, or carry a colon)."""

    first = next(i for i, r in enumerate(rows) if r.page == rows[at].page)
    for above in range(at - 1, max(at - _HEADING_REACH, first - 1) - 1, -1):
        if _is_heading(rows[above]):
            if _restates(rows[above]):
                return _row_text(rows[above]), _STRONG_RE.search(_row_text(rows[above])) is not None
            break
    for row in rows[first:min(at, first + _PAGE_HEADING_ROWS)]:
        if _restates(row):
            return _row_text(row), _STRONG_RE.search(_row_text(row)) is not None
    return None


def _statement_headings(rows: Sequence[Row], infos: list[tuple[int, tuple[str, tuple[str, str]],
                                                               tuple[str, bool] | None]]) -> set[str]:
    """Headings that only look like a restatement: "Bill Summary" or "Budget Billing Plan Customer" printed on
    every statement. A heading without a strongly restating word, on two or more pages that each state a
    different period and an account number (or a title of their own), is a statement's own heading, but only
    when the page of the file's first period line carries it too: appendix pages headed "Budget Billing
    Summary" after a bill that does not are restatements."""

    pages: dict[str, dict[int, set[tuple[str, str]]]] = {}
    for at, (_, period), restating in infos:
        if restating is not None and not restating[1]:
            pages.setdefault(restating[0], {}).setdefault(rows[at].page or 0, set()).add(period)
    first_heading = infos[0][2][0] if infos and infos[0][2] is not None else None
    out: set[str] = set()
    for heading, by_page in pages.items():
        periods = {p for found in by_page.values() for p in found}
        if heading != first_heading or len(by_page) < 2 or len(periods) < 2:
            continue
        if all(_accounts([r for r in rows if (r.page or 0) == page])
               or any((t := _title_text(r)) is not None and t != heading
                      for r in rows if (r.page or 0) == page) for page in by_page):
            out.add(heading)
    return out


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


def _runs_backward(previous: tuple[str, str], period: tuple[str, str]) -> bool:
    """True when a statement's period starts before the previous statement's: statements are in time order,
    while a restated or earlier period points back (a newest-first bundle is read whole and flagged)."""

    try:
        return _days(period[0]) < _days(previous[0])
    except ValueError:
        return False


def _title_text(row: Row) -> str | None:
    """The statement title a row carries ("Your Electric Service Statement"), whatever else is on the row."""

    for cell in row.cells:
        text = _norm(cell.text)
        if _TITLE_RE.search(text) and len(text.split()) <= _TITLE_MAX_WORDS and not re.search(r"\d", text):
            return text
    return None


def _accounts(rows: Sequence[Row]) -> set[str]:
    """The account numbers a run of rows states ("Account Number: 4471-20983-6")."""

    labels = {label for group in ACCOUNT_LABELS for label in group}
    found: set[str] = set()
    for row in rows:
        for at, cell in enumerate(row.cells):
            text = _norm(cell.text).rstrip(":").strip()
            value = None
            if text in labels:
                value = " ".join(c.text for c in row.cells[at + 1: at + 2])
            else:
                for label in labels:
                    if _norm(cell.text).startswith(label + ":"):
                        value = cell.text.split(":", 1)[1]
                        break
            if value and re.search(r"\d", value):
                found.add(re.sub(r"\s+", "", value).lower())
    return found


def _has_usage_table_row(row: Row) -> bool:
    """A table row with a figure and its unit ("WEC-1  Total kWh  1,000  2,000  1,000 kWh")."""

    return len(row.cells) >= 3 and any(
        re.search(r"\d", cell.text) and fuel_units.find_unit(cell.text) is not None for cell in row.cells)


def split_statements(rows: Sequence[Row]) -> Split:
    """The rows cut into one list per statement, or ``Split(None)`` (with a note when the file looks like
    several statements but could not be cut cleanly)."""

    infos = [(at, found, _restating_heading(rows, at)) for at, row in enumerate(rows)
             if (found := _labelled_period(row)) is not None]
    real = _statement_headings(rows, infos)
    labelled = [(at, found) for at, found, restating in infos if restating is None or restating[0] in real]
    left_out = {found[1] for _, found, restating in infos if restating is not None and restating[0] not in real}
    if not labelled:
        return Split(None, SPLIT_NOTE if left_out else None)  # every period line was taken for a restatement
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
            if _runs_backward(firsts[-1][1], period):
                return Split(None, SPLIT_NOTE)  # a bundle runs forward in time; this one does not
            firsts.append((at, period))
        elif period != firsts[-1][1]:
            merged = True
    # Two real statements can overlap or start days apart, and a period line left out as a restatement may have
    # been a statement's own: either way the reviewer is told.
    note = SPLIT_NOTE if merged or (left_out - {period for _, period in periods}) else None
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
    # A new part is a statement only when it repeats the first one's title or its account number: a page that
    # merely carries a billing-period line and a total (a previous bill, a comparison) is not one.
    first_accounts = _accounts(parts[0])
    for part in parts[1:]:
        titles = {t for r in part if (t := _title_text(r)) is not None}
        if not ((title is not None and title in titles) or (first_accounts & _accounts(part))):
            return Split(None, SPLIT_NOTE)
    return Split(parts, note)
