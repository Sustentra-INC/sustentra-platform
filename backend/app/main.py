from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from . import observability
from .api import (
    assistant,
    documents,
    engagements,
    evidence,
    methodology,
    pipeline,
    processing_runs,
    reviews,
)
from .api import v1 as api_v1
from .core.config import Settings, get_settings
from .core.db import dispose_engine
from .core.rate_limit import limiter
from .core.security import JSONContentTypeMiddleware, OriginCheckMiddleware, UploadSizeLimitMiddleware

APP_TITLE = "Sustentra Evidence Extraction API"

# S1 workpaper routes the frontend seam calls (features/s1/api/s1Backend.ts).
# Served at /v1/* (local, NEXT_PUBLIC_BACKEND_API_URL=http://localhost:8000) and at
# /api/v1/* (prod via Caddy, NEXT_PUBLIC_BACKEND_API_URL=https://app.sustentra.com/api).
S1_ROUTERS = (
    engagements.router,
    documents.router,
    processing_runs.router,
    pipeline.router,
    evidence.router,
    methodology.router,
    reviews.router,
    assistant.router,
)
# The S1 routes are also mounted at root /v1/* for local development and existing
# tests (never on staging/prod). The old bearer-token identity routes (/v1/auth,
# /v1/users, /v1/clients, /v1/audit-events) were removed in CLEANUP-001; /api/v1/auth
# (AUTH-004..006) is the only auth.
LEGACY_ROUTERS = S1_ROUTERS


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
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)  # type: ignore[arg-type]

    # Middleware: the LAST added runs FIRST. Order of execution:
    #   request logging (observability) -> CORS (local only) -> origin check -> JSON content type
    #   -> upload size limit
    app.state.max_upload_bytes = settings.max_upload_bytes  # the upload route checks the exact file size
    app.add_middleware(UploadSizeLimitMiddleware, max_bytes=settings.max_upload_bytes)
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

    # SEC-001: every S1 route requires a session and is scoped to the caller's org
    # (api/s1_access.py).
    for router in S1_ROUTERS:
        app.include_router(router, prefix="/api")

    # S1 routes at root /v1/*, for local development and existing tests only -
    # never mounted on staging/prod (Caddy does not route them there either).
    if not settings.is_production_like:
        for router in LEGACY_ROUTERS:
            app.include_router(router)

    return app


app = create_app()
