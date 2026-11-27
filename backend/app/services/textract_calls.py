"""A record of every Textract call the app makes (MVP-244), for the usage ledger (MVP-245) to build on.

``AwsTextractParser`` calls ``record_textract_call`` once per AnalyzeDocument call, successful or not,
with the number of pages billed and the mode. The record is logged (``textract_call``) and handed to
every registered hook. Who the call was for (organization, document, content hash) comes from
``textract_context``, which ``ParserService`` binds around a read; a call made with nothing bound
carries ``None`` for those. A hook that raises never stops a read.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger("sustentra.textract_calls")

ANALYZE_DOCUMENT = "analyze_document"  # the synchronous API: one image, or one page of a PDF

_context: ContextVar[dict[str, Any] | None] = ContextVar("textract_call_context", default=None)
_hooks: list[Callable[[dict[str, Any]], None]] = []


@contextmanager
def textract_context(**fields: Any) -> Iterator[None]:
    """Bind who the Textract calls inside the block are for (``org_id``, ``document_id``, ``sha256``)."""

    token = _context.set({**(_context.get() or {}), **fields})
    try:
        yield
    finally:
        _context.reset(token)


def register_textract_hook(hook: Callable[[dict[str, Any]], None]) -> Callable[[], None]:
    """Call ``hook(record)`` for every Textract call from now on. Returns a function that removes it."""

    _hooks.append(hook)

    def remove() -> None:
        if hook in _hooks:
            _hooks.remove(hook)

    return remove


def record_textract_call(*, pages: int = 1, mode: str = ANALYZE_DOCUMENT, ok: bool = True,
                         feature_types: list[str] | None = None) -> dict[str, Any]:
    record: dict[str, Any] = {
        "at": datetime.now(UTC).isoformat(),
        "pages": pages,
        "mode": mode,
        "ok": ok,
        "feature_types": feature_types or [],
        "org_id": None,
        "document_id": None,
        "sha256": None,
        **(_context.get() or {}),
    }
    logger.info("textract_call", extra={k: v for k, v in record.items() if k != "at"})
    for hook in list(_hooks):
        try:
            hook(record)
        except Exception:  # noqa: BLE001 - a ledger fault must not fail a read
            logger.exception("textract call hook failed")
    return record
