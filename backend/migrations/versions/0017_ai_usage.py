"""ai_usage: the ledger of Claude calls, one row per call, so the monthly spend cap can be
checked before the next call and the spend can be shown.

- Append only: the app can SELECT and INSERT, never UPDATE or DELETE. A call is recorded
  whatever its outcome (ok, refused, incomplete, invalid), so a refused or unreadable reply
  that was still billed counts toward the cap.
- RLS and grants as the other s1 tables (0013, 0015): each organization sees only its own
  rows, provider scope sees all.
- ``engagement_id`` has no foreign key: the ledger must outlive the engagement. No prompt,
  document text or reply is stored, only ids, counts and cost.

Revision ID: 0017
Revises: 0016
Create Date: 2026-11-11
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "ai_usage"
OUTCOMES = ("ok", "refused", "incomplete", "invalid")
TENANT_PREDICATE = (
    "org_id::text = current_setting('app.tenant_id', true) "
    "OR current_setting('app.is_provider', true) = 'true'"
)


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "org_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="RESTRICT", name=f"fk_{TABLE}_org_id"),
            nullable=False,
        ),
        sa.Column("engagement_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("feature", sa.Text(), nullable=False),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("request_id", sa.Text(), nullable=True),
        sa.Column("outcome", sa.Text(), nullable=False),
        sa.Column("input_tokens", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
        sa.Column("output_tokens", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
        sa.Column("cost_microusd", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("feature <> ''", name=f"ck_{TABLE}_feature"),
        sa.CheckConstraint(
            "outcome IN (" + ", ".join(f"'{o}'" for o in OUTCOMES) + ")", name=f"ck_{TABLE}_outcome"
        ),
        sa.CheckConstraint(
            "input_tokens >= 0 AND output_tokens >= 0 AND cost_microusd >= 0", name=f"ck_{TABLE}_non_negative"
        ),
    )
    op.execute(f"CREATE INDEX ix_{TABLE}_org_month ON {TABLE} (org_id, created_at)")
    op.execute(f"ALTER TABLE {TABLE} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {TABLE} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY {TABLE}_tenant_isolation ON {TABLE}
          FOR ALL
          USING ({TENANT_PREDICATE})
          WITH CHECK ({TENANT_PREDICATE})
        """
    )
    op.execute(f"GRANT SELECT, INSERT ON {TABLE} TO app_user")
    op.execute(f"REVOKE UPDATE, DELETE ON {TABLE} FROM app_user")


def downgrade() -> None:
    op.execute(f"DROP TABLE {TABLE}")
