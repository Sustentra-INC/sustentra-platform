"""Where one statement ends and the next begins, in a file that holds several (EXT-015).

A utility sends an annual package, or a client scans a stack of bills into one PDF: twelve monthly
statements in one file. Read as a single bill it gives one record, for the first statement only.
Here the rows (as the extractors build them, with their pages) are cut into one part per statement,
and each part is then read like the single bill it is. The cut follows the billing period each
statement states, because that is what makes it a different statement:

- a labelled period ("Billing Period: 12/16/2024 - 01/15/2025", "Service period") with two dates
  is a statement's period; a second page of the same statement repeats the same period;
- a new period starts a new statement. On a fresh page the statement starts at the top of the page
  (letterhead and all). When the page already holds usage lines of the earlier statement, the new one
  starts at its own title line ("Electric Service Statement") or, failing that, at its period line;
- pages with no period (a cover, the terms at the back) stay with the statement before them, and a
  part that yields no record is dropped by the caller;
- a file with fewer than two different periods is one statement: nothing is split.

Pure and layout-only: it reads no values. Each part's rows are renumbered from 0.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import replace

from backend.app.domain import fuel_units
from backend.app.services.stationary_combustion_extractor import (
    RANGE_PERIOD_LABELS,
    Row,
    _norm,
    parse_dates,
)

# "period" alone also heads columns and sentences ("reporting period"); a statement's period is named.
_PERIOD_LABELS = tuple(sorted(
    {label for group in RANGE_PERIOD_LABELS for label in group if label != "period"}, key=len, reverse=True))
_TITLE_RE = re.compile(r"\b(?:statement|invoice|bill)\b")
_TITLE_MAX_WORDS = 8
_TITLE_REACH = 12  # how far above its period line a statement's title can sit


def statement_period(row: Row) -> tuple[str, str] | None:
    """(start, end) ISO dates when the row is a labelled billing-period line, else None."""

    for at, cell in enumerate(row.cells):
        text = _norm(cell.text)
        for label in _PERIOD_LABELS:
            if text.startswith(label) and (len(text) == len(label) or text[len(label)] in ": "):
                after = cell.text[len(label):].lstrip(" :")
                value = after if after.strip() else " ".join(c.text for c in row.cells[at + 1: at + 2])
                dates = parse_dates(value)
                if len(dates) >= 2:
                    return dates[0], dates[1]
                break
    return None


def _has_usage(row: Row) -> bool:
    """A usage figure with its unit ("143,230 kWh"): the body of a statement, not its heading."""

    return any(re.search(r"\d", cell.text) and fuel_units.find_unit(cell.text) is not None for cell in row.cells)


def _is_title(row: Row) -> bool:
    if len(row.cells) != 1:
        return False
    text = _norm(row.cells[0].text)
    return bool(_TITLE_RE.search(text)) and len(text.split()) <= _TITLE_MAX_WORDS and not re.search(r"\d", text)


def split_statements(rows: Sequence[Row]) -> list[list[Row]] | None:
    """The rows cut into one list per statement, or None when the file is a single statement."""

    periods = [(at, statement_period(row)) for at, row in enumerate(rows)]
    periods = [(at, period) for at, period in periods if period is not None]
    if len({period for _, period in periods}) < 2:
        return None

    starts = [0]
    current = periods[0][1]
    previous_at = periods[0][0]
    for at, period in periods[1:]:
        if period == current:
            previous_at = at
            continue
        row = rows[at]
        page_first = next(i for i, r in enumerate(rows) if r.page == row.page)
        before = rows[page_first:at]
        if rows[previous_at].page != row.page and not any(_has_usage(r) for r in before):
            start = page_first  # a fresh page: the whole page is the new statement's
        else:  # two statements share the page: the new one starts at its title, else at its period line
            floor = max(previous_at + 1, page_first, at - _TITLE_REACH)
            start = next((i for i in range(at - 1, floor - 1, -1) if _is_title(rows[i])), at)
        starts.append(start)
        current, previous_at = period, at
    bounds = [*starts, len(rows)]
    # The readers address rows by ``row.index`` as a position in the list they are given, so each part's
    # rows are renumbered from 0 (the cells are shared, nothing is copied).
    return [[replace(row, index=at) for at, row in enumerate(rows[bounds[i]:bounds[i + 1]])]
            for i in range(len(starts)) if bounds[i] < bounds[i + 1]]
