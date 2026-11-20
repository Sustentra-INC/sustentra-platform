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


# --- a contract is not a bill -----------------------------------------------------------------
CONTRACT_MESSAGE = (
    "This reads as a contract or agreement, not a bill, a log or a record, so it is not used as evidence. "
    "If it is one of those, set the document type."
)
# The heading of an agreement: "ELECTRIC SERVICE AGREEMENT", "Supply Contract", near the top.
_CONTRACT_TITLE = re.compile(r"\b(?:agreement|contract)\b", re.I)
# Wording an agreement has and a bill does not (each counted once).
_CONTRACT_CUES = tuple(re.compile(p, re.I) for p in (
    r"\bby and between\b|\bentered into\b",
    r"\bthe parties\b|\bneither party\b|\beither party\b",
    r"\bshall\b",
    r"\bgoverning law\b|\bgoverned by the laws\b",
    r"\blimitation of liability\b|\bconsequential damages\b",
    r"\bentire agreement\b",
    r"\bforce majeure\b",
    r"\bassign(?:ment)?\b",
    r"\beffective date\b",
    r"\brenew(?:s|ing|al)?\b.*\bterm\b|\bterm\b.*\brenew",
    r"\bnotices shall\b|\bnotice of non-renewal\b",
))
_MIN_CONTRACT_CUES = 5
# A usage figure or a labelled bill row: what a contract does not have.
_USAGE_ROW = re.compile(
    r"\b(?:total|usage|consumption|used|delivered)\b[^\n]{0,40}\d[\d,.]*\s*(?:k?wh|mwh|therms?|ccf|mcf|gal(?:lons?)?|lbs?|mmbtu)\b",
    re.I)
_BILL_LABEL = re.compile(
    r"^\s*(?:account (?:number|no)|billing period|service period|amount due|meter (?:number|no))\s*[:\t]", re.I | re.M)


def looks_like_a_contract(parser_output: dict[str, Any]) -> bool:
    """Whether the document is an agreement: a heading that names one, plenty of contract wording
    (parties, "shall", term, governing law, liability) and no consumption table or bill rows.

    A bill that mentions "agreement" in its terms has labelled bill rows and no such heading, so it is
    not one; a contract that names a rate schedule or "monthly statements" has no usage figures."""

    if parser_output.get("tables") or parser_output.get("key_value_pairs"):
        return False
    if any(isinstance(r, dict) and r.get("sheet_name") for r in parser_output.get("source_references") or []):
        return False
    text = "\n".join(str(b.get("text") or "") for b in parser_output.get("text_blocks") or [] if isinstance(b, dict))
    if not text.strip():
        text = "\n".join(str(p.get("text") or "") for p in parser_output.get("pages") or [] if isinstance(p, dict))
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) < _MIN_LINES:
        return False
    heading = any(_CONTRACT_TITLE.search(line) and len(line) <= 80 for line in lines[:12])
    cues = sum(1 for cue in _CONTRACT_CUES if cue.search(text))
    if not heading or cues < _MIN_CONTRACT_CUES:
        return False
    return not _USAGE_ROW.search(text) and not _BILL_LABEL.search(text)
