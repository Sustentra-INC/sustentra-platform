"""What a bill says about itself besides its numbers: that a read was estimated, and that it revises an earlier bill.

Two signals the reviewer needs, found in the bill's own words (EXT-025). Neither changes a value:

- **Estimated read.** The utility could not read the meter and billed an estimate. A bill says so in a
  sentence ("This bill is based on an ESTIMATED read"), or in a read-type column of the meter table
  ("Read Type": "Estimated", "EST", or "E" with a legend "E = Estimated read"). The quantity then carries the
  ``estimated_read`` flag, which the review screen words as "Estimated read".
- **Revised bill.** The bill says it replaces, corrects or supersedes an earlier bill ("This statement replaces
  the statement dated 04/04/2025"). The reference (the earlier bill's number, or its date) is kept so the data
  quality check can suggest marking the earlier bill as superseded. That stays a suggestion.

Pure functions over the extractor's rows (``cells`` with ``text``, ``block_id``); no I/O.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Sequence

ESTIMATED_FLAG = "estimated_read"
REVISES_FIELD = "supersedes_reference"
REVISES_LABEL = "Replaces an earlier bill"
REVISED_WITHOUT_REFERENCE = "revised"

# A read-type column heading ("Read Type", "Reading Code", "Type of read").
_READ_TYPE_HEADER = re.compile(
    r"\b(?:read(?:ing)?\s+(?:type|code|status|method)|type\s+of\s+read(?:ing)?|meter\s+read\s+type)\b", re.I)
_ESTIMATED_CELL = re.compile(r"^(?:estimated|estimate|est\.?)$", re.I)
_ESTIMATED_MARK = re.compile(r"^\(?E\)?$|\d\s+E$")  # "E", or a read printed as "853,925 E"
# A legend: "E = Estimated read", "A = Actual, E = Estimated".
_LEGEND = re.compile(r"(?:^|[\s,;(])E\s*[=:\-]\s*estimat", re.I)
_STATEMENT = re.compile(
    r"\bestimated\s+(?:meter\s+)?read(?:ing)?s?\b"
    r"|\b(?:this\s+)?(?:bill|statement|usage|reading)\s+(?:is|was|has\s+been)\s+(?:based\s+on\s+)?(?:an?\s+)?estimat"
    r"|\bestimated\s+bill\b", re.I)
_NEGATED = re.compile(r"\b(?:not|no|never|isn't|wasn't|without)\b[^.]{0,30}\bestimat", re.I)

_REVISED = re.compile(
    r"\b(?:revised|corrected|amended|replacement|restated)\s+(?:statement|bill|invoice)\b"
    r"|\b(?:statement|bill|invoice)\s*\(?\s*(?:revised|corrected|amended)\s*\)?", re.I)
_REPLACES = re.compile(
    r"\b(?:replaces|replacing|supersedes|superseding|corrects|amends|revises|revision\s+of|in\s+place\s+of)\b"
    r"\s+(?:the\s+|our\s+|an?\s+)?(?:earlier\s+|original\s+|previous\s+|prior\s+)?"
    r"(?:statement|bill|invoice)\b", re.I)
_DATE_REF = re.compile(
    r"\b\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}\b|\b\d{4}-\d{2}-\d{2}\b"
    r"|\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},?\s+\d{4}\b"
    r"|\b\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.?,?\s+\d{4}\b", re.I)
_ID_REF = re.compile(r"(?=[A-Za-z0-9#-]*\d)[A-Za-z0-9#][\w-]{2,}(?![\w-])")
_REF_WINDOW = 48  # how far after "replaces the statement" its date or number may stand
# The words that introduce the reference: "the statement dated 04/04/2025", "bill no. 3348-0042".
_REF_LEAD = re.compile(r"\s*(?:(?:dated|of|from|issued(?:\s+on)?|no\.?|number|num\.?|#|ref\.?|reference|id)\s*:?\s*)?",
                       re.I)
_DATE_REF_START = re.compile(_DATE_REF.pattern, re.I)
_ID_REF_START = _ID_REF


@dataclass
class EstimatedReads:
    statement: bool = False  # the bill says, in a sentence, that a read was estimated
    marked_rows: list[Any] = field(default_factory=list)  # rows whose read-type cell says estimated

    def any(self) -> bool:
        return self.statement or bool(self.marked_rows)


@dataclass
class Revision:
    reference: str  # the earlier bill's number or date as printed, or REVISED_WITHOUT_REFERENCE
    row: Any
    cell: Any


def estimated_reads(rows: Sequence[Any]) -> EstimatedReads:
    """Where the bill says a read was estimated. Never raises: a bill with no such words gives nothing."""

    texts = [(row, " ".join(cell.text for cell in row.cells)) for row in rows]
    has_header = any(_READ_TYPE_HEADER.search(text) for _, text in texts)
    has_legend = any(_LEGEND.search(text) for _, text in texts)
    found = EstimatedReads()
    for row, text in texts:
        if not _LEGEND.search(text) and _STATEMENT.search(text) and not _NEGATED.search(text):
            found.statement = True
        if not has_header:
            continue  # a bare "EST" or "E" is only a read type under a read-type heading
        for cell in row.cells:
            value = " ".join(cell.text.split())
            if _ESTIMATED_CELL.match(value) or (has_legend and _ESTIMATED_MARK.search(value)):
                found.marked_rows.append(row)
                break
    return found


def revision(rows: Sequence[Any]) -> Revision | None:
    """The earlier bill this one replaces, or that it is a revised bill, from its own words."""

    marked: Revision | None = None
    for row in rows:
        for cell in row.cells:
            text = " ".join(cell.text.split())
            hit = _REPLACES.search(text)
            if hit is not None:
                tail = text[hit.end():hit.end() + _REF_WINDOW]
                lead = _REF_LEAD.match(tail)
                rest = tail[lead.end():] if lead else tail
                found = _DATE_REF_START.match(rest) or _ID_REF_START.match(rest)
                if found is not None:
                    return Revision(found.group(0).strip(" .,;:"), row, cell)
                if marked is None:
                    marked = Revision(REVISED_WITHOUT_REFERENCE, row, cell)
            elif marked is None and _REVISED.search(text):
                marked = Revision(REVISED_WITHOUT_REFERENCE, row, cell)
    return marked
