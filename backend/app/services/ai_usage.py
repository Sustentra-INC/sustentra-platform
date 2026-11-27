"""The ledger of Claude calls (table ``ai_usage``, migration 0017) and the monthly spend cap.

Every call is recorded, whatever its outcome, so a refused or unreadable reply that was
billed still counts. Only ids, counts and cost are stored: never a prompt, document text
or reply. A call about one document carries its ``document_id`` (migration 0030), so the cost of a
whole-document read is the sum of its parts' rows. The month is the UTC calendar month.
"""

from __future__ import annotations

import uuid

from sqlalchemy import Connection, text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.adapters.llm.base import StructuredReply

MICRO = 1_000_000

# The month's spend against the cap is the AI's plus the scans' (``textract_usage``, 0029): one limit for both.
_MONTH_SPEND = text(
    """
    SELECT (
      COALESCE((SELECT SUM(cost_microusd) FROM ai_usage
                 WHERE org_id = :org_id
                   AND created_at >= date_trunc('month', now() AT TIME ZONE 'UTC') AT TIME ZONE 'UTC'), 0)
    + COALESCE((SELECT SUM(cost_microusd) FROM textract_usage
                 WHERE org_id = :org_id
                   AND created_at >= date_trunc('month', now() AT TIME ZONE 'UTC') AT TIME ZONE 'UTC'), 0)
    )::bigint AS spent
    """
)
# One statement, so the AI's and the scans' numbers come from the same snapshot.
_MONTH_BREAKDOWN = text(
    """
    SELECT
      COALESCE((SELECT SUM(cost_microusd) FROM ai_usage
                 WHERE org_id = :org_id
                   AND created_at >= date_trunc('month', now() AT TIME ZONE 'UTC') AT TIME ZONE 'UTC'), 0)::bigint AS ai,
      COALESCE((SELECT SUM(cost_microusd) FROM textract_usage
                 WHERE org_id = :org_id
                   AND created_at >= date_trunc('month', now() AT TIME ZONE 'UTC') AT TIME ZONE 'UTC'), 0)::bigint AS scans,
      COALESCE((SELECT SUM(pages) FROM textract_usage
                 WHERE org_id = :org_id
                   AND created_at >= date_trunc('month', now() AT TIME ZONE 'UTC') AT TIME ZONE 'UTC'), 0)::bigint AS pages
    """
)
_INSERT = text(
    """
    INSERT INTO ai_usage (org_id, engagement_id, feature, model, provider, request_id, outcome,
                          input_tokens, output_tokens, cost_microusd, created_by, document_id)
    VALUES (:org_id, :engagement_id, :feature, :model, :provider, :request_id, :outcome,
            :input_tokens, :output_tokens, :cost_microusd, :created_by, :document_id)
    """
)


async def month_spend_microusd(db: AsyncSession, org_id: uuid.UUID) -> int:
    """What the organization's Claude calls and Textract scans cost this month together, in micro-USD:
    the number the monthly cap is checked against."""

    return int((await db.execute(_MONTH_SPEND, {"org_id": org_id})).scalar_one())


async def month_breakdown(db: AsyncSession, org_id: uuid.UUID) -> tuple[int, int, int]:
    """(AI micro-USD, scan micro-USD, scan pages) this month, read in one statement; none is ever negative."""

    row = (await db.execute(_MONTH_BREAKDOWN, {"org_id": org_id})).one()
    return max(0, int(row.ai)), max(0, int(row.scans)), max(0, int(row.pages))


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
    document_id: str | None = None,
) -> None:
    await db.execute(_INSERT, _row(org_id, engagement_id, feature, provider, reply, user_id, document_id))


def _row(org_id: uuid.UUID, engagement_id: uuid.UUID | None, feature: str, provider: str, reply: StructuredReply,
         user_id: uuid.UUID | None, document_id: str | None = None) -> dict[str, object]:
    return {
        "org_id": org_id, "engagement_id": engagement_id, "feature": feature, "model": reply.model,
        "provider": provider, "request_id": reply.request_id, "outcome": reply.outcome,
        "input_tokens": reply.usage.prompt_tokens, "output_tokens": reply.usage.output_tokens,
        "cost_microusd": reply.cost_microusd or 0, "created_by": user_id, "document_id": document_id or None,
    }


# The same two statements for the synchronous S1 pipeline (its stores use ``tenant_transaction``).

def month_spend_microusd_sync(conn: Connection, org_id: uuid.UUID) -> int:
    return int(conn.execute(_MONTH_SPEND, {"org_id": org_id}).scalar_one())


def record_sync(conn: Connection, *, org_id: uuid.UUID, engagement_id: uuid.UUID | None, feature: str, provider: str,
                reply: StructuredReply, user_id: uuid.UUID | None, document_id: str | None = None) -> None:
    conn.execute(_INSERT, _row(org_id, engagement_id, feature, provider, reply, user_id, document_id))


_DOCUMENT_SPEND = text(
    """
    SELECT COALESCE(SUM(cost_microusd), 0)::bigint FROM ai_usage WHERE org_id = :org_id AND document_id = :document_id
    """
)


def document_spend_microusd_sync(conn: Connection, org_id: uuid.UUID, document_id: str) -> int:
    """What Sustentra's AI has cost for one document, all its parts and features together, in micro-USD."""

    return int(conn.execute(_DOCUMENT_SPEND, {"org_id": org_id, "document_id": document_id}).scalar_one())
