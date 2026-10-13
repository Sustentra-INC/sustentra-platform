"""Refrigerant and fire-suppression gas names, and the masses written next to them.

Service records name gases loosely ("R410A", "R-410a", "Puron", "HFC134a", "R-134A",
"FM-200", "Freon 22"). ``find_refrigerant`` returns the name the EPA GHG Emission Factors
Hub uses (Table 11 "HFC-134a", "SF6"; Table 12 "R-410A"), so the GWP lookup is exact, and
the gas family. CFCs, HCFCs and halons are Montreal Protocol gases: the GHG Protocol does
not count them in Scope 1, so the recalculation lists them instead of adding them.

``parse_mass`` reads refrigerant amounts ("4.5 lbs", "4 lb 8 oz", "72 oz", "2.1 kg",
"500 g") into lb or kg; ounces and grams are converted because emission math works in
lb / kg / tonnes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Pure HFCs in the Hub's Table 11, by R-number suffix ("R-134a" is "HFC-134a").
_HFC = ("23", "32", "41", "125", "134", "134a", "143", "143a", "152", "152a", "161", "227ea", "236cb", "236ea",
        "236fa", "245ca", "245fa", "365mfc", "43-10mee")
_HCFC = ("21", "22", "31", "123", "124", "141b", "142b", "225ca", "225cb")
_CFC = ("11", "12", "13", "113", "114", "115", "500", "502", "503")
# Natural and low-GWP refrigerants: not in the Hub tables; the reviewer gives the GWP.
_OTHER = {"717": "R-717 (ammonia)", "290": "R-290 (propane)", "600": "R-600 (butane)",
          "600a": "R-600a (isobutane)", "1270": "R-1270 (propylene)", "1234yf": "R-1234yf",
          "1234ze": "R-1234ze", "1233zd": "R-1233zd", "514a": "R-514A"}

# Trade names seen on HVAC and fire-suppression paperwork.
_TRADE_NAMES: tuple[tuple[str, str, str], ...] = (
    (r"\bfm[- ]?200\b|\bhfc[- ]?227\b", "HFC-227ea", "hfc"),
    (r"\bfe[- ]?13\b", "HFC-23", "hfc"),
    (r"\bfe[- ]?25\b", "HFC-125", "hfc"),
    (r"\bfe[- ]?36\b", "HFC-236fa", "hfc"),
    (r"\bpuron\b|\bgenetron az[- ]?20\b|\bsuva 410a\b", "R-410A", "blend"),
    (r"\bhalon[- ]?(?:1211|1301|2402)\b", "Halon", "halon"),
    (r"\bnovec[- ]?1230\b", "FK-5-1-12 (Novec 1230)", "other"),
)

_FAMILY_WORDS: tuple[tuple[str, str], ...] = (
    (r"\bsulph?ur hexafluoride\b|\bsf6\b", "SF6"),
    (r"\bnitrogen trifluoride\b|\bnf3\b", "NF3"),
    (r"\bcf4\b|\bpfc[- ]?14\b|\btetrafluoromethane\b", "PFC-14"),
    (r"\bc2f6\b|\bpfc[- ]?116\b|\bhexafluoroethane\b", "PFC-116"),
)

_R_NUMBER = re.compile(r"(?<![a-z0-9])(?:r|refrigerant|freon|hfc|hcfc|cfc)[- ]?(\d{2,4}(?:-10mee)?[a-z]{0,3})(?![a-z0-9])")
_CO2 = re.compile(r"(?<![a-z0-9])(?:r[- ]?744|co2|carbon dioxide)(?![a-z0-9])")


@dataclass(frozen=True)
class Refrigerant:
    name: str  # the EPA Hub's name when it has one ("R-410A", "HFC-134a", "SF6")
    family: str  # hfc | pfc | sf6 | nf3 | co2 | blend | hcfc | cfc | halon | other
    raw: str  # the text it was read from

    @property
    def montreal(self) -> bool:
        """CFCs, HCFCs and halons: Montreal Protocol gases, outside the GHG Protocol's Scope 1."""

        return self.family in ("cfc", "hcfc", "halon")


def _from_number(number: str, prefix: str, raw: str) -> Refrigerant | None:
    low = number.lower()
    if prefix == "hcfc" or (prefix != "hfc" and low in _HCFC):
        return Refrigerant(f"HCFC-{low}", "hcfc", raw)
    if prefix == "cfc" or (prefix != "hfc" and low in _CFC):
        return Refrigerant(f"R-{low.upper()}" if low in ("500", "502", "503") else f"CFC-{low}", "cfc", raw)
    if low in _HFC:
        return Refrigerant(f"HFC-{low}", "hfc", raw)
    if low in _OTHER:
        return Refrigerant(_OTHER[low], "other", raw)
    if low == "744":
        return Refrigerant("CO2", "co2", raw)
    # Zeotropic (4xx) and azeotropic (5xx) blends: R-404A, R-407C, R-410A, R-454B, R-507A.
    if re.fullmatch(r"[45]\d\d[a-z]?", low):
        return Refrigerant(f"R-{low.upper()}", "blend", raw)
    return None


def find_refrigerant(text: str) -> Refrigerant | None:
    """The first refrigerant or fire-suppression gas named in ``text``, or None."""

    low = " ".join(str(text).lower().split())
    for pattern, name, family in _TRADE_NAMES:
        match = re.search(pattern, low)
        if match:
            return Refrigerant(match.group(0).title() if family == "halon" else name, family, match.group(0))
    for pattern, name in _FAMILY_WORDS:
        match = re.search(pattern, low)
        if match:
            return Refrigerant(name, "pfc" if name.startswith("PFC") else name.lower(), match.group(0))
    for match in _R_NUMBER.finditer(low):
        prefix = re.match(r"[a-z]+", match.group(0))
        found = _from_number(match.group(1), prefix.group(0) if prefix else "r", match.group(0))
        if found is not None:
            return found
    match = _CO2.search(low)
    if match:
        return Refrigerant("CO2", "co2", match.group(0))
    return None


# =========================================================================================
# Masses
# =========================================================================================
_NUM = r"(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?|\.\d+)"
_LB = r"(?:lbs?\.?|pounds?|#)"
_OZ = r"(?:oz\.?|ounces?)"
_KG = r"(?:kgs?\.?|kilograms?)"
_G = r"(?:g|grams?)"
_LB_OZ = re.compile(rf"(?<![\d.]){_NUM}\s*{_LB}\s*,?\s*(?:and\s+)?{_NUM}\s*{_OZ}(?![a-z])", re.I)
_SINGLE = re.compile(rf"(?<![\d.]){_NUM}\s*(?:({_LB})|({_OZ})|({_KG})|({_G}))(?![a-z0-9])", re.I)
_BARE = re.compile(rf"^\s*{_NUM}\s*$")


@dataclass(frozen=True)
class Mass:
    value: float
    unit: str  # "lb" or "kg"
    raw: str
    converted: bool = False  # ounces -> lb or grams -> kg


def _num(text: str) -> float:
    return float(text.replace(",", ""))


def parse_mass(text: str, default_unit: str | None = None) -> Mass | None:
    """A refrigerant amount in lb or kg. A bare number takes ``default_unit`` (from a
    column header such as "Added (lb)"); without one it is not a mass."""

    raw = str(text)
    match = _LB_OZ.search(raw)
    if match:
        return Mass(_num(match.group(1)) + _num(match.group(2)) / 16, "lb", match.group(0), converted=True)
    match = _SINGLE.search(raw)
    if match:
        value = _num(match.group(1))
        if match.group(2):
            return Mass(value, "lb", match.group(0))
        if match.group(3):
            return Mass(value / 16, "lb", match.group(0), converted=True)
        if match.group(4):
            return Mass(value, "kg", match.group(0))
        return Mass(value / 1000, "kg", match.group(0), converted=True)
    match = _BARE.match(raw)
    if match and default_unit:
        unit = mass_unit(default_unit)
        if unit == "oz":
            return Mass(_num(match.group(1)) / 16, "lb", raw.strip(), converted=True)
        if unit == "g":
            return Mass(_num(match.group(1)) / 1000, "kg", raw.strip(), converted=True)
        if unit in ("lb", "kg"):
            return Mass(_num(match.group(1)), unit, raw.strip())
    return None


def mass_unit(text: str | None) -> str | None:
    """lb / oz / kg / g named in a header or label ("Added (lbs)", "Qty (kg)"), else None."""

    if not text:
        return None
    low = str(text).lower()
    if re.search(r"(?<![a-z])(?:lbs?|pounds?)(?![a-z])", low):
        return "lb"
    if re.search(r"(?<![a-z])(?:oz|ounces?)(?![a-z])", low):
        return "oz"
    if re.search(r"(?<![a-z])(?:kgs?|kilograms?)(?![a-z])", low):
        return "kg"
    if re.search(r"(?<![a-z])(?:g|grams?)(?![a-z])", low):
        return "g"
    return None
