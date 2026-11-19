"""Account and meter numbers on a Setup facility, and the matching step that uses them.

PROVISIONAL (approved by the product owner, 18 Nov 2026). The ops lead may change the format of
the client's facility list, so everything that depends on that format lives here, in one place:
the field names, the limits, the comparison rule and the one matching function
(``match_by_identifier``). The values are plain lists of strings on each facility in the
engagement settings: ``accountNumbers`` and, optionally, ``meterNumbers``. A facility saved
before this existed has neither key, and every function here treats that as "no numbers".

A leaf module: it imports nothing of the services.

The comparison drops case, spaces, dashes and dots. Only a whole number counts: "4417-2290" never
matches "4417-2290-31". The stored value stays as the user typed it.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any

MAX_PER_FACILITY = 50
MAX_LENGTH = 64

ACCOUNT = "account"
METER = "meter"
# kind -> (settings key on a facility, label used in sentences)
KINDS: dict[str, tuple[str, str]] = {ACCOUNT: ("accountNumbers", "Account"), METER: ("meterNumbers", "Meter")}

_IGNORED = re.compile(r"[\s.\-‐-―−]+")  # whitespace, dots, hyphens and the Unicode dashes
_SEPARATORS = re.compile(r"[\r\n,;]+")


def normalise(value: Any) -> str:
    """The form two numbers are compared in: case, spaces, dashes and dots dropped."""

    return _IGNORED.sub("", unicodedata.normalize("NFKC", str(value if value is not None else ""))).casefold()


def split_pasted(text: str) -> list[str]:
    """A pasted list split on newlines, commas and semicolons; blanks dropped, spacing trimmed."""

    return [part.strip() for part in _SEPARATORS.split(text) if part.strip()]


def check_value(value: Any) -> str | None:
    """Why a single number is refused, in a plain sentence; None when it is fine."""

    if not isinstance(value, str) or not value.strip():
        return "A number can't be empty."
    if len(value.strip()) > MAX_LENGTH:
        return f"A number can be at most {MAX_LENGTH} characters."
    if not any(ch.isdigit() for ch in unicodedata.normalize("NFKC", value)):
        return "A number needs at least one digit."
    return None


def numbers_of(facility: dict[str, Any], kind: str) -> list[str]:
    """The numbers listed on a facility, for reading. Tolerates a missing or malformed field."""

    raw = facility.get(KINDS[kind][0])
    return [v for v in raw if isinstance(v, str) and v.strip()] if isinstance(raw, list) else []


def validate_numbers(facility: dict[str, Any]) -> None:
    """Raise ValueError (a plain sentence) when a facility's lists break the format or the limits."""

    name = facility.get("name") or "A facility"
    for key, label in KINDS.values():
        raw = facility.get(key)
        if raw is None:
            continue
        if not isinstance(raw, list):
            raise ValueError(f"{name}: {label.lower()} numbers must be a list.")
        if len(raw) > MAX_PER_FACILITY:
            raise ValueError(f"{name}: at most {MAX_PER_FACILITY} {label.lower()} numbers per facility.")
        for value in raw:
            if (problem := check_value(value)) is not None:
                raise ValueError(f"{name}: {problem}")


def shared_numbers(facilities: list[dict[str, Any]], kind: str) -> dict[str, list[str]]:
    """Each number listed on two or more facilities (keyed by the first spelling met), with the
    names of those facilities. The same data the Setup warning shows."""

    seen: dict[str, tuple[str, list[str]]] = {}
    for facility in facilities:
        for value in {normalise(v): v for v in numbers_of(facility, kind)}.values():
            _, owners = seen.setdefault(normalise(value), (value, []))
            owners.append(str(facility.get("name") or ""))
    return {spelling: owners for spelling, owners in seen.values() if len(owners) > 1}


@dataclass(frozen=True)
class IdentifierMatch:
    """The outcome of the account and meter step. ``facility`` is set for exactly one match;
    ``ambiguous`` carries the reason when a number is listed on two or more facilities."""

    facility: dict[str, Any] | None = None
    reason: str | None = None
    ambiguous: str | None = None


def match_by_identifier(account: Any, meter: Any, facilities: list[dict[str, Any]]) -> IdentifierMatch:
    """The facility whose listed numbers contain the bill's account number, else its meter number.

    Exactly one facility places the bill. Two or more place nothing and say why. No match is an empty
    result, so the caller behaves as it did before. Only a whole number counts, never a partial one.
    """

    for kind, value in ((ACCOUNT, account), (METER, meter)):
        wanted = normalise(value)
        if not wanted or not any(ch.isdigit() for ch in wanted):
            continue
        label = KINDS[kind][1]
        found = [f for f in facilities if any(normalise(v) == wanted for v in numbers_of(f, kind))]
        if len(found) == 1:
            return IdentifierMatch(facility=found[0], reason=f"{label} number in Setup")
        if len(found) > 1:
            count = "two" if len(found) == 2 else str(len(found))
            return IdentifierMatch(ambiguous=f"{label} {str(value).strip()} is listed on {count} facilities")
    return IdentifierMatch()
