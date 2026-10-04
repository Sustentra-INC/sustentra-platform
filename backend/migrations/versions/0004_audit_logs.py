"""audit_logs: append-only audit trail with Row-Level Security.

- app_user may only INSERT and SELECT. UPDATE and DELETE are revoked (permission
  error), and there are no UPDATE/DELETE policies either, so even a future grant
  would still match zero rows.
- RLS enabled and forced:
    SELECT: org_id matches app.tenant_id, or app.is_provider = 'true'.
            Rows with org_id NULL (provider-level / pre-login events) are
            visible to providers only.
    INSERT: same, plus org_id NULL is allowed from any context, so events that
            happen before a tenant is known (e.g. login with an unknown org)
            can still be recorded.
- No foreign keys: the trail must outlive users and organizations (erasure in
  COMP-001 must not rewrite history), so ids are stored as plain values.
- All rows are retained in Postgres (archival deferred).

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-04
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TENANT_OR_PROVIDER = (
    "org_id::text = current_setting('app.tenant_id', true) "
    "OR current_setting('app.is_provider', true) = 'true'"
)


def upgrade() -> None:
    op.create_table(
        "audit_logs",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")
        ),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("actor_role", sa.Text(), nullable=True),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("target_type", sa.Text(), nullable=True),
        sa.Column("target_id", sa.Text(), nullable=True),
        sa.Column("request_id", sa.Text(), nullable=True),
        sa.Column("ip_address", postgresql.INET(), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        # Never put passwords, OTP codes or tokens in here.
        sa.Column(
            "metadata", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("event_type ~ '^[a-z][a-z0-9_]{1,63}$'", name="ck_audit_logs_event_type_format"),
        sa.CheckConstraint("jsonb_typeof(metadata) = 'object'", name="ck_audit_logs_metadata_is_object"),
    )
    op.execute("CREATE INDEX ix_audit_logs_org_id_created_at ON audit_logs (org_id, created_at DESC)")
    op.create_index("ix_audit_logs_actor_user_id", "audit_logs", ["actor_user_id"])
    op.create_index("ix_audit_logs_event_type", "audit_logs", ["event_type"])

    op.execute("ALTER TABLE audit_logs ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE audit_logs FORCE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY audit_logs_select ON audit_logs
          FOR SELECT
          USING ({TENANT_OR_PROVIDER})
        """
    )
    op.execute(
        f"""
        CREATE POLICY audit_logs_insert ON audit_logs
          FOR INSERT
          WITH CHECK (org_id IS NULL OR {TENANT_OR_PROVIDER})
        """
    )

    # Append-only for the application: undo the DML default privileges from 0001.
    op.execute("REVOKE ALL ON audit_logs FROM app_user")
    op.execute("GRANT SELECT, INSERT ON audit_logs TO app_user")


def downgrade() -> None:
    op.drop_table("audit_logs")
