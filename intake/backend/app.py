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
from fastapi.middleware.cors import CORSMiddleware

from intake.backend.api import (
    auth,
    evidence_requests,
    interview,
    metrics,
    orgs,
    profile,
    review,
    seed_form,
    sites,
)
from intake.backend.config import load_settings

INTAKE_ROUTERS = (
    auth.router,
    orgs.router,
    sites.router,
    seed_form.router,
    interview.router,
    review.router,
    profile.router,
    evidence_requests.router,
    metrics.router,
)

# The intake screens run on a different port from the API, so the browser will
# not call it at all without these. Headers are listed explicitly rather than
# using "*", and credentials are off because auth travels in the Authorization
# header, not a cookie.
CORS_HEADERS = ("Authorization", "Content-Type", "X-Intake-Admin-Key")
CORS_METHODS = ("GET", "POST", "PUT", "OPTIONS")


def register_intake(target: FastAPI) -> FastAPI:
    """Add the intake routers, CORS policy and health probe to any FastAPI app."""
    origins = load_settings().api.cors_allowed_origins
    target.add_middleware(
        CORSMiddleware,
        allow_origins=list(origins),
        allow_credentials=False,
        allow_methods=list(CORS_METHODS),
        allow_headers=list(CORS_HEADERS),
    )

    for router in INTAKE_ROUTERS:
        target.include_router(router)

    @target.get("/v1/intake/health")
    def intake_health() -> dict[str, str]:
        """Liveness probe for the intake surface specifically."""
        return {"status": "ok", "surface": "intake"}

    return target


def create_intake_app() -> FastAPI:
    """A standalone app serving only the intake surface.

    Used by the intake tests, and by a hosted intake pilot, so neither depends
    on the S1 app's dependency set (parsers, storage adapters, multipart
    uploads).
    """
    return register_intake(FastAPI(title="Sustentra Intake API", version="0.1.0"))


def create_app() -> FastAPI:
    """The composed app: everything S1 serves, plus intake."""
    from backend.app.main import app as s1_app

    return register_intake(s1_app)


_app: FastAPI | None = None


def __getattr__(name: str) -> FastAPI:
    """Build the composed app only when something actually asks for it.

    ``uvicorn intake.backend.app:app`` still works exactly as before. What
    changed is that merely *importing* this module no longer builds the S1 app,
    which used to import the whole S1 dependency set as a side effect.

    That side effect made an intake-only deployment impossible: asking uvicorn
    for ``create_intake_app`` still imported this module first, so the process
    died at boot on a missing S1 dependency it was never going to use. Found by
    running the API in a clean environment with only the intake requirements.
    """
    global _app
    if name == "app":
        if _app is None:
            _app = create_app()
        return _app
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
