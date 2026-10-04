"""Auth support columns + session resolver (AUTH-004, prepares AUTH-005).

- organizations.status ('active' | 'suspended'): suspended orgs cannot authenticate.
- users: first_name, last_name; failed_login_count, locked_until (AUTH-005 lockout);
  status may also be 'suspended' or 'deleted'.
- auth_resolve_session(token_hash): the one lookup that must happen BEFORE the
  tenant is known (a request only carries a cookie). SECURITY DEFINER with
  app.is_provider set for its own execution; it returns only what's needed to
  validate the session and pick the tenant. Everything after that runs under
  normal RLS with the session's tenant.

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-04
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "organizations", sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'active'"))
    )
    op.create_check_constraint("ck_organizations_status", "organizations", "status IN ('active', 'suspended')")

    op.add_column("users", sa.Column("first_name", sa.Text(), nullable=True))
    op.add_column("users", sa.Column("last_name", sa.Text(), nullable=True))
    op.add_column(
        "users", sa.Column("failed_login_count", sa.Integer(), nullable=False, server_default=sa.text("0"))
    )
    op.add_column("users", sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True))
    op.create_check_constraint("ck_users_failed_login_count", "users", "failed_login_count >= 0")
    op.drop_constraint("ck_users_status", "users", type_="check")
    op.create_check_constraint(
        "ck_users_status", "users", "status IN ('active', 'suspended', 'disabled', 'deleted')"
    )

    op.execute(
        """
        CREATE FUNCTION auth_resolve_session(p_token_hash text)
          RETURNS TABLE (
            session_id   uuid,
            user_id      uuid,
            org_id       uuid,
            created_at   timestamptz,
            expires_at   timestamptz,
            last_seen_at timestamptz,
            revoked_at   timestamptz,
            user_role    text,
            user_status  text,
            org_status   text
          )
          LANGUAGE sql
          STABLE
          SECURITY DEFINER
          SET search_path = public, pg_temp
          SET app.is_provider = 'true'
        AS $$
          SELECT s.id, s.user_id, s.org_id, s.created_at, s.expires_at, s.last_seen_at, s.revoked_at,
                 u.role, u.status, o.status
            FROM sessions s
            JOIN users u ON u.id = s.user_id
            LEFT JOIN organizations o ON o.id = s.org_id
           WHERE s.token_hash = p_token_hash
        $$
        """
    )
    op.execute("REVOKE ALL ON FUNCTION auth_resolve_session(text) FROM PUBLIC")
    op.execute("GRANT EXECUTE ON FUNCTION auth_resolve_session(text) TO app_user")


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS auth_resolve_session(text)")
    op.drop_constraint("ck_users_status", "users", type_="check")
    op.create_check_constraint("ck_users_status", "users", "status IN ('active', 'disabled')")
    op.drop_constraint("ck_users_failed_login_count", "users", type_="check")
    for column in ("locked_until", "failed_login_count", "last_name", "first_name"):
        op.drop_column("users", column)
    op.drop_constraint("ck_organizations_status", "organizations", type_="check")
    op.drop_column("organizations", "status")
