"""organizations + users with Row-Level Security.

- organizations: no RLS (the slug must resolve before login); holds no secrets.
- users: RLS enabled AND forced. A row is visible/writable only when
    org_id::text = current_setting('app.tenant_id', true)
  or
    current_setting('app.is_provider', true) = 'true'
  With neither setting, no rows are visible.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-03
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

USER_ROLES = ("provider_admin", "org_admin", "org_member")
USER_STATUSES = ("active", "disabled")

TENANT_PREDICATE = (
    "org_id::text = current_setting('app.tenant_id', true) "
    "OR current_setting('app.is_provider', true) = 'true'"
)


def _uuid_pk() -> sa.Column:
    return sa.Column(
        "id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")
    )


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    ]


def upgrade() -> None:
    op.create_table(
        "organizations",
        _uuid_pk(),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("slug", sa.Text(), nullable=False),
        *_timestamps(),
        sa.UniqueConstraint("slug", name="uq_organizations_slug"),
        sa.CheckConstraint(
            "slug ~ '^[a-z0-9-]{3,63}$'",
            name="ck_organizations_slug_format",
        ),
    )

    op.create_table(
        "users",
        _uuid_pk(),
        sa.Column(
            "org_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="RESTRICT", name="fk_users_org_id"),
            nullable=True,
        ),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("full_name", sa.Text(), nullable=True),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'active'")),
        sa.Column("password_hash", sa.Text(), nullable=True),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.CheckConstraint("email = lower(email)", name="ck_users_email_lowercase"),
        sa.CheckConstraint(
            "role IN (" + ", ".join(f"'{r}'" for r in USER_ROLES) + ")",
            name="ck_users_role",
        ),
        sa.CheckConstraint(
            "status IN (" + ", ".join(f"'{s}'" for s in USER_STATUSES) + ")",
            name="ck_users_status",
        ),
        # org_id IS NULL  <=>  role = 'provider_admin'
        sa.CheckConstraint(
            "(org_id IS NULL) = (role = 'provider_admin')",
            name="ck_users_provider_admin_has_no_org",
        ),
    )
    # (email, org_id) unique; NULLS NOT DISTINCT also makes provider-admin emails unique.
    op.execute(
        "ALTER TABLE users ADD CONSTRAINT uq_users_email_org_id UNIQUE NULLS NOT DISTINCT (email, org_id)"
    )
    op.create_index("ix_users_org_id", "users", ["org_id"])
    op.create_index("ix_users_email", "users", ["email"])

    op.execute("ALTER TABLE users ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE users FORCE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY users_tenant_isolation ON users
          FOR ALL
          USING ({TENANT_PREDICATE})
          WITH CHECK ({TENANT_PREDICATE})
        """
    )

    # Default privileges from 0001 cover these tables; grant explicitly too in case
    # the tables were created by a different owner than the one that ran 0001.
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON organizations, users TO app_user")


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS users_tenant_isolation ON users")
    op.drop_table("users")
    op.drop_table("organizations")
