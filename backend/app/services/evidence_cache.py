"""A small in-process cache for the Evidence page's heavy reads (MVP-160).

The Evidence tree, a line's schedule and the recalculation all start from the same expensive step:
reading every document of the engagement with its extraction results and review decisions, placing
every record and calculating. For an engagement of hundreds of documents that is seconds, and the
schedule used to repeat the whole thing on every request.

What is kept, per engagement: the loaded documents and lines (``LOADED``) and the recalculation
(``RECALCULATION``). Each entry carries a *stamp*, a cheap digest of everything the result is built from
(the engagement row, the reviewers' workpaper items, and the engagement's documents, extraction results
and review decisions: ``stamp()`` below, a handful of aggregate queries and no row reads). A request
computes the stamp first and uses an entry only when the stamp is unchanged, so any change that could
alter a total (a decision, an edit in Setup, a new document, a re-read, a Methodology choice) makes the
next request calculate afresh. The stamp is read before the data, so a change that lands in between is at
worst caught on the next request, never missed.

Rules:
* in-process only (no Redis), and bounded: at most ``max_entries`` engagements per cache, least recently
  used first out;
* organization-scoped: the key holds the signed-in organization (or "provider"), because what a reader may
  see differs by organization, so one organization can never be served another's entry;
* values are shared between requests: callers must treat them as read-only.
"""

from __future__ import annotations

import hashlib
import json
import threading
from collections import OrderedDict
from collections.abc import Hashable
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


class EvidenceCache:
    def __init__(self, max_entries: int, max_bytes: int = 32 * 1024 * 1024) -> None:
        self._max = max_entries
        self._max_bytes = max_bytes
        self._bytes = 0
        self._entries: OrderedDict[Hashable, tuple[str, Any, int]] = OrderedDict()
        self._lock = threading.Lock()
        self.hits = 0
        self.misses = 0

    def get(self, key: Hashable, stamp: str | None) -> Any | None:
        """The value kept for ``key`` when it was built from exactly ``stamp``, else None."""

        if stamp is None:
            return None
        with self._lock:
            found = self._entries.get(key)
            if found is None or found[0] != stamp:
                self.misses += 1
                return None
            self._entries.move_to_end(key)
            self.hits += 1
            return found[1]

    def put(self, key: Hashable, stamp: str | None, value: Any, size: int = 0) -> None:
        """Keep ``value`` (about ``size`` bytes) for ``key``. Least recently used entries go first when there
        are more than ``max_entries`` or more than ``max_bytes`` in all; a value larger than ``max_bytes`` is not kept."""

        if stamp is None:
            return
        with self._lock:
            old = self._entries.pop(key, None)
            if old is not None:
                self._bytes -= old[2]
            if size > self._max_bytes:
                return
            self._entries[key] = (stamp, value, size)
            self._bytes += size
            while len(self._entries) > self._max or self._bytes > self._max_bytes:
                _, (_, _, dropped) = self._entries.popitem(last=False)
                self._bytes -= dropped

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
            self._bytes = 0
            self.hits = self.misses = 0

    def __len__(self) -> int:
        return len(self._entries)

    @property
    def size_bytes(self) -> int:
        return self._bytes


# One engagement's loaded documents and lines, and its recalculation. Few entries: each holds every record of
# an engagement, which for hundreds of documents is megabytes.
# 32 MB each, 64 MB per worker in all, whichever limit is reached first.
LOADED = EvidenceCache(max_entries=8, max_bytes=32 * 1024 * 1024)
RECALCULATION = EvidenceCache(max_entries=8, max_bytes=32 * 1024 * 1024)


def size_of_response(value: Any) -> int:
    """About how large a JSON-like result is: the length of its JSON text (a recalculation is served as JSON anyway)."""

    return len(json.dumps(value, default=str, ensure_ascii=False))


def scope_of(user: Any) -> str:
    """Whose view an entry is: one organization's, or the provider's (who also sees records no organization owns)."""

    return "provider" if getattr(user, "is_provider", False) else f"org:{getattr(user, 'org_id', None)}"


def digest(value: Any) -> str:
    return hashlib.md5(json.dumps(value, sort_keys=True, default=str, ensure_ascii=False).encode("utf-8"),
                       usedforsecurity=False).hexdigest()


# The reviewers' items (decisions, Methodology choices, requests ...) of one engagement. A heartbeat on a
# running Methodology read (``claim``) is not a change to what they say, so it is left out of the digest.
_ITEMS_STAMP = text(
    "SELECT count(*) AS n, coalesce(max(updated_at)::text, '') AS top, "
    "md5(coalesce(string_agg(kind || ':' || item_key || ':' || md5((payload - 'claim')::text), '|' "
    "ORDER BY kind, item_key), '')) AS digest FROM workpaper_items WHERE engagement_id = :engagement_id"
)


async def stamp(db: AsyncSession, engagement: dict[str, Any], upload: Any, pipeline: Any, reviews: Any,
                *, fresh: bool = False) -> str | None:
    """The digest of everything the Evidence tree, schedule and recalculation of this engagement are built from,
    or None when a store cannot give one (then nothing is cached). ``fresh``: read the engagement row again too
    (the stamp taken after a load, to see whether anything changed meanwhile).

    It holds the content (a hash) and, as well, the newest change time or count of each source: a change that is
    undone again (A, then B, then A) still leaves a different stamp, since the change time only moves forward."""

    stamps = (getattr(upload, "documents_stamp", None), getattr(pipeline, "extraction_stamp", None),
              getattr(reviews, "engagement_stamp", None))
    if any(s is None for s in stamps):
        return None
    engagement_id = engagement["id"]
    if fresh:
        from backend.app.services import engagement_service

        engagement = await engagement_service.get_engagement(db, str(engagement_id)) or engagement
    row = (await db.execute(_ITEMS_STAMP, {"engagement_id": engagement_id})).one()
    key = str(engagement_id)
    return digest([engagement, f"{row.n}:{row.top}:{row.digest}", *(read(key) for read in stamps if read is not None)])
