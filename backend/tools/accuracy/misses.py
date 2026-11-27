"""Sort the misses on files with several records (``--sort-misses``, MVP-238).

Each ``missed`` key cell on a document the extractor read into two or more records is sorted into one of:

* ``not_printed``: the value is not in the document's text (nor in its file name);
* ``printed_missed``: it is printed on the record's own rows (``ai_record_fill.record_rows``), so a reader of that
  record could have read it; when the extractor never made the record, or the cell is about no one record, printed
  on any record's own rows;
* ``elsewhere``: it is printed, but not on that record's rows: a header, a title, another page or record, a summary
  row, or the file name.

Deterministic text search on the parser's stored text (no AI): numbers compare as numbers (thousands separators,
currency signs and units ignored), dates as calendar days (the formats ``normalize.parse_date`` reads), ids with case
and punctuation ignored, names and addresses as letters and digits only. Only counts leave this module.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence
from datetime import date

from backend.tools.accuracy.mapping import FAMILIES
from backend.tools.accuracy.model import MISSED, ExtractedDoc, Outcome
from backend.tools.accuracy.normalize import _MONTH_NAMES, norm_id, norm_name, parse_date, parse_number

NOT_PRINTED = "not_printed"
PRINTED_MISSED = "printed_missed"
ELSEWHERE = "elsewhere"
CLASSES = (NOT_PRINTED, PRINTED_MISSED, ELSEWHERE)

_DATES = (
    re.compile(r"\b\d{4}-\d{1,2}-\d{1,2}\b"),
    re.compile(r"\b\d{1,2}[/.-]\d{1,2}[/.-](?:\d{4}|\d{2})\b"),
    re.compile(rf"\b(?:{_MONTH_NAMES})\.?\s+\d{{1,2}}(?:st|nd|rd|th)?,?\s+\d{{4}}\b", re.I),
    re.compile(rf"\b\d{{1,2}}(?:st|nd|rd|th)?\s+(?:{_MONTH_NAMES})\.?,?\s+\d{{4}}\b", re.I),
)
# A number standing on its own: not a piece of an id ("88-1200"), a date or a word ("GEN-1").
_STANDALONE_NUMBER = re.compile(r"(?<![\w.\-/])\$?\d[\d,]*(?:\.\d+)?(?![\w\-/]|\.\d)")
MIN_TOKEN = 3  # an id or name shorter than this is found everywhere: never counted as printed


def kind_of(family: str) -> str:
    spec = FAMILIES.get(family)
    return spec.kind if spec is not None else "name"


def dates_in(text: str) -> set[date]:
    return {d for pattern in _DATES for m in pattern.finditer(text) if (d := parse_date(m.group(0)))}


def printed_in(kind: str, expected: str, texts: Iterable[str]) -> bool:
    """Whether ``expected`` is printed in any of ``texts``, compared the way the family's kind compares."""

    if kind in ("number", "year"):
        wanted = parse_number(expected)
        if wanted is None:
            return False
        return any(parse_number(m.group(0)) == wanted for text in texts for m in _STANDALONE_NUMBER.finditer(text))
    if kind == "date":
        day = parse_date(expected)
        return day is not None and any(day in dates_in(text) for text in texts)
    norm = norm_id if kind == "id" else norm_name
    wanted_text = norm(expected)
    if len(wanted_text) < MIN_TOKEN:
        return False
    return any(wanted_text in norm(text) for text in texts)


def is_multi_record(doc: ExtractedDoc) -> bool:
    return len({i.record for i in doc.items if i.record is not None}) > 1


def sort_miss(outcome: Outcome, doc: ExtractedDoc) -> str:
    kind = kind_of(outcome.family)
    if not printed_in(kind, outcome.expected, doc.line_texts):
        return ELSEWHERE if printed_in(kind, outcome.expected, [_file_words(doc.filename)]) else NOT_PRINTED
    if outcome.record is not None:
        own: Sequence[str] = doc.record_texts.get(outcome.record, ())
    else:
        own = [text for texts in doc.record_texts.values() for text in texts]
    return PRINTED_MISSED if printed_in(kind, outcome.expected, own) else ELSEWHERE


def _file_words(filename: str) -> str:
    return re.sub(r"[_]+", " ", filename.rsplit(".", 1)[0])


def sort_misses(outcomes: Iterable[Outcome], docs: dict[str, ExtractedDoc]) -> dict[str, dict[str, int]]:
    """Per family, the misses on multi-record files counted by class (counts only)."""

    counts: dict[str, Counter[str]] = defaultdict(Counter)
    for outcome in outcomes:
        doc = docs.get(outcome.filename)
        if outcome.status != MISSED or doc is None or not is_multi_record(doc):
            continue
        counts[outcome.family][sort_miss(outcome, doc)] += 1
    return {family: {c: counts[family][c] for c in CLASSES} for family in sorted(counts)}


def record_fields(docs: dict[str, ExtractedDoc]) -> dict[str, int]:
    """Over the multi-record files: record-level fields, how many are empty, how many Sustentra's AI filled."""

    out = Counter({"files": 0, "fields": 0, "empty": 0, "ai_filled": 0})
    for doc in docs.values():
        if not is_multi_record(doc):
            continue
        out["files"] += 1
        for item in doc.items:
            if item.record is None:
                continue
            out["fields"] += 1
            out["empty"] += int(not item.has_value)
            out["ai_filled"] += int(item.has_value and "ai_suggested" in item.flags)
    return dict(out)


def render_sort(name: str, sorted_misses: dict[str, dict[str, int]], fields: dict[str, int] | None = None) -> str:
    lines = [f"== {name}: misses on multi-record files ==",
             f"{'family':<24} {'not_printed':>11} {'printed_missed':>14} {'elsewhere':>9}"]
    total: Counter[str] = Counter()
    for family, c in sorted_misses.items():
        lines.append(f"{family:<24} {c[NOT_PRINTED]:>11} {c[PRINTED_MISSED]:>14} {c[ELSEWHERE]:>9}")
        total.update(c)
    lines.append(f"{'ALL':<24} {total[NOT_PRINTED]:>11} {total[PRINTED_MISSED]:>14} {total[ELSEWHERE]:>9}")
    if fields:
        lines.append(f"record fields on {fields['files']} multi-record files: {fields['fields']}, empty {fields['empty']}, "
                     f"filled by Sustentra's AI {fields['ai_filled']}")
    return "\n".join(lines)
