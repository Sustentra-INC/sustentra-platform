"""Append-only audit events (DB-003 table). Never put secrets in `metadata`."""

from __future__ import annotations

import json
import uuid
from typing import Any

from sqlalchemy import text
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
    clean = {k: v for k, v in (metadata or {}).items() if k.lower() not in _FORBIDDEN_METADATA_KEYS}
    await session.execute(
        _INSERT,
        {
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
        },
    )
