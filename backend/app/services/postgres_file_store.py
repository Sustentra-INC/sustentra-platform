"""Uploaded S1 files in Postgres (``s1_document_files``), behind LocalStorageService's interface.

The bytes live in the database, so they are backed up with it and no longer tied to one
server's disk. Parsers, downloads and previews still take a local path: the first time a
file is needed on a server it is copied into a cache directory (checked against its size and
sha256) and read from there afterwards. The cache can be deleted at any time.

Storage URIs keep the LocalStorageService form (``local-data/uploads/<org>/<engagement>/
<evidence>/<document>/<file>``), so documents written by either store name their file the same
way. Every read and write runs in the bound S1 scope: RLS keeps each organization to its own
files, and with no scope bound the call raises.
"""

from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path, PurePosixPath

from sqlalchemy import text
from sqlalchemy.engine import Engine

from backend.app.core.db import get_sync_engine, tenant_transaction
from backend.app.core.s1_scope import current_scope
from backend.app.services.local_storage_service import LocalStorageService

DEFAULT_CACHE_DIR = Path(tempfile.gettempdir()) / "sustentra-s1-files"

_sanitize_component = LocalStorageService._sanitize_component
_sanitize_file_name = LocalStorageService._sanitize_file_name


class PostgresFileStore:
    def __init__(
        self,
        storage_uri_prefix: str = "local-data/uploads",
        *,
        cache_dir: str | Path = DEFAULT_CACHE_DIR,
        engine: Engine | None = None,
    ) -> None:
        self._prefix = PurePosixPath(storage_uri_prefix)
        self._cache_dir = Path(cache_dir)
        self._engine = engine

    @property
    def storage_uri_prefix(self) -> Path:
        return Path(self._prefix)

    def _transaction(self):  # noqa: ANN202 - a context manager yielding a Connection
        return tenant_transaction(current_scope(), self._engine or get_sync_engine())

    def save_upload(
        self,
        *,
        file_name: str,
        content: bytes,
        engagement_id: str,
        evidence_id: str,
        document_id: str,
        owner: str | None = None,
    ) -> dict:
        """Store an upload; a name already taken for the document gets ``_1``, ``_2``…"""

        if not isinstance(content, (bytes, bytearray)):
            raise ValueError("content must be bytes.")
        raw_bytes = bytes(content)
        if not raw_bytes:
            raise ValueError("Upload content cannot be empty.")

        safe_file_name = _sanitize_file_name(file_name)
        folder = self._prefix
        if owner:
            folder /= _sanitize_component(owner, "owner")
        folder = (folder / _sanitize_component(engagement_id, "engagement_id")
                  / _sanitize_component(evidence_id, "evidence_id")
                  / _sanitize_component(document_id, "document_id"))

        with self._transaction() as connection:
            taken = {
                row.storage_uri
                for row in connection.execute(
                    text("SELECT storage_uri FROM s1_document_files WHERE storage_uri LIKE :folder"),
                    {"folder": _like_prefix(f"{folder.as_posix()}/")},
                )
            }
            final_file_name = safe_file_name
            stem, suffix = PurePosixPath(safe_file_name).stem, PurePosixPath(safe_file_name).suffix
            counter = 1
            while (folder / final_file_name).as_posix() in taken:
                final_file_name = f"{stem}_{counter}{suffix}"
                counter += 1
            storage_uri = (folder / final_file_name).as_posix()
            connection.execute(
                text(
                    "INSERT INTO s1_document_files "
                    "(storage_uri, org_id, document_id, file_name, size_bytes, sha256, content) "
                    "VALUES (:uri, :org_id, :document_id, :file_name, :size, :sha256, :content)"
                ),
                {
                    "uri": storage_uri,
                    "org_id": owner or None,
                    "document_id": document_id,
                    "file_name": final_file_name,
                    "size": len(raw_bytes),
                    "sha256": hashlib.sha256(raw_bytes).hexdigest(),
                    "content": raw_bytes,
                },
            )
        return {"storage_uri": storage_uri, "stored_file_name": final_file_name, "size_bytes": len(raw_bytes)}

    def resolve_storage_uri(self, storage_uri: str) -> Path:
        """A local copy of the stored file; ValueError when this scope has no such file."""

        self._suffix_parts(storage_uri)
        with self._transaction() as connection:
            row = connection.execute(
                text("SELECT file_name, size_bytes, sha256 FROM s1_document_files WHERE storage_uri = :uri"),
                {"uri": storage_uri},
            ).first()
        if row is None:
            raise ValueError("storage_uri is not a stored file.")
        target = self._cache_dir / row.sha256 / _sanitize_file_name(row.file_name)
        if target.is_file() and target.stat().st_size == row.size_bytes:
            return target

        with self._transaction() as connection:
            content = connection.execute(
                text("SELECT content FROM s1_document_files WHERE storage_uri = :uri"), {"uri": storage_uri}
            ).scalar_one()
        content = bytes(content)
        if hashlib.sha256(content).hexdigest() != row.sha256:  # pragma: no cover - the table's CHECKs
            raise ValueError("Stored file does not match its checksum.")
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        handle, partial = tempfile.mkstemp(dir=target.parent, prefix=".partial-")
        try:
            with os.fdopen(handle, "wb") as out:
                out.write(content)
            os.replace(partial, target)
        except BaseException:
            Path(partial).unlink(missing_ok=True)
            raise
        return target

    def is_owned_by(self, storage_uri: str, owner: str) -> bool:
        """True when ``storage_uri`` names a file in ``owner``'s folder (SEC-001), as
        LocalStorageService decides it. Whether the file exists is resolve's question."""

        try:
            parts = self._suffix_parts(storage_uri)
            return len(parts) > 1 and parts[0] == _sanitize_component(owner, "owner")
        except ValueError:
            return False

    def exists(self, storage_uri: str) -> bool:
        try:
            self._suffix_parts(storage_uri)
        except ValueError:
            return False
        with self._transaction() as connection:
            return connection.execute(
                text("SELECT 1 FROM s1_document_files WHERE storage_uri = :uri"), {"uri": storage_uri}
            ).first() is not None

    def _suffix_parts(self, storage_uri: str) -> tuple[str, ...]:
        """The URI's parts after the prefix; ValueError for an empty, absolute or escaping URI."""

        if not isinstance(storage_uri, str) or not storage_uri.strip():
            raise ValueError("storage_uri must be a non-empty string.")
        path = PurePosixPath(storage_uri)
        if path.is_absolute() or Path(storage_uri).is_absolute():
            raise ValueError("storage_uri must be a relative path.")
        if any(part in ("..", ".") for part in path.parts) or "\\" in storage_uri:
            raise ValueError("storage_uri resolves outside of storage root.")
        prefix = self._prefix.parts
        parts = path.parts
        return parts[len(prefix):] if parts[: len(prefix)] == prefix else parts


def _like_prefix(value: str) -> str:
    """A LIKE pattern matching strings that start with ``value``."""

    escaped = value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"{escaped}%"

