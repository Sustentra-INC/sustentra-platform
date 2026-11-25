"""Keeping the workpaper that is served: the rules around ``WorkpaperCopyStore``.

``keep_for_download`` runs inside the request's transaction, before any byte is sent. Either the copy (or
the existing copy it matches), the download record and the audit event are all saved, or the caller gets
``CopyNotKept`` and sends nothing: an auditor never holds a workpaper that Sustentra has no record of.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass

from backend.app.services.workpaper_copy_store import (
    CopyRecord,
    WorkpaperCopyCorrupt,
    WorkpaperCopyStore,
    sha256_of,
)

logger = logging.getLogger("sustentra.workpaper_copies")


class CopyTooLarge(Exception):
    def __init__(self, size: int, limit: int) -> None:
        super().__init__(f"workpaper is {size} bytes; the limit for a kept copy is {limit}")
        self.size = size
        self.limit = limit


class CopyNotKept(Exception):
    """The copy could not be saved. Nothing may be sent."""


@dataclass(frozen=True)
class Kept:
    copy: CopyRecord
    content: bytes
    reused: bool  # the content matched the engagement's newest copy, so no new copy was made


async def keep_for_download(
    store: WorkpaperCopyStore,
    *,
    build: Callable[[], tuple[bytes, str]],
    org_id: str,
    engagement_id: str,
    file_name: str,
    app_version: str,
    user_id: uuid.UUID | None,
    email: str | None,
    request_id: str | None,
    max_bytes: int,
) -> Kept:
    """Build the workpaper, keep it, record the download; return the bytes to serve.

    When what the workbook says (its fingerprint, which ignores the time it was prepared, includes who
    prepared it and the app version) equals the engagement's newest copy, no new copy is made: that copy's
    own bytes are served and the download is recorded against it, so the file an auditor holds is always
    byte-for-byte a kept one. Its "Exported" time is then the time it was first prepared. Only one set of
    bytes is held at a time: the freshly built file is dropped before the kept one is read.
    """

    content, fingerprint = build()
    size = len(content)
    if size > max_bytes:
        raise CopyTooLarge(size, max_bytes)
    try:
        await store.lock(engagement_id)
        latest = await store.latest(engagement_id)
        copy: CopyRecord | None = None
        if latest is not None and latest.content_fingerprint == fingerprint:
            del content  # one copy of the bytes in memory, not two
            try:
                found = await store.read(engagement_id, latest.id)
            except WorkpaperCopyCorrupt:
                # The kept copy is damaged: say so, and keep a fresh one rather than hand out the damaged file
                # or stop the download.
                logger.error("kept workpaper %s of engagement %s does not match its SHA-256; keeping a new copy",
                             latest.id, engagement_id)
                found = None
                content, fingerprint = build()
            else:
                if found is None:  # pragma: no cover - the row was just read
                    raise RuntimeError("the newest copy vanished")
                copy, content = found
        reused = copy is not None
        if copy is None:
            copy = await store.add(
                CopyRecord(
                    id=uuid.uuid4(), org_id=org_id, engagement_id=engagement_id, file_name=file_name,
                    size_bytes=len(content), sha256=sha256_of(content), content_fingerprint=fingerprint,
                    app_version=app_version, prepared_by_user_id=user_id, prepared_by_email=email,
                    request_id=request_id, created_at=None,  # the database sets it
                ),
                content,
            )
        await store.add_download(copy, kind="prepared", user_id=user_id, email=email, request_id=request_id)
    except Exception as exc:
        logger.exception("workpaper copy not kept (engagement %s, request %s)", engagement_id, request_id)
        raise CopyNotKept(str(exc)) from exc
    return Kept(copy=copy, content=content, reused=reused)
