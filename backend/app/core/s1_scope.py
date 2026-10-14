"""Whose S1 data a request may touch, for code that runs outside the request's async session.

The S1 document pipeline is synchronous (sync endpoints run in the threadpool), so its
Postgres stores open their own short transactions on a sync engine
(``core.db.tenant_transaction``). They take the tenant from here: ``bind_s1_scope`` runs as
a dependency of every S1 router and records the signed-in user's organization (or provider
scope) in a ContextVar, which FastAPI copies into the threadpool for sync endpoints.

As in ``core.db``, the tenant only ever comes from the authenticated session: never from a
request body, query string or header. With nothing bound, ``current_scope`` raises, so a
store reached outside a request fails closed instead of reading every organization.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass

from fastapi import Depends

from .auth import CurrentUser, get_current_user


@dataclass(frozen=True)
class S1Scope:
    """One organization's data, or every organization's (provider scope)."""

    org_id: uuid.UUID | None
    provider: bool = False

    def __post_init__(self) -> None:
        if self.provider == (self.org_id is not None):
            raise ValueError("an S1 scope is either one organization or provider scope")

    @classmethod
    def tenant(cls, org_id: uuid.UUID | str) -> S1Scope:
        return cls(org_id if isinstance(org_id, uuid.UUID) else uuid.UUID(str(org_id)))

    @classmethod
    def platform(cls) -> S1Scope:
        return cls(None, provider=True)


class MissingS1Scope(RuntimeError):
    """An S1 store was used with no signed-in user (or explicit scope) behind it."""


_scope: ContextVar[S1Scope | None] = ContextVar("s1_scope", default=None)


def current_scope() -> S1Scope:
    scope = _scope.get()
    if scope is None:
        raise MissingS1Scope("No S1 scope is bound: S1 data is read and written only for a signed-in user.")
    return scope


@contextmanager
def scoped(scope: S1Scope) -> Iterator[S1Scope]:
    """Bind a scope explicitly (CLI commands, the JSONL import, tests)."""

    token = _scope.set(scope)
    try:
        yield scope
    finally:
        _scope.reset(token)


async def bind_s1_scope(user: CurrentUser = Depends(get_current_user)) -> None:
    """Router dependency: the request's S1 scope is the signed-in user's organization.

    A plain async function (not a generator), so the ContextVar is set in the request's own
    context and copied into the threadpool for sync endpoints.
    """

    _scope.set(S1Scope.platform() if user.org_id is None else S1Scope.tenant(user.org_id))
