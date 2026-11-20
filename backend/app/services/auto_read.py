"""Sustentra's AI reads a company summary document by itself, once, after it is read.

When a processing run completes and the document is a summary type (Block 1, ``calculation_lines.
SUMMARY_TYPES``: a GHG workbook, boundary statement, methodology statement, ...), the executor
(``DocumentProcessingService.finish``, in the API for inline reads and in the reader process for queued
ones) calls ``notify_completed``. This module then runs the same code as the "Read the client's reports"
button (``methodology_review.run_automatic_prefill``), never inside that request:

* a background thread with its own event loop and its own small database pool runs it, so it never
  holds a request or the reader's own work up;
* debounce per engagement: every new summary document of the engagement restarts the wait
  (``AI_AUTO_READ_DEBOUNCE_SECONDS``, 30 s); a batch of uploads is read once, after the last one;
* only a new summary document starts a read: there is no timer that re-reads;
* the read itself respects the busy lock, the deployment's AI switch and the monthly spend gate and
  skips, recording why, when one says no; a reviewer's decision is never overwritten;
* the organization may switch it off (``organizations.auto_read_summaries``; PATCH /orgs/{id}/settings).

It never raises into the caller: a document's read is recorded as it ended whatever happens here.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from collections.abc import Awaitable, Callable
from typing import Any

from backend.app.core.config import get_settings
from backend.app.services.calculation_lines import SUMMARY_TYPES

logger = logging.getLogger("sustentra.auto_read")

# (org_id, engagement_id, file names) -> whether to go on; writes the page's "will read ... shortly" marker.
Prepare = Callable[[str, str, list[str]], Awaitable[bool]]
# (org_id, engagement_id, file names) -> None; reads, records what it did.
Run = Callable[[str, str, list[str]], Awaitable[Any]]


class AutoReader:
    def __init__(self, *, debounce_seconds: Callable[[], float] | float | None = None,
                 prepare: Prepare | None = None, run: Run | None = None) -> None:
        self._debounce = debounce_seconds
        self._prepare, self._run = prepare, run
        self._lock = threading.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._pending: dict[str, tuple[asyncio.Task[None], list[str]]] = {}  # on the loop thread only
        self._busy: dict[str, asyncio.Lock] = {}
        self._sessions: Any = None

    def debounce_seconds(self) -> float:
        value = self._debounce
        return float(value() if callable(value) else value) if value is not None \
            else get_settings().ai_auto_read_debounce_seconds

    def note(self, org_id: str, engagement_id: str, file_name: str) -> None:
        """A summary document of the engagement finished reading. Safe from any thread."""

        loop = self._ensure_loop()
        loop.call_soon_threadsafe(self._schedule, str(org_id), str(engagement_id), file_name)

    def _ensure_loop(self) -> asyncio.AbstractEventLoop:
        with self._lock:
            if self._loop is None:
                loop = asyncio.new_event_loop()
                threading.Thread(target=loop.run_forever, name="auto-read", daemon=True).start()
                self._loop = loop
            return self._loop

    def _schedule(self, org_id: str, engagement_id: str, file_name: str) -> None:
        current = self._pending.pop(engagement_id, None)
        names = current[1] if current else []
        if current:
            current[0].cancel()  # restart the wait: one read after the last document of the batch
        if file_name not in names:
            names = [*names, file_name]
        task = asyncio.ensure_future(self._after_wait(org_id, engagement_id, names))
        self._pending[engagement_id] = (task, names)

    async def _after_wait(self, org_id: str, engagement_id: str, names: list[str]) -> None:
        try:
            if not await self._prepare_fn()(org_id, engagement_id, names):
                self._pending.pop(engagement_id, None)
                return
            await asyncio.sleep(self.debounce_seconds())
        except asyncio.CancelledError:
            raise  # a newer document restarted the wait
        except Exception as exc:
            self._pending.pop(engagement_id, None)
            logger.error("auto_read_not_scheduled", extra={"error_type": type(exc).__name__})
            return
        self._pending.pop(engagement_id, None)  # from here on a new document starts the next wait
        async with self._busy.setdefault(engagement_id, asyncio.Lock()):  # one read of an engagement at a time
            try:
                await self._run_fn()(org_id, engagement_id, names)
            except Exception as exc:
                logger.error("auto_read_failed", extra={"error_type": type(exc).__name__})

    # The real work is built on first use, on the loop thread (the pool belongs to this loop).
    def _sessionmaker(self) -> Any:
        if self._sessions is None:
            from backend.app.core.db import build_sessionmaker, create_engine, runtime_database_url

            self._sessions = build_sessionmaker(create_engine(runtime_database_url(get_settings()), pool_size=2,
                                                              max_overflow=0))
        return self._sessions

    def _prepare_fn(self) -> Prepare:
        if self._prepare is not None:
            return self._prepare

        async def prepare(org_id: str, engagement_id: str, names: list[str]) -> bool:
            from backend.app.api import methodology_review as review

            return await review.prepare_automatic_prefill(org_id, engagement_id, names, self._sessionmaker())

        return prepare

    def _run_fn(self) -> Run:
        if self._run is not None:
            return self._run

        async def run(org_id: str, engagement_id: str, names: list[str]) -> Any:
            from backend.app.api import methodology_review as review

            return await review.run_automatic_prefill(org_id, engagement_id, names, self._sessionmaker())

        return run


_reader: AutoReader | None = None
_reader_lock = threading.Lock()


def default_reader() -> AutoReader:
    global _reader
    with _reader_lock:
        if _reader is None:
            _reader = AutoReader()
        return _reader


def set_reader(reader: AutoReader | None) -> None:
    """Swap the process's reader (tests)."""

    global _reader
    _reader = reader


def summary_type(pipeline_run: dict[str, Any] | None) -> bool:
    return str((pipeline_run or {}).get("canonical_type_id") or "") in SUMMARY_TYPES


def notify_completed(org_id: str, engagement_id: str, file_name: str, pipeline_run: dict[str, Any] | None) -> None:
    """A read completed: if the document is a summary type, ask for the automatic read. Never raises."""

    try:
        if not summary_type(pipeline_run) or not get_settings().ai_suggestions_enabled:
            return
        default_reader().note(org_id, engagement_id, file_name)
    except Exception as exc:  # the document's read is recorded either way
        logger.error("auto_read_not_requested", extra={"error_type": type(exc).__name__})
