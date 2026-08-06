from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class RuntimeSettings:
    persistence_backend: str = "jsonl"
    database_url: str | None = None
    storage_backend: str = "local"
    local_upload_root: str = "local-data/uploads"
    s3_endpoint_url: str | None = None
    s3_access_key_id: str | None = None
    s3_secret_access_key: str | None = None
    s3_region: str = "us-east-1"
    s3_bucket: str = "sustentra-documents"
    s3_secure: bool = False
    llm_extraction_enabled: bool = False
    openai_api_key: str | None = None
    openai_extraction_model: str = "gpt-4.1-mini"


def load_runtime_settings() -> RuntimeSettings:
    return RuntimeSettings(
        persistence_backend=os.getenv("SUSTENTRA_PERSISTENCE_BACKEND", "jsonl").strip().lower(),
        database_url=os.getenv("DATABASE_URL"),
        storage_backend=os.getenv("SUSTENTRA_STORAGE_BACKEND", "local").strip().lower(),
        local_upload_root=os.getenv("SUSTENTRA_LOCAL_UPLOAD_ROOT", "local-data/uploads"),
        s3_endpoint_url=os.getenv("SUSTENTRA_S3_ENDPOINT_URL"),
        s3_access_key_id=os.getenv("SUSTENTRA_S3_ACCESS_KEY_ID"),
        s3_secret_access_key=os.getenv("SUSTENTRA_S3_SECRET_ACCESS_KEY"),
        s3_region=os.getenv("SUSTENTRA_S3_REGION", "us-east-1"),
        s3_bucket=os.getenv("SUSTENTRA_S3_BUCKET", "sustentra-documents"),
        s3_secure=os.getenv("SUSTENTRA_S3_SECURE", "false").strip().lower()
        in {"1", "true", "yes"},
        llm_extraction_enabled=os.getenv(
            "SUSTENTRA_LLM_EXTRACTION_ENABLED",
            "true" if os.getenv("OPENAI_API_KEY") else "false",
        ).strip().lower()
        in {"1", "true", "yes"},
        openai_api_key=os.getenv("OPENAI_API_KEY"),
        openai_extraction_model=os.getenv("OPENAI_EXTRACTION_MODEL", "gpt-4.1-mini"),
    )
