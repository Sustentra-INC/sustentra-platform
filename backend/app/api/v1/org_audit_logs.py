"""COMP-002: keyset-paginated audit-log query for one organization."""

import base64
import binascii
import json
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.db import get_db_session
from .deps import Principal, require_org_admin

router = APIRouter(prefix="/orgs/{org_id}/audit-logs", tags=["org-audit-logs"])

_PAGE_SIZE = 100
_CURSOR_VERSION = 1
_MAX_CURSOR_LENGTH = 4096
_EVENT_TYPE_PATTERN = re.compile(r"^[a-z][a-z0-9_]{1,63}$")
_CURSOR_KEYS = frozenset({"v", "org_id", "event_type", "user_id", "from_date", "to_date", "created_at", "id"})
_CURSOR_TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")

_INVALID_CURSOR = HTTPException(status_code=422, detail="Invalid cursor")
_CURSOR_SCOPE_MISMATCH = HTTPException(
    status_code=400,
    detail="Cursor does not match the requested organization or filters",
)
_INVALID_DATE_RANGE = HTTPException(status_code=422, detail="from_date must be less than or equal to to_date")


class AuditLogItem(BaseModel):
    id: UUID
    org_id: UUID
    actor_user_id: UUID | None
    actor_role: str | None
    actor_email: str | None
    event_type: str
    target_type: str | None
    target_id: str | None
    request_id: str | None
    ip_address: str | None
    user_agent: str | None
    metadata: dict[str, Any]
    created_at: datetime


class AuditLogPage(BaseModel):
    items: list[AuditLogItem]
    next_cursor: str | None


@dataclass(frozen=True)
class _CursorState:
    org_id: UUID
    event_type: str | None
    user_id: UUID | None
    from_date: date | None
    to_date: date | None
    created_at: datetime
    row_id: UUID


def _utc_day_start(day: date) -> datetime:
    return datetime.combine(day, time.min, tzinfo=UTC)


def _utc_day_end_exclusive(day: date) -> datetime | None:
    if day == date.max:
        return None
    return _utc_day_start(day) + timedelta(days=1)


def _encode_cursor(
    *,
    org_id: UUID,
    event_type: str | None,
    user_id: UUID | None,
    from_date: date | None,
    to_date: date | None,
    created_at: datetime,
    row_id: UUID,
) -> str:
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=UTC)
    payload = {
        "v": _CURSOR_VERSION,
        "org_id": str(org_id),
        "event_type": event_type,
        "user_id": str(user_id) if user_id else None,
        "from_date": from_date.isoformat() if from_date else None,
        "to_date": to_date.isoformat() if to_date else None,
        "created_at": created_at.astimezone(UTC).isoformat(),
        "id": str(row_id),
    }
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _required_non_empty_str(payload: dict[str, Any], key: str) -> str:
    if key not in payload:
        raise ValueError
    value = payload[key]
    if not isinstance(value, str) or value == "":
        raise ValueError
    return value


def _optional_non_empty_str(payload: dict[str, Any], key: str) -> str | None:
    if key not in payload:
        raise ValueError
    value = payload[key]
    if value is None:
        return None
    if not isinstance(value, str) or value == "":
        raise ValueError
    return value


def _decode_cursor(cursor: str) -> _CursorState:
    try:
        if cursor == "" or len(cursor) > _MAX_CURSOR_LENGTH:
            raise ValueError
        if _CURSOR_TOKEN_PATTERN.fullmatch(cursor) is None:
            raise ValueError

        padding = "=" * (-len(cursor) % 4)
        raw = base64.b64decode((cursor + padding).encode("ascii"), altchars=b"-_", validate=True).decode("utf-8")
        data = json.loads(raw)
        if not isinstance(data, dict) or set(data.keys()) != _CURSOR_KEYS or data.get("v") != _CURSOR_VERSION:
            raise ValueError

        event_type = _optional_non_empty_str(data, "event_type")
        if event_type is not None and _EVENT_TYPE_PATTERN.fullmatch(event_type) is None:
            raise ValueError

        user_id_raw = _optional_non_empty_str(data, "user_id")
        from_date_raw = _optional_non_empty_str(data, "from_date")
        to_date_raw = _optional_non_empty_str(data, "to_date")

        created_at = datetime.fromisoformat(_required_non_empty_str(data, "created_at"))
        if created_at.tzinfo is None:
            raise ValueError

        from_date = date.fromisoformat(from_date_raw) if from_date_raw else None
        to_date = date.fromisoformat(to_date_raw) if to_date_raw else None
        if from_date and to_date and from_date > to_date:
            raise ValueError

        return _CursorState(
            org_id=UUID(_required_non_empty_str(data, "org_id")),
            event_type=event_type,
            user_id=UUID(str(user_id_raw)) if user_id_raw else None,
            from_date=from_date,
            to_date=to_date,
            created_at=created_at.astimezone(UTC),
            row_id=UUID(_required_non_empty_str(data, "id")),
        )
    except (ValueError, TypeError, KeyError, json.JSONDecodeError, binascii.Error, OverflowError, UnicodeDecodeError) as exc:
        raise _INVALID_CURSOR from exc


def _assert_cursor_scope(
    cursor_state: _CursorState,
    *,
    org_id: UUID,
    event_type: str | None,
    user_id: UUID | None,
    from_date: date | None,
    to_date: date | None,
) -> None:
    if (
        cursor_state.org_id != org_id
        or cursor_state.event_type != event_type
        or cursor_state.user_id != user_id
        or cursor_state.from_date != from_date
        or cursor_state.to_date != to_date
    ):
        raise _CURSOR_SCOPE_MISMATCH


def _to_item(row: Any) -> AuditLogItem:
    metadata = row["metadata"] if isinstance(row["metadata"], dict) else {}
    return AuditLogItem(
        id=row["id"],
        org_id=row["org_id"],
        actor_user_id=row["actor_user_id"],
        actor_role=row["actor_role"],
        actor_email=row["actor_email"],
        event_type=row["event_type"],
        target_type=row["target_type"],
        target_id=row["target_id"],
        request_id=row["request_id"],
        ip_address=row["ip_address"],
        user_agent=row["user_agent"],
        metadata=metadata,
        created_at=row["created_at"],
    )


@router.get("", response_model=AuditLogPage)
async def list_org_audit_logs(
    org_id: UUID,
    principal: Annotated[Principal, Depends(require_org_admin)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    event_type: Annotated[
        str | None,
        Query(
            pattern=r"^[a-z][a-z0-9_]{1,63}$",
            description="Optional audit event type filter.",
        ),
    ] = None,
    user_id: Annotated[
        UUID | None,
        Query(description="Optional actor user filter (mapped to actor_user_id)."),
    ] = None,
    from_date: Annotated[
        date | None,
        Query(
            description=(
                "Inclusive UTC calendar date lower bound. Events from 00:00:00Z on this date are included."
            ),
        ),
    ] = None,
    to_date: Annotated[
        date | None,
        Query(
            description=(
                "Inclusive UTC calendar date upper bound. Events through 23:59:59.999999Z on this date are included."
            ),
        ),
    ] = None,
    cursor: Annotated[
        str | None,
        Query(description="Opaque cursor for keyset pagination."),
    ] = None,
) -> AuditLogPage:
    if from_date and to_date and from_date > to_date:
        raise _INVALID_DATE_RANGE

    cursor_state = _decode_cursor(cursor) if cursor is not None else None
    if cursor_state is not None:
        _assert_cursor_scope(
            cursor_state,
            org_id=org_id,
            event_type=event_type,
            user_id=user_id,
            from_date=from_date,
            to_date=to_date,
        )

    conditions = ["l.org_id = :org_id"]
    params: dict[str, Any] = {"org_id": org_id, "limit": _PAGE_SIZE + 1}

    if event_type:
        conditions.append("l.event_type = :event_type")
        params["event_type"] = event_type
    if user_id:
        conditions.append("l.actor_user_id = :actor_user_id")
        params["actor_user_id"] = user_id
    if from_date:
        conditions.append("l.created_at >= :from_created_at")
        params["from_created_at"] = _utc_day_start(from_date)
    if to_date:
        to_created_at_exclusive = _utc_day_end_exclusive(to_date)
        if to_created_at_exclusive is not None:
            conditions.append("l.created_at < :to_created_at_exclusive")
            params["to_created_at_exclusive"] = to_created_at_exclusive
    if cursor_state is not None:
        conditions.append(
            "(l.created_at < :cursor_created_at OR (l.created_at = :cursor_created_at AND l.id < :cursor_id))"
        )
        params["cursor_created_at"] = cursor_state.created_at
        params["cursor_id"] = cursor_state.row_id

    query = text(
        f"""
        SELECT
          l.id,
          l.org_id,
          l.actor_user_id,
          l.actor_role,
          u.email AS actor_email,
          l.event_type,
          l.target_type,
          l.target_id,
          l.request_id,
          host(l.ip_address) AS ip_address,
          l.user_agent,
          l.metadata,
          l.created_at
        FROM audit_logs l
        LEFT JOIN users u ON u.id = l.actor_user_id
        WHERE {' AND '.join(conditions)}
        ORDER BY l.created_at DESC, l.id DESC
        LIMIT :limit
        """
    )

    rows = (await db.execute(query, params)).mappings().all()
    page_rows = rows[:_PAGE_SIZE]
    items = [_to_item(row) for row in page_rows]

    next_cursor: str | None = None
    if len(rows) > _PAGE_SIZE and page_rows:
        last = page_rows[-1]
        next_cursor = _encode_cursor(
            org_id=org_id,
            event_type=event_type,
            user_id=user_id,
            from_date=from_date,
            to_date=to_date,
            created_at=last["created_at"],
            row_id=last["id"],
        )

    return AuditLogPage(items=items, next_cursor=next_cursor)
