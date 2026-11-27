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
import concurrent.futures
import logging
import threading
from collections.abc import Awaitable, Callable
from typing import Any

from backend.app.core.config import get_settings
from backend.app.services.calculation_lines import SUMMARY_TYPES

logger = logging.getLogger("sustentra.auto_read")

# How long shutdown waits for reads under way to end (their calls recorded, their claim released). Inside the api
# container's stop grace period (40 s, deploy/docker-compose.prod.yml), with room for the rest of the shutdown.
SHUTDOWN_DRAIN_SECONDS = 25.0

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
        self._engine: Any = None
        # Reads under way (started by ``submit``, or an automatic read past its wait) and not yet ended: shutdown waits
        # for them, so every call they paid for is written to the ledger and their claim is released.
        self._jobs: set[concurrent.futures.Future[Any]] = set()
        self._stopping = threading.Event()

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
        if self._stopping.is_set():
            return  # shutting down: nothing new starts (the next summary document asks again)
        running: concurrent.futures.Future[Any] = concurrent.futures.Future()
        self._jobs.add(running)
        try:
            async with self._busy.setdefault(engagement_id, asyncio.Lock()):  # one read of an engagement at a time
                try:
                    await self._run_fn()(org_id, engagement_id, names)
                except Exception as exc:
                    logger.error("auto_read_failed", extra={"error_type": type(exc).__name__})
        finally:
            running.set_result(None)
            self._jobs.discard(running)

    def submit(self, job: Callable[[Any], Awaitable[Any]]) -> None:
        """Run ``job(sessions)`` on this reader's loop, with its own database pool, now (no debounce): the read a
        reviewer asked for (``methodology_review.prefill_methodology``). It outlives the request that asked for it.
        Safe from any thread; never raises from the job into the caller."""

        if self._stopping.is_set():
            raise RuntimeError("the reader is shutting down")
        loop = self._ensure_loop()

        async def run() -> None:
            try:
                await job(self._sessionmaker())
            except Exception as exc:  # the job records its own ending; this is the last resort
                logger.error("requested_read_failed", extra={"error_type": type(exc).__name__})

        future = asyncio.run_coroutine_threadsafe(run(), loop)
        self._jobs.add(future)  # a reference until it ends, so the task is never collected mid-read
        future.add_done_callback(self._jobs.discard)

    # The real work is built on first use, on the loop thread (the pool belongs to this loop).
    def _sessionmaker(self) -> Any:
        if self._sessions is None:
            from backend.app.core.db import build_sessionmaker, create_engine, runtime_database_url

            # Four: a read's ledger rows (up to four calls of a part at once), its claim heartbeat and its marker.
            self._engine = create_engine(runtime_database_url(get_settings()), pool_size=4, max_overflow=2)
            self._sessions = build_sessionmaker(self._engine)
        return self._sessions

    def is_stopping(self) -> bool:
        """True once shutdown has begun: a read under way starts no new part (``methodology_review``)."""

        return self._stopping.is_set()

    def shutdown(self, timeout: float = 5.0, drain_seconds: float = SHUTDOWN_DRAIN_SECONDS) -> None:
        """Stop the background loop and close its database pool (the API's shutdown), without losing what was paid
        for: (1) nothing new starts, and a read under way starts no new part or call; (2) the reads under way get up
        to ``drain_seconds`` to finish the calls already sent, write their ledger rows, leave their marker and release
        their claim, while the loop still runs; (3) the waits are cancelled and the pool is closed. A read still going
        after ``drain_seconds`` is cut off: its claim expires on its own (CLAIM_TTL_SECONDS) and reads as interrupted.
        ``drain_seconds`` stays inside the api container's stop grace period (deploy/docker-compose.prod.yml)."""

        self._stopping.set()
        with self._lock:
            loop = self._loop
        if loop is None:
            return
        jobs = list(self._jobs)
        if jobs:
            _done, left = concurrent.futures.wait(jobs, timeout=drain_seconds)
            if left:
                logger.error("auto_read_shutdown_cut_off", extra={"reads": len(left)})
        with self._lock:
            loop, self._loop = self._loop, None
        if loop is None:
            return

        async def close() -> None:
            for task, _names in list(self._pending.values()):
                task.cancel()
            self._pending.clear()
            if self._engine is not None:
                await self._engine.dispose()
                self._engine, self._sessions = None, None

        try:
            asyncio.run_coroutine_threadsafe(close(), loop).result(timeout)
        except Exception as exc:  # shutting down anyway
            logger.error("auto_read_shutdown_failed", extra={"error_type": type(exc).__name__})
        loop.call_soon_threadsafe(loop.stop)

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


def stopping() -> bool:
    """Whether the process's reader is shutting down (a read under way then starts no new part)."""

    reader = _reader
    return reader is not None and reader.is_stopping()


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


def shutdown() -> None:
    """Close the process's reader, if one was started."""

    with _reader_lock:
        reader = _reader
    if reader is not None:
        reader.shutdown()


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
