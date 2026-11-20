"""Account and meter numbers on a Setup facility, and the matching step that uses them.

PROVISIONAL (approved by the product owner, 18 Nov 2026). The ops lead may change the format of
the client's facility list, so everything that depends on that format lives here, in one place:
the field names, the limits, the comparison rule and the one matching function
(``match_by_identifier``). The values are plain lists of strings on each facility in the
engagement settings: ``accountNumbers`` and, optionally, ``meterNumbers``. A facility saved
before this existed has neither key, and every function here treats that as "no numbers".

A leaf module: it imports nothing of the services. Its frontend twin is
``frontend/features/s1/utils/facilityNumbers.ts``; keep the two in step (the shared cases in
``backend/tests/fixtures/facility_placement_cases.json`` check that they agree).

The comparison (NFKC, case-folded, invisible characters such as a BOM dropped):
* spaces, dashes and dots separate groups of characters; two numbers are the same when their
  groups are the same ("4417 2290 31" = "4417-2290-31"), or when one of them is written without
  separators and the characters are the same ("442290" = "44-2290"). "12-345" is not "1234-5";
* only a whole number counts, never a partial one ("4417-2290" is not "4417-2290-31");
* a number needs at least ``MIN_DIGITS`` digits, on the bill and in Setup, before it can match.

Not done yet, because the format is provisional and waits on the ops lead: a supplier per number
(two utilities can issue the same account number).
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any

MAX_PER_FACILITY = 50
MAX_LENGTH = 64
MIN_DIGITS = 4  # a number with fewer digits can be saved but never matches a bill

ACCOUNT = "account"
METER = "meter"
# kind -> (settings key on a facility, label used in sentences)
KINDS: dict[str, tuple[str, str]] = {ACCOUNT: ("accountNumbers", "Account"), METER: ("meterNumbers", "Meter")}
REASON = "Account or meter number in Setup"  # how a bill placed by its number is described, everywhere

_SEPARATORS = re.compile(r"[\s.\-‐-―−]+")  # whitespace, dots, hyphens and the Unicode dashes
_INVISIBLE = re.compile(r"[﻿​-‍⁠]")  # BOM, zero-width characters


def fold(value: Any) -> str:
    """NFKC, invisible characters dropped, case-folded."""

    return unicodedata.normalize("NFKC", _INVISIBLE.sub("", str(value if value is not None else ""))).casefold()


# A label an OCR line can leave in front of a number ("SERVICE FOR: 8830-1174-562", "Acct #: 4417"): the account
# labels and the service-block headings, each with its colon or number sign.
_LEADING_LABEL = re.compile(
    r"^\s*(?:account\s*(?:number|no\.?|#)?|acct\s*(?:number|no\.?|#)?|customer\s*(?:account|number|no\.?|#)?|"
    r"service\s+(?:for|to|site|premises?)|bill(?:ed)?\s+to|meter\s*(?:number|no\.?|#)?)\s*[:#]\s*", re.IGNORECASE)


def clean_account(value: Any) -> str:
    """An account number without the label in front of it: "SERVICE FOR: 8830-1174-562" is "8830-1174-562". Only a
    label with its colon or number sign is taken off, and only while something is left after it."""

    text = str(value if value is not None else "").strip()
    for _ in range(3):
        stripped = _LEADING_LABEL.sub("", text, count=1)
        if stripped == text or not stripped.strip():
            break
        text = stripped
    return text.strip()


def groups(value: Any) -> tuple[str, ...]:
    """A number's groups of characters between spaces, dashes and dots."""

    return tuple(part for part in _SEPARATORS.split(fold(value)) if part)


def normalise(value: Any) -> str:
    """The groups run together: case, spaces, dashes and dots dropped."""

    return "".join(groups(value))


def digit_count(value: Any) -> int:
    return sum(1 for ch in fold(value) if ch.isdigit())


def same_number(a: Any, b: Any) -> bool:
    """Whether two numbers are the same: the same groups, or one written without separators and the
    same characters. Only whole numbers; never a partial match."""

    ga, gb = groups(a), groups(b)
    if not ga or not gb:
        return False
    if ga == gb:
        return True
    return (len(ga) == 1 or len(gb) == 1) and "".join(ga) == "".join(gb)


def split_pasted(text: str) -> list[str]:
    """A pasted list split on newlines, commas and semicolons, outside double quotes. Quotes are removed
    ("4417, 22" stays one value); blanks are dropped and spacing trimmed."""

    parts: list[str] = []
    current: list[str] = []
    quoted = False
    for ch in text:
        if ch == '"':
            quoted = not quoted
        elif ch in "\r\n,;" and not quoted:
            parts.append("".join(current))
            current = []
        else:
            current.append(ch)
    parts.append("".join(current))
    return [part.strip() for part in parts if part.strip()]


def check_value(value: Any) -> str | None:
    """Why a single number is refused, in a plain sentence; None when it is fine."""

    if not isinstance(value, str) or not value.strip():
        return "A number can't be empty."
    if len(value.strip()) > MAX_LENGTH:
        return f"A number can be at most {MAX_LENGTH} characters."
    if digit_count(value) == 0:
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

    seen: list[tuple[str, list[str], list[int]]] = []  # (first spelling, facility names, facility positions)
    for position, facility in enumerate(facilities):
        for value in numbers_of(facility, kind):
            entry = next((e for e in seen if same_number(e[0], value)), None)
            if entry is None:
                seen.append((value, [str(facility.get("name") or "")], [position]))
            elif position not in entry[2]:
                entry[1].append(str(facility.get("name") or ""))
                entry[2].append(position)
    return {spelling: owners for spelling, owners, _ in seen if len(owners) > 1}


@dataclass(frozen=True)
class IdentifierMatch:
    """The outcome of the account and meter step. ``facility`` is set for exactly one match;
    ``ambiguous`` carries the reason when the numbers point at two or more facilities; ``what`` names
    the number that matched ("Account 4417-2290-31")."""

    facility: dict[str, Any] | None = None
    reason: str | None = None
    ambiguous: str | None = None
    what: str | None = None


def _listing(kind: str, value: Any, facilities: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The facilities that list this number (none when the bill's number is too short to trust)."""

    if digit_count(value) < MIN_DIGITS:
        return []
    return [f for f in facilities
            if any(digit_count(v) >= MIN_DIGITS and same_number(v, value) for v in numbers_of(f, kind))]


def match_by_identifier(account: Any, meter: Any, facilities: list[dict[str, Any]]) -> IdentifierMatch:
    """The facility whose listed numbers contain the bill's account number and/or meter number.

    Exactly one facility places the bill. A number listed on two facilities, or an account and a meter
    number that point at different facilities, place nothing and say why. No match is an empty result,
    so the caller behaves as it did before. Only a whole number counts, never a partial one.
    """

    found: dict[str, tuple[str, list[dict[str, Any]]]] = {}
    for kind, value in ((ACCOUNT, account), (METER, meter)):
        hits = _listing(kind, value, facilities)
        if hits:
            found[kind] = (str(value).strip(), hits)
    for kind, (value, hits) in found.items():
        if len(hits) > 1:
            count = "two" if len(hits) == 2 else str(len(hits))
            return IdentifierMatch(ambiguous=f"{KINDS[kind][1]} {value} is listed on {count} facilities")
    if len(found) == 2 and found[ACCOUNT][1][0] is not found[METER][1][0]:
        return IdentifierMatch(ambiguous=f"Account {found[ACCOUNT][0]} and meter {found[METER][0]} "
                                         "are listed on different facilities")
    if not found:
        return IdentifierMatch()
    kind = ACCOUNT if ACCOUNT in found else METER
    value, hits = found[kind]
    return IdentifierMatch(facility=hits[0], reason=REASON, what=f"{KINDS[kind][1]} {value}")
