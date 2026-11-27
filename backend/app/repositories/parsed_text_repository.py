"""S1 parsed texts (migration 0027): what a reader made of a file, kept so the file is never read (and
Textract never paid for) twice.

One row per (organization, SHA-256 of the file's bytes, reader version, page range). The row holds the
whole ``parser_output`` (page text, and for a scan the OCR blocks, tables and source references that the
pipeline uses), the reader that made it, its page count and whether OCR was used. ``page_from`` and
``page_to`` are 0 for the whole document, or the 1-based range of a chunk of a large PDF.

Never shared across organizations: the organization is part of the key, and the Postgres store works in
that organization's own scope (RLS), whatever scope the caller is in.

Three implementations with the same interface, as the other S1 stores:

* ``PostgresParsedTextRepository``: ``s1_parsed_texts``.
* ``JsonlParsedTextRepository``: an append-only file (the newest row for a key wins).
* ``InMemoryParsedTextRepository``: for tests.

``get`` returns ``None`` for a missing row and for a row that cannot be used (corrupt, or empty); the
caller then reads the file again and ``put`` replaces the row.
"""

from __future__ import annotations

import copy
import json
import logging
import threading
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Engine

from backend.app.core.db import get_sync_engine, tenant_transaction
from backend.app.core.s1_scope import S1Scope

logger = logging.getLogger("sustentra.parsed_texts")

DEFAULT_JSONL_PATH = "local-data/parsed-texts/parsed_texts.jsonl"
MAX_STORED_BYTES = 40 * 1024 * 1024  # a parsed document larger than this is read again, not kept
USABLE_STATUSES = ("parsed", "partial", "empty")


def usable(record: Any) -> dict[str, Any] | None:
    """The row's ``parser_output`` when it can stand in for a read; ``None`` for a corrupt or empty row."""

    if not isinstance(record, dict):
        return None
    output = record.get("parser_output")
    if not isinstance(output, dict) or output.get("status") not in USABLE_STATUSES:
        return None
    pages = output.get("pages")
    if not isinstance(pages, list) or not isinstance(record.get("page_count"), int):
        return None
    if record["page_count"] != len(pages):
        return None  # a row cut or changed after it was written
    if output["status"] != "empty" and not pages:
        return None
    return output


def _key(org_id: str, sha256: str, reader_version: str, page_from: int, page_to: int) -> tuple[str, str, str, int, int]:
    return (str(org_id).lower(), sha256, reader_version, int(page_from), int(page_to))


def build_record(org_id: str, sha256: str, reader_version: str, page_from: int, page_to: int,
                 output: dict[str, Any]) -> dict[str, Any]:
    pages = output.get("pages") or []
    warnings = output.get("warnings") or []
    return {
        "org_id": str(org_id), "sha256": sha256, "reader_version": reader_version,
        "page_from": int(page_from), "page_to": int(page_to),
        "reader_name": str(output.get("parser_name") or ""),
        "page_count": len(pages),
        "ocr_used": str(output.get("parser_name")) == "aws_textract" or any(
            isinstance(w, dict) and w.get("code") == "ocr_applied" for w in warnings),
        "status": str(output.get("status")),
        "parser_output": output,
    }


class InMemoryParsedTextRepository:
    def __init__(self) -> None:
        self._rows: dict[tuple[str, str, str, int, int], dict[str, Any]] = {}
        self._lock = threading.Lock()

    def get(self, org_id: str, sha256: str, reader_version: str, page_from: int = 0,
            page_to: int = 0) -> dict[str, Any] | None:
        with self._lock:
            row = self._rows.get(_key(org_id, sha256, reader_version, page_from, page_to))
            return copy.deepcopy(usable(row))

    def put(self, org_id: str, sha256: str, reader_version: str, page_from: int, page_to: int,
            output: dict[str, Any]) -> None:
        record = build_record(org_id, sha256, reader_version, page_from, page_to, copy.deepcopy(output))
        with self._lock:
            self._rows[_key(org_id, sha256, reader_version, page_from, page_to)] = record


class JsonlParsedTextRepository:
    def __init__(self, path: str | Path = DEFAULT_JSONL_PATH) -> None:
        self._path = Path(path)

    @property
    def path(self) -> Path:
        return self._path

    def get(self, org_id: str, sha256: str, reader_version: str, page_from: int = 0,
            page_to: int = 0) -> dict[str, Any] | None:
        if not self._path.exists():
            return None
        wanted = _key(org_id, sha256, reader_version, page_from, page_to)
        found: dict[str, Any] | None = None
        for line in self._path.read_text(encoding="utf-8").splitlines():
            try:
                record = json.loads(line)
                key = _key(record["org_id"], record["sha256"], record["reader_version"],
                           record["page_from"], record["page_to"])
            except (ValueError, KeyError, TypeError):
                continue  # a damaged line is skipped, not fatal
            if key == wanted:
                found = record  # the newest row for the key wins
        return usable(found)

    def put(self, org_id: str, sha256: str, reader_version: str, page_from: int, page_to: int,
            output: dict[str, Any]) -> None:
        record = build_record(org_id, sha256, reader_version, page_from, page_to, output)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")


_GET = text(
    "SELECT page_count, status, parser_output FROM s1_parsed_texts "
    "WHERE org_id = :org_id AND sha256 = :sha256 AND reader_version = :reader_version "
    "AND page_from = :page_from AND page_to = :page_to"
)
_PUT = text(
    "INSERT INTO s1_parsed_texts (id, org_id, sha256, reader_version, page_from, page_to, reader_name, "
    "page_count, ocr_used, status, parser_output) "
    "VALUES (:id, :org_id, :sha256, :reader_version, :page_from, :page_to, :reader_name, :page_count, "
    ":ocr_used, :status, CAST(:parser_output AS jsonb)) "
    "ON CONFLICT (org_id, sha256, reader_version, page_from, page_to) DO UPDATE SET "
    "reader_name = EXCLUDED.reader_name, page_count = EXCLUDED.page_count, ocr_used = EXCLUDED.ocr_used, "
    "status = EXCLUDED.status, parser_output = EXCLUDED.parser_output, updated_at = now()"
)


class PostgresParsedTextRepository:
    """``s1_parsed_texts``. Every call is one short transaction in the scope of the row's own
    organization, so another organization's row is never visible, even from provider scope."""

    def __init__(self, engine: Engine | None = None) -> None:
        self._engine = engine

    def _scope(self, org_id: str) -> S1Scope:
        return S1Scope.tenant(uuid.UUID(str(org_id)))

    def get(self, org_id: str, sha256: str, reader_version: str, page_from: int = 0,
            page_to: int = 0) -> dict[str, Any] | None:
        with tenant_transaction(self._scope(org_id), self._engine or get_sync_engine()) as connection:
            row = connection.execute(_GET, {
                "org_id": str(uuid.UUID(str(org_id))), "sha256": sha256, "reader_version": reader_version,
                "page_from": int(page_from), "page_to": int(page_to)}).first()
        if row is None:
            return None
        output = row.parser_output
        if isinstance(output, str):
            try:
                output = json.loads(output)
            except ValueError:
                return None
        return usable({"page_count": row.page_count, "parser_output": output})

    def put(self, org_id: str, sha256: str, reader_version: str, page_from: int, page_to: int,
            output: dict[str, Any]) -> None:
        record = build_record(org_id, sha256, reader_version, page_from, page_to, output)
        payload = json.dumps(record["parser_output"], ensure_ascii=False, default=str)
        if len(payload) > MAX_STORED_BYTES:
            logger.warning("parsed text not kept: too large", extra={"sha256": sha256, "bytes": len(payload)})
            return
        payload = payload.replace("\\u0000", "")  # Postgres jsonb refuses the NUL escape
        with tenant_transaction(self._scope(org_id), self._engine or get_sync_engine()) as connection:
            connection.execute(_PUT, {
                "id": str(uuid.uuid4()), "org_id": str(uuid.UUID(str(org_id))), "sha256": sha256,
                "reader_version": reader_version, "page_from": record["page_from"], "page_to": record["page_to"],
                "reader_name": record["reader_name"], "page_count": record["page_count"],
                "ocr_used": record["ocr_used"], "status": record["status"], "parser_output": payload})
