"""organizations.max_users + one vocabulary for user statuses (DB-004).

organizations.status ('active' | 'suspended') already exists (migration 0005).

- organizations.max_users: seat limit, NOT NULL, CHECK 1..10000, default 25.
  Existing orgs get 25, or their current number of non-deleted users when that is
  higher, so no org is over its limit after the upgrade.
- users.status: the database stores exactly the API's values (decision, DB-004):
      invited | active | suspended | deleted
  'invited' is new (ORG-003: created at invite time, active once the invite is
  accepted). 'disabled' is retired: existing 'disabled' rows become 'suspended',
  which is what the API calls them. Login, reset and sessions already accept
  'active' only, so nothing else changes.
- Roles were already aligned (provider_admin | org_admin | org_member).
- No RLS change: organizations has none (0002); the users policy is untouched.

Downgrade restores the 0005 constraint; 'invited' users become 'disabled' (they
cannot log in under either vocabulary) and max_users is dropped.

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-07
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DEFAULT_MAX_USERS = 25
MAX_MAX_USERS = 10_000
USER_STATUSES = ("invited", "active", "suspended", "deleted")
OLD_USER_STATUSES = ("active", "suspended", "disabled", "deleted")  # migration 0005


def _in(values: tuple[str, ...]) -> str:
    return "status IN (" + ", ".join(f"'{v}'" for v in values) + ")"


def _provider_scope() -> None:
    # users has FORCE ROW LEVEL SECURITY, which applies to the table owner too, and
    # the RDS migration user is not a superuser: without provider scope the UPDATE
    # and the seat count below would silently see zero rows. Transaction-local.
    op.execute("SELECT set_config('app.is_provider', 'true', true)")


def upgrade() -> None:
    _provider_scope()
    op.add_column("organizations", sa.Column("max_users", sa.Integer(), nullable=True))
    op.execute(
        f"""
        UPDATE organizations o
           SET max_users = GREATEST(
                 {DEFAULT_MAX_USERS},
                 (SELECT count(*) FROM users u WHERE u.org_id = o.id AND u.status <> 'deleted')
               )
        """
    )
    op.alter_column(
        "organizations", "max_users", nullable=False, server_default=sa.text(str(DEFAULT_MAX_USERS))
    )
    op.create_check_constraint(
        "ck_organizations_max_users_range", "organizations", f"max_users BETWEEN 1 AND {MAX_MAX_USERS}"
    )

    op.drop_constraint("ck_users_status", "users", type_="check")
    op.execute("UPDATE users SET status = 'suspended' WHERE status = 'disabled'")
    op.create_check_constraint("ck_users_status", "users", _in(USER_STATUSES))


def downgrade() -> None:
    _provider_scope()
    op.drop_constraint("ck_users_status", "users", type_="check")
    op.execute("UPDATE users SET status = 'disabled' WHERE status = 'invited'")
    op.create_check_constraint("ck_users_status", "users", _in(OLD_USER_STATUSES))

    op.drop_constraint("ck_organizations_max_users_range", "organizations", type_="check")
    op.drop_column("organizations", "max_users")
