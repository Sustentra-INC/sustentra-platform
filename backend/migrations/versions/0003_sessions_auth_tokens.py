"""sessions + auth_tokens with Row-Level Security, and expired-row purge.

Both tables carry org_id (copied from the user) so they can use the same
tenant/provider RLS policy as `users`. A composite foreign key
(user_id, org_id) -> users(id, org_id) guarantees the copy always matches the
user's org. Provider-admin rows have org_id NULL (visible to providers only).

Expired rows are purged opportunistically - the API calls
purge_expired_auth_rows() after each successful login. It is SECURITY DEFINER
and sets app.is_provider for its own execution, so the purge covers all tenants
while app_user itself still cannot see other tenants' rows.

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-03
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TOKEN_TYPES = ("email_otp", "password_reset", "invite", "email_verification")

TENANT_PREDICATE = (
    "org_id::text = current_setting('app.tenant_id', true) "
    "OR current_setting('app.is_provider', true) = 'true'"
)


def _uuid(name: str, *args: object, **kw: object) -> sa.Column:
    return sa.Column(name, postgresql.UUID(as_uuid=True), *args, **kw)


def _user_fk(table: str) -> sa.ForeignKeyConstraint:
    # MATCH SIMPLE: when org_id is NULL (provider admin) only user_id is checked by fk_<table>_user_id.
    return sa.ForeignKeyConstraint(
        ["user_id", "org_id"],
        ["users.id", "users.org_id"],
        name=f"fk_{table}_user_org",
        ondelete="CASCADE",
        onupdate="CASCADE",
    )


def _enable_rls(table: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY {table}_tenant_isolation ON {table}
          FOR ALL
          USING ({TENANT_PREDICATE})
          WITH CHECK ({TENANT_PREDICATE})
        """
    )


def upgrade() -> None:
    # Target for the composite FKs below.
    op.create_unique_constraint("uq_users_id_org_id", "users", ["id", "org_id"])

    op.create_table(
        "sessions",
        _uuid("id", primary_key=True, server_default=sa.text("gen_random_uuid()")),
        _uuid("user_id", sa.ForeignKey("users.id", ondelete="CASCADE", name="fk_sessions_user_id"), nullable=False),
        _uuid("org_id", nullable=True),
        sa.Column("token_hash", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ip_address", postgresql.INET(), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        _user_fk("sessions"),
        sa.CheckConstraint("expires_at > created_at", name="ck_sessions_expiry_after_creation"),
    )
    op.create_index("uq_sessions_token_hash", "sessions", ["token_hash"], unique=True)
    op.create_index("ix_sessions_user_id", "sessions", ["user_id"])
    op.create_index("ix_sessions_expires_at", "sessions", ["expires_at"])

    op.create_table(
        "auth_tokens",
        _uuid("id", primary_key=True, server_default=sa.text("gen_random_uuid()")),
        _uuid("user_id", sa.ForeignKey("users.id", ondelete="CASCADE", name="fk_auth_tokens_user_id"), nullable=False),
        _uuid("org_id", nullable=True),
        sa.Column("type", sa.Text(), nullable=False),
        sa.Column("token_hash", sa.Text(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        _user_fk("auth_tokens"),
        sa.CheckConstraint(
            "type IN (" + ", ".join(f"'{t}'" for t in TOKEN_TYPES) + ")",
            name="ck_auth_tokens_type",
        ),
        sa.CheckConstraint("attempts >= 0", name="ck_auth_tokens_attempts_non_negative"),
    )
    op.create_index("ix_auth_tokens_token_hash", "auth_tokens", ["token_hash"])
    op.create_index("ix_auth_tokens_user_id_type", "auth_tokens", ["user_id", "type"])
    op.create_index("ix_auth_tokens_expires_at", "auth_tokens", ["expires_at"])

    _enable_rls("sessions")
    _enable_rls("auth_tokens")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON sessions, auth_tokens TO app_user")

    # Opportunistic purge (called after each successful login). Cross-tenant by design,
    # but it can only DELETE rows expired for more than a day and returns just a count.
    op.execute(
        """
        CREATE FUNCTION purge_expired_auth_rows() RETURNS integer
          LANGUAGE plpgsql
          SECURITY DEFINER
          SET search_path = public, pg_temp
        AS $$
        DECLARE
          removed integer := 0;
          n integer;
          prev_is_provider text := current_setting('app.is_provider', true);
        BEGIN
          -- RDS: only a superuser may attach a custom GUC (SET app.is_provider) to a
          -- function definition, so switch it on with set_config() inside the body and
          -- restore the caller's value before returning.
          PERFORM set_config('app.is_provider', 'true', true);
          DELETE FROM sessions WHERE expires_at < now() - interval '1 day';
          GET DIAGNOSTICS n = ROW_COUNT; removed := removed + n;
          DELETE FROM auth_tokens WHERE expires_at < now() - interval '1 day';
          GET DIAGNOSTICS n = ROW_COUNT; removed := removed + n;
          PERFORM set_config('app.is_provider', coalesce(prev_is_provider, ''), true);
          RETURN removed;
        END
        $$
        """
    )
    op.execute("REVOKE ALL ON FUNCTION purge_expired_auth_rows() FROM PUBLIC")
    op.execute("GRANT EXECUTE ON FUNCTION purge_expired_auth_rows() TO app_user")


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS purge_expired_auth_rows()")
    op.drop_table("auth_tokens")
    op.drop_table("sessions")
    op.drop_constraint("uq_users_id_org_id", "users", type_="unique")
