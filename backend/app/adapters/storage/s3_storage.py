from __future__ import annotations

import re
from pathlib import Path
from tempfile import gettempdir
from urllib.parse import urlparse

import boto3

_SAFE_COMPONENT_RE = re.compile(r"[^A-Za-z0-9._-]+")
_SAFE_FILENAME_RE = re.compile(r"[^A-Za-z0-9._-]+")


class S3Storage:
    """S3/MinIO-backed document storage with the LocalStorageService contract."""

    def __init__(
        self,
        *,
        bucket: str,
        endpoint_url: str | None = None,
        access_key_id: str | None = None,
        secret_access_key: str | None = None,
        region: str = "us-east-1",
        cache_root: str | Path | None = None,
    ) -> None:
        if not bucket or not bucket.strip():
            raise ValueError("bucket is required.")
        self._bucket = bucket.strip()
        self._cache_root = Path(cache_root or Path(gettempdir()) / "sustentra-s3-cache").resolve()
        self._client = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key,
            region_name=region,
        )
        self._ensure_bucket()

    @property
    def bucket(self) -> str:
        return self._bucket

    def save_upload(
        self,
        *,
        file_name: str,
        content: bytes,
        engagement_id: str,
        evidence_id: str,
        document_id: str,
    ) -> dict:
        if not isinstance(content, (bytes, bytearray)):
            raise ValueError("content must be bytes.")
        raw_bytes = bytes(content)
        if not raw_bytes:
            raise ValueError("Upload content cannot be empty.")

        stored_file_name = self._sanitize_file_name(file_name)
        key = "/".join(
            [
                self._sanitize_component(engagement_id, "engagement_id"),
                self._sanitize_component(evidence_id, "evidence_id"),
                self._sanitize_component(document_id, "document_id"),
                stored_file_name,
            ]
        )
        self._client.put_object(Bucket=self._bucket, Key=key, Body=raw_bytes)
        return {
            "storage_uri": f"s3://{self._bucket}/{key}",
            "stored_file_name": stored_file_name,
            "size_bytes": len(raw_bytes),
        }

    def resolve_storage_uri(self, storage_uri: str) -> Path:
        bucket, key = self._parse_storage_uri(storage_uri)
        cache_path = self._safe_cache_path(bucket=bucket, key=key)
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        self._client.download_file(bucket, key, str(cache_path))
        return cache_path

    def exists(self, storage_uri: str) -> bool:
        try:
            bucket, key = self._parse_storage_uri(storage_uri)
            self._client.head_object(Bucket=bucket, Key=key)
        except Exception:
            return False
        return True

    def _ensure_bucket(self) -> None:
        try:
            self._client.head_bucket(Bucket=self._bucket)
        except Exception:
            self._client.create_bucket(Bucket=self._bucket)

    def _parse_storage_uri(self, storage_uri: str) -> tuple[str, str]:
        parsed = urlparse(storage_uri)
        if parsed.scheme != "s3" or not parsed.netloc or not parsed.path.strip("/"):
            raise ValueError("storage_uri must use s3://bucket/key format.")
        return parsed.netloc, parsed.path.lstrip("/")

    def _safe_cache_path(self, *, bucket: str, key: str) -> Path:
        safe_parts = [
            self._sanitize_component(bucket, "bucket"),
            *[self._sanitize_component(part, "key") for part in key.split("/") if part],
        ]
        candidate = self._cache_root.joinpath(*safe_parts).resolve()
        try:
            candidate.relative_to(self._cache_root)
        except ValueError as exc:
            raise ValueError("storage_uri resolves outside of cache root.") from exc
        return candidate

    @staticmethod
    def _sanitize_component(value: str, field_name: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{field_name} is required.")
        sanitized = _SAFE_COMPONENT_RE.sub("_", value.strip())
        sanitized = sanitized.strip("._")
        if not sanitized:
            raise ValueError(f"{field_name} contains no safe characters.")
        return sanitized

    @staticmethod
    def _sanitize_file_name(file_name: str) -> str:
        if not isinstance(file_name, str) or not file_name.strip():
            raise ValueError("file_name is required.")
        basename = file_name.strip().replace("\\", "/").split("/")[-1]
        basename = _SAFE_FILENAME_RE.sub("_", basename).strip(" ")
        if not basename or basename in {".", ".."}:
            raise ValueError("file_name is invalid after sanitization.")
        return basename
