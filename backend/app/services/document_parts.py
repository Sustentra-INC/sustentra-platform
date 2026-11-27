"""Whole-document reads (MVP-237): a document's stored text cut into parts that each fit one AI call,
and the monthly limit checked before every part.

Sustentra's AI reads the whole document, never only its first pages: the type, the values, the facility and the
methodology read all go through ``iter_parts``. The text is the parser output already in hand (or kept by
``parsed_text_repository``), so a whole-document read never scans a file again.

How a document is cut (``iter_parts``):

* by pages: a part holds whole pages while they fit its character budget (``part_chars``: the call's token budget,
  less what the prompt and the reply need, at ``CHARS_PER_TOKEN``), and at most ``max_pages`` of them when given;
* a page too long for one part is cut between its lines; a single line too long for one part (a 200 KB line) is cut
  into pieces of the budget, each piece repeating the last ``PIECE_OVERLAP_CHARS`` of the one before, so a value
  cut in two is still whole in one piece;
* lines with no page (a workbook, a CSV, an email) are cut between lines;
* parts overlap only where a table runs over a page break: the table rows that end the page before (at most
  ``TABLE_OVERLAP_LINES``) are shown again at the start of the next part, counted in ``Part.overlap``. A value read
  twice there is the same line (same alias and reference), so the callers count it once.

Every line keeps its page number, alias and the parser's reference, so a quote is found and cited where it is
printed. Parts are produced one at a time (a generator): a 2,000-page document is never held as 2,000-page prompts.

Spend (``Spend``): every part is checked against the organization's one monthly limit on Sustentra's AI and scans
before it is sent. When the limit is reached mid-document the read stops, what was read is kept, and the document
is marked "Read in part" with the pages not read (``read_in_part``): a partly read document is never shown as read.
"""

from __future__ import annotations

import dataclasses
import re
import uuid
from collections.abc import Callable, Iterable, Iterator, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from backend.app.services import ai_usage
from backend.app.services.ai_locator import DocumentLine

CHARS_PER_TOKEN = 3  # conservative: prose is about 4 characters a token, numbers and tables fewer
MIN_PART_CHARS = 2_000
TABLE_OVERLAP_LINES = 8
UNPAGED_PAGE_LINES = 100  # lines with no page (a sheet's rows) that count as one page for ``max_pages``
PIECE_OVERLAP_CHARS = 400
READ_IN_PART = "ai_read_in_part"
LIMIT_REASON = "this month's limit on Sustentra's AI and scans is reached"
TIME_REASON = "the time for one read ran out"
FAILED_REASON = "Sustentra's AI could not be reached or gave no usable answer"

_NUMBER = re.compile(r"\d[\d,.]*")


def part_chars(budget_tokens: int, reserved_tokens: int) -> int:
    """The characters of document text one part may hold: the call's input budget less the prompt's and the
    reply's share, at ``CHARS_PER_TOKEN``; never under ``MIN_PART_CHARS``."""

    return max(MIN_PART_CHARS, (budget_tokens - reserved_tokens) * CHARS_PER_TOKEN)


def line_cost(line: DocumentLine) -> int:
    """What a line takes in a prompt: ``"L3: text"`` and its newline."""

    return len(line.alias) + len(line.text) + 3


@dataclass(frozen=True)
class Part:
    """One part of a document. ``lines`` is what the model is shown: the ``overlap`` lines first (repeated from
    the part before), then the part's own lines, which are ``start`` to ``end`` (exclusive) of the document's
    lines. ``piece`` is set when the part is one piece of a line too long for a part: the character range of that
    line this piece adds."""

    index: int  # 1-based
    lines: tuple[DocumentLine, ...]
    overlap: int
    start: int
    end: int
    piece: tuple[int, int] | None = None

    @property
    def own_lines(self) -> tuple[DocumentLine, ...]:
        return self.lines[self.overlap:]

    @property
    def pages(self) -> tuple[int, ...]:
        """The pages this part's own lines are on, in order (a page cut between parts is in both)."""

        return tuple(dict.fromkeys(int(line.page_number) for line in self.own_lines if line.page_number is not None))

    def label(self) -> str:
        return describe_lines(self.own_lines)


def describe_lines(lines: Sequence[DocumentLine]) -> str:
    """"pages 3–7", "page 4", "lines L10–L90" (lines with no page), or both, for the lines given in order."""

    pages = [int(line.page_number) for line in lines if line.page_number is not None]
    unpaged = [line.alias for line in lines if line.page_number is None]
    parts: list[str] = []
    if pages:
        low, high = min(pages), max(pages)
        parts.append(f"page {low}" if low == high else f"pages {low}–{high}")
    if unpaged:
        parts.append(f"line {unpaged[0]}" if unpaged[0] == unpaged[-1] else f"lines {unpaged[0]}–{unpaged[-1]}")
    return " and ".join(parts) or "nothing"


def looks_like_table_row(line: DocumentLine) -> bool:
    """A table row: a sheet row, a cell of a parser table, or a short line of two or more numbers."""

    reference = line.source_reference or {}
    if " | " in line.text or reference.get("cell_or_range") or reference.get("table_id"):
        return True
    return len(_NUMBER.findall(line.text)) >= 2 and len(line.text.split()) <= 16


def _pages(lines: Iterable[DocumentLine]) -> Iterator[list[DocumentLine]]:
    """Consecutive lines of one page as one group; each line with no page is a group of its own."""

    group: list[DocumentLine] = []
    for line in lines:
        if group and (line.page_number is None or line.page_number != group[-1].page_number):
            yield group
            group = []
        group.append(line)
        if line.page_number is None:
            yield group
            group = []
    if group:
        yield group


def _table_tail(page: Sequence[DocumentLine], max_chars: int) -> list[DocumentLine]:
    """The table rows that end a page (at most TABLE_OVERLAP_LINES, and a quarter of a part)."""

    tail: list[DocumentLine] = []
    chars = 0
    for line in reversed(page):
        if not looks_like_table_row(line) or len(tail) >= TABLE_OVERLAP_LINES or chars + line_cost(line) > max_chars // 4:
            break
        tail.insert(0, line)
        chars += line_cost(line)
    return tail


def _pieces(line: DocumentLine, max_chars: int) -> Iterator[tuple[DocumentLine, tuple[int, int]]]:
    """A line too long for a part, as pieces that each fit one; each repeats the end of the one before. The span
    is the character range of the line the piece adds."""

    room = max(max_chars - len(line.alias) - 3, PIECE_OVERLAP_CHARS * 2)
    start = 0
    while start < len(line.text):
        begin = max(0, start - PIECE_OVERLAP_CHARS)
        end = min(len(line.text), begin + room)
        yield dataclasses.replace(line, text=line.text[begin:end]), (start, end)
        start = end


def iter_parts(lines: Iterable[DocumentLine], *, max_chars: int, max_pages: int | None = None) -> Iterator[Part]:
    """The document's lines as parts (see the module docstring), one at a time, in document order. With
    ``max_pages``, a part holds at most that many pages; ``UNPAGED_PAGE_LINES`` lines with no page count as one."""

    index = 0
    position = 0  # lines handed out so far
    current: list[DocumentLine] = []
    overlap: list[DocumentLine] = []
    held: set[int] = set()  # the pages of ``current``
    unpaged = 0  # the lines of ``current`` with no page
    chars = 0
    start = 0
    last_page: list[DocumentLine] = []

    def make(piece: tuple[int, int] | None = None) -> Part:
        nonlocal index
        index += 1
        return Part(index, (*overlap, *current), len(overlap), start, position, piece)

    def reset(tail: Sequence[DocumentLine] = ()) -> None:
        nonlocal overlap, current, held, unpaged, chars, start
        overlap, current, held, unpaged, start = list(tail), [], set(), 0, position
        chars = sum(line_cost(line) for line in tail)

    def take(line: DocumentLine) -> None:
        nonlocal chars, position, unpaged
        current.append(line)
        chars += line_cost(line)
        position += 1
        if line.page_number is None:
            unpaged += 1
        else:
            held.add(int(line.page_number))

    def too_many_pages(page: Sequence[DocumentLine]) -> bool:
        if max_pages is None:
            return False
        number = page[0].page_number
        pages = len(held | ({int(number)} if number is not None else set()))
        rows = unpaged + (1 if number is None else 0)
        return pages + -(-rows // UNPAGED_PAGE_LINES) > max_pages

    for page in _pages(lines):
        paged = page[0].page_number is not None
        page_chars = sum(line_cost(line) for line in page)
        if current and (chars + page_chars > max_chars or too_many_pages(page)):
            yield make()
            # A table that runs over the page break is shown again at the start of the next part.
            table = paged and bool(last_page) and last_page[-1].page_number is not None and looks_like_table_row(page[0])
            reset(_table_tail(last_page, max_chars) if table else ())
        if chars + page_chars <= max_chars:
            for line in page:
                take(line)
        else:  # the page alone does not fit: cut it between lines, and a line too long into pieces
            for line in page:
                cost = line_cost(line)
                if current and chars + cost > max_chars:
                    yield make()
                    reset()
                if cost <= max_chars - chars:
                    take(line)
                    continue
                at = position
                position += 1
                for piece, span in _pieces(line, max_chars):
                    overlap, current, start = [], [piece], at
                    yield make(span)
                reset()
        last_page = page
    if current:
        yield make()


# --- time --------------------------------------------------------------------------------------------------

BUDGET_FRACTION = 0.8  # of S1_READER_MAX_RUN_SECONDS: a queued run starts no part after it


@dataclass(frozen=True)
class Deadline:
    """When a run's AI reads stop starting parts. Inline (inside the upload request): ``AI_INLINE_BUDGET_SECONDS``
    from the start of the run. Queued (the reader): 80% of ``S1_READER_MAX_RUN_SECONDS``. And never a part whose
    worst-case call (timeout and retries) would end after the run's own limit. The type check, the values and the
    facility read of one run share it, counted from the run's start."""

    stop_starting: float
    hard_limit: float
    clock: Callable[[], float]

    def allows(self, worst_case_s: float) -> bool:
        now = self.clock()
        return now < self.stop_starting and now + worst_case_s <= self.hard_limit


def deadline_for(settings: Any, started: float, clock: Callable[[], float]) -> Deadline:
    inline = settings.s1_processing == "inline"
    budget = settings.ai_inline_budget_seconds if inline else BUDGET_FRACTION * settings.s1_reader_max_run_seconds
    return Deadline(started + budget, started + settings.s1_reader_max_run_seconds, clock)


# --- spend ---------------------------------------------------------------------------------------------------

class SpendLedger(Protocol):
    def month_spend_microusd(self, org_id: uuid.UUID) -> int: ...


class Spend:
    """The one monthly limit, checked before every part: this month's spend as the ledger has it (AI and scans,
    so a scan paid while the document is read counts too), and never less than what this read has cost so far."""

    def __init__(self, ledger: SpendLedger, org_id: uuid.UUID, cap_usd: float) -> None:
        self._ledger, self._org_id, self._cap = ledger, org_id, cap_usd
        self.at_start = ledger.month_spend_microusd(org_id)
        self.cost = 0  # micro-USD this read has spent

    def reached(self, *, fresh: bool = True) -> bool:
        spent = self.at_start + self.cost
        if fresh:
            spent = max(spent, self._ledger.month_spend_microusd(self._org_id))
        return ai_usage.cap_reached(spent, self._cap)

    def add(self, reply: Any) -> None:
        self.cost += int(getattr(reply, "cost_microusd", 0) or 0)


def read_in_part(not_read: str, reason: str = LIMIT_REASON) -> str:
    """The warning for a document the read stopped in: ``not_read`` is ``describe_lines`` of what was not read."""

    return f"{READ_IN_PART}: Read in part: {not_read} not read because {reason}."


def not_read(lines: Sequence[DocumentLine], part: Part) -> str:
    """What is left unread when the read stops before ``part``: its own lines to the document's end."""

    return describe_lines(lines[part.start:])
