"""Normalisers for the accuracy harness: numbers, dates, ids, names and units.

Everything here is pure and deterministic. A value is compared only after both sides have been
through the same normaliser, so formatting ("1,200 kWh" against 1200) never counts as an error
and a real difference (a different digit, a different day) always does.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import date
from decimal import Decimal, InvalidOperation

_NUMBER = re.compile(r"\(?-?\$?\d{1,3}(?: \d{3})+(?:\.\d+)?\)?|\(?-?\$?\d[\d,]*(?:\.\d+)?\)?|\(?-?\$?\.\d+\)?")

MONTHS = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3, "apr": 4, "april": 4,
    "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7, "aug": 8, "august": 8,
    "sep": 9, "sept": 9, "september": 9, "oct": 10, "october": 10, "nov": 11, "november": 11,
    "dec": 12, "december": 12,
}
_MONTH_NAMES = "|".join(sorted(MONTHS, key=len, reverse=True))


def parse_number(value: object) -> Decimal | None:
    """The first number in ``value``: thousands separators, currency signs and a unit suffix are
    ignored; "(3.5)" is negative. ``None`` when there is no number."""

    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float, Decimal)):
        return Decimal(str(value))
    text = str(value).strip()
    match = _NUMBER.search(text)
    if not match:
        return None
    token = match.group(0)
    negative = token.strip().startswith("(") or "-" in token
    digits = re.sub(r"[^\d.]", "", token)
    if not digits or digits == ".":
        return None
    try:
        number = Decimal(digits)
    except InvalidOperation:
        return None
    return -number if negative else number


def numbers_equal(expected: Decimal, actual: Decimal, *, rel_tol: Decimal = Decimal("0")) -> bool:
    """Equal within a relative tolerance (``0`` = the same number), or within the last printed digit."""

    if expected == actual:
        return True
    if rel_tol > 0 and abs(actual - expected) <= rel_tol * abs(expected):
        return True
    return False


def is_exact(expected: Decimal, actual: Decimal) -> bool:
    """Same number as printed: equal, or only a float-conversion error apart (1e-9 relative)."""

    return abs(actual - expected) <= Decimal("1e-9") * max(abs(expected), Decimal(1))


def parse_date(value: object) -> date | None:
    """A calendar day from the formats bills and keys use (US month-first); ``None`` if none fits."""

    if value is None:
        return None
    if isinstance(value, date):
        return value
    text = str(value).strip()
    m = re.search(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b", text)
    if m:
        return _safe_date(int(m[1]), int(m[2]), int(m[3]))
    m = re.search(r"\b(\d{1,2})[/.-](\d{1,2})[/.-](\d{4}|\d{2})\b", text)
    if m:
        year = int(m[3])
        year += 2000 if year < 100 else 0
        return _safe_date(year, int(m[1]), int(m[2]))
    m = re.search(rf"\b({_MONTH_NAMES})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s+(\d{{4}})\b", text, re.I)
    if m:
        return _safe_date(int(m[3]), MONTHS[m[1].lower()], int(m[2]))
    m = re.search(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+({_MONTH_NAMES})\.?,?\s+(\d{{4}})\b", text, re.I)
    if m:
        return _safe_date(int(m[3]), MONTHS[m[2].lower()], int(m[1]))
    return None


def _safe_date(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def strip_accents(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))


def norm_id(value: object) -> str:
    """Account / meter / invoice ids: case, spaces, dashes and other punctuation do not matter."""

    if value is None:
        return ""
    return re.sub(r"[^a-z0-9]", "", strip_accents(str(value)).casefold())


def norm_name(value: object) -> str:
    """Names (supplier, facility): case, spacing, punctuation and accents do not matter."""

    if value is None:
        return ""
    return re.sub(r"[^a-z0-9]", "", strip_accents(str(value)).casefold())


UNIT_ALIASES = {
    "kwh": "kwh", "kilowatthour": "kwh", "kilowatthours": "kwh", "mwh": "mwh", "megawatthour": "mwh",
    "therm": "therms", "therms": "therms", "ccf": "ccf", "mcf": "mcf", "mmbtu": "mmbtu", "mbtu": "mmbtu",
    "gal": "gal", "gals": "gal", "gallon": "gal", "gallons": "gal", "usgal": "gal", "l": "l", "liter": "l",
    "liters": "l", "litre": "l", "litres": "l", "lb": "lb", "lbs": "lb", "pound": "lb", "pounds": "lb",
    "kg": "kg", "kilogram": "kg", "kilograms": "kg", "mi": "mi", "mile": "mi", "miles": "mi", "km": "km",
    "kilometer": "km", "kilometers": "km", "kilometre": "km", "kilometres": "km", "kw": "kw", "usd": "usd",
    "hours": "hours", "hour": "hours", "hr": "hours", "hrs": "hours", "days": "days", "mlb": "mlb", "klb": "mlb", "mlbs": "mlb", "klbs": "mlb",
}

# (from, to) -> multiplier. Only exact or defined-constant conversions; heat-content conversions that
# depend on a bill's own factor (CCF -> therms) are deliberately absent.
CONVERSIONS: dict[tuple[str, str], Decimal] = {
    ("mwh", "kwh"): Decimal(1000),
    ("kwh", "mwh"): Decimal("0.001"),
    ("therms", "mmbtu"): Decimal("0.1"),
    ("mmbtu", "therms"): Decimal(10),
    ("gal", "l"): Decimal("3.785411784"),
    ("l", "gal"): Decimal(1) / Decimal("3.785411784"),
    ("lb", "kg"): Decimal("0.45359237"),
    ("kg", "lb"): Decimal(1) / Decimal("0.45359237"),
    ("mi", "km"): Decimal("1.609344"),
    ("km", "mi"): Decimal(1) / Decimal("1.609344"),
}


def norm_unit(value: object) -> str:
    """Canonical unit token ("US gal", "Gallons" -> "gal"); the first word of a phrase like "gal diesel"."""

    if value is None:
        return ""
    text = strip_accents(str(value)).casefold().strip()
    if not text:
        return ""
    compact = re.sub(r"[^a-z]", "", text)
    if compact in UNIT_ALIASES:
        return UNIT_ALIASES[compact]
    first = re.split(r"[\s/(,]+", text)[0]
    first = re.sub(r"[^a-z]", "", first)
    return UNIT_ALIASES.get(first, compact)


def convert(value: Decimal, from_unit: str, to_unit: str) -> Decimal | None:
    """``value`` in ``to_unit``, or ``None`` when no defined conversion exists."""

    a, b = norm_unit(from_unit), norm_unit(to_unit)
    if not a or not b:
        return None
    if a == b:
        return value
    factor = CONVERSIONS.get((a, b))
    return None if factor is None else value * factor


def norm_refrigerant(value: object) -> str:
    """"R-999z", "HFC-999z" and "r999Z" are one refrigerant."""

    text = re.sub(r"[^a-z0-9]", "", strip_accents(str(value or "")).casefold())
    return re.sub(r"^(hfc|hcfc|cfc|r)", "r", text)
