"""MVP-245: what each organization spent in a month on Sustentra's AI and on Textract scans.

Read-only and provider_admin only (403 for any other role, 401 without a session). The numbers come from the
``ai_usage`` and ``textract_usage`` ledgers, which the provider scope reads across organizations.

No ``from __future__ import annotations``: FastAPI resolves these annotations at runtime.
"""

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.config import get_settings
from ...core.db import get_db_session
from .deps import Principal, require_provider_admin

router = APIRouter(prefix="/admin/spend", tags=["admin-spend"])

MICRO = 1_000_000
_MONTH = r"^\d{4}-(0[1-9]|1[0-2])$"

_SPEND = text(
    """
    SELECT o.id AS org_id, o.name, o.slug,
           COALESCE(a.cost, 0)::bigint AS ai, COALESCE(t.cost, 0)::bigint AS scans, COALESCE(t.pages, 0)::bigint AS pages
      FROM organizations o
      LEFT JOIN (SELECT org_id, SUM(cost_microusd) AS cost FROM ai_usage
                  WHERE created_at >= :start AND created_at < :end GROUP BY org_id) a ON a.org_id = o.id
      LEFT JOIN (SELECT org_id, SUM(cost_microusd) AS cost, SUM(pages) AS pages FROM textract_usage
                  WHERE created_at >= :start AND created_at < :end GROUP BY org_id) t ON t.org_id = o.id
     ORDER BY o.name, o.id
    """
)


class OrgSpend(BaseModel):
    org_id: str
    name: str
    slug: str
    ai_usd: float
    scan_usd: float
    scan_pages: int
    total_usd: float


class SpendResponse(BaseModel):
    month: str
    cap_usd: float
    items: list[OrgSpend]


def _bounds(month: str) -> tuple[datetime, datetime]:
    year, number = int(month[:4]), int(month[5:])
    start = datetime(year, number, 1, tzinfo=UTC)
    end = datetime(year + (number == 12), number % 12 + 1, 1, tzinfo=UTC)
    return start, end


@router.get("", response_model=SpendResponse)
async def month_spend(
    principal: Annotated[Principal, Depends(require_provider_admin)],
    db: Annotated[AsyncSession, Depends(get_db_session, scope="function")],
    month: Annotated[str | None, Query(pattern=_MONTH, description="YYYY-MM (UTC); default: this month")] = None,
) -> SpendResponse:
    chosen = month or datetime.now(UTC).strftime("%Y-%m")
    start, end = _bounds(chosen)
    rows = (await db.execute(_SPEND, {"start": start, "end": end})).mappings().all()
    items = [OrgSpend(org_id=str(r["org_id"]), name=r["name"], slug=r["slug"], ai_usd=max(0, r["ai"]) / MICRO,
                      scan_usd=max(0, r["scans"]) / MICRO, scan_pages=max(0, r["pages"]),
                      total_usd=(max(0, r["ai"]) + max(0, r["scans"])) / MICRO) for r in rows]
    return SpendResponse(month=chosen, cap_usd=get_settings().ai_monthly_cap_usd, items=items)
