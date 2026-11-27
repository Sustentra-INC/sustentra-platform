"""Read a number as it is printed, and refuse to read one whose comma could mean two things (MVP-238).

Used wherever a printed number becomes a stored one from an AI read (``ai_extraction``, ``ai_record_fill``) and by the
accuracy harness's miss sorter, so both read "1,20" the same way: not at all.

``read_number(text, decimal_comma)``: the number, or None when the text is not one bare number or its separators are
ambiguous. ``decimal_comma`` is the document's convention (``document_convention``), decided conservatively because a
wrong switch turns "1,204" into 1.204 (a 1,000x error):

* True (a decimal-comma document): at least ``MIN_COMMA_EVIDENCE`` (2) unambiguous decimal-comma numbers ("88,0",
  "1.234,56") and no unambiguous decimal-point number ("1,234.56", "12,345.6", "1,234,567");
* None (unsettled): any decimal-comma number together with any decimal-point number, or a single decimal-comma number.
  Every ambiguous number ("1,204", "1.234", "0,500"...) is then not read: dropped and left for a person, never guessed
  either way;
* False (the default, a decimal-point document): no decimal-comma number at all, as US documents are.

Rules (a token's separators):

* comma and dot both: the last one is the decimal mark and the other must group digits in threes ("12,345.6",
  "€1.234,56"); anything else is not read;
* commas only:
  - two or more groups of three ("1,234,567"): thousands;
  - one comma and exactly one digit after it ("88,0"): a decimal comma (grouping needs three digits);
  - one comma, 1–3 digits before it (not a lone "0") and three after ("1,204"): thousands in a decimal-point
    document, a decimal in a decimal-comma one, not read when the convention is unsettled;
  - any other single comma ("0,500", "1234,567", "1,20", "12,34", "1,2345"): a decimal only when the document's
    convention is a decimal comma; otherwise not read;
* dots only: one dot is a decimal point, except "1.234": thousands in a decimal-comma document, not read when the
  convention is unsettled; two or more
  dots must group in threes ("1.234.567": thousands);
* space, no-break space, thin space or apostrophe grouping in threes is dropped first ("1 204,5", "12'345").

A currency sign or a minus sign may lead the token. Pure functions; nothing is logged.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
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


def read_number(text: str, decimal_comma: bool | None = False) -> Decimal | None:
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
        if len(tail) == 3 and _THOUSANDS_COMMA.fullmatch(body) and decimal_comma is False:
            return head + tail
        return f"{head}.{tail}" if decimal_comma is True else None
    if dots > 1:
        return body.replace(".", "") if re.fullmatch(r"[1-9]\d{0,2}(?:\.\d{3})+", body) else None
    if dots == 1 and decimal_comma is not False and re.fullmatch(r"[1-9]\d{0,2}\.\d{3}", body):
        return body.replace(".", "") if decimal_comma is True else None
    return body


def tokens(text: str) -> list[str]:
    """The numbers standing on their own in a line of text, as printed."""

    return [m.group(0) for m in TOKEN.finditer(text)]


MIN_COMMA_EVIDENCE = 2


@dataclass(frozen=True)
class Convention:
    """A document's number convention and the evidence for it (unambiguous numbers of each kind)."""

    decimal_comma: bool | None
    comma_numbers: int
    point_numbers: int

    @property
    def name(self) -> str:
        return {True: "decimal_comma", False: "decimal_point", None: "unsettled"}[self.decimal_comma]

    def as_record(self) -> dict[str, object]:
        """For the extraction result, so a reviewer can see how the document's numbers were read."""

        return {"convention": self.name, "decimal_comma_numbers": self.comma_numbers,
                "decimal_point_numbers": self.point_numbers}


def convention_of(texts: Iterable[str]) -> Convention:
    """The document's convention from its unambiguous numbers (module docstring)."""

    comma = point = 0
    for text in texts:
        for token in tokens(text):
            stripped = _strip(token)
            if stripped is None:
                continue
            body = stripped[0]
            if "," in body and "." in body:
                if body.rfind(",") > body.rfind("."):
                    comma += int(_plain(body, True) is not None)
                else:
                    point += int(_plain(body, False) is not None)
            elif body.count(",") == 1 and len(body.partition(",")[2]) == 1:
                comma += 1
            elif body.count(",") > 1 and _THOUSANDS_COMMA.fullmatch(body):
                point += 1
    if comma == 0:
        decided: bool | None = False
    elif point == 0 and comma >= MIN_COMMA_EVIDENCE:
        decided = True
    else:
        decided = None
    return Convention(decided, comma, point)


def document_convention(texts: Iterable[str]) -> bool | None:
    """True: a decimal-comma document; False: a decimal-point one (the default); None: unsettled."""

    return convention_of(texts).decimal_comma
