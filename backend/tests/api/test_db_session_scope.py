"""Every request transaction commits before its response is sent.

With FastAPI's default scope for a yield dependency the commit runs after the response, and a
browser that acts on the response at once can arrive first: the session check right after a
login came back 401 (a flaky e2e smoke test). Every use of get_db_session must be
scope="function".
"""

from __future__ import annotations

from collections.abc import Iterator

from fastapi.dependencies.models import Dependant
from fastapi.routing import APIRoute

from backend.app.core.db import get_db_session
from backend.app.main import app


def _routes(routes: list) -> Iterator[APIRoute]:  # type: ignore[type-arg]
    """Every APIRoute, including those of included routers (wrapped since FastAPI 0.14x)."""

    for route in routes:
        included = getattr(route, "original_router", None)
        if included is not None:
            yield from _routes(included.routes)
        elif isinstance(route, APIRoute):
            yield route


def _dependants(dependant: Dependant) -> Iterator[Dependant]:
    for sub in dependant.dependencies:
        yield sub
        yield from _dependants(sub)


def _db_routes() -> dict[str, set[str | None]]:
    """Endpoint name -> the scopes its get_db_session dependencies are declared with."""

    found: dict[str, set[str | None]] = {}
    for route in _routes(app.routes):
        for dependant in _dependants(route.dependant):
            if dependant.call is get_db_session:
                found.setdefault(f"{route.endpoint.__module__}.{route.name}", set()).add(dependant.scope)
    return found


def test_every_route_commits_its_transaction_before_responding() -> None:
    late = sorted(name for name, scopes in _db_routes().items() if scopes != {"function"})
    assert late == []


def test_the_check_reaches_the_routes_that_use_the_database() -> None:
    names = {name.rsplit(".", 1)[-1] for name in _db_routes()}
    assert {"login_verify", "me"} <= names
    assert len(names) > 20
