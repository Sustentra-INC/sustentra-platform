"""ZIP code -> eGRID subregion(s), from the EPA Power Profiler ZIP Code Tool (eGRID2023).

Reads reference-data/emission-factors/egrid_zip_subregions_2023.json, which
``backend/scripts/build_egrid_zip_reference.py`` generates from the EPA workbook in
reference-data/emission-factors/source/. A ZIP code with one subregion is definitive;
one with several needs the facility's electric utility to choose (EPA's guidance).
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

ZIP_PATH = Path(__file__).resolve().parents[3] / "reference-data" / "emission-factors" / "egrid_zip_subregions_2023.json"
DATASET = "EPA Power Profiler ZIP Code Tool v14.2 (eGRID2023 rev 1)"

# A ZIP code ends a US address ("..., Albany, NY 12207", "..., VA 23234-1234", optionally
# followed by the country). A 5-digit number elsewhere is a street number ("12345 Main St").
_ZIP_RE = re.compile(r"(?<![\d-])(\d{5})(?:-\d{4})?\s*(?:,?\s*(?:USA|U\.S\.A\.|US|United States))?\s*$", re.I)


@lru_cache(maxsize=1)
def _zips() -> dict[str, str]:
    data: dict[str, Any] = json.loads(ZIP_PATH.read_text(encoding="utf-8"))
    return data["zips"]


def subregions_for_zip(zip_code: str | None) -> list[str]:
    """Possible eGRID subregions for a 5-digit ZIP code, in EPA's order; [] when unknown."""

    if not zip_code or not re.fullmatch(r"\d{5}", zip_code):
        return []
    found = _zips().get(zip_code)
    return found.split("|") if found else []


def zip_from_address(address: Any) -> str | None:
    """The ZIP code ending a US address ("..., Albany, NY 12207-1234"), else None.

    Only a ZIP code at the end counts: a bill's address line without a city line
    ("12345 Main St") has no ZIP code, and its street number must not be read as one.
    """

    match = _ZIP_RE.search(" ".join(str(address or "").split()))
    return match.group(1) if match else None
