from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from . import observability
from .api import (
    assistant,
    audit,
    auth,
    clients,
    documents,
    engagements,
    evidence,
    methodology,
    pipeline,
    processing_runs,
    reviews,
    users,
)
from .api import v1 as api_v1
from .core.config import Settings, get_settings
from .core.db import dispose_engine
from .core.rate_limit import limiter
from .core.security import JSONContentTypeMiddleware, OriginCheckMiddleware

APP_TITLE = "Sustentra Evidence Extraction API"

LEGACY_ROUTERS = (
    auth.router,
    users.router,
    clients.router,
    audit.router,
    engagements.router,
    documents.router,
    processing_runs.router,
    pipeline.router,
    evidence.router,
    methodology.router,
    reviews.router,
    assistant.router,
)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    # The DB engine is created lazily on first use; close its pool on shutdown.
    yield
    await dispose_engine()


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    docs = settings.docs_enabled
    app = FastAPI(
        title=APP_TITLE,
        version=settings.git_sha,
        docs_url="/api/v1/docs" if docs else None,
        openapi_url="/api/v1/openapi.json" if docs else None,
        redoc_url=None,
        lifespan=lifespan,
    )

    # Rate limiting (slowapi) - 429 with Retry-After.
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    # Middleware: the LAST added runs FIRST. Order of execution:
    #   request logging (observability) -> CORS (local only) -> origin check -> JSON content type
    app.add_middleware(JSONContentTypeMiddleware)
    app.add_middleware(OriginCheckMiddleware, allowed_origins=settings.allowed_origins)
    if not settings.is_production_like:
        # In prod the web app and API share one origin behind Caddy, so no CORS.
        app.add_middleware(
            CORSMiddleware,
            allow_origins=sorted(settings.allowed_origins),
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )
    observability.install(app)

    def health() -> dict[str, str]:
        return {"status": "ok", "version": settings.git_sha}

    # /health for the container healthcheck, /api/health through Caddy.
    app.add_api_route("/health", health, methods=["GET"], include_in_schema=False)
    app.add_api_route("/api/health", health, methods=["GET"], include_in_schema=False)

    app.include_router(api_v1.router)

    # Legacy (pre-AUTH-001) routes at /v1/*, kept for local development and
    # existing tests until the new /api/v1 endpoints replace them.
    for router in LEGACY_ROUTERS:
        app.include_router(router)

    return app


app = create_app()
