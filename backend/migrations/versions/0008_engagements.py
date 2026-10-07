"""engagements: S1 workpaper engagements per organization, with Row-Level Security.

- One row per engagement; ``org_id`` is required (provider admins never own one).
- ``settings`` holds the rest of the workpaper's Setup screen (facilities,
  regulation, assurance, contacts ...) as a JSON object; the columns are what
  lists and filters need.
- RLS enabled and forced with the same predicate as ``users``: a row is visible
  and writable only in its org's tenant context, or in provider scope.
  (Provider admins are read-only on engagements; the API enforces that.)

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-07
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

STATUSES = ("active", "archived")

TENANT_PREDICATE = (
    "org_id::text = current_setting('app.tenant_id', true) "
    "OR current_setting('app.is_provider', true) = 'true'"
)


def upgrade() -> None:
    op.create_table(
        "engagements",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")
        ),
        sa.Column(
            "org_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="RESTRICT", name="fk_engagements_org_id"),
            nullable=False,
        ),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("client_name", sa.Text(), nullable=True),
        sa.Column("reporting_period_start", sa.Date(), nullable=True),
        sa.Column("reporting_period_end", sa.Date(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'active'")),
        sa.Column("settings", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        # Plain id, no FK: the record must survive user erasure (COMP-001).
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("length(btrim(name)) BETWEEN 1 AND 200", name="ck_engagements_name_length"),
        sa.CheckConstraint(
            "status IN (" + ", ".join(f"'{s}'" for s in STATUSES) + ")", name="ck_engagements_status"
        ),
        sa.CheckConstraint(
            "reporting_period_start IS NULL OR reporting_period_end IS NULL "
            "OR reporting_period_end >= reporting_period_start",
            name="ck_engagements_period_order",
        ),
        sa.CheckConstraint("jsonb_typeof(settings) = 'object'", name="ck_engagements_settings_is_object"),
    )
    op.execute("CREATE INDEX ix_engagements_org_id_updated_at ON engagements (org_id, updated_at DESC)")

    op.execute("ALTER TABLE engagements ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE engagements FORCE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY engagements_tenant_isolation ON engagements
          FOR ALL
          USING ({TENANT_PREDICATE})
          WITH CHECK ({TENANT_PREDICATE})
        """
    )
    # No DELETE for the app: engagements are archived, never removed.
    op.execute("GRANT SELECT, INSERT, UPDATE ON engagements TO app_user")
    op.execute("REVOKE DELETE ON engagements FROM app_user")


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS engagements_tenant_isolation ON engagements")
    op.drop_table("engagements")
