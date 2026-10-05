"""Login OTP challenges (AUTH-005).

auth_tokens becomes the challenge store for the second login step:
- type 'login_otp' (challenge_id = auth_tokens.id, token_hash = HMAC of the code)
- attempts -> attempt_count (wrong codes for this challenge)
- resend_count, last_sent_at (60 s cooldown, max 3 resends)

auth_resolve_challenge(id): like auth_resolve_session, the one lookup that
happens before the tenant is known (verify/resend only carry a challenge_id).
SECURITY DEFINER, returns just enough to pick the tenant and validate.

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-04
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NEW_TYPES = ("login_otp", "email_otp", "password_reset", "invite", "email_verification")
OLD_TYPES = ("email_otp", "password_reset", "invite", "email_verification")


def _types_check(types: tuple[str, ...]) -> str:
    return "type IN (" + ", ".join(f"'{t}'" for t in types) + ")"


def upgrade() -> None:
    op.drop_constraint("ck_auth_tokens_type", "auth_tokens", type_="check")
    op.create_check_constraint("ck_auth_tokens_type", "auth_tokens", _types_check(NEW_TYPES))

    op.drop_constraint("ck_auth_tokens_attempts_non_negative", "auth_tokens", type_="check")
    op.alter_column("auth_tokens", "attempts", new_column_name="attempt_count")
    op.create_check_constraint("ck_auth_tokens_attempt_count", "auth_tokens", "attempt_count >= 0")

    op.add_column(
        "auth_tokens", sa.Column("resend_count", sa.Integer(), nullable=False, server_default=sa.text("0"))
    )
    op.add_column("auth_tokens", sa.Column("last_sent_at", sa.DateTime(timezone=True), nullable=True))
    op.create_check_constraint("ck_auth_tokens_resend_count", "auth_tokens", "resend_count >= 0")

    op.execute(
        """
        CREATE FUNCTION auth_resolve_challenge(p_id uuid)
          RETURNS TABLE (
            challenge_id  uuid,
            user_id       uuid,
            org_id        uuid,
            type          text,
            token_hash    text,
            expires_at    timestamptz,
            consumed_at   timestamptz,
            attempt_count integer,
            resend_count  integer,
            last_sent_at  timestamptz
          )
          LANGUAGE plpgsql
          SECURITY DEFINER
          SET search_path = public, pg_temp
        AS $$
        #variable_conflict use_column
        DECLARE
          prev_is_provider text := current_setting('app.is_provider', true);
        BEGIN
          -- RDS: only a superuser may attach a custom GUC (SET app.is_provider) to a
          -- function definition, so switch it on with set_config() inside the body and
          -- restore the caller's value before returning.
          PERFORM set_config('app.is_provider', 'true', true);
          RETURN QUERY
            SELECT t.id, t.user_id, t.org_id, t.type, t.token_hash, t.expires_at, t.consumed_at,
                   t.attempt_count, t.resend_count, t.last_sent_at
              FROM auth_tokens t
             WHERE t.id = p_id;
          PERFORM set_config('app.is_provider', coalesce(prev_is_provider, ''), true);
        END
        $$
        """
    )
    op.execute("REVOKE ALL ON FUNCTION auth_resolve_challenge(uuid) FROM PUBLIC")
    op.execute("GRANT EXECUTE ON FUNCTION auth_resolve_challenge(uuid) TO app_user")


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS auth_resolve_challenge(uuid)")
    op.drop_constraint("ck_auth_tokens_resend_count", "auth_tokens", type_="check")
    op.drop_column("auth_tokens", "last_sent_at")
    op.drop_column("auth_tokens", "resend_count")
    op.drop_constraint("ck_auth_tokens_attempt_count", "auth_tokens", type_="check")
    op.alter_column("auth_tokens", "attempt_count", new_column_name="attempts")
    op.create_check_constraint("ck_auth_tokens_attempts_non_negative", "auth_tokens", "attempts >= 0")
    op.execute("DELETE FROM auth_tokens WHERE type = 'login_otp'")
    op.drop_constraint("ck_auth_tokens_type", "auth_tokens", type_="check")
    op.create_check_constraint("ck_auth_tokens_type", "auth_tokens", _types_check(OLD_TYPES))
