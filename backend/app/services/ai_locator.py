"""Locate an AI-suggested value on the document, using only the parser's own text.

The model sees the document as numbered lines (``document_lines``: "L1", "L2", ... in
parser order) and answers with a value, the line it read it from and a short quote of
that line. It is never shown coordinates and nothing it returns is used as one: the
highlight, page, sheet and cell all come from the parser's source_reference for the line.

A suggestion is kept only when

1. its quote is printed on the line it cites (compared after ``norm``: Unicode NFKC,
   one kind of quote and dash, case and whitespace ignored). If the cited line is unknown
   the suggestion is dropped; if the quote is not on the cited line it is accepted only
   when it is printed on exactly one other line;
2. its value is printed inside that quote as a whole token, by the deterministic
   extractor's rule (``ExtractionCandidateService.has_token``: "12" is not found in
   "112" or "1,200"; "1,915.3" and "1915.3" are the same number).

Anything else is dropped with a reason, never guessed. Pure functions: no I/O, no model
call, inputs are not modified.
"""

from __future__ import annotations

import copy
import dataclasses
import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from backend.app.adapters.parsers.base import snippet, to_reference_box
from backend.app.services.extraction_candidate_service import ExtractionCandidateService

DropReason = Literal["empty_value", "unknown_line", "quote_not_on_document", "ambiguous_quote", "value_not_in_quote"]

# Applied after NFKC, which already folds full-width forms.
_QUOTES = str.maketrans({c: "'" for c in "\u2018\u2019\u201a\u201b\u2032"}
                        | {c: '"' for c in "\u201c\u201d\u201e\u201f\u00ab\u00bb"})
_DASHES = re.compile("[\u2010-\u2015\u2212]")  # hyphens, en/em dashes, minus sign
ROW_SEPARATOR = " | "
ROW_MAX_CHARS = 2_000  # a longer sheet row is shown as several lines, cut between cells
_CELL = re.compile(r"\$?([A-Za-z]{1,3})\$?(\d+)")


@dataclass(frozen=True)
class DocumentLine:
    """One parser text block, as the model is shown it."""

    alias: str  # "L1", "L2", ... in parser order
    text: str
    page_number: int | None
    block_id: str
    # The parser's own reference for the block, shaped by contracts/source_reference.schema.json.
    source_reference: dict[str, Any]


@dataclass(frozen=True)
class RowLine(DocumentLine):
    """A sheet row (or a piece of a long one) as one line: its cells, left to right, joined by
    ``ROW_SEPARATOR``. ``cells`` are the cell lines it was built from, each with its own reference."""

    cells: tuple[DocumentLine, ...] = ()


@dataclass(frozen=True)
class Suggestion:
    """What the model answered. There is deliberately no page, box or cell here."""

    value: str
    quote: str
    line: str | None = None  # the alias it cites, e.g. "L17"

    @classmethod
    def from_model(cls, answer: Mapping[str, Any]) -> Suggestion:
        """Only ``value``, ``quote`` and ``line`` are read; any other key (a page, a box) is ignored."""
        line = answer.get("line")
        return cls(value=str(answer.get("value") or ""), quote=str(answer.get("quote") or ""),
                   line=str(line) if line else None)


@dataclass(frozen=True)
class Located:
    line: DocumentLine
    # A deep copy of the parser's reference for that line; text_snippet is the line text.
    source_reference: dict[str, Any]


@dataclass(frozen=True)
class NotLocated:
    reason: DropReason


def norm(text: str) -> str:
    """Compare text as printed: NFKC, one kind of quote and dash, casefolded, single spaces."""
    text = unicodedata.normalize("NFKC", text).translate(_QUOTES)
    return " ".join(_DASHES.sub("-", text).casefold().split())


def document_lines(parser_output: Mapping[str, Any]) -> list[DocumentLine]:
    """The parser's text blocks as numbered lines, each tied to its parser source_reference.

    One line per text block: a visual line for PDFs and Textract, a cell for workbooks, a
    row for CSV. Blank blocks are skipped and get no number.
    """
    document_id = str(parser_output.get("document_id") or "")
    references = {
        reference["source_reference_id"]: reference
        for reference in parser_output.get("source_references") or []
        if isinstance(reference, Mapping) and reference.get("source_reference_id")
    }
    lines: list[DocumentLine] = []
    for block in parser_output.get("text_blocks") or []:
        if not isinstance(block, Mapping) or not block.get("block_id"):
            continue
        text = " ".join(str(block.get("text") or "").split())
        if not text:
            continue
        reference = _contract_reference(block, references.get(block.get("source_reference_id") or ""), document_id)
        reference["text_snippet"] = snippet(text)
        page = block.get("page_number") or reference.get("page_number")
        lines.append(DocumentLine(alias=f"L{len(lines) + 1}", text=text, page_number=page,
                                  block_id=str(block["block_id"]), source_reference=reference))
    return lines


def row_lines(parser_output: Mapping[str, Any]) -> list[DocumentLine]:
    """``document_lines`` with each workbook row as one line (a ``RowLine``) instead of one line per cell.

    A cell is a block whose reference has a sheet name and a single-cell address ("B7"); the cells of
    one sheet row are joined left to right. Every other block (PDF, Word, CSV, email, a merged range)
    stays the line ``document_lines`` gives. Cells are never merged across rows or sheets, so two
    sheets with the same row numbers stay apart. Only the AI extraction reads this; ``locate_cell``
    then finds the one cell a value is printed in."""
    rows: dict[tuple[str, int], list[tuple[int, DocumentLine]]] = {}
    order: list[DocumentLine | tuple[str, int]] = []
    for line in document_lines(parser_output):
        sheet = line.source_reference.get("sheet_name")
        address = _CELL.fullmatch(str(line.source_reference.get("cell_or_range") or "").strip())
        if not sheet or address is None:
            order.append(line)
            continue
        key = (str(sheet), int(address.group(2)))
        if key not in rows:
            rows[key] = []
            order.append(key)
        rows[key].append((_column(address.group(1)), line))
    lines: list[DocumentLine] = []
    for item in order:
        if isinstance(item, DocumentLine):
            lines.append(dataclasses.replace(item, alias=f"L{len(lines) + 1}"))
            continue
        for chunk in _chunks([cell for _, cell in sorted(rows[item], key=lambda pair: pair[0])]):
            text = ROW_SEPARATOR.join(cell.text for cell in chunk)
            lines.append(RowLine(alias=f"L{len(lines) + 1}", text=text, page_number=None, block_id=chunk[0].block_id,
                                 source_reference=copy.deepcopy(chunk[0].source_reference), cells=tuple(chunk)))
    return lines


def _column(letters: str) -> int:
    number = 0
    for letter in letters.upper():
        number = number * 26 + ord(letter) - 64
    return number


def _chunks(cells: Sequence[DocumentLine]) -> list[list[DocumentLine]]:
    chunks: list[list[DocumentLine]] = []
    size = 0
    for cell in cells:
        if chunks and size + len(ROW_SEPARATOR) + len(cell.text) <= ROW_MAX_CHARS:
            chunks[-1].append(cell)
            size += len(ROW_SEPARATOR) + len(cell.text)
        else:
            chunks.append([cell])
            size = len(cell.text)
    return chunks


def locate_cell(row: RowLine, quote: str, value: str) -> DocumentLine | NotLocated:
    """The one cell of ``row`` that holds ``value``, given a quote already found on the row.

    The value must be printed as a whole token inside one cell, in the part of that cell the quote
    covers (never across cells, whatever the cell text contains). If the quote covers the value in
    more than one cell, or the quote is on the row more than once with different cells, it is
    ambiguous and dropped."""
    wanted = norm(quote)
    pieces = [norm(cell.text) for cell in row.cells]
    full = ROW_SEPARATOR.join(pieces)
    if not wanted or full != norm(row.text):
        return NotLocated("ambiguous_quote")
    spans: list[tuple[int, int]] = []
    start = 0
    for piece in pieces:
        spans.append((start, start + len(piece)))
        start += len(piece) + len(ROW_SEPARATOR)
    holders: set[int] = set()
    at = full.find(wanted)
    while at != -1:
        end = at + len(wanted)
        for index, (low, high) in enumerate(spans):
            if low < end and at < high and value_in_quote(value, full[max(at, low):min(end, high)]) \
                    and value_in_quote(value, pieces[index]):
                holders.add(index)
        at = full.find(wanted, at + 1)
    if not holders:
        return NotLocated("value_not_in_quote")
    if len(holders) > 1:
        return NotLocated("ambiguous_quote")
    return row.cells[holders.pop()]


def locate_quote(quote: str, line_alias: str | None, lines: Sequence[DocumentLine]) -> DocumentLine | NotLocated:
    """The line the quote was read from (rule 1 in the module docstring)."""
    wanted = norm(quote)
    if not wanted:
        return NotLocated("quote_not_on_document")
    cited: DocumentLine | None = None
    if line_alias is not None:
        cited = next((line for line in lines if line.alias == line_alias.strip().upper()), None)
        if cited is None:
            return NotLocated("unknown_line")
        if wanted in norm(cited.text):
            return cited
    others = [line for line in lines if line is not cited and wanted in norm(line.text)]
    if len(others) == 1:
        return others[0]
    return NotLocated("ambiguous_quote" if others else "quote_not_on_document")


def value_in_quote(value: str, quote: str) -> bool:
    """Rule 2: the value is printed in the quote as a whole token."""
    wanted = norm(value)
    if not wanted:
        return False
    text = norm(quote)
    needles = dict.fromkeys([wanted, wanted.replace(",", "")])
    return any(ExtractionCandidateService.has_token(text, needle) for needle in needles if needle)


def locate(suggestion: Suggestion, lines: Sequence[DocumentLine]) -> Located | NotLocated:
    """Where on the document the suggested value is printed, from the parser's geometry only."""
    if not norm(suggestion.value):
        return NotLocated("empty_value")
    line = locate_quote(suggestion.quote, suggestion.line, lines)
    if isinstance(line, NotLocated):
        return line
    if not value_in_quote(suggestion.value, suggestion.quote):
        return NotLocated("value_not_in_quote")
    return Located(line=line, source_reference=copy.deepcopy(line.source_reference))


def _contract_reference(block: Mapping[str, Any], parser_reference: Mapping[str, Any] | None,
                        document_id: str) -> dict[str, Any]:
    """The parser's reference for ``block``, cut to the keys contracts/source_reference.schema.json
    allows (it has additionalProperties: false, so e.g. the parser's source_kind is left out).
    A block without a reference gets an inline one, as ExtractionCandidateService does."""
    block_id = str(block["block_id"])
    source = copy.deepcopy(dict(parser_reference)) if parser_reference else {}
    page = source.get("page_number")
    reference: dict[str, Any] = {
        "source_reference_id": source.get("source_reference_id") or f"inline::{document_id}::{block_id}",
        "document_id": source.get("document_id") or document_id,
        "page_number": page if page is not None else block.get("page_number"),
        "sheet_name": source.get("sheet_name"),
        "cell_or_range": source.get("cell_or_range"),
        "text_snippet": source.get("text_snippet"),
        # Blocks use {left, top, ...} and references {x, y, ...}; to_reference_box reads both.
        "bounding_box": to_reference_box(source.get("bounding_box") or block.get("bounding_box")),
        "parser_block_ids": list(source.get("parser_block_ids") or [block_id]),
    }
    if "record_key" in source:
        reference["record_key"] = source["record_key"]
    return reference
