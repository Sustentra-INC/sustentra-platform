from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlsplit

from alembic.config import Config
from alembic.script import ScriptDirectory
import psycopg2

TEST_DATABASE_URL_ENV = "TEST_DATABASE_URL"
TEST_APP_DATABASE_URL_ENV = "TEST_APP_DATABASE_URL"
TEST_DATABASE_REQUIRED_ENV = "TEST_DB_REQUIRED"
TEST_DATABASE_DISPOSABLE_ENV = "TEST_DB_DISPOSABLE"

APP_RUNTIME_ROLE = "app_user"
_DEFAULT_PG_PORT = 5432
_CONNECT_TIMEOUT_SECONDS = 3
_TRUTHY_VALUES = frozenset({"1", "true", "yes", "on"})
_REQUIRED_TABLES = ("organizations", "users", "sessions", "auth_tokens", "audit_logs")


class DatabaseContractError(RuntimeError):
    pass


@dataclass(frozen=True)
class TestDatabaseUrls:
    admin_url: str
    app_url: str


@dataclass(frozen=True)
class UrlTarget:
    username: str
    host: str
    port: int
    database: str

    @property
    def display(self) -> str:
        return f"{self.username}@{self.host}:{self.port}/{self.database}"


@dataclass(frozen=True)
class RoleFlags:
    rolsuper: bool
    rolbypassrls: bool
    rolcreatedb: bool
    rolcreaterole: bool

    @property
    def all_false(self) -> bool:
        return not any((self.rolsuper, self.rolbypassrls, self.rolcreatedb, self.rolcreaterole))


@dataclass(frozen=True)
class ValidatedTestDatabase:
    urls: TestDatabaseUrls
    admin_target: UrlTarget
    app_target: UrlTarget
    runtime_database: str
    runtime_user: str
    role_flags: RoleFlags
    alembic_version: str
    expected_heads: tuple[str, ...]


def env_truthy(value: str | None) -> bool:
    if value is None:
        return False
    return value.strip().lower() in _TRUTHY_VALUES


def required_database_mode_from_env() -> bool:
    return env_truthy(os.environ.get(TEST_DATABASE_REQUIRED_ENV))


def _backend_dir() -> Path:
    return Path(__file__).resolve().parents[2]


def expected_alembic_heads() -> frozenset[str]:
    backend_dir = _backend_dir()
    alembic_ini = backend_dir / "alembic.ini"
    if not alembic_ini.exists():
        raise DatabaseContractError(f"Alembic config was not found at {alembic_ini}.")

    config = Config(str(alembic_ini))
    script = ScriptDirectory.from_config(config)
    heads = frozenset(script.get_heads())
    if not heads:
        raise DatabaseContractError("Unable to resolve expected Alembic head revision from repository configuration.")
    return heads


def load_test_database_urls(*, required: bool) -> TestDatabaseUrls | None:
    admin_url = (os.environ.get(TEST_DATABASE_URL_ENV) or "").strip()
    app_url = (os.environ.get(TEST_APP_DATABASE_URL_ENV) or "").strip()

    if not admin_url and not app_url:
        if required:
            raise DatabaseContractError(
                "Required test-database mode is enabled, but TEST_DATABASE_URL and TEST_APP_DATABASE_URL are unset."
            )
        return None

    if not admin_url or not app_url:
        raise DatabaseContractError(
            "Both TEST_DATABASE_URL and TEST_APP_DATABASE_URL must be set together for database integration tests."
        )

    return TestDatabaseUrls(admin_url=admin_url, app_url=app_url)


def _parse_target(url: str, *, env_name: str) -> UrlTarget:
    parts = urlsplit(url)
    if not parts.scheme.startswith("postgres"):
        raise DatabaseContractError(f"{env_name} must be a PostgreSQL URL.")

    username = unquote(parts.username) if parts.username else ""
    host = parts.hostname or ""
    port = parts.port or _DEFAULT_PG_PORT
    database = parts.path.lstrip("/")

    if not username:
        raise DatabaseContractError(f"{env_name} is missing a username.")
    if not host:
        raise DatabaseContractError(f"{env_name} is missing a hostname.")
    if not database:
        raise DatabaseContractError(f"{env_name} is missing a database name.")

    return UrlTarget(username=username, host=host, port=port, database=database)


def _connect(url: str):
    return psycopg2.connect(url, connect_timeout=_CONNECT_TIMEOUT_SECONDS)


def validate_required_database_setup(*, required: bool) -> ValidatedTestDatabase:
    urls = load_test_database_urls(required=required)
    if urls is None:
        raise DatabaseContractError(
            "Database integration tests are disabled because TEST_DATABASE_URL/TEST_APP_DATABASE_URL are not set."
        )

    if not env_truthy(os.environ.get(TEST_DATABASE_DISPOSABLE_ENV)):
        raise DatabaseContractError(
            "Refusing destructive DB tests: set TEST_DB_DISPOSABLE=1 to acknowledge disposable test data."
        )

    admin_target = _parse_target(urls.admin_url, env_name=TEST_DATABASE_URL_ENV)
    app_target = _parse_target(urls.app_url, env_name=TEST_APP_DATABASE_URL_ENV)

    if (
        admin_target.host != app_target.host
        or admin_target.port != app_target.port
        or admin_target.database != app_target.database
    ):
        raise DatabaseContractError(
            "TEST_DATABASE_URL and TEST_APP_DATABASE_URL must point to the same host:port/database target."
        )

    if app_target.username != APP_RUNTIME_ROLE:
        raise DatabaseContractError(
            f"TEST_APP_DATABASE_URL must connect as {APP_RUNTIME_ROLE!r}, got {app_target.username!r}."
        )

    expected_heads = expected_alembic_heads()

    try:
        with _connect(urls.app_url) as app_conn:
            with app_conn.cursor() as cur:
                cur.execute("SELECT current_database(), current_user")
                runtime_db, runtime_user = cur.fetchone()
    except Exception as exc:  # noqa: BLE001
        raise DatabaseContractError(
            f"Unable to connect with TEST_APP_DATABASE_URL ({app_target.display}): {exc}"
        ) from exc

    if runtime_user != APP_RUNTIME_ROLE:
        raise DatabaseContractError(
            f"Runtime app connection user must be {APP_RUNTIME_ROLE!r}, got {runtime_user!r}."
        )

    if runtime_db != app_target.database:
        raise DatabaseContractError(
            "Runtime app connection database does not match TEST_APP_DATABASE_URL target."
        )

    try:
        with _connect(urls.admin_url) as admin_conn:
            with admin_conn.cursor() as cur:
                cur.execute(
                    "SELECT rolsuper, rolbypassrls, rolcreatedb, rolcreaterole "
                    "FROM pg_roles WHERE rolname = %s",
                    (APP_RUNTIME_ROLE,),
                )
                row = cur.fetchone()
                if row is None:
                    raise DatabaseContractError(f"Role {APP_RUNTIME_ROLE!r} was not found.")
                role_flags = RoleFlags(
                    rolsuper=bool(row[0]),
                    rolbypassrls=bool(row[1]),
                    rolcreatedb=bool(row[2]),
                    rolcreaterole=bool(row[3]),
                )

                if not role_flags.all_false:
                    raise DatabaseContractError(
                        "app_user role flags are unsafe for runtime tests "
                        f"(rolsuper={role_flags.rolsuper}, rolbypassrls={role_flags.rolbypassrls}, "
                        f"rolcreatedb={role_flags.rolcreatedb}, rolcreaterole={role_flags.rolcreaterole})."
                    )

                cur.execute("SELECT to_regclass('public.alembic_version')")
                version_table = cur.fetchone()
                if version_table is None or version_table[0] is None:
                    raise DatabaseContractError(
                        "Database schema is not migrated: alembic_version table is missing."
                    )

                cur.execute("SELECT version_num FROM alembic_version ORDER BY version_num")
                revision_rows = cur.fetchall()
                db_revisions = frozenset(str(row[0]) for row in revision_rows if row and row[0])
                if not db_revisions:
                    raise DatabaseContractError(
                        "Database schema is not migrated: alembic_version has no current revision."
                    )

                if db_revisions != expected_heads:
                    missing = sorted(expected_heads.difference(db_revisions))
                    unexpected = sorted(db_revisions.difference(expected_heads))
                    raise DatabaseContractError(
                        "Database Alembic revision mismatch: "
                        f"expected head(s) {sorted(expected_heads)}, found {sorted(db_revisions)}; "
                        f"missing={missing}, unexpected={unexpected}."
                    )

                alembic_version = ",".join(sorted(db_revisions))

                missing_tables: list[str] = []
                for table in _REQUIRED_TABLES:
                    cur.execute("SELECT to_regclass(%s)", (f"public.{table}",))
                    table_ref = cur.fetchone()
                    if table_ref is None or table_ref[0] is None:
                        missing_tables.append(table)
                if missing_tables:
                    missing = ", ".join(sorted(missing_tables))
                    raise DatabaseContractError(
                        f"Database schema is missing required tables: {missing}."
                    )
    except DatabaseContractError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise DatabaseContractError(
            f"Unable to validate TEST_DATABASE_URL ({admin_target.display}): {exc}"
        ) from exc

    return ValidatedTestDatabase(
        urls=urls,
        admin_target=admin_target,
        app_target=app_target,
        runtime_database=str(runtime_db),
        runtime_user=str(runtime_user),
        role_flags=role_flags,
        alembic_version=alembic_version,
        expected_heads=tuple(sorted(expected_heads)),
    )
