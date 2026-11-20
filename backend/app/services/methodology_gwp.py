"""The GWP set the calculation uses: the one chosen on the Methodology review screen.

Product ruling (Claire, C-M6): the GWP set chosen on Methodology review drives the calculation.
Only the fixed "gwp" field counts, and only once a reviewer accepted or edited it (a suggestion,
a pending or a rejected decision is not a choice). With no choice the calculation keeps its
default, AR5, and every screen says so. The reference data holds 100-year values only (AR4, AR5
and AR6), so any other horizon is blocked, never replaced by another set or horizon.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from typing import Any, TypedDict

from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.reference.emission_factor_loader import DEFAULT_GWP_SET, GWP_SETS
from backend.app.services import workpaper_item_service

KIND = "methodology"
FIELD_ID = "gwp"
SUPPORTED_HORIZON = "100-year"
DEFAULT_LABEL = f"{DEFAULT_GWP_SET} (default — not set in Methodology review)"
UNSUPPORTED = "not supported for calculation"


class GwpChoice(TypedDict):
    set: str  # the set the numbers use (the default when blocked: nothing is calculated then)
    horizon: str
    source: str  # "methodology" | "default"
    supported: bool
    label: str  # what Results and the workpaper print
    message: str | None  # why it is blocked
    row: str | None  # the Methodology row that drove the choice (None: the default)


def default_choice() -> GwpChoice:
    return {"set": DEFAULT_GWP_SET, "horizon": SUPPORTED_HORIZON, "source": "default", "supported": True,
            "label": DEFAULT_LABEL, "message": None, "row": None}


def _confirmed(record: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """The value of a record's decision when the reviewer accepted or edited it, else None."""

    if not record or record.get("removed"):
        return None
    decision = record.get("decision") or {}
    value = decision.get("value")
    if decision.get("status") in ("accepted", "edited") and isinstance(value, Mapping):
        return dict(value)
    return None


def _blocked(gwp_set: Any, horizon: Any, message: str, label: str, source: str = "methodology",
             row: str | None = None) -> GwpChoice:
    return {"set": DEFAULT_GWP_SET, "horizon": str(horizon), "source": source, "supported": False,
            "label": label, "message": message, "row": row}


def _choice(value: Mapping[str, Any], row: str, position: int) -> GwpChoice:
    gwp_set, horizon = value.get("set"), value.get("horizon")
    where = "Methodology review" if position == 1 else f"Methodology review, GWP set row {position}"
    if gwp_set not in GWP_SETS:
        return _blocked(gwp_set, horizon, f"The GWP set chosen in Methodology review ({gwp_set}) is {UNSUPPORTED}. "
                        f"Choose one of {', '.join(GWP_SETS)} there.", f"{gwp_set} — {UNSUPPORTED}", row=row)
    if horizon != SUPPORTED_HORIZON:
        return _blocked(gwp_set, horizon,
                        f"The {horizon} horizon chosen in Methodology review is {UNSUPPORTED}: the reference data "
                        f"holds {SUPPORTED_HORIZON} GWPs only. Nothing is calculated until the horizon there is "
                        f"{SUPPORTED_HORIZON}.", f"{gwp_set} {horizon} — {UNSUPPORTED}", row=row)
    return {"set": str(gwp_set), "horizon": SUPPORTED_HORIZON, "source": "methodology", "supported": True,
            "label": f"{gwp_set} · {SUPPORTED_HORIZON} ({where})", "message": None, "row": row}


def choice_from_records(records: Mapping[str, Mapping[str, Any]]) -> GwpChoice:
    """The choice of the GWP rows of Methodology review (the fixed field, then the rows the report or the
    reviewer added, oldest first). The driving set is the row the reviewer accepted or edited. Two confirmed
    rows that name different sets or horizons block the calculation: one source of truth."""

    keys = [k for k in records if k == FIELD_ID or k.startswith(f"{FIELD_ID}:")]
    ordered = sorted(keys, key=lambda k: (k != FIELD_ID,))  # the fixed field first, rows in stored order
    confirmed = [(i + 1, k, v) for i, k in enumerate(ordered) if (v := _confirmed(records[k])) is not None]
    if not confirmed:
        return default_choice()
    distinct = {(v.get("set"), v.get("horizon")) for _, _, v in confirmed}
    if len(distinct) > 1:
        sets = {v.get("set") for _, _, v in confirmed}
        message = ("Two GWP sets confirmed in Methodology review — keep one" if len(sets) > 1 else
                   "Two GWP horizons confirmed in Methodology review — keep one")
        return _blocked(None, "", message, message)
    position, row, value = confirmed[0]
    return _choice(value, row, position)


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
