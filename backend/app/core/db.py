"""Async database layer and per-request tenant context (AUTH-002).

- One async SQLAlchemy engine per process, connecting as `app_user`
  (Settings.database_url = the /<env>/db_app_url parameter) with TLS in prod.
  pool_size=5, max_overflow=5.
- `get_db_session` (FastAPI dependency): one AsyncSession and ONE transaction
  per request - committed when the endpoint returns, rolled back on error.
- `set_tenant(session, org_id)` / `set_provider(session)` set the Row-Level
  Security context with set_config(..., is_local=true): parameterized, and
  scoped to the current transaction, so nothing leaks to the next request
  that reuses the same pooled connection.

Where the tenant comes from (enforced by convention + review):
  * the authenticated session (AUTH-004 `get_current_user`), or
  * at login, the organization resolved from the slug (AUTH-005).
  Never from a request body, query string or header.

The migration / master credentials are never used here: in staging/prod the
engine refuses to start unless it connects as app_user.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from urllib.parse import parse_qsl, unquote, urlencode, urlsplit, urlunsplit

from contextlib import contextmanager
from typing import TYPE_CHECKING

from sqlalchemy import Connection, Engine, text
from sqlalchemy import create_engine as create_sync_engine
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

if TYPE_CHECKING:
    from collections.abc import Iterator

    from .s1_scope import S1Scope

from .config import Settings, get_settings

APP_DB_ROLE = "app_user"
POOL_SIZE = 5
MAX_OVERFLOW = 5

_SET_TENANT = text(
    "SELECT set_config('app.tenant_id', :org_id, true), set_config('app.is_provider', 'false', true)"
)
_SET_PROVIDER = text(
    "SELECT set_config('app.is_provider', 'true', true), set_config('app.tenant_id', '', true)"
)

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None
_sync_engine: Engine | None = None


class DatabaseNotConfiguredError(RuntimeError):
    pass


# --- URL handling ---------------------------------------------------------------

def to_async_url(url: str) -> str:
    """postgresql://u:p@h/db?sslmode=require -> postgresql+asyncpg://u:p@h/db?ssl=require"""
    parts = urlsplit(url)
    scheme = "postgresql+asyncpg" if parts.scheme in ("postgres", "postgresql", "postgresql+psycopg2") else parts.scheme
    query = [("ssl", v) if k == "sslmode" else (k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)]
    return urlunsplit((scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def to_sync_url(url: str) -> str:
    """postgresql://u:p@h/db?sslmode=require -> postgresql+psycopg2://u:p@h/db?sslmode=require"""
    parts = urlsplit(url)
    scheme = "postgresql+psycopg2" if parts.scheme in ("postgres", "postgresql", "postgresql+asyncpg") else parts.scheme
    query = [("sslmode", v) if k == "ssl" else (k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)]
    return urlunsplit((scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def database_user(url: str) -> str | None:
    username = urlsplit(url).username
    return unquote(username) if username else None


def runtime_database_url(settings: Settings) -> str:
    """The URL the API may use at runtime. Refuses anything but app_user in staging/prod."""
    if settings.database_url is None:
        raise DatabaseNotConfiguredError("DATABASE_URL is not set")
    url = settings.database_url.get_secret_value()
    user = database_user(url)
    if settings.is_production_like and user != APP_DB_ROLE:
        raise DatabaseNotConfiguredError(
            f"The API must connect as {APP_DB_ROLE!r} (db_app_url), not {user!r}. "
            "Migration/master credentials are for alembic only."
        )
    return url


# --- engine / sessions ------------------------------------------------------------

def create_engine(url: str, *, pool_size: int = POOL_SIZE, max_overflow: int = MAX_OVERFLOW) -> AsyncEngine:
    return create_async_engine(
        to_async_url(url),
        pool_size=pool_size,
        max_overflow=max_overflow,
        pool_pre_ping=True,
        pool_recycle=1800,
    )


def build_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False, autoflush=False)


def get_engine() -> AsyncEngine:
    global _engine, _sessionmaker
    if _engine is None:
        _engine = create_engine(runtime_database_url(get_settings()))
        _sessionmaker = build_sessionmaker(_engine)
    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    get_engine()
    assert _sessionmaker is not None
    return _sessionmaker


async def dispose_engine() -> None:
    global _engine, _sessionmaker, _sync_engine
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _sessionmaker = None
    if _sync_engine is not None:
        _sync_engine.dispose()
    _sync_engine = None


# --- sync engine (the S1 document stores) ------------------------------------------

def get_sync_engine() -> Engine:
    """A sync engine on the same app_user URL, for the synchronous S1 pipeline's stores.

    Same pool size as the async engine; each store call holds a connection only for its
    own short transaction (``tenant_transaction``), never while documents are parsed.
    """
    global _sync_engine
    if _sync_engine is None:
        _sync_engine = create_sync_engine(
            to_sync_url(runtime_database_url(get_settings())),
            pool_size=POOL_SIZE,
            max_overflow=MAX_OVERFLOW,
            pool_pre_ping=True,
            pool_recycle=1800,
        )
    return _sync_engine


@contextmanager
def tenant_transaction(scope: S1Scope, engine: Engine | None = None) -> Iterator[Connection]:
    """One transaction in the scope's RLS context, committed on exit (rolled back on error).

    Uses the same set_config(..., true) statements as the request session, so the tenant
    lasts only for this transaction and never reaches the next user of the pooled connection.
    """
    with (engine or get_sync_engine()).begin() as connection:
        if scope.provider:
            connection.execute(_SET_PROVIDER)
        else:
            connection.execute(_SET_TENANT, {"org_id": str(_as_uuid(scope.org_id))})  # type: ignore[arg-type]
        yield connection


def get_sessionmaker_dependency() -> async_sessionmaker[AsyncSession]:
    """FastAPI dependency for background tasks that open their own session/transaction."""
    return get_sessionmaker()


async def get_db_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: one session, one transaction per request."""
    async with get_sessionmaker()() as session:
        async with session.begin():
            yield session


# --- tenant context ---------------------------------------------------------------

def _as_uuid(org_id: uuid.UUID | str) -> uuid.UUID:
    # Only well-formed UUIDs ever reach the database.
    return org_id if isinstance(org_id, uuid.UUID) else uuid.UUID(str(org_id))


async def set_tenant(session: AsyncSession, org_id: uuid.UUID | str) -> None:
    """Scope this transaction to one organization (RLS: app.tenant_id)."""
    await session.execute(_SET_TENANT, {"org_id": str(_as_uuid(org_id))})


async def set_provider(session: AsyncSession) -> None:
    """Provider (platform admin) scope for this transaction: sees all orgs."""
    await session.execute(_SET_PROVIDER)
