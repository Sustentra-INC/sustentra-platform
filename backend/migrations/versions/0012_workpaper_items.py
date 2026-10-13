"""workpaper_items: the verifier's work on an engagement, kept in Postgres with RLS.

Evidence requests ("asks"), registered findings and per-data-point examination
states used to live only in the browser, so a reload lost them. Each is one row,
keyed by (engagement, kind, item_key), holding the frontend's object as JSON.

- ``org_id`` mirrors the engagement's org so RLS can use the same predicate as
  ``engagements``; rows are visible and writable only in that org's tenant context
  (or provider scope, which the API keeps read-only).
- Rows are never deleted by the app: requests are withdrawn and findings resolved by
  state, so the record of what the verifier did stays complete.

Revision ID: 0012
Revises: 0011
Create Date: 2026-10-12
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

KINDS = ("ask", "finding", "examination")

TENANT_PREDICATE = (
    "org_id::text = current_setting('app.tenant_id', true) "
    "OR current_setting('app.is_provider', true) = 'true'"
)


def upgrade() -> None:
    op.create_table(
        "workpaper_items",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")
        ),
        sa.Column(
            "org_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="RESTRICT", name="fk_workpaper_items_org_id"),
            nullable=False,
        ),
        sa.Column(
            "engagement_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("engagements.id", ondelete="CASCADE", name="fk_workpaper_items_engagement_id"),
            nullable=False,
        ),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("item_key", sa.Text(), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        # Plain ids, no FK: the record must survive user erasure (COMP-001).
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint(
            "kind IN (" + ", ".join(f"'{k}'" for k in KINDS) + ")", name="ck_workpaper_items_kind"
        ),
        sa.CheckConstraint("length(item_key) BETWEEN 1 AND 200", name="ck_workpaper_items_key_length"),
        sa.CheckConstraint("jsonb_typeof(payload) = 'object'", name="ck_workpaper_items_payload_is_object"),
        sa.UniqueConstraint("engagement_id", "kind", "item_key", name="uq_workpaper_items_engagement_kind_key"),
    )
    op.execute("CREATE INDEX ix_workpaper_items_engagement_kind ON workpaper_items (engagement_id, kind)")

    op.execute("ALTER TABLE workpaper_items ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE workpaper_items FORCE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY workpaper_items_tenant_isolation ON workpaper_items
          FOR ALL
          USING ({TENANT_PREDICATE})
          WITH CHECK ({TENANT_PREDICATE})
        """
    )
    op.execute("GRANT SELECT, INSERT, UPDATE ON workpaper_items TO app_user")
    op.execute("REVOKE DELETE ON workpaper_items FROM app_user")


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS workpaper_items_tenant_isolation ON workpaper_items")
    op.drop_table("workpaper_items")
