"""Kept copies of the Excel workpaper: the exact bytes served, and a record of every download.

``WorkpaperCopyStore`` is the one place that knows where the bytes live. Today it is Postgres
(``workpaper_copies`` holds the bytes and the facts about them, ``workpaper_downloads`` one row per
download), in the request's own transaction, so a copy, its download record and its audit event commit
together or not at all. Moving the bytes to S3 later means a new class with the same methods (and the bytes
column left empty); nothing else changes.

Both tables are add-only for the app role (migration 0026): a copy is never changed or deleted.
Every read and write runs under the request's RLS context, so one organization never sees another's copies.
The org is always the engagement's own, never taken from the request.

An S1_STORE of ``jsonl`` does not change this: the engagement, the audit log and the review decisions' own
queue are in Postgres whatever S1_STORE says, and this endpoint needs the engagement first, so there is
no case where the workpaper can be built but Postgres cannot be reached. There is no file fallback.
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any, Protocol

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger("sustentra.workpaper_copies")


class WorkpaperCopyCorrupt(Exception):
    """A kept copy's bytes no longer match the SHA-256 or the size recorded when it was kept."""


@dataclass(frozen=True)
class CopyRecord:
    id: uuid.UUID
    org_id: str
    engagement_id: str  # uuids, as text: the engagement's own ids as the API holds them
    file_name: str
    size_bytes: int
    sha256: str
    content_fingerprint: str
    app_version: str
    prepared_by_user_id: uuid.UUID | None
    prepared_by_email: str | None
    request_id: str | None
    created_at: datetime | None  # None only before the database has set it
    downloads: int = 0


class WorkpaperCopyStore(Protocol):
    async def lock(self, engagement_id: str) -> None:
        """Make concurrent savers of this engagement take turns, until the transaction ends."""

    async def latest(self, engagement_id: str) -> CopyRecord | None:
        """The engagement's newest copy (no bytes)."""

    async def add(self, copy: CopyRecord, content: bytes) -> CopyRecord: ...

    async def read(self, engagement_id: str, copy_id: uuid.UUID) -> tuple[CopyRecord, bytes] | None:
        """The copy and its bytes, checked against the size and SHA-256 kept with it (``WorkpaperCopyCorrupt``
        when they differ); None when the engagement has no such copy."""

    async def add_download(
        self, copy: CopyRecord, *, kind: str, user_id: uuid.UUID | None, email: str | None, request_id: str | None
    ) -> None: ...

    async def list(self, engagement_id: str, *, limit: int, offset: int) -> tuple[list[CopyRecord], int]:
        """Newest first, each with its number of downloads; and the total number of copies."""


def sha256_of(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


_COLUMNS = (
    "id, org_id, engagement_id, file_name, size_bytes, sha256, content_fingerprint, app_version, "
    "prepared_by_user_id, prepared_by_email, request_id, created_at"
)


def _record(row: Any) -> CopyRecord:
    return CopyRecord(
        id=row["id"], org_id=str(row["org_id"]), engagement_id=str(row["engagement_id"]), file_name=row["file_name"],
        size_bytes=row["size_bytes"], sha256=row["sha256"], content_fingerprint=row["content_fingerprint"],
        app_version=row["app_version"], prepared_by_user_id=row["prepared_by_user_id"],
        prepared_by_email=row["prepared_by_email"], request_id=row["request_id"], created_at=row["created_at"],
        downloads=row.get("downloads", 0) if hasattr(row, "get") else 0,
    )


class PostgresWorkpaperCopyStore:
    """The bytes in ``workpaper_copies.content``, in the request's transaction."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def lock(self, engagement_id: str) -> None:
        # Held until the transaction ends. Two downloads of the same figures at once must not both see "no
        # copy yet" and keep two.
        await self._db.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"), {"key": f"workpaper-copy:{engagement_id}"}
        )

    async def latest(self, engagement_id: str) -> CopyRecord | None:
        row = (await self._db.execute(
            text(f"SELECT {_COLUMNS} FROM workpaper_copies WHERE engagement_id = CAST(:e AS uuid) "
                 "ORDER BY created_at DESC, id DESC LIMIT 1"), {"e": str(engagement_id)})).mappings().first()
        return _record(row) if row else None

    async def add(self, copy: CopyRecord, content: bytes) -> CopyRecord:
        row = (await self._db.execute(
            text("INSERT INTO workpaper_copies (org_id, engagement_id, file_name, size_bytes, sha256, "
                 "content_fingerprint, app_version, prepared_by_user_id, prepared_by_email, request_id, content, "
                 "created_at) "
                 # clock_timestamp(), not now(): the time of the insert, so "newest" is the last one kept
                 # even when two requests started in the other order.
                 "VALUES (CAST(:org AS uuid), CAST(:e AS uuid), :name, :size, :sha, :fp, :version, :uid, :email, :rid, :content, "
                 "clock_timestamp()) "
                 f"RETURNING {_COLUMNS}"),
            {"org": str(copy.org_id), "e": str(copy.engagement_id), "name": copy.file_name, "size": copy.size_bytes,
             "sha": copy.sha256, "fp": copy.content_fingerprint, "version": copy.app_version,
             "uid": copy.prepared_by_user_id, "email": copy.prepared_by_email, "rid": copy.request_id,
             "content": content})).mappings().one()
        return _record(row)

    async def read(self, engagement_id: str, copy_id: uuid.UUID) -> tuple[CopyRecord, bytes] | None:
        row = (await self._db.execute(
            text(f"SELECT {_COLUMNS}, content FROM workpaper_copies WHERE id = :id AND engagement_id = CAST(:e AS uuid)"),
            {"id": copy_id, "e": str(engagement_id)})).mappings().first()
        if row is None:
            return None
        content = bytes(row["content"])
        record = _record(row)
        if len(content) != record.size_bytes or sha256_of(content) != record.sha256:
            raise WorkpaperCopyCorrupt(str(copy_id))
        return record, content

    async def add_download(
        self, copy: CopyRecord, *, kind: str, user_id: uuid.UUID | None, email: str | None, request_id: str | None
    ) -> None:
        await self._db.execute(
            text("INSERT INTO workpaper_downloads (org_id, engagement_id, copy_id, kind, downloaded_by_user_id, "
                 "downloaded_by_email, request_id) VALUES (CAST(:org AS uuid), CAST(:e AS uuid), :copy, :kind, :uid, :email, :rid)"),
            {"org": str(copy.org_id), "e": str(copy.engagement_id), "copy": copy.id, "kind": kind, "uid": user_id,
             "email": email, "rid": request_id})

    async def list(self, engagement_id: str, *, limit: int, offset: int) -> tuple[list[CopyRecord], int]:
        total = (await self._db.execute(
            text("SELECT count(*) FROM workpaper_copies WHERE engagement_id = CAST(:e AS uuid)"), {"e": str(engagement_id)})).scalar_one()
        rows = (await self._db.execute(
            text("SELECT c.id, c.org_id, c.engagement_id, c.file_name, c.size_bytes, c.sha256, c.content_fingerprint, "
                 "c.app_version, c.prepared_by_user_id, c.prepared_by_email, c.request_id, c.created_at, "
                 "(SELECT count(*) FROM workpaper_downloads d WHERE d.copy_id = c.id) AS downloads "
                 "FROM workpaper_copies c WHERE c.engagement_id = CAST(:e AS uuid) "
                 "ORDER BY c.created_at DESC, c.id DESC LIMIT :limit OFFSET :offset"),
            {"e": str(engagement_id), "limit": limit, "offset": offset})).mappings().all()
        return [_record(r) for r in rows], int(total)


class InMemoryWorkpaperCopyStore:
    """The same behaviour in memory, for tests that have no database."""

    def __init__(self) -> None:
        self.copies: list[tuple[CopyRecord, bytes]] = []
        self.downloads: list[dict[str, Any]] = []
        self.fail_on_add = False

    async def lock(self, engagement_id: str) -> None:
        return None

    async def latest(self, engagement_id: str) -> CopyRecord | None:
        mine = [c for c, _ in self.copies if c.engagement_id == engagement_id]
        return mine[-1] if mine else None

    async def add(self, copy: CopyRecord, content: bytes) -> CopyRecord:
        if self.fail_on_add:
            raise RuntimeError("storage is down")
        stored = replace(copy, id=uuid.uuid4(), created_at=datetime.now(UTC))
        self.copies.append((stored, content))
        return stored

    async def read(self, engagement_id: str, copy_id: uuid.UUID) -> tuple[CopyRecord, bytes] | None:
        for record, content in self.copies:
            if record.id == copy_id and record.engagement_id == engagement_id:
                if len(content) != record.size_bytes or sha256_of(content) != record.sha256:
                    raise WorkpaperCopyCorrupt(str(copy_id))
                return record, content
        return None

    async def add_download(
        self, copy: CopyRecord, *, kind: str, user_id: uuid.UUID | None, email: str | None, request_id: str | None
    ) -> None:
        self.downloads.append({"copy_id": copy.id, "kind": kind, "user_id": user_id, "email": email,
                               "request_id": request_id})

    async def list(self, engagement_id: str, *, limit: int, offset: int) -> tuple[list[CopyRecord], int]:
        mine = [c for c, _ in reversed(self.copies) if c.engagement_id == engagement_id]
        counted = [replace(c, downloads=sum(1 for d in self.downloads if d["copy_id"] == c.id)) for c in mine]
        return counted[offset:offset + limit], len(mine)
