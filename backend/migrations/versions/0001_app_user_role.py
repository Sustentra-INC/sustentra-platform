"""Application database role `app_user`.

`app_user` is what the running API connects as (`/<env>/db_app_url`):
NOSUPERUSER, NOBYPASSRLS, no DDL - only SELECT/INSERT/UPDATE/DELETE on tables
created by migrations. Row-Level Security therefore always applies to it.

The password is taken from APP_DATABASE_URL (the db_app_url parameter) when
present, so the role's password always matches what Terraform generated.
Without it (e.g. a local throwaway DB) the role is created with LOGIN disabled.

Revision ID: 0001
Revises:
Create Date: 2026-10-03
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from urllib.parse import unquote, urlsplit

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ROLE = "app_user"


def _app_password() -> str | None:
    url = os.environ.get("APP_DATABASE_URL")
    if not url:
        return None
    parts = urlsplit(url)
    if parts.username and unquote(parts.username) != ROLE:
        raise RuntimeError(f"APP_DATABASE_URL user must be {ROLE!r}, got {parts.username!r}")
    return unquote(parts.password) if parts.password else None


def _quote_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def upgrade() -> None:
    password = _app_password()
    login = f"LOGIN PASSWORD {_quote_literal(password)}" if password else "NOLOGIN"
    # NOSUPERUSER / NOBYPASSRLS / NOCREATEDB / NOCREATEROLE / NOREPLICATION are the
    # CREATE ROLE defaults. They are not spelled out because on RDS (no real superuser)
    # naming BYPASSRLS/REPLICATION at all can be refused. The tests assert the result.
    op.execute(
        f"""
        DO $$
        BEGIN
          IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{ROLE}') THEN
            CREATE ROLE {ROLE} {login} NOINHERIT;
          ELSE
            ALTER ROLE {ROLE} {login};
          END IF;
        END
        $$;
        """
    )
    op.execute(
        f"""
        DO $$
        BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{ROLE}'
                     AND (rolsuper OR rolbypassrls OR rolcreatedb OR rolcreaterole)) THEN
            RAISE EXCEPTION 'role {ROLE} must be NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE';
          END IF;
        END
        $$;
        """
    )

    # Nobody but the migration owner may create objects in public.
    op.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")
    op.execute(f"GRANT USAGE ON SCHEMA public TO {ROLE}")
    op.execute(f"GRANT CONNECT ON DATABASE {_current_db()} TO {ROLE}")

    # DML only, on everything the migration owner creates from now on.
    op.execute(
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA public "
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {ROLE}"
    )
    op.execute(f"ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO {ROLE}")


def downgrade() -> None:
    op.execute(f"ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON SEQUENCES FROM {ROLE}")
    op.execute(f"ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON TABLES FROM {ROLE}")
    op.execute(f"REVOKE ALL ON DATABASE {_current_db()} FROM {ROLE}")
    op.execute(f"REVOKE ALL ON SCHEMA public FROM {ROLE}")
    op.execute(f"DROP ROLE IF EXISTS {ROLE}")


def _current_db() -> str:
    # current_database() can't be used in GRANT ... ON DATABASE, so resolve it first.
    bind = op.get_bind()
    name = bind.exec_driver_sql("SELECT current_database()").scalar_one()
    return '"' + str(name).replace('"', '""') + '"'
