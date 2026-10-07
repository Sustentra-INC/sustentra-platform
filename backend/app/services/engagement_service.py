"""S1-BE-002 - engagements (migration 0008), read and written in the caller's RLS context.

The request's DB session already carries the tenant context set by
``get_current_user`` (org users: their org; provider admins: provider scope), so
every query here is filtered by Row-Level Security as well as by the API's checks.
"""

from __future__ import annotations

import json
import uuid
from datetime import date
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

_COLUMNS = (
    "id, org_id, name, client_name, reporting_period_start, reporting_period_end, status, settings, "
    "created_by, created_at, updated_at"
)

# Columns PATCH may change (settings is replaced as a whole).
UPDATABLE = ("name", "client_name", "reporting_period_start", "reporting_period_end", "status", "settings")


def _row(mapping: Any) -> dict[str, Any]:
    row = dict(mapping)
    if isinstance(row.get("settings"), str):  # pragma: no cover - asyncpg returns JSONB as str without a codec
        row["settings"] = json.loads(row["settings"])
    return row


def _as_uuid(value: str) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(value))
    except ValueError:
        return None


async def list_engagements(
    db: AsyncSession, *, include_archived: bool = False, org_id: uuid.UUID | None = None
) -> list[dict[str, Any]]:
    where = ["TRUE"]
    params: dict[str, Any] = {}
    if not include_archived:
        where.append("status = 'active'")
    if org_id is not None:
        where.append("org_id = :org_id")
        params["org_id"] = org_id
    rows = await db.execute(
        text(f"SELECT {_COLUMNS} FROM engagements WHERE {' AND '.join(where)} ORDER BY updated_at DESC, id"),
        params,
    )
    return [_row(r) for r in rows.mappings()]


async def get_engagement(db: AsyncSession, engagement_id: str) -> dict[str, Any] | None:
    key = _as_uuid(engagement_id)
    if key is None:
        return None
    row = (
        await db.execute(text(f"SELECT {_COLUMNS} FROM engagements WHERE id = :id"), {"id": key})
    ).mappings().first()
    return _row(row) if row else None


async def create_engagement(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    created_by: uuid.UUID,
    name: str,
    client_name: str | None,
    reporting_period_start: date | None,
    reporting_period_end: date | None,
    settings: dict[str, Any],
) -> dict[str, Any]:
    row = (
        await db.execute(
            text(
                f"""
                INSERT INTO engagements
                  (org_id, name, client_name, reporting_period_start, reporting_period_end, settings, created_by)
                VALUES
                  (:org_id, :name, :client_name, :start, :end, CAST(:settings AS jsonb), :created_by)
                RETURNING {_COLUMNS}
                """
            ),
            {
                "org_id": org_id,
                "name": name,
                "client_name": client_name,
                "start": reporting_period_start,
                "end": reporting_period_end,
                "settings": json.dumps(settings),
                "created_by": created_by,
            },
        )
    ).mappings().one()
    return _row(row)


async def update_engagement(db: AsyncSession, engagement_id: uuid.UUID, changes: dict[str, Any]) -> dict[str, Any]:
    assignments = []
    params: dict[str, Any] = {"id": engagement_id}
    for column in UPDATABLE:
        if column not in changes:
            continue
        if column == "settings":
            assignments.append("settings = CAST(:settings AS jsonb)")
            params["settings"] = json.dumps(changes["settings"])
        else:
            assignments.append(f"{column} = :{column}")
            params[column] = changes[column]
    assignments.append("updated_at = now()")
    row = (
        await db.execute(
            text(f"UPDATE engagements SET {', '.join(assignments)} WHERE id = :id RETURNING {_COLUMNS}"), params
        )
    ).mappings().one()
    return _row(row)
