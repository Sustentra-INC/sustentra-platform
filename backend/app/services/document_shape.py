"""What a document looks like, apart from what it says: a note from a person is not a bill.

A bill, a log or a statement states its quantities in labelled rows or table cells. A note (a
letter, a memo, an email body) states them inside sentences: "In February we used 4,120 therms".
Those numbers are what someone says they used, not source evidence, so a document of that shape
is never read as a fuel, electricity, refrigerant or thermal record, however many quantities and
dates it quotes.
"""

from __future__ import annotations

import re
from typing import Any

NOT_EVIDENCE_MESSAGE = (
    "This reads as a note written by a person, not a bill, a log or a record, so its numbers are not "
    "used as evidence. If it is one of those, set the document type."
)

# Memo and email header lines: they are labelled, but they do not make a document structured.
_HEADER_LABELS = {"to", "from", "cc", "bcc", "date", "re", "subject", "sent", "attn", "attention", "regarding"}
_LABEL_ROW = re.compile(r"^(?P<label>[^\W\d_][\w #/().&'-]{0,30}?)\s*:\s*\S")
_GAP = re.compile(r"\t|\s{3,}")
_GREETING = re.compile(
    r"^(hi|hello|hey|dear|good (morning|afternoon)|hallo|guten tag|sehr geehrte|bonjour|hola|buongiorno|"
    r"お世話になっております|拝啓|各位|您好)", re.I)
_SIGN_OFF = re.compile(
    r"^(thanks|thank you|regards|kind regards|best|best regards|sincerely|cheers|let me know|danke|"
    r"viele gr|mit freundlichen gr|merci|cordialement|gracias|saludos|grazie|よろしくお願い|敬具|此致)", re.I)
_MIN_LINES = 4
_MIN_SENTENCES = 3


def _is_sentence(line: str) -> bool:
    """A long, punctuated line of running text (a line of Chinese or Japanese has few or no spaces)."""

    words = len(line.split())
    long_enough = words >= 8 or (words <= 2 and len(line) >= 20)
    return long_enough and (line[-1] in ".!?。！？" or ", " in line or any(c in line for c in "、，"))


def looks_like_a_note(parser_output: dict[str, Any]) -> bool:
    """Whether the document is prose from a person: sentences, a greeting or sign-off or a memo
    header, and no labelled rows, columns, tables or sheet cells that a record would have."""

    if parser_output.get("tables") or parser_output.get("key_value_pairs"):
        return False
    if any(isinstance(r, dict) and r.get("sheet_name") for r in parser_output.get("source_references") or []):
        return False
    lines: list[str] = []
    for block in parser_output.get("text_blocks") or []:
        if isinstance(block, dict):
            if block.get("bounding_box"):
                return False  # a laid-out page (a PDF or a scan), not running text
            lines.extend(line.strip() for line in str(block.get("text") or "").splitlines())
    lines = [line for line in lines if line]
    if len(lines) < _MIN_LINES:
        return False

    headers = 0
    body: list[str] = []
    for line in lines:
        match = _LABEL_ROW.match(line)
        if match and match.group("label").strip().lower() in _HEADER_LABELS:
            headers += 1
            continue
        if match or _GAP.search(line):
            return False  # a labelled row or a column: structure a record has
        body.append(line)

    sentences = sum(1 for line in body if _is_sentence(line))
    cue = headers >= 2 or any(_GREETING.match(line) or _SIGN_OFF.match(line) for line in body)
    return cue and sentences >= _MIN_SENTENCES and sentences * 2 >= len(body)
