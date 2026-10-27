"""Workpaper items (migration 0012): requests, findings and examination states per
engagement, read and written in the caller's RLS context like ``engagement_service``."""

from __future__ import annotations

import json
import re
import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import Text, bindparam, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.ext.asyncio import AsyncSession

KINDS = ("ask", "finding", "examination", "document")
# An item's key (a request's id, a finding's id ...): it appears in URLs.
ITEM_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9:._\-]{0,199}$")
MAX_PAYLOAD_BYTES = 32 * 1024

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


def payload_size(payload: dict[str, Any]) -> int:
    """The payload's size as MAX_PAYLOAD_BYTES counts it."""

    return len(json.dumps(payload))


async def get_items(
    db: AsyncSession,
    engagement_id: uuid.UUID,
    kind: str,
    keys: Sequence[str],
    *,
    for_update: bool = False,
) -> list[dict[str, Any]]:
    """The engagement's items of ``kind`` with these keys, ordered by key. ``for_update``
    locks them until the transaction ends; locking in key order means two writers that
    lock overlapping sets cannot deadlock."""

    statement = text(
        f"""
        SELECT {_COLUMNS} FROM workpaper_items
         WHERE engagement_id = :engagement_id AND kind = :kind AND item_key = ANY(:keys)
         ORDER BY item_key
         {"FOR UPDATE" if for_update else ""}
        """
    ).bindparams(bindparam("keys", type_=ARRAY(Text())))
    rows = await db.execute(statement, {"engagement_id": engagement_id, "kind": kind, "keys": list(keys)})
    return [_row(r) for r in rows.mappings()]


async def insert_item(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    engagement_id: uuid.UUID,
    kind: str,
    item_key: str,
    payload: dict[str, Any],
    user_id: uuid.UUID,
) -> dict[str, Any] | None:
    """Create the item. None when one with this key already exists: it is never replaced."""

    row = (
        await db.execute(
            text(
                f"""
                INSERT INTO workpaper_items (org_id, engagement_id, kind, item_key, payload, created_by, updated_by)
                VALUES (:org_id, :engagement_id, :kind, :item_key, CAST(:payload AS jsonb), :user_id, :user_id)
                ON CONFLICT (engagement_id, kind, item_key) DO NOTHING
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
    ).mappings().one_or_none()
    return _row(row) if row is not None else None


async def update_payload(
    db: AsyncSession,
    engagement_id: uuid.UUID,
    kind: str,
    item_key: str,
    payload: dict[str, Any],
    user_id: uuid.UUID,
) -> dict[str, Any]:
    """Replace an existing item's payload. The caller has locked the row and checked it."""

    row = (
        await db.execute(
            text(
                f"""
                UPDATE workpaper_items
                   SET payload = CAST(:payload AS jsonb), updated_by = :user_id, updated_at = now()
                 WHERE engagement_id = :engagement_id AND kind = :kind AND item_key = :item_key
                RETURNING {_COLUMNS}
                """
            ),
            {
                "engagement_id": engagement_id,
                "kind": kind,
                "item_key": item_key,
                "payload": json.dumps(payload, ensure_ascii=False),
                "user_id": user_id,
            },
        )
    ).mappings().one()
    return _row(row)


async def lock_request_numbers(db: AsyncSession, engagement_id: uuid.UUID) -> None:
    """Serialise request numbering for one engagement until the transaction ends.

    A transaction-scoped advisory lock: it needs no grants, is released at commit or
    rollback, and holds across API workers. Take it before any row lock (``get_items``
    with ``for_update``), so a send never holds a request another send is waiting for.
    """

    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(CAST(:key AS text), 0))"),
        {"key": f"workpaper-request-number:{engagement_id}"},
    )


async def next_request_number(db: AsyncSession, engagement_id: uuid.UUID) -> int:
    """One more than the highest request number on the engagement's requests, so numbering
    continues after requests numbered in the browser before MVP-86. Call it while holding
    ``lock_request_numbers``. Numbers outside 1 to 999,999,999 (only a hand-edited row
    could hold one) are ignored, so they cannot stop every later send."""

    # CASE, not a WHERE filter, guards the cast: Postgres may evaluate WHERE terms in any order.
    value = (
        await db.execute(
            text(
                """
                SELECT COALESCE(MAX(n), 0)::bigint + 1
                  FROM (SELECT CASE WHEN jsonb_typeof(payload->'requestNumber') = 'number'
                                    THEN floor((payload->>'requestNumber')::numeric) END AS n
                          FROM workpaper_items
                         WHERE engagement_id = :engagement_id AND kind = 'ask') AS numbers
                 WHERE n BETWEEN 1 AND 999999999
                """
            ),
            {"engagement_id": engagement_id},
        )
    ).scalar_one()
    return int(value)
