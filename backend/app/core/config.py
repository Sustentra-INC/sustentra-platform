"""Application settings, loaded from environment variables only.

Local: export variables or use docker-compose.yml.
Prod:  deploy.sh writes /opt/sustentra/app.env from SSM Parameter Store (/<env>/*)
       and docker compose injects it into the api container at start.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

Environment = Literal["local", "test", "staging", "prod"]
# Who serves Claude: the Anthropic API (ANTHROPIC_API_KEY) or Amazon Bedrock (the
# instance role, no key). See backend/app/adapters/llm/claude.py.
AiProvider = Literal["anthropic", "bedrock"]
AiEffort = Literal["low", "medium", "high"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, extra="ignore", case_sensitive=False, populate_by_name=True)

    environment: Environment = "local"
    # Baked into the image at build time (Dockerfile ARG GIT_SHA).
    git_sha: str = "dev"

    # Comma-separated list of origins allowed to make state-changing requests,
    # e.g. "https://app.sustentra.com". Local defaults cover the Next.js dev server.
    allowed_origins_csv: str = Field(
        default="http://localhost:3000,http://127.0.0.1:3000",
        alias="ALLOWED_ORIGINS",
    )

    # Runtime DB connection = app_user (db_app_url). Never the migration/master URL.
    database_url: SecretStr | None = None
    otp_hmac_secret: SecretStr | None = None
    ses_from_address: str | None = None

    # Public URL of the web app, used in emailed links (password reset, invites).
    public_base_url: str = "http://localhost:3000"

    # Local email goes to Mailpit; prod uses SES (EMAIL-001).
    smtp_host: str = "localhost"
    smtp_port: int = 1025

    # Where the S1 document stores live: "jsonl" (files on the server's disk, today),
    # "postgres+jsonl" (Postgres, also written to the files so a switch back loses nothing)
    # or "postgres". Set in /opt/sustentra/.env; deploy.sh passes it to the api container.
    s1_store: Literal["jsonl", "postgres+jsonl", "postgres"] = "jsonl"

    # How a document is read once someone asks for it (S1_PROCESSING): "inline" reads it in
    # that request, as before, and records it as a processing run; "queued" only queues the
    # run, for the reader process to pick up. Queued needs Postgres-backed stores (refused
    # with jsonl below). Set in /opt/sustentra/.env like S1_STORE.
    s1_processing: Literal["inline", "queued"] = "inline"

    # Largest S1 document upload, in MB (INFRA-007). deploy/Caddyfile allows the same
    # size on the upload route only (+1 MB for the multipart envelope); the frontend
    # mirrors it in features/s1/constants/uploads.ts.
    max_upload_mb: int = Field(default=25, ge=1, le=200)

    # Per-session limit for GET /api/v1/auth/me (AUTH-007): called on every page
    # render, so it is kept out of the brute-force bucket below.
    session_rate_limit: str = "600/minute"

    # Per-IP limit shared by all /api/v1/auth/* endpoints except /me.
    auth_rate_limit: str = "100/5 minutes"

    # AI suggestions for documents the system cannot read on its own (docs/backend_services.md).
    # Off by default. deploy.sh writes ANTHROPIC_API_KEY into app.env only when the
    # SecureString /<env>/anthropic_api_key exists, so prod (no parameter) has no key.
    ai_suggestions_enabled: bool = False
    ai_provider: AiProvider = "anthropic"
    # Only for AI_PROVIDER=anthropic. Bedrock signs with the instance role instead.
    anthropic_api_key: SecretStr | None = None
    # Claude API model id. On Bedrock the adapter adds the "anthropic." prefix. A model the
    # adapter has no price for is refused (claude.py PRICES), so a switch forces a price check.
    ai_model: str = "claude-sonnet-5-5"
    ai_effort: AiEffort = "low"
    # Per-organization monthly spend cap in USD, checked by the usage ledger (later PR).
    # The Anthropic Console spend limit is the hard ceiling across all organizations.
    ai_monthly_cap_usd: float = Field(default=25.0, ge=0)

    @field_validator("allowed_origins_csv", "ai_model")
    @classmethod
    def _strip(cls, value: str) -> str:
        return value.strip()

    @field_validator("anthropic_api_key", mode="before")
    @classmethod
    def _blank_key_is_no_key(cls, value: object) -> object:
        # docker-compose.yml passes ANTHROPIC_API_KEY through as "" when it is unset.
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @model_validator(mode="after")
    def _queued_reads_need_postgres_stores(self) -> Settings:
        # With jsonl the files on one server's disk are the only copy of the S1 records, and a
        # second process (the reader) would append to them as well.
        if self.s1_processing == "queued" and self.s1_store == "jsonl":
            raise ValueError("S1_PROCESSING=queued needs S1_STORE=postgres or postgres+jsonl, not jsonl.")
        return self

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    @property
    def allowed_origins(self) -> frozenset[str]:
        return frozenset(normalize_origin(o) for o in self.allowed_origins_csv.split(",") if o.strip())

    @property
    def docs_enabled(self) -> bool:
        # OpenAPI docs only for local development.
        return self.environment == "local"

    @property
    def is_production_like(self) -> bool:
        return self.environment in ("staging", "prod")


def normalize_origin(value: str) -> str:
    """'https://App.Example.com:443/' -> 'https://app.example.com'."""
    parts = urlsplit(value.strip())
    scheme = parts.scheme.lower()
    host = (parts.hostname or "").lower()
    port = parts.port
    if port is None or (scheme, port) in (("https", 443), ("http", 80)):
        return f"{scheme}://{host}"
    return f"{scheme}://{host}:{port}"


@lru_cache
def get_settings() -> Settings:
    return Settings()
