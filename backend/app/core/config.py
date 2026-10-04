"""Application settings, loaded from environment variables only.

Local: export variables or use docker-compose.yml.
Prod:  deploy.sh writes /opt/sustentra/app.env from SSM Parameter Store (/<env>/*)
       and docker compose injects it into the api container at start.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

Environment = Literal["local", "test", "staging", "prod"]


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

    # Local email goes to Mailpit; prod uses SES (EMAIL-001).
    smtp_host: str = "localhost"
    smtp_port: int = 1025

    # Per-IP limit shared by all /api/v1/auth/* endpoints.
    auth_rate_limit: str = "100/5 minutes"

    @field_validator("allowed_origins_csv")
    @classmethod
    def _strip(cls, value: str) -> str:
        return value.strip()

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
