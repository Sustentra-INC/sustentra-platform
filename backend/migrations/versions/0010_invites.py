"""Invites (ORG-003): users.invited_by + invite-token lookup.

- users.invited_by: who sent the invite (an org admin, or a provider admin for an
  org's first admin). Nullable - users that were not invited have none - and
  ON DELETE SET NULL. Users are never hard-deleted (COMP-001 anonymizes), so this
  is only a safety net.
- auth_resolve_invite_token(token_hash): the validate/accept requests only carry
  the token from the email link, so - like sessions, login challenges and reset
  tokens (0005-0007) - the first lookup has to happen before the tenant is known.
  SECURITY DEFINER, returns only what is needed to validate the token and pick
  the tenant.

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-07
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "invited_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL", name="fk_users_invited_by"),
            nullable=True,
        ),
    )
    op.execute(
        """
        CREATE FUNCTION auth_resolve_invite_token(p_token_hash text)
          RETURNS TABLE (
            token_id    uuid,
            user_id     uuid,
            org_id      uuid,
            expires_at  timestamptz,
            consumed_at timestamptz
          )
          LANGUAGE plpgsql
          SECURITY DEFINER
          SET search_path = public, pg_temp
        AS $$
        #variable_conflict use_column
        DECLARE
          prev_is_provider text := current_setting('app.is_provider', true);
        BEGIN
          -- Same pattern as auth_resolve_reset_token (0007): set_config() in the body,
          -- restored before returning (RDS cannot attach a custom GUC to a function).
          PERFORM set_config('app.is_provider', 'true', true);
          RETURN QUERY
            SELECT t.id, t.user_id, t.org_id, t.expires_at, t.consumed_at
              FROM auth_tokens t
             WHERE t.token_hash = p_token_hash
               AND t.type = 'invite';
          PERFORM set_config('app.is_provider', coalesce(prev_is_provider, ''), true);
        END
        $$
        """
    )
    op.execute("REVOKE ALL ON FUNCTION auth_resolve_invite_token(text) FROM PUBLIC")
    op.execute("GRANT EXECUTE ON FUNCTION auth_resolve_invite_token(text) TO app_user")


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS auth_resolve_invite_token(text)")
    op.drop_column("users", "invited_by")
