"""Reading a large PDF in page chunks (queued mode).

Three steps, on the queue the document reads already use:

1. **Plan** (``DocumentChunkService.step``, called by the executor of a run): a PDF with more than
   ``S1_CHUNK_THRESHOLD_PAGES`` pages is split into blocks of ``S1_CHUNK_PAGES`` pages. The chunk
   rows are queued and the run parks in ``waiting_on_chunks`` in one transaction. A document over
   ``S1_MAX_DOCUMENT_PAGES`` is not read at all: the run is partial with the halt
   ``document_too_long``.
2. **Read a chunk** (``execute`` / ``finish``, called by the reader, which claims chunks before
   runs): the chunk's pages go through ``ParserService`` with a page range, so page numbers in the
   output are the document's own. The output is stored on the chunk. A chunk that fails is read
   again after the run backoff, up to its ``max_attempts``, and is then ``failed``. The last
   chunk to end wakes the parked run (``document_chunk_repository``).
3. **Assemble** (``step`` again, when the woken run is claimed): the chunk outputs are merged in
   page order into one parser output, and the run goes on with classify, targets, extract and
   persist as for any document, so the extractors see the whole document. Pages of failed chunks
   are reported as unread: the run is ``partial`` with a ``pages_unread`` warning.

Nothing here runs inline (``S1_PROCESSING=inline``) or for a PDF at or under the threshold: those
are read as before.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from backend.app.adapters.parsers.base import build_empty_parser_output, build_warning
from backend.app.core.config import Settings
from backend.app.repositories.document_chunk_repository import OCR_PAGE_FAILED, DocumentChunk, ocr_failed_pages
from backend.app.services.document_processing_service import RETRY_DELAYS_SECONDS, stored_file
from backend.app.services.parser_service import ParserService

logger = logging.getLogger("sustentra.chunks")

HALT_DOCUMENT_TOO_LONG = "document_too_long"
PAGES_UNREAD = "pages_unread"
_RENAMED_IDS = ("block_id", "source_reference_id", "key_source_reference_id", "value_source_reference_id")


@dataclass(frozen=True)
class ChunkingSettings:
    enabled: bool = False  # chunk new large PDFs (queued mode); parked runs are assembled either way
    threshold_pages: int = 20
    chunk_pages: int = 10
    max_pages: int = 500
    max_attempts: int = 3

    @classmethod
    def from_settings(cls, settings: Settings) -> ChunkingSettings:
        return cls(
            enabled=settings.s1_processing == "queued",
            threshold_pages=settings.s1_chunk_threshold_pages,
            chunk_pages=settings.s1_chunk_pages,
            max_pages=settings.s1_max_document_pages,
            max_attempts=settings.s1_chunk_max_attempts,
        )


# --- pure helpers ---------------------------------------------------------------------------

def split_pages(page_count: int, chunk_pages: int) -> list[tuple[int, int]]:
    """Page ranges (1-based, inclusive) of ``chunk_pages`` pages each; the last may be shorter."""

    return [(first, min(first + chunk_pages - 1, page_count)) for first in range(1, page_count + 1, chunk_pages)]


def _page_ranges(ranges: list[tuple[int, int]]) -> str:
    joined: list[list[int]] = []
    for first, last in sorted(ranges):
        if joined and first <= joined[-1][1] + 1:
            joined[-1][1] = max(joined[-1][1], last)
        else:
            joined.append([first, last])
    return ", ".join(str(a) if a == b else f"{a}-{b}" for a, b in joined)


def pages_unread_message(ranges: list[tuple[int, int]]) -> str:
    return f"Pages {_page_ranges(ranges)} could not be read, so any values on them are missing."


def too_long_halt(page_count: int, max_pages: int) -> dict[str, str]:
    return {
        "code": HALT_DOCUMENT_TOO_LONG,
        "message": f"This document has {page_count} pages, more than the {max_pages} we read in one document. "
                   "Split it into smaller files and upload them separately.",
    }


def pdf_page_count(path: Path) -> int | None:
    """Pages of a PDF, ``None`` when it cannot be opened (the normal read reports that)."""

    try:
        import fitz

        with fitz.open(path) as pdf:
            return int(pdf.page_count)
    except Exception:  # noqa: BLE001 - any unreadable file is the normal read's to report
        return None


def _renamed(item: dict[str, Any], prefix: str) -> dict[str, Any]:
    out = dict(item)
    for key in _RENAMED_IDS + ("pair_id", "table_id"):
        if isinstance(out.get(key), str):
            out[key] = prefix + out[key]
    if isinstance(out.get("parser_block_ids"), list):
        out["parser_block_ids"] = [prefix + str(i) for i in out["parser_block_ids"]]
    return out


def merge_chunk_outputs(
    chunks: list[DocumentChunk], document_id: str, run_id: str
) -> tuple[dict[str, Any], list[tuple[int, int]]]:
    """One parser output from the chunks' outputs, in page order, and the page ranges nothing read.

    Text blocks, key-value pairs, tables, source references, pages and warnings are
    concatenated. Ids stay as the parser made them (they carry their page number); a chunk
    whose ids would collide with an earlier chunk's gets all of them prefixed ``c{index}:``,
    references included. The status follows what a one-pass read of the same pages would say:
    ``parsed`` when every chunk is, ``empty`` when none found text, ``partial`` otherwise
    (including when some pages are unread).
    """

    ordered = sorted(chunks, key=lambda c: c.page_from)
    done = [c for c in ordered if c.status == "completed" and isinstance(c.parser_output, dict)]
    unread = [(c.page_from, c.page_to) for c in ordered if c not in done]
    for chunk in done:  # pages Textract failed on in a chunk kept on its last attempt
        failed = [str(w.get("message")) for w in (chunk.parser_output or {}).get("warnings") or []
                  if isinstance(w, dict) and w.get("code") == OCR_PAGE_FAILED]
        unread += [(n, n) for n in ocr_failed_pages(failed)]
    if not done:
        warnings = [build_warning(PAGES_UNREAD, pages_unread_message(unread), severity="warning")] if unread else []
        return build_empty_parser_output(document_id=document_id, processing_run_id=run_id,
                                         parser_name="pdf_parser", warnings=warnings), unread

    merged: dict[str, Any] = {key: [] for key in
                              ("pages", "text_blocks", "tables", "key_value_pairs", "source_references", "warnings")}
    seen: set[str] = set()
    for chunk in done:
        output = chunk.parser_output or {}
        ids = {str(item[key]) for name in ("text_blocks", "source_references", "key_value_pairs", "tables")
               for item in output.get(name) or [] for key in (*_RENAMED_IDS, "pair_id", "table_id")
               if isinstance(item.get(key), str)}
        prefix = f"c{chunk.chunk_index}:" if ids & seen else ""
        seen |= {prefix + i for i in ids}
        for key in merged:
            for item in output.get(key) or []:
                merged[key].append(_renamed(item, prefix) if prefix and key != "pages" and key != "warnings" else item)

    statuses = {str((c.parser_output or {}).get("status")) for c in done}
    if unread:
        merged["warnings"].append(build_warning(PAGES_UNREAD, pages_unread_message(unread), severity="warning"))
    status = ("parsed" if statuses == {"parsed"} and not unread else
              "empty" if statuses == {"empty"} and not unread else "partial")
    base = dict(done[0].parser_output or {})  # header fields (parser_name, created_at, ...) come from the first chunk
    return {**base, "document_id": document_id, "processing_run_id": run_id, "status": status, **merged}, unread


# --- executor hooks -------------------------------------------------------------------------

@dataclass(frozen=True)
class ChunkStep:
    """What the executor of a run does next. ``kind``: ``none`` (read the document as usual),
    ``waiting`` (the run is parked on its chunks), ``assembled`` (read with ``parser_output``,
    ``unread_pages``) or ``too_long`` (stop with ``halt``)."""

    kind: Literal["none", "waiting", "assembled", "too_long"]
    parser_output: dict[str, Any] | None = None
    unread_pages: list[tuple[int, int]] = field(default_factory=list)
    halt: dict[str, str] | None = None


@dataclass(frozen=True)
class ChunkOutcome:
    status: Literal["completed", "failed", "retry"]
    parser_output: dict[str, Any] | None = None
    error_code: str | None = None  # on a completed chunk: OCR_PAGE_FAILED when some pages stayed unread


class DocumentChunkService:
    def __init__(self, chunks: Any, uploads: Any, storage: Any, settings: ChunkingSettings | None = None,
                 parser: Any | None = None) -> None:
        self._chunks = chunks
        self._uploads = uploads
        self._storage = storage
        self.settings = settings or ChunkingSettings()
        self._parser = parser or ParserService()

    # --- the run's side: plan, then assemble -----------------------------------------------------

    def step(self, run: Any, worker_id: str, document: dict[str, Any], path: Path) -> ChunkStep:
        """Called by the executor with the claimed run, inside its organization's scope."""

        existing = self._chunks.list_for_run(run.run_id)
        if existing:  # woken after its chunks ended
            output, unread = merge_chunk_outputs(existing, run.document_id, run.run_id)
            logger.info("chunks_assembled", extra={
                "run_id": run.run_id, "chunks": len(existing), "unread_chunks": len(unread)})
            return ChunkStep("assembled", parser_output=output, unread_pages=unread)
        s = self.settings
        if not s.enabled or ParserService.parser_kind(path, document.get("mime_type")) != "pdf":
            return ChunkStep("none")
        count = pdf_page_count(path)
        if count is None or count <= s.threshold_pages:
            return ChunkStep("none")
        if count > s.max_pages:
            logger.info("document_too_long", extra={"run_id": run.run_id, "pages": count})
            return ChunkStep("too_long", halt=too_long_halt(count, s.max_pages))
        ranges = split_pages(count, s.chunk_pages)
        if self._chunks.plan(run, worker_id, ranges, s.max_attempts):
            logger.info("chunks_planned", extra={"run_id": run.run_id, "pages": count, "chunks": len(ranges)})
        return ChunkStep("waiting")  # also when the run is no longer this reader's: nothing to do

    # --- the chunk's side: read, record ----------------------------------------------------------

    def execute(self, chunk: DocumentChunk) -> ChunkOutcome:
        """Read the chunk's pages (one attempt), in the chunk's organization scope. Never raises."""

        document = self._uploads.get_document(chunk.document_id)
        if document is None:
            return ChunkOutcome("failed", error_code="document_missing")
        path = stored_file(self._storage, document, chunk.org_id)
        if path is None:
            return ChunkOutcome("failed", error_code="file_missing")
        try:
            output = self._parser.parse_document(
                file_path=str(path), document_id=chunk.document_id, processing_run_id=chunk.run_id,
                mime_type=document.get("mime_type"), pages=(chunk.page_from, chunk.page_to))
        except Exception as exc:  # the type only: a message can carry file names
            logger.error("chunk_read_failed", extra={
                "run_id": chunk.run_id, "chunk_index": chunk.chunk_index, "error_type": type(exc).__name__})
            return ChunkOutcome("retry", error_code="chunk_error")
        if output.get("status") == "failed":
            return ChunkOutcome("retry", error_code="parse_failed")
        codes = {w.get("code") for w in output.get("warnings") or [] if isinstance(w, dict)}
        if OCR_PAGE_FAILED in codes and chunk.attempts < chunk.max_attempts:
            return ChunkOutcome("retry", error_code=OCR_PAGE_FAILED)  # Textract failed on a page: try again
        return ChunkOutcome("completed", parser_output=output,
                            error_code=OCR_PAGE_FAILED if OCR_PAGE_FAILED in codes else None)

    def finish(self, chunk: DocumentChunk, outcome: ChunkOutcome, worker_id: str) -> DocumentChunk | None:
        """Record the outcome, fenced to this reader. ``None`` when the chunk is no longer its."""

        if outcome.status == "completed":
            result = self._chunks.finalize_completed(chunk, worker_id, outcome.parser_output or {},
                                                   outcome.error_code)
        elif outcome.status == "retry" and chunk.attempts < chunk.max_attempts:
            delay = RETRY_DELAYS_SECONDS[min(chunk.attempts, len(RETRY_DELAYS_SECONDS)) - 1]
            result = self._chunks.retry_later(chunk, worker_id, delay, outcome.error_code)
        else:
            result = self._chunks.finalize_failed(chunk, worker_id, outcome.error_code or "chunk_error")
        if result is not None:
            logger.info("chunk_finished", extra={
                "run_id": chunk.run_id, "chunk_index": chunk.chunk_index, "status": result.status,
                "attempt": chunk.attempts, "error_code": result.error_code})
        return result
