"""The GWP sets the calculation uses: the ones chosen on the Methodology review screen.

Product rulings (Claire, C-M6 and after): the GWP set chosen on Methodology review drives the calculation.

- A GWP row (the fixed field or a ``gwp:N`` row) counts only once a reviewer accepted or edited it.
- The driving set is the confirmed set whose use note (``applies_to``) is empty or general ("default",
  "primary", "unless otherwise stated"). A confirmed set whose note limits it to refrigerants or HFCs drives
  only the refrigerant GWPs. A set whose note says it is embedded in third-party factors drives nothing: it is
  shown as information. Two different general sets block ("keep one").
- With no choice the calculation keeps its default, AR5, and every screen says so.
- A horizon of "Not stated" is taken as 100-year (the GHG Protocol requires it) and labelled as assumed. The
  reference data holds 100-year values only (AR4, AR5 and AR6): a stated 20-year or 500-year horizon is
  blocked, never replaced by another set or horizon.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Mapping
from typing import Any, NotRequired, TypedDict

from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.reference.emission_factor_loader import DEFAULT_GWP_SET, GWP_SETS
from backend.app.services import workpaper_item_service

KIND = "methodology"
FIELD_ID = "gwp"
SUPPORTED_HORIZON = "100-year"
NOT_STATED = "Not stated"
DEFAULT_LABEL = f"{DEFAULT_GWP_SET} (default — not set in Methodology review)"
UNSUPPORTED = "not supported for calculation"
KEEP_ONE = "Two GWP sets confirmed in Methodology review — keep one"

GENERAL, REFRIGERANTS, EMBEDDED = "general", "refrigerants", "embedded"
# Embedded in third-party factors: needs "embedded", "included in", "built into" or "inside", and a mention of factors.
_EMBEDDED = re.compile(r"\b(embedded|included|built|inside|within)\b[^;.]*\bfactors?\b", re.I)
# Limited to refrigerants: refrigerant, HFC, HCFC, an R-number, or cooling / AC equipment wording.
_REFRIGERANT = re.compile(
    r"\b(refrigerants?|hfcs?|hcfcs?|r-?\d{2,3}[a-z]?|(air[- ]conditioning|cooling|a/?c|hvac)\s+equipment)\b", re.I)
# "except refrigerants", "other than HFCs": the set covers everything else, so it is general.
_NEGATED = re.compile(r"\b(except|excluding|other than|apart from|not for|without)\b[^;.]*$", re.I)


def _scoped_to_refrigerants(text: str) -> bool:
    return any(not _NEGATED.search(text[:m.start()]) for m in _REFRIGERANT.finditer(text))


def use_of(note: Any) -> str:
    """What a set's use note limits it to: refrigerants, embedded in third-party factors (drives nothing), or
    nothing / the general case ("default", "primary", "unless otherwise stated", an empty note)."""

    text = str(note or "")
    if _EMBEDDED.search(text):
        return EMBEDDED
    if _scoped_to_refrigerants(text):
        return REFRIGERANTS
    return GENERAL


class GwpChoice(TypedDict):
    set: str  # the set the numbers use (the default when blocked: nothing is calculated then)
    horizon: str
    source: str  # "methodology" | "default" | "settings"
    supported: bool
    label: str  # what Results, Output and the workpaper print
    message: str | None  # why it is blocked
    row: str | None  # the Methodology row that drove the choice (None: the default)
    refrigerant_set: NotRequired[str]  # the set the refrigerant GWPs use (the same unless a row limits one to them)
    refrigerant_row: NotRequired[str | None]
    info: NotRequired[list[str]]  # confirmed sets that drive nothing, as sentences


def default_choice() -> GwpChoice:
    return {"set": DEFAULT_GWP_SET, "horizon": SUPPORTED_HORIZON, "source": "default", "supported": True,
            "label": DEFAULT_LABEL, "message": None, "row": None, "refrigerant_set": DEFAULT_GWP_SET,
            "refrigerant_row": None, "info": []}


def _confirmed(record: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """The value of a record's decision when the reviewer accepted or edited it, else None."""

    if not record or record.get("removed"):
        return None
    decision = record.get("decision") or {}
    value = decision.get("value")
    if decision.get("status") in ("accepted", "edited") and isinstance(value, Mapping):
        return dict(value)
    return None


def _blocked(horizon: Any, message: str, label: str, row: str | None = None) -> GwpChoice:
    return {"set": DEFAULT_GWP_SET, "horizon": str(horizon), "source": "methodology", "supported": False,
            "label": label, "message": message, "row": row, "refrigerant_set": DEFAULT_GWP_SET,
            "refrigerant_row": None, "info": []}


def _problem(value: Mapping[str, Any], row: str) -> GwpChoice | None:
    """A confirmed set the data cannot calculate: an unknown set, or a stated horizon other than 100-year."""

    gwp_set, horizon = value.get("set"), value.get("horizon")
    if gwp_set not in GWP_SETS:
        return _blocked(horizon, f"The GWP set chosen in Methodology review ({gwp_set}) is {UNSUPPORTED}. "
                        f"Choose one of {', '.join(GWP_SETS)} there.", f"{gwp_set} — {UNSUPPORTED}", row)
    if horizon not in (SUPPORTED_HORIZON, NOT_STATED):
        return _blocked(horizon, f"The {horizon} horizon chosen in Methodology review is {UNSUPPORTED}: the "
                        f"reference data holds {SUPPORTED_HORIZON} GWPs only. Nothing is calculated until the "
                        f"horizon there is {SUPPORTED_HORIZON}.", f"{gwp_set} {horizon} — {UNSUPPORTED}", row)
    return None


def _label(value: Mapping[str, Any], position: int) -> str:
    row = f"GWP set row {position}"
    if value.get("horizon") == NOT_STATED:
        return f"{value['set']} · {SUPPORTED_HORIZON} (assumed — horizon not stated{'; ' + row if position > 1 else ''})"
    return f"{value['set']} · {SUPPORTED_HORIZON} (Methodology review{', ' + row if position > 1 else ''})"


def _one(rows: list[tuple[int, str, dict[str, Any]]]) -> tuple[int, str, dict[str, Any]] | None:
    """The single choice of rows that all name the same set (a stated horizon is kept over "Not stated"); None
    when they name different sets."""

    if len({v["set"] for _, _, v in rows}) > 1:
        return None
    return next((r for r in rows if r[2].get("horizon") != NOT_STATED), rows[0])


def choice_from_records(records: Mapping[str, Mapping[str, Any]]) -> GwpChoice:
    """The choice of the GWP rows of Methodology review (the fixed field, then the rows the report or the
    reviewer added, oldest first). See the module docstring for which set drives what."""

    keys = [k for k in records if k == FIELD_ID or k.startswith(f"{FIELD_ID}:")]
    ordered = sorted(keys, key=lambda k: (k != FIELD_ID,))  # the fixed field first, rows in stored order
    confirmed = [(i + 1, k, v) for i, k in enumerate(ordered) if (v := _confirmed(records[k])) is not None]
    if not confirmed:
        return default_choice()
    general = [c for c in confirmed if use_of(c[2].get("applies_to")) == GENERAL]
    fridge = [c for c in confirmed if use_of(c[2].get("applies_to")) == REFRIGERANTS]
    info = [f"{v['set']} ({v.get('applies_to')}): information only, it drives no calculation."
            for _, _, v in confirmed if use_of(v.get("applies_to")) == EMBEDDED]
    for position, row, value in [*general, *fridge]:  # a set that drives something must be one the data holds
        if (bad := _problem(value, row)) is not None:
            return bad
    main = _one(general) if general else None
    if general and main is None:
        return _blocked("", KEEP_ONE, KEEP_ONE)
    sub = _one(fridge) if fridge else None
    if fridge and sub is None:
        return _blocked("", "Two GWP sets confirmed for refrigerants in Methodology review — keep one",
                        "Two GWP sets confirmed for refrigerants — keep one")
    if main is None and sub is None:  # only information rows
        choice = default_choice()
        choice["info"] = info
        return choice
    choice = default_choice()
    if main is not None:
        position, row, value = main
        choice["set"], choice["source"], choice["row"] = str(value["set"]), "methodology", row
        choice["label"], choice["refrigerant_set"], choice["refrigerant_row"] = _label(value, position), str(value["set"]), row
    if sub is not None:
        position, row, value = sub
        fridge_label = _label(value, position)
        choice["refrigerant_set"], choice["refrigerant_row"], choice["source"] = str(value["set"]), row, "methodology"
        if main is None:
            choice["label"] = f"{DEFAULT_LABEL} for fuels and electricity; {fridge_label} for refrigerants"
        elif value["set"] != main[2]["set"]:
            choice["label"] = f"{choice['label']} for fuels and electricity; {fridge_label} for refrigerants"
    choice["info"] = info
    return choice


def choice_from_record(record: Mapping[str, Any] | None) -> GwpChoice:
    """The choice a single stored record of the fixed "gwp" field makes."""

    return choice_from_records({FIELD_ID: record} if record else {})


async def load_choice(db: AsyncSession, engagement_id: uuid.UUID) -> GwpChoice:
    rows = await workpaper_item_service.list_items(db, engagement_id, KIND)
    return choice_from_records({r["item_key"]: r["payload"] for r in rows
                                if r["item_key"] == FIELD_ID or str(r["item_key"]).startswith(f"{FIELD_ID}:")})


async def attach_choice(db: AsyncSession, engagement: dict[str, Any]) -> dict[str, Any]:
    """The engagement with the Methodology GWP choice the recalculation reads."""

    return {**engagement, "methodology_gwp": await load_choice(db, engagement["id"])}
