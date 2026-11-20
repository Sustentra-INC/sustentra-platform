"""Where a quoted passage is printed on a PDF page, from the PDF's own text layer.

The Methodology review keeps, for each suggestion, the words quoted from a document and the
page they were read on. This finds those words on that page so the viewer can highlight them.
Nothing is guessed: a quote is "located" only when its words are printed, in order, on the page
(compared as ``ai_locator.norm`` compares: Unicode NFKC, one kind of quote and dash, case and
whitespace ignored). A quote that is not found (a scanned page with no text layer, words the
PDF splits differently) is reported as not located, never placed approximately.

When the suggestion kept no page, the whole document is searched and the quote must be printed
on exactly one page. Every place a page prints the quote is returned, so a repeated phrase is
not pinned on one of its occurrences.

Pure with respect to the database; reads the file only.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from backend.app.services.ai_locator import norm

MAX_PAGES = 300  # the viewer shows no more (documents.py _MAX_PAGES)
MAX_RECTS = 12  # boxes returned for one quote


@dataclass(frozen=True)
class Placed:
    page: int  # 1-based
    rects: list[dict[str, float]]  # {x, y, w, h}, 0..1 of the page as the viewer draws it


_EDGE = ".,;:!?()[]{}\"'*\u2022\u2026"  # punctuation at a word's edge: a quote may start or stop mid-sentence


def _tokens(text: str) -> list[str]:
    """The words of the text as ``norm`` reads them, without punctuation at their edges ("1,234." is "1,234")."""

    return [word for word in (token.strip(_EDGE) for token in norm(text).split()) if word]


def _word_tokens(words: Sequence[Sequence[Any]]) -> tuple[list[str], list[int]]:
    """Every token of the page's words (a word can fold into several), and the word each came from."""

    tokens: list[str] = []
    owner: list[int] = []
    for index, word in enumerate(words):
        for token in _tokens(str(word[4])):
            tokens.append(token)
            owner.append(index)
    return tokens, owner


def _matches(tokens: list[str], wanted: list[str]) -> list[int]:
    if not wanted or len(wanted) > len(tokens):
        return []
    first = wanted[0]
    return [i for i in range(len(tokens) - len(wanted) + 1)
            if tokens[i] == first and tokens[i:i + len(wanted)] == wanted]


def _page_rects(page: Any, words: Sequence[Sequence[Any]], found: list[tuple[int, int]]) -> list[dict[str, float]]:
    """One box per printed line of each match, as fractions of the page the viewer draws."""

    import fitz

    shown = page.rect
    if shown.width <= 0 or shown.height <= 0:
        return []
    rects: list[dict[str, float]] = []
    for first, last in found:
        by_line: dict[tuple[int, int], Any] = {}
        for word in words[first:last + 1]:
            box = fitz.Rect(word[:4]) * page.rotation_matrix
            key = (int(word[5]), int(word[6]))
            by_line[key] = by_line[key] | box if key in by_line else box
        for box in by_line.values():
            x0, y0 = max(box.x0 - shown.x0, 0.0), max(box.y0 - shown.y0, 0.0)
            x1, y1 = min(box.x1 - shown.x0, shown.width), min(box.y1 - shown.y0, shown.height)
            if x1 > x0 and y1 > y0:
                rects.append({"x": x0 / shown.width, "y": y0 / shown.height,
                              "w": (x1 - x0) / shown.width, "h": (y1 - y0) / shown.height})
    return rects[:MAX_RECTS]


def _on_page(page: Any, wanted: list[str]) -> list[dict[str, float]]:
    words = page.get_text("words")
    tokens, owner = _word_tokens(words)
    starts = _matches(tokens, wanted)
    if not starts:
        return []
    spans: list[tuple[int, int]] = []
    last_end = -1
    for start in starts:
        first, last = owner[start], owner[start + len(wanted) - 1]
        if first > last_end:  # overlapping matches share their words once
            spans.append((first, last))
            last_end = last
    return _page_rects(page, words, spans)


def locate_on_pdf(path: Path, quote: str, page: int | None) -> Placed | None:
    """The quote's place on the PDF, or None when it is not printed there (or the file cannot be read)."""

    wanted = _tokens(quote)
    if not wanted:
        return None
    import fitz

    try:
        with fitz.open(path) as pdf:
            count = min(pdf.page_count, MAX_PAGES)
            if page is not None:
                if not 1 <= page <= count:
                    return None
                rects = _on_page(pdf[page - 1], wanted)
                return Placed(page, rects) if rects else None
            hits = [(n + 1, rects) for n in range(count) if (rects := _on_page(pdf[n], wanted))]
    except Exception:  # an unreadable or encrypted file: the quote is simply not located
        return None
    return Placed(hits[0][0], hits[0][1]) if len(hits) == 1 else None


def sources_on_document(record: Mapping[str, Any], document_id: str) -> list[dict[str, Any]]:
    """The quotes of one stored methodology record that were read from ``document_id``: the
    suggestion's own quote (``entry`` None) and one per list entry (``entry`` its index)."""

    suggestion = record.get("suggestion")
    if not isinstance(suggestion, Mapping):
        return []
    out: list[dict[str, Any]] = []

    def add(item: Mapping[str, Any], entry: int | None) -> None:
        quote = item.get("quote")
        if item.get("document_id") != document_id or not isinstance(quote, str) or not quote.strip():
            return
        reference = item.get("source_reference")
        page = reference.get("page_number") if isinstance(reference, Mapping) else None
        out.append({"entry": entry, "quote": quote,
                    "page": page if isinstance(page, int) and not isinstance(page, bool) and page >= 1 else None})

    evidence = suggestion.get("evidence")
    if isinstance(evidence, list) and evidence:
        for index, item in enumerate(evidence):
            if isinstance(item, Mapping):
                add(item, index)
    else:
        add(suggestion, None)
    return out
