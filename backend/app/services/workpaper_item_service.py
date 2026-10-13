"""Workpaper items (migration 0012): requests, findings and examination states per
engagement, read and written in the caller's RLS context like ``engagement_service``."""

from __future__ import annotations

import json
import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

KINDS = ("ask", "finding", "examination", "document")

_COLUMNS = "kind, item_key, payload, created_by, created_at, updated_by, updated_at"


def _row(mapping: Any) -> dict[str, Any]:
    row = dict(mapping)
    if isinstance(row.get("payload"), str):  # pragma: no cover - asyncpg returns JSONB as str without a codec
        row["payload"] = json.loads(row["payload"])
    return row


async def list_items(db: AsyncSession, engagement_id: uuid.UUID, kind: str | None = None) -> list[dict[str, Any]]:
    where = "engagement_id = :engagement_id" + (" AND kind = :kind" if kind else "")
    params: dict[str, Any] = {"engagement_id": engagement_id}
    if kind:
        params["kind"] = kind
    rows = await db.execute(
        text(f"SELECT {_COLUMNS} FROM workpaper_items WHERE {where} ORDER BY created_at, item_key"), params
    )
    return [_row(r) for r in rows.mappings()]


async def save_item(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    engagement_id: uuid.UUID,
    kind: str,
    item_key: str,
    payload: dict[str, Any],
    user_id: uuid.UUID,
) -> dict[str, Any]:
    """Create the item, or replace its payload if it exists (latest save wins)."""

    row = (
        await db.execute(
            text(
                f"""
                INSERT INTO workpaper_items (org_id, engagement_id, kind, item_key, payload, created_by, updated_by)
                VALUES (:org_id, :engagement_id, :kind, :item_key, CAST(:payload AS jsonb), :user_id, :user_id)
                ON CONFLICT (engagement_id, kind, item_key) DO UPDATE
                  SET payload = EXCLUDED.payload, updated_by = EXCLUDED.updated_by, updated_at = now()
                RETURNING {_COLUMNS}
                """
            ),
            {
                "org_id": org_id,
                "engagement_id": engagement_id,
                "kind": kind,
                "item_key": item_key,
                "payload": json.dumps(payload, ensure_ascii=False),
                "user_id": user_id,
            },
        )
    ).mappings().one()
    return _row(row)
