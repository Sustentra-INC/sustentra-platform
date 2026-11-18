"""The ledger of Claude calls (table ``ai_usage``, migration 0017) and the monthly spend cap.

Every call is recorded, whatever its outcome, so a refused or unreadable reply that was
billed still counts. Only ids, counts and cost are stored: never a prompt, document text
or reply. The month is the UTC calendar month.
"""

from __future__ import annotations

import uuid

from sqlalchemy import Connection, text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.adapters.llm.claude import StructuredReply

MICRO = 1_000_000

_MONTH_SPEND = text(
    """
    SELECT COALESCE(SUM(cost_microusd), 0)::bigint AS spent FROM ai_usage
     WHERE org_id = :org_id AND created_at >= date_trunc('month', now() AT TIME ZONE 'UTC') AT TIME ZONE 'UTC'
    """
)
_INSERT = text(
    """
    INSERT INTO ai_usage (org_id, engagement_id, feature, model, provider, request_id, outcome,
                          input_tokens, output_tokens, cost_microusd, created_by)
    VALUES (:org_id, :engagement_id, :feature, :model, :provider, :request_id, :outcome,
            :input_tokens, :output_tokens, :cost_microusd, :created_by)
    """
)


async def month_spend_microusd(db: AsyncSession, org_id: uuid.UUID) -> int:
    """What the organization's Claude calls cost this month, in micro-USD."""

    return int((await db.execute(_MONTH_SPEND, {"org_id": org_id})).scalar_one())


async def month_spend(db: AsyncSession, org_id: uuid.UUID) -> float:
    """What the organization's Claude calls cost this month, in USD."""

    return await month_spend_microusd(db, org_id) / MICRO


def cap_reached(spent_microusd: int, cap_usd: float) -> bool:
    return spent_microusd >= round(cap_usd * MICRO)


async def try_lock_org(db: AsyncSession, org_id: uuid.UUID) -> bool:
    """Try to take the organization's prefill advisory lock until this transaction ends. False
    when another transaction holds it (a prefill is deciding right now); never waits."""

    return bool((await db.execute(text("SELECT pg_try_advisory_xact_lock(hashtextextended(:key, 0))"),
                                  {"key": f"ai_usage:{org_id}"})).scalar_one())


async def record(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    engagement_id: uuid.UUID | None,
    feature: str,
    provider: str,
    reply: StructuredReply,
    user_id: uuid.UUID | None,
) -> None:
    await db.execute(_INSERT, _row(org_id, engagement_id, feature, provider, reply, user_id))


def _row(org_id: uuid.UUID, engagement_id: uuid.UUID | None, feature: str, provider: str, reply: StructuredReply,
         user_id: uuid.UUID | None) -> dict[str, object]:
    return {
        "org_id": org_id, "engagement_id": engagement_id, "feature": feature, "model": reply.model,
        "provider": provider, "request_id": reply.request_id, "outcome": reply.outcome,
        "input_tokens": reply.usage.prompt_tokens, "output_tokens": reply.usage.output_tokens,
        "cost_microusd": reply.cost_microusd or 0, "created_by": user_id,
    }


# The same two statements for the synchronous S1 pipeline (its stores use ``tenant_transaction``).

def month_spend_microusd_sync(conn: Connection, org_id: uuid.UUID) -> int:
    return int(conn.execute(_MONTH_SPEND, {"org_id": org_id}).scalar_one())


def record_sync(conn: Connection, *, org_id: uuid.UUID, engagement_id: uuid.UUID | None, feature: str, provider: str,
                reply: StructuredReply, user_id: uuid.UUID | None) -> None:
    conn.execute(_INSERT, _row(org_id, engagement_id, feature, provider, reply, user_id))
