"""COMP-002 - reading an org's audit log (org admin for their org, provider admin for any).

- Newest first: ORDER BY created_at DESC, id DESC. The (created_at, id) pair is the
  keyset, so pages never skip or repeat a row, even when many events share one
  timestamp (one transaction writes several with the same now()).
- The cursor is opaque to clients: urlsafe base64 of "<created_at iso>|<id>". A
  cursor that does not decode -> 400. Filters must be sent again with each page.
- Filters: event_type (exact), user_id (events BY or ABOUT that user), from_date /
  to_date (dates, UTC, both inclusive).
- Scope: WHERE org_id = :org plus RLS (tenant scope for an org admin). Events with
  no org (provider-only actions, failed logins for unknown accounts) never appear.
- Display names: the actor / target user's name (or email) when the caller can see
  that user. Under tenant RLS an org admin cannot see provider admins, so their
  actions show as "Sustentra"; erased users (COMP-001) show as "Deleted User".
  IP addresses and user agents are not returned.
"""

from __future__ import annotations

import base64
import binascii
import json
import uuid
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

MAX_LIMIT = 100
DEFAULT_LIMIT = 50

_ORG_NOT_FOUND = HTTPException(status_code=404, detail="Organization not found")
_BAD_CURSOR = HTTPException(status_code=400, detail="Invalid cursor")


def encode_cursor(created_at: datetime, row_id: uuid.UUID) -> str:
    raw = f"{created_at.isoformat()}|{row_id}".encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)).decode()
        stamp, row_id = raw.split("|", 1)
        created_at = datetime.fromisoformat(stamp)
        if created_at.tzinfo is None:
            raise ValueError("naive timestamp")
        return created_at, uuid.UUID(row_id)
    except (ValueError, UnicodeDecodeError, binascii.Error):
        raise _BAD_CURSOR from None


def _metadata(value: Any) -> dict[str, Any]:
    if isinstance(value, str):
        value = json.loads(value)
    return value if isinstance(value, dict) else {}


def _display(name: str | None, email: str | None, role: str | None, user_id: Any) -> str | None:
    if name:
        return name
    if email:
        return email
    if role == "provider_admin":
        return "Sustentra"
    return None if user_id is None else "Unknown user"


async def list_events(db: AsyncSession, org_id: str, *, event_type: str | None, user_id: uuid.UUID | None,
                      from_date: date | None, to_date: date | None, cursor: str | None,
                      limit: int) -> tuple[list[dict[str, Any]], str | None]:
    try:
        oid = uuid.UUID(str(org_id))
    except ValueError:
        raise _ORG_NOT_FOUND from None
    if (await db.execute(text("SELECT 1 FROM organizations WHERE id = :id"), {"id": oid})).first() is None:
        raise _ORG_NOT_FOUND

    where = ["a.org_id = :org_id"]
    params: dict[str, Any] = {"org_id": oid, "limit": limit + 1}
    if event_type:
        where.append("a.event_type = :event_type")
        params["event_type"] = event_type
    if user_id is not None:
        where.append("(a.actor_user_id = :user_id OR (a.target_type = 'user' AND a.target_id = :user_id_text))")
        params["user_id"] = user_id
        params["user_id_text"] = str(user_id)
    if from_date is not None:
        where.append("a.created_at >= :from_ts")
        params["from_ts"] = datetime.combine(from_date, time.min, tzinfo=UTC)
    if to_date is not None:
        where.append("a.created_at < :to_ts")
        params["to_ts"] = datetime.combine(to_date + timedelta(days=1), time.min, tzinfo=UTC)
    if cursor:
        params["c_at"], params["c_id"] = decode_cursor(cursor)
        where.append("(a.created_at, a.id) < (:c_at, :c_id)")

    rows = (await db.execute(
        text(f"""
            SELECT a.id, a.event_type, a.created_at, a.actor_user_id, a.actor_role, a.target_type, a.target_id,
                   a.metadata,
                   NULLIF(trim(COALESCE(au.full_name, concat_ws(' ', au.first_name, au.last_name))), '') AS actor_name,
                   au.email AS actor_email,
                   NULLIF(trim(COALESCE(tu.full_name, concat_ws(' ', tu.first_name, tu.last_name))), '') AS target_name,
                   tu.email AS target_email, tu.role AS target_role
              FROM audit_logs a
              LEFT JOIN users au ON au.id = a.actor_user_id
              LEFT JOIN users tu ON a.target_type = 'user' AND tu.id::text = a.target_id
             WHERE {" AND ".join(where)}
             ORDER BY a.created_at DESC, a.id DESC
             LIMIT :limit
        """),
        params,
    )).mappings().all()

    more = len(rows) > limit
    rows = rows[:limit]
    items = [{
        "id": r["id"],
        "event_type": r["event_type"],
        "created_at": r["created_at"],
        "actor_user_id": r["actor_user_id"],
        "actor_role": r["actor_role"],
        "actor": _display(r["actor_name"], r["actor_email"], r["actor_role"], r["actor_user_id"]),
        "target_type": r["target_type"],
        "target_id": r["target_id"],
        "target": (_display(r["target_name"], r["target_email"], r["target_role"], r["target_id"])
                   if r["target_type"] == "user" else None),
        "metadata": _metadata(r["metadata"]),
    } for r in rows]
    next_cursor = encode_cursor(rows[-1]["created_at"], rows[-1]["id"]) if more and rows else None
    return items, next_cursor
