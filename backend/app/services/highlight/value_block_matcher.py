"""Map an extracted value back to the Textract block(s) that produced it (step C).

The value came from an LLM reading the page text; Textract gives geometry per
WORD/LINE. This module finds the block(s) whose text produced the value and
unions their boxes into one span, in normalized {x,y,w,h} fractions.

THE CONFIDENCE GATE IS THE POINT. A box in the wrong place is worse than no box
in a traceability product, so:
  * a numeric value matches only on an EXACT canonical-number equality (not a
    substring — "400" never matches inside "182,400");
  * when a value appears more than once on a page, we disambiguate with the
    LLM's source snippet, and if that does not yield a single clear winner we
    return None;
  * a value the LLM derived rather than read verbatim will not be found on the
    page, so it returns None;
  * any uncertainty returns None. The caller's fallback (open at the page, show
    the snippet, say the highlight is unavailable) is the correct behaviour.
"""

from __future__ import annotations

import re
from typing import Any

from backend.app.services.highlight.textract_geometry import (
    BBox,
    LineBlock,
    WordBlock,
    union_boxes,
)

_NUMERIC_WORD = re.compile(r"^[-+]?[\d., ]*\d[\d., ]*$")
_NUM_CORE = re.compile(r"[-+]?\d[\d.,  ]*\d|\d")


def canonical_number(raw: Any) -> str | None:
    """Canonicalize a number so thousands separators and decimal conventions do
    not defeat equality. Returns a string like "182400" or "0.223", or None."""

    if raw is None:
        return None
    match = _NUM_CORE.search(str(raw))
    if not match:
        return None
    core = match.group().replace(" ", "").replace(" ", "")
    has_comma = "," in core
    has_dot = "." in core

    if has_comma and has_dot:
        # The rightmost separator is the decimal point.
        if core.rfind(",") > core.rfind("."):
            core = core.replace(".", "").replace(",", ".")  # 182.400,50 -> 182400.50
        else:
            core = core.replace(",", "")  # 182,400.50 -> 182400.50
    elif has_comma:
        parts = core.split(",")
        if len(parts) > 1 and all(len(p) == 3 for p in parts[1:]) and 1 <= len(parts[0]) <= 3:
            core = core.replace(",", "")  # 182,400 -> thousands
        else:
            core = core.replace(",", ".")  # 0,223 -> decimal
    elif core.count(".") > 1:
        core = core.replace(".", "")  # 1.182.400 -> dot thousands

    try:
        value = float(core)
    except ValueError:
        return None
    if value.is_integer():
        return str(int(value))
    return ("%f" % value).rstrip("0").rstrip(".")


def _norm_text(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", s.lower())).strip()


def _norm_tokens(s: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", s.lower())


def _is_numeric_word(text: str) -> bool:
    stripped = re.sub(r"[$€£%]", "", text.strip())
    return bool(stripped) and bool(_NUMERIC_WORD.match(stripped))


def _is_pure_number(s: str) -> bool:
    """A value we should match numerically — not an alphanumeric code like E-19
    or a phrase. Currency and percent are allowed; letters are not."""

    t = re.sub(r"[$€£%\s]", "", s.strip())
    return bool(t) and bool(re.fullmatch(r"[-+]?[\d.,]*\d[\d.,]*", t))


class _Candidate:
    __slots__ = ("bbox", "line_text", "word_ids", "kind")

    def __init__(self, bbox: BBox, line_text: str, word_ids: list[str], kind: str) -> None:
        self.bbox = bbox
        self.line_text = line_text
        self.word_ids = word_ids
        self.kind = kind


def _numeric_candidates(line: LineBlock, target: str) -> list[_Candidate]:
    out: list[_Candidate] = []
    words = line.words
    if not words:
        # No word geometry: only usable if the whole line reduces to exactly the
        # target number (otherwise we cannot say which number it is).
        if canonical_number(line.text) == target and len(_NUM_CORE.findall(line.text)) == 1:
            out.append(_Candidate(line.bbox, line.text, [line.block_id], "line_only"))
        return out

    # Single words that equal the target.
    for w in words:
        if _is_numeric_word(w.text) and canonical_number(w.text) == target:
            out.append(_Candidate(w.bbox, line.text, [w.block_id], "word"))

    # Maximal runs of numeric-ish words concatenated (value split across words).
    i = 0
    while i < len(words):
        if not _is_numeric_word(words[i].text):
            i += 1
            continue
        j = i
        run: list[WordBlock] = []
        while j < len(words) and _is_numeric_word(words[j].text):
            run.append(words[j])
            j += 1
        if len(run) > 1:
            joined = "".join(w.text for w in run)
            if canonical_number(joined) == target:
                box = union_boxes([w.bbox for w in run])
                if box is not None:
                    out.append(_Candidate(box, line.text, [w.block_id for w in run], "word_run"))
        i = j
    return out


def _text_candidates(line: LineBlock, target_text: str) -> list[_Candidate]:
    if not target_text:
        return []
    if target_text not in _norm_text(line.text):
        return []
    words = line.words
    if not words:
        # Only trust a line-level box when the whole line IS the phrase.
        if _norm_text(line.text) == target_text:
            return [_Candidate(line.bbox, line.text, [line.block_id], "line_only")]
        return []
    # Find the consecutive word subsequence whose normalized text is the target.
    norm_words = [_norm_text(w.text) for w in words]
    target_seq = target_text.split(" ")
    for start in range(len(words)):
        acc: list[str] = []
        chosen: list[WordBlock] = []
        for k in range(start, len(words)):
            if not norm_words[k]:
                continue
            acc.append(norm_words[k])
            chosen.append(words[k])
            if acc == target_seq:
                box = union_boxes([w.bbox for w in chosen])
                if box is not None:
                    return [_Candidate(box, line.text, [w.block_id for w in chosen], "word_phrase")]
            if len(acc) >= len(target_seq):
                break
    return []


def _disambiguate(cands: list[_Candidate], source_snippet: str | None) -> _Candidate | None:
    if len(cands) == 1:
        return cands[0]
    if not source_snippet:
        return None  # repeated value, no snippet -> cannot place it safely
    snip = set(_norm_tokens(source_snippet))
    if not snip:
        return None
    scored = sorted(
        cands,
        key=lambda c: len(set(_norm_tokens(c.line_text)) & snip),
        reverse=True,
    )
    top = len(set(_norm_tokens(scored[0].line_text)) & snip)
    second = len(set(_norm_tokens(scored[1].line_text)) & snip)
    if top > 0 and top > second:
        return scored[0]
    return None  # no clear winner -> null


def match_value_to_span(
    *,
    value: Any,
    unit: str | None,
    source_snippet: str | None,
    page_number: int | None,
    page_lines: dict[int, list[LineBlock]],
) -> dict[str, Any] | None:
    """Return {"page_number", "bounding_box": {x,y,w,h}, "match_kind", "word_ids"}
    for a confident match, else None."""

    if page_number is None:
        # Without a page we would have to search all pages and disambiguate
        # across them — too weak to be safe. Return None.
        return None
    lines = page_lines.get(int(page_number), [])
    if not lines:
        return None

    value_str = "" if value is None else str(value)
    candidates: list[_Candidate] = []
    if _is_pure_number(value_str):
        target_number = canonical_number(value_str)
        if target_number is None:
            return None
        for line in lines:
            candidates.extend(_numeric_candidates(line, target_number))
    else:
        target_text = _norm_text(value_str)
        for line in lines:
            candidates.extend(_text_candidates(line, target_text))

    if not candidates:
        return None

    chosen = _disambiguate(candidates, source_snippet)
    if chosen is None:
        return None
    return {
        "page_number": int(page_number),
        "bounding_box": chosen.bbox.as_dict(),
        "match_kind": chosen.kind,
        "word_ids": chosen.word_ids,
    }
