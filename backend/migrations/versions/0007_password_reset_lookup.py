"""Password reset token lookup (AUTH-006).

auth_resolve_reset_token(token_hash): the confirm request only carries the
token from the email link, so - like sessions and login challenges - the first
lookup has to happen before the tenant is known. SECURITY DEFINER, returns only
what's needed to validate the token and pick the tenant.

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-04
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE FUNCTION auth_resolve_reset_token(p_token_hash text)
          RETURNS TABLE (
            token_id    uuid,
            user_id     uuid,
            org_id      uuid,
            expires_at  timestamptz,
            consumed_at timestamptz
          )
          LANGUAGE sql
          STABLE
          SECURITY DEFINER
          SET search_path = public, pg_temp
          SET app.is_provider = 'true'
        AS $$
          SELECT t.id, t.user_id, t.org_id, t.expires_at, t.consumed_at
            FROM auth_tokens t
           WHERE t.token_hash = p_token_hash
             AND t.type = 'password_reset'
        $$
        """
    )
    op.execute("REVOKE ALL ON FUNCTION auth_resolve_reset_token(text) FROM PUBLIC")
    op.execute("GRANT EXECUTE ON FUNCTION auth_resolve_reset_token(text) TO app_user")


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS auth_resolve_reset_token(text)")
