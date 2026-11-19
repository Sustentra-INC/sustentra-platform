"""What a bill says about itself besides its numbers: that a read was estimated, and that it revises an earlier bill.

Two signals the reviewer needs, found in the bill's own words (EXT-025). Neither changes a value:

- **Estimated read.** The utility could not read the meter and billed an estimate. A bill says so in a
  sentence ("This bill is based on an ESTIMATED read"), under an "ESTIMATED READ" heading, or in a read-type
  column of the meter table ("Read Type": "Estimated", "Estimate", "EST"; or "E" / "853,925 (E)" with a legend
  "E = Estimated read"). An "E" always needs its legend. The quantity then carries the ``estimated_read`` flag,
  which the review screen words as "Estimated read". Fee schedules, conditions ("if we estimate your read"),
  dates ("estimated reading date") and "not applicable" are not estimated reads.
- **Revised bill.** The bill is headed "REVISED STATEMENT" / "CORRECTED BILL", or says "This statement replaces
  the statement dated 04/04/2025". The reference (the earlier bill's number, or its date) is kept so the data
  quality check can suggest marking the earlier bill as superseded. That stays a suggestion. Boilerplate
  ("a corrected bill will be issued if an error is found", "pay this revised statement") is not a revision.

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

# --- estimated reads -----------------------------------------------------------------------
# A read-type column heading ("Read Type", "Reading Code", "Type of read"), as a cell or a label before a value.
_READ_TYPE_HEADER = re.compile(
    r"\b(?:read(?:ing)?\s+(?:type|code|status|method)|type\s+of\s+read(?:ing)?|meter\s+read\s+type)\b", re.I)
# A heading over reads ("Read", "Current Read", "Reading"): enough for an "E" marker, together with a legend.
_READ_HEADING = re.compile(r"^(?:(?:meter|current|present|previous|prior)\s+)?read(?:ing)?s?$", re.I)
_ESTIMATED_WORD = re.compile(r"^(?:estimated|estimate|est\.?)$", re.I)
# "Read Type: Estimated" / "Read Type: E" in one cell.
_READ_TYPE_VALUE = re.compile(
    r"^\W*(?:read(?:ing)?\s+(?:type|code|status|method)|type\s+of\s+read(?:ing)?)\s*[:=\-]\s*"
    r"(?P<value>estimated|estimate|est\.?|e)\W*$", re.I)
_ESTIMATED_MARK = re.compile(r"^\(?E\)?$|^\d[\d,]*(?:\.\d+)?\s*\(?E\)?$")  # "E", "(E)", a read "853,925 E" / "853,925 (E)"
# A legend: "E = Estimated read", "A = Actual, E = Estimated".
_LEGEND = re.compile(r"(?:^|[\s,;(])E\s*[=:\-]\s*estimat", re.I)
_STATEMENT = re.compile(
    r"\b(?:bill|statement|usage|reading|read|charges)\s+(?:is|was|has\s+been|are|were)\s+(?:based\s+on\s+)?"
    r"(?:an?\s+|the\s+)?(?:an?\s+)?estimat", re.I)
_HEADING = re.compile(r"^\W*ESTIMATED (?:READ|READING|BILL)\W*$")  # an upper-case heading, not a column title
_NEGATED = re.compile(r"\b(?:not|no|never|isn't|wasn't|without)\b[^.]{0,30}\bestimat", re.I)
# Words that make a sentence a condition, a fee, a date or a non-answer, not a statement about this bill.
_NOT_A_STATEMENT = re.compile(
    r"\b(?:if|may|might|when|whenever|unless|should|could|would|fee|fees|charge|charges|rate|date|n/a|"
    r"not\s+applicable|policy|will\s+be|can\s+be)\b|\$|\d{1,2}/\d{1,2}", re.I)
_SENTENCES = re.compile(r"(?<!\b[Nn]o\.)(?<=[.!?;])\s+")  # not after "No."


@dataclass
class EstimatedReads:
    statement: bool = False  # the bill says, in a sentence or a heading, that a read was estimated
    marked_rows: list[Any] = field(default_factory=list)  # rows whose read-type cell says estimated

    def any(self) -> bool:
        return self.statement or bool(self.marked_rows)


def _is_statement(text: str) -> bool:
    if _HEADING.match(text.strip()):
        return True
    for sentence in _SENTENCES.split(text):
        if (_STATEMENT.search(sentence) and not _NEGATED.search(sentence)
                and not _NOT_A_STATEMENT.search(sentence)):
            return True
    return False


def estimated_reads(rows: Sequence[Any]) -> EstimatedReads:
    """Where the bill says a read was estimated. Never raises: a bill with no such words gives nothing."""

    texts = [(row, [" ".join(cell.text.split()) for cell in row.cells]) for row in rows]
    joined = [(row, " ".join(cells)) for row, cells in texts]
    has_legend = any(_LEGEND.search(text) for _, text in joined)
    has_type_header = any(_READ_TYPE_HEADER.search(text) for _, text in joined)
    has_read_heading = has_legend and any(_READ_HEADING.match(c) for _, cells in texts for c in cells)
    found = EstimatedReads()
    for (row, cells), (_, text) in zip(texts, joined):
        if not _LEGEND.search(text) and _is_statement(text):
            found.statement = True
        for value in cells:
            labelled = _READ_TYPE_VALUE.match(value)
            word = _ESTIMATED_WORD.match(value) and has_type_header
            mark = has_legend and (has_type_header or has_read_heading) and _ESTIMATED_MARK.search(value)
            if labelled is not None and (labelled.group("value").lower() != "e" or has_legend):
                found.marked_rows.append(row)
                break
            if word or mark:
                found.marked_rows.append(row)
                break
    return found


# --- revised bills -------------------------------------------------------------------------
# A heading of its own: "REVISED STATEMENT", "CORRECTED BILL", "REVISED", a short cell.
_REVISED_HEADING = re.compile(
    r"^\W*(?:revised|corrected|amended|replacement|restated)(?:\s+(?:statement|bill|invoice))?\W*$", re.I)
# A sentence that begins "This bill replaces ..." / "Replaces the statement dated ...".
_REPLACES = re.compile(
    r"^\W*(?:this\s+(?:revised\s+|corrected\s+)?(?:statement|bill|invoice)\s+)?"
    r"(?:replaces|replacing|supersedes|superseding|corrects|amends|revises|is\s+a\s+revision\s+of|"
    r"cancels\s+and\s+replaces)\b\s+(?:the\s+|our\s+|an?\s+)?(?:earlier\s+|original\s+|previous\s+|prior\s+)?"
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


@dataclass
class Revision:
    reference: str  # the earlier bill's number or date as printed, or REVISED_WITHOUT_REFERENCE
    row: Any
    cell: Any


def revision(rows: Sequence[Any]) -> Revision | None:
    """The earlier bill this one replaces, or that it is a revised bill, from its own words: a heading, or a
    sentence that begins "This bill replaces ...". Boilerplate that merely mentions a revision does not count."""

    marked: Revision | None = None
    for row in rows:
        for cell in row.cells:
            text = " ".join(cell.text.split())
            for sentence in _SENTENCES.split(text):
                if len(sentence) <= 40 and _REVISED_HEADING.match(sentence) and marked is None:
                    marked = Revision(REVISED_WITHOUT_REFERENCE, row, cell)
                hit = _REPLACES.match(sentence)
                if hit is None:
                    continue
                tail = sentence[hit.end():hit.end() + _REF_WINDOW]
                lead = _REF_LEAD.match(tail)
                rest = tail[lead.end():] if lead else tail
                found = _DATE_REF.match(rest) or _ID_REF.match(rest)
                if found is not None:
                    return Revision(found.group(0).strip(" .,;:"), row, cell)
                if marked is None:
                    marked = Revision(REVISED_WITHOUT_REFERENCE, row, cell)
    return marked
