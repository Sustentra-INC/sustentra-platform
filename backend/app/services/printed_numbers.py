"""Read a number as it is printed, and refuse to read one whose comma could mean two things (MVP-238).

Used wherever a printed number becomes a stored one from an AI read (``ai_extraction``, ``ai_record_fill``) and by the
accuracy harness's miss sorter, so both read "1,20" the same way: not at all.

``read_number(text, decimal_comma)``: the number, or None when the text is not one bare number or its separators are
ambiguous. ``decimal_comma`` is the document's convention (``document_convention``): True when its other numbers show
a decimal comma ("1.234,56", "88,0"), False when they show a decimal point ("12,345.6", "1,234,567"), None when they
do not settle it (or show both).

Rules (a token's separators):

* comma and dot both: the last one is the decimal mark and the other must group digits in threes ("12,345.6",
  "€1.234,56"); anything else is not read;
* commas only:
  - two or more groups of three ("1,234,567"): thousands;
  - one comma and exactly one digit after it ("88,0"): a decimal comma (grouping needs three digits);
  - one comma, 1–3 digits before it (not a lone "0") and three after ("1,204"): thousands, unless the document's
    convention is a decimal comma, then a decimal;
  - any other single comma ("0,500", "1234,567", "1,20", "12,34", "1,2345"): a decimal only when the document's
    convention is a decimal comma; otherwise not read;
* dots only: one dot is a decimal point, except that "1.234" in a decimal-comma document is thousands; two or more
  dots must group in threes ("1.234.567": thousands);
* space, no-break space, thin space or apostrophe grouping in threes is dropped first ("1 204,5", "12'345").

A currency sign or a minus sign may lead the token. Pure functions; nothing is logged.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from decimal import Decimal, InvalidOperation

_SPACES = re.compile(r"[   ]")
_SPACE_GROUPED = re.compile(r"\d{1,3}(?:[ '’]\d{3})+(?:[.,]\d+)?")
_CURRENCY = re.compile(r"^[$€£¥]|^(?:USD|EUR|GBP)\s*", re.I)
_THOUSANDS_COMMA = re.compile(r"[1-9]\d{0,2}(?:,\d{3})+|0")
# A number standing on its own in a line of text: not a piece of an id ("88-1200"), a date or a word ("GEN-1").
TOKEN = re.compile(r"(?<![\w.,\-/])[-−]?[$€£¥]?\d(?:[\d.,]|[    '](?=\d{3}\b))*(?<![.,])(?![\w\-/]|[.,]\d)")


def _strip(text: str) -> tuple[str, bool] | None:
    """The token's digits and separators, and whether it is negative; None when there is something else in it."""

    text = _SPACES.sub(" ", text).strip()
    negative = text[:1] in ("-", "−")
    if negative:
        text = text[1:].lstrip()
    text = _CURRENCY.sub("", text).strip()
    if _SPACE_GROUPED.fullmatch(text):
        text = re.sub(r"[ '’]", "", text)
    if not text or not re.fullmatch(r"\d[\d.,]*", text) or text[-1] in ".,":
        return None
    return text, negative


def read_number(text: str, decimal_comma: bool | None = None) -> Decimal | None:
    """The number ``text`` prints (module docstring), or None when it is not one or could be read two ways."""

    stripped = _strip(str(text))
    if stripped is None:
        return None
    body, negative = stripped
    plain = _plain(body, decimal_comma)
    if plain is None:
        return None
    try:
        number = Decimal(plain)
    except InvalidOperation:
        return None
    return -number if negative else number


def _plain(body: str, decimal_comma: bool | None) -> str | None:
    commas, dots = body.count(","), body.count(".")
    if commas and dots:
        mark = "," if body.rfind(",") > body.rfind(".") else "."
        group = "." if mark == "," else ","
        head, _, tail = body.rpartition(mark)
        if mark in head or group in tail or not re.fullmatch(rf"\d{{1,3}}(?:{re.escape(group)}\d{{3}})*", head):
            return None
        return head.replace(group, "") + "." + tail
    if commas:
        if commas > 1:
            return body.replace(",", "") if _THOUSANDS_COMMA.fullmatch(body) else None
        head, _, tail = body.partition(",")
        if len(tail) == 1:
            return f"{head}.{tail}"
        if len(tail) == 3 and _THOUSANDS_COMMA.fullmatch(body) and decimal_comma is not True:
            return head + tail
        return f"{head}.{tail}" if decimal_comma is True else None
    if dots > 1:
        return body.replace(".", "") if re.fullmatch(r"[1-9]\d{0,2}(?:\.\d{3})+", body) else None
    if dots == 1 and decimal_comma is True and re.fullmatch(r"[1-9]\d{0,2}\.\d{3}", body):
        return body.replace(".", "")
    return body


def tokens(text: str) -> list[str]:
    """The numbers standing on their own in a line of text, as printed."""

    return [m.group(0) for m in TOKEN.finditer(text)]


def document_convention(texts: Iterable[str]) -> bool | None:
    """True: the document's unambiguous numbers use a decimal comma; False: a decimal point; None: unsettled."""

    comma = dot = False
    for text in texts:
        for token in tokens(text):
            stripped = _strip(token)
            if stripped is None:
                continue
            body = stripped[0]
            if "," in body and "." in body:
                if body.rfind(",") > body.rfind("."):
                    comma = comma or _plain(body, True) is not None
                else:
                    dot = dot or _plain(body, False) is not None
            elif body.count(",") == 1 and len(body.partition(",")[2]) == 1:
                comma = True
            elif body.count(",") > 1 and _THOUSANDS_COMMA.fullmatch(body):
                dot = True
            if comma and dot:
                return None
    return True if comma else False if dot else None
