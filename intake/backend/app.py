"""Composed ASGI entrypoint: existing S1 API + intake API.

CLAUDE.md rule 1 forbids modifying existing files, and registering the intake
routers the usual way would mean editing ``backend/app/main.py``. This module is
a new entrypoint instead: it imports the existing FastAPI app untouched, adds the
intake routers to it, and exposes the result.

Run it in place of the S1 entrypoint::

    uvicorn intake.backend.app:app --reload

Everything the S1 app served is still served, on the same paths. The intake
routes live under ``/v1/intake/*``. Running ``backend.app.main:app`` directly
still works and simply has no intake routes.
"""

from __future__ import annotations

from fastapi import FastAPI

from intake.backend.api import auth, orgs, seed_form, sites

INTAKE_ROUTERS = (auth.router, orgs.router, sites.router, seed_form.router)


def register_intake(target: FastAPI) -> FastAPI:
    """Add the intake routers and health probe to any FastAPI app."""
    for router in INTAKE_ROUTERS:
        target.include_router(router)

    @target.get("/v1/intake/health")
    def intake_health() -> dict[str, str]:
        """Liveness probe for the intake surface specifically."""
        return {"status": "ok", "surface": "intake"}

    return target


def create_intake_app() -> FastAPI:
    """A standalone app serving only the intake surface.

    Used by the intake tests so they do not depend on the S1 app's dependency
    set (parsers, storage adapters, multipart uploads).
    """
    return register_intake(FastAPI(title="Sustentra Intake API", version="0.1.0"))


def create_app() -> FastAPI:
    """The composed app: everything S1 serves, plus intake."""
    from backend.app.main import app as s1_app

    return register_intake(s1_app)


app = create_app()
