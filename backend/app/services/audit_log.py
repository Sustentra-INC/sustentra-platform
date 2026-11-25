"""Append-only audit events (DB-003 table). Never put secrets in `metadata`."""

from __future__ import annotations

import json
import uuid
from typing import Any

from sqlalchemy import Connection, text
from sqlalchemy.ext.asyncio import AsyncSession

_INSERT = text(
    """
    INSERT INTO audit_logs
      (org_id, actor_user_id, actor_role, event_type, target_type, target_id,
       request_id, ip_address, user_agent, metadata)
    VALUES
      (:org_id, :actor_user_id, :actor_role, :event_type, :target_type, :target_id,
       :request_id, CAST(:ip_address AS inet), :user_agent, CAST(:metadata AS jsonb))
    """
)

# Keys that must never be persisted, even by mistake.
_FORBIDDEN_METADATA_KEYS = {"password", "otp", "code", "token", "secret", "authorization"}


def _params(
    event_type: str,
    *,
    org_id: uuid.UUID | str | None,
    actor_user_id: uuid.UUID | None,
    actor_role: str | None,
    target_type: str | None,
    target_id: str | None,
    request_id: str | None,
    ip_address: str | None,
    user_agent: str | None,
    metadata: dict[str, Any] | None,
) -> dict[str, Any]:
    clean = {k: v for k, v in (metadata or {}).items() if k.lower() not in _FORBIDDEN_METADATA_KEYS}
    return {
        "org_id": org_id,
        "actor_user_id": actor_user_id,
        "actor_role": actor_role,
        "event_type": event_type,
        "target_type": target_type,
        "target_id": target_id,
        "request_id": request_id,
        "ip_address": ip_address,
        "user_agent": (user_agent or "")[:512] or None,
        "metadata": json.dumps(clean, default=str),
    }


async def write_audit_event(
    session: AsyncSession,
    event_type: str,
    *,
    org_id: uuid.UUID | None,
    actor_user_id: uuid.UUID | None = None,
    actor_role: str | None = None,
    target_type: str | None = None,
    target_id: str | None = None,
    request_id: str | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    await session.execute(
        _INSERT,
        _params(
            event_type, org_id=org_id, actor_user_id=actor_user_id, actor_role=actor_role, target_type=target_type,
            target_id=target_id, request_id=request_id, ip_address=ip_address, user_agent=user_agent,
            metadata=metadata,
        ),
    )


def write_audit_event_sync(
    connection: Connection,
    event_type: str,
    *,
    org_id: uuid.UUID | str | None,
    actor_user_id: uuid.UUID | None = None,
    actor_role: str | None = None,
    target_type: str | None = None,
    target_id: str | None = None,
    request_id: str | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    """The same insert on a sync connection: for the S1 stores, whose transactions are sync, so an
    event can commit (or roll back) together with the record it describes."""

    connection.execute(
        _INSERT,
        _params(
            event_type, org_id=org_id, actor_user_id=actor_user_id, actor_role=actor_role, target_type=target_type,
            target_id=target_id, request_id=request_id, ip_address=ip_address, user_agent=user_agent,
            metadata=metadata,
        ),
    )


def write_audit_event_in_own_transaction(event: dict[str, Any]) -> None:
    """One event in its own short transaction, in the S1 scope bound for the request. For S1 stores that
    are not in Postgres, where the event cannot share the record's transaction."""

    from backend.app.core.db import tenant_transaction
    from backend.app.core.s1_scope import current_scope

    with tenant_transaction(current_scope()) as connection:
        write_audit_event_sync(connection, **event)
