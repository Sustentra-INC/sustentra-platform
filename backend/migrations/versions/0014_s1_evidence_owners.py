"""s1 evidence owners: one row per evidence id, naming the organization that owns it.

Under RLS an organization cannot see another organization's S1 records, so "is this
evidence id free, or already mine?" can no longer be answered by reading the records (the
JSONL check). The first record saved with an evidence id claims it here, in the same
transaction; the primary key means no second organization can ever claim the same id, and a
claim conflicts even with a row its caller cannot see.

- ``org_id`` NULL: evidence from before uploads were owned (SEC-001), provider scope only.
- UPDATE is granted only so the ownership claim can stamp an owner on such a legacy row;
  nothing is deleted by the app.

Revision ID: 0014
Revises: 0013
Create Date: 2026-10-16
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TENANT_PREDICATE = (
    "org_id::text = current_setting('app.tenant_id', true) "
    "OR current_setting('app.is_provider', true) = 'true'"
)


def upgrade() -> None:
    op.create_table(
        "s1_evidence_owners",
        sa.Column("evidence_id", sa.Text(), primary_key=True),
        sa.Column(
            "org_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="RESTRICT", name="fk_s1_evidence_owners_org_id"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("evidence_id <> ''", name="ck_s1_evidence_owners_evidence_id"),
    )
    op.execute("ALTER TABLE s1_evidence_owners ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE s1_evidence_owners FORCE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY s1_evidence_owners_tenant_isolation ON s1_evidence_owners
          FOR ALL
          USING ({TENANT_PREDICATE})
          WITH CHECK ({TENANT_PREDICATE})
        """
    )
    op.execute("GRANT SELECT, INSERT, UPDATE ON s1_evidence_owners TO app_user")
    op.execute("REVOKE DELETE ON s1_evidence_owners FROM app_user")


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS s1_evidence_owners_tenant_isolation ON s1_evidence_owners")
    op.drop_table("s1_evidence_owners")
