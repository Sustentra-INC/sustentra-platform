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
# The heading of an agreement: a short line with no colon and no digit whose last word is "agreement" or
# "contract" ("ELECTRIC SERVICE AGREEMENT", "Fuel Supply Agreement"). "Contract Account", "Contract Number",
# "Contract #4471" and "Contract Date:" are bill labels, not headings.
_CONTRACT_TITLE = re.compile(r"^[^:\d#]{0,58}\b(?:agreement|contract)\W*$", re.I)
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
# What a contract does not have, found in the text alone (the parser may leave tables and key-value pairs empty):
# a quantity with a unit, a quantity label, a bill-row label (with a colon, a tab or only spaces after it), or the
# words of an invoice.
_UNITS = r"(?:gal(?:lons?)?|k?wh|mwh|therms?|ccf|mcf|mmbtu|dth|lbs?|kg|l|litres?|liters?)"
_QUANTITY_WITH_UNIT = re.compile(rf"\d[\d,.]*\s*{_UNITS}\b", re.I)
_QUANTITY_LABEL = re.compile(r"\b(?:quantity|qty|gallons?|kwh|therms?)\b", re.I)
_BILL_ROW_LABEL = re.compile(
    # "Account Number   3305", "Account No. 3305", "Account #3305", "Meter No. 12": the label, then anything or nothing
    r"^\s*(?:(?:account|meter|invoice)\s+(?:number\b|no\b\.?|#)\s*(?:$|[:#\t]|\S)"
    # a label of words, not abbreviations: followed by a colon, a tab, a value or the end of the line, so a wrapped
    # sentence that starts "statement date. Late payments..." is not a bill row
    r"|(?:billing\s+period|service\s+period|invoice\s+date|statement\s+date|due\s+date)\b(?=$|[:#\t]|\s+\S))",
    re.I | re.M)
_INVOICE_WORDS = re.compile(r"\bamount\s+due\b|\binvoice\b|\bstatement\s+date\s*[:\t ]\s*\d", re.I)


def looks_like_a_contract(parser_output: dict[str, Any]) -> bool:
    """Whether the document is an agreement: a heading that names one, plenty of contract wording
    (parties, "shall", term, governing law, liability) and nothing a bill has: no quantity with a unit, no
    quantity label, no bill-row label, no "amount due" or "invoice", whatever the parser made of the layout.

    A bill or delivery ticket that mentions an agreement in its terms has such rows (and "Contract Account" is a
    label, not a heading), so it is never stopped as a contract; a contract that names a rate schedule or
    "monthly statements" has no usage figures."""

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
    heading = any(_CONTRACT_TITLE.match(line) for line in lines[:12])
    cues = sum(1 for cue in _CONTRACT_CUES if cue.search(text))
    if not heading or cues < _MIN_CONTRACT_CUES:
        return False
    return not any(veto.search(text) for veto in (
        _QUANTITY_WITH_UNIT, _QUANTITY_LABEL, _BILL_ROW_LABEL, _INVOICE_WORDS))


# --- a company's own narrative GHG document ----------------------------------------------------
# A published GHG statement, a management assertion, an inventory management plan, a basis of reporting or an
# accountants' review report is prose about the inventory, not source evidence. It always says kWh, MWh and
# "invoices" in passing, so those words cannot veto it; what vetoes it is the shape of a bill or a log near the top.
WORKBOOK_TYPE_ID = "CT-GHG-WORKBOOK"
METHODDOC_TYPE_ID = "CT-S1-METHODDOC"
_APOS = "['’ʼ`]"
_GHG = r"(?:greenhouse\s+gas|ghg)"
_NARRATIVE_METHOD_HEADING = re.compile(
    r"\bbasis\s+of\s+(?:reporting|preparation)\b|\bmethodology\b|\bmethods\s+and\s+assumptions\b", re.I)
_NARRATIVE_HEADING = re.compile(
    rf"\bstatement\s+of\s+{_GHG}\s+emissions\b|\bmanagement{_APOS}?s?\s+assertion\b"
    rf"|\b{_GHG}\s+inventory\s+(?:management\s+plan|report)\b|\bclimate\s+accounting\s+statement\b"
    rf"|\bindependent\s+accountants?{_APOS}?s?{_APOS}?\s+(?:review|examination)\s+report\b"
    rf"|\b(?:limited\s+|reasonable\s+)?assurance\s+(?:statement|report)\b|\blimited\s+assurance\b"
    rf"|\boperational\s+{_GHG}\s+emissions\b|\bannual\s+{_GHG}\s+(?:emissions\s+)?report\b", re.I)
_TOP_LINES = 40  # where a title or heading cue is looked for
_BILL_TOP_LINES = 30  # where bill rows and quantity tables veto
_HEADING_WORDS = 16
_NARRATIVE_MIN_LINES = 12
_NARRATIVE_MIN_PROSE = 0.4
_ACTIVITY_UNIT = re.compile(
    r"\d[\d,.]*\s*(?:gal(?:lons?)?|k?wh|mwh|therms?|ccf|mcf|mmbtu|dth|litres?|liters?)\b"
    r"|\b(?:gallons?|litres?|liters?|therms?|ccf|mcf|kwh|mwh|mmbtu|dth|odometer|meter reading)\b", re.I)
_TABULAR = re.compile(r"\||\t|\s{3,}|^[^,]*(?:,[^,]*){3,}$")
_BILL_TOP = re.compile(r"\bamount\s+due\b|\btotal\s+due\b|\bpay\s+by\b|\bpay\s+this\s+amount\b", re.I)


def _document_lines(parser_output: dict[str, Any] | None, text: str) -> tuple[list[str], int | None]:
    """The document's non-empty lines in reading order, and its page count when the parser gave one."""

    raw = ""
    pages = None
    if isinstance(parser_output, dict):
        page_list = [p for p in parser_output.get("pages") or [] if isinstance(p, dict)]
        pages = len(page_list) or None
        raw = "\n".join(str(p.get("text") or "") for p in page_list)
        if not raw.strip():
            raw = "\n".join(str(b.get("text") or "") for b in parser_output.get("text_blocks") or []
                            if isinstance(b, dict))
    if not raw.strip():
        raw = text
    return [line.strip() for line in raw.splitlines() if line.strip()], pages


def narrative_ghg_document_type(parser_output: dict[str, Any] | None = None, text: str = "") -> str | None:
    """The summary type (``CT-GHG-WORKBOOK`` or ``CT-S1-METHODDOC``) of a company's narrative GHG document, or
    ``None``.

    It needs a title or heading cue near the top (statement of GHG emissions, management assertion, inventory
    management plan, basis of reporting, climate accounting statement, accountants' review report, assurance
    statement, GHG inventory report, methodology), mostly prose across several pages, and none of a bill's or a
    log's shape near the top: bill rows (account number, billing period, amount due) or a table of quantities.
    kWh, MWh and "invoices" inside sentences do not count against it. A contract is never one."""

    if isinstance(parser_output, dict):
        if parser_output.get("tables") or any(
                isinstance(r, dict) and r.get("sheet_name") for r in parser_output.get("source_references") or []):
            return None  # a spreadsheet or a document with tables: the summary cue for workbooks decides
        if looks_like_a_contract(parser_output):
            return None
    lines, pages = _document_lines(parser_output, text)
    if len(lines) < _NARRATIVE_MIN_LINES or (pages is not None and pages < 2):
        return None
    top = lines[:_TOP_LINES]
    headings = [line for line in top if len(line.split()) <= _HEADING_WORDS]
    report = any(_NARRATIVE_HEADING.search(line) for line in headings)
    if not report and not any(_NARRATIVE_METHOD_HEADING.search(line) for line in headings):
        return None
    for line in lines[:_BILL_TOP_LINES]:
        if _BILL_ROW_LABEL.search(line) or _BILL_TOP.search(line):
            return None
        if _TABULAR.search(line) and _ACTIVITY_UNIT.search(line):
            return None
    prose = sum(1 for line in lines if len(line.split()) >= 8 or _is_sentence(line))
    if prose < 3 or prose / len(lines) < _NARRATIVE_MIN_PROSE:
        return None
    return WORKBOOK_TYPE_ID if report else METHODDOC_TYPE_ID
