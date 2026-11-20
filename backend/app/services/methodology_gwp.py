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


def default_choice() -> GwpChoice:
    return {"set": DEFAULT_GWP_SET, "horizon": SUPPORTED_HORIZON, "source": "default", "supported": True,
            "label": DEFAULT_LABEL, "message": None}


def choice_from_record(record: Mapping[str, Any] | None) -> GwpChoice:
    """The choice a stored methodology record of the "gwp" field makes."""

    decision = (record or {}).get("decision") or {}
    value = decision.get("value")
    if decision.get("status") not in ("accepted", "edited") or not isinstance(value, Mapping):
        return default_choice()
    gwp_set, horizon = value.get("set"), value.get("horizon")
    if gwp_set not in GWP_SETS:
        return {"set": DEFAULT_GWP_SET, "horizon": str(horizon), "source": "methodology", "supported": False,
                "label": f"{gwp_set} — {UNSUPPORTED}",
                "message": f"The GWP set chosen in Methodology review ({gwp_set}) is {UNSUPPORTED}. "
                           f"Choose one of {', '.join(GWP_SETS)} there."}
    if horizon != SUPPORTED_HORIZON:
        return {"set": DEFAULT_GWP_SET, "horizon": str(horizon), "source": "methodology", "supported": False,
                "label": f"{gwp_set} {horizon} — {UNSUPPORTED}",
                "message": f"The {horizon} horizon chosen in Methodology review is {UNSUPPORTED}: the reference "
                           f"data holds {SUPPORTED_HORIZON} GWPs only. Nothing is calculated until the horizon "
                           f"there is {SUPPORTED_HORIZON}."}
    return {"set": str(gwp_set), "horizon": SUPPORTED_HORIZON, "source": "methodology", "supported": True,
            "label": f"{gwp_set} · {SUPPORTED_HORIZON} (Methodology review)", "message": None}


async def load_choice(db: AsyncSession, engagement_id: uuid.UUID) -> GwpChoice:
    rows = await workpaper_item_service.get_items(db, engagement_id, KIND, [FIELD_ID])
    return choice_from_record(rows[0]["payload"] if rows else None)


async def attach_choice(db: AsyncSession, engagement: dict[str, Any]) -> dict[str, Any]:
    """The engagement with the Methodology GWP choice the recalculation reads."""

    return {**engagement, "methodology_gwp": await load_choice(db, engagement["id"])}
