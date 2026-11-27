"""S1 parsed texts (migration 0027): what a reader made of a file, kept so the file is never read (and
Textract never paid for) twice.

One row per (organization, SHA-256 of the file's bytes, reader version, page range, file kind). The row
holds the whole ``parser_output`` (page text, and for a scan the OCR blocks, tables and source references
that the pipeline uses), the reader that made it, its page count and whether OCR was used. ``page_from``
and ``page_to`` are 0 for the whole document, or the 1-based range of a chunk of a large PDF.
``file_ext`` is the file's extension (and mime type): the same bytes named ``.xls`` or ``.xlsx`` are read
by different readers.

Never shared across organizations: the organization is part of the key, and the Postgres store works in
that organization's own scope (RLS), whatever scope the caller is in.

An output whose encoded size is over ``MAX_STORED_BYTES`` is not kept (the file is read again next time);
that is logged once per file and key. NUL characters are removed from the strings before encoding (Postgres
refuses them).

Three implementations with the same interface, as the other S1 stores:

* ``PostgresParsedTextRepository``: ``s1_parsed_texts``.
* ``JsonlParsedTextRepository``: an append-only file (the newest row for a key wins), indexed by key.
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
MAX_STORED_BYTES = 10 * 1024 * 1024  # encoded: a parsed document larger than this is read again, not kept
USABLE_STATUSES = ("parsed", "partial", "empty")

Key = tuple[str, str, str, int, int, str]
_logged_too_large: set[Key] = set()


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


def _key(org_id: str, sha256: str, reader_version: str, page_from: int, page_to: int, file_ext: str = "") -> Key:
    return (str(org_id).lower(), sha256, reader_version, int(page_from), int(page_to), file_ext)


def strip_nul(value: Any) -> Any:
    """``value`` without NUL characters in any string. The same object when it has none; a changed part is
    rebuilt, so the caller's output is never changed."""

    if isinstance(value, str):
        return value.replace("\x00", "") if "\x00" in value else value
    if isinstance(value, list):
        items = [strip_nul(item) for item in value]
        return value if all(a is b for a, b in zip(items, value)) else items
    if isinstance(value, dict):
        cleaned = {strip_nul(k): strip_nul(v) for k, v in value.items()}
        same = all(a is b and cleaned[a] is v for (a, v), b in zip(value.items(), cleaned))
        return value if same else cleaned
    return value


def too_large(key: Key, size: int) -> None:
    if key not in _logged_too_large:
        if len(_logged_too_large) < 10_000:
            _logged_too_large.add(key)
        logger.warning("parsed text not kept: over the size cap", extra={"sha256": key[1], "bytes": size})


def build_record(org_id: str, sha256: str, reader_version: str, page_from: int, page_to: int,
                 output: dict[str, Any], file_ext: str = "") -> dict[str, Any]:
    pages = output.get("pages") or []
    warnings = output.get("warnings") or []
    return {
        "org_id": str(org_id), "sha256": sha256, "reader_version": reader_version,
        "page_from": int(page_from), "page_to": int(page_to), "file_ext": file_ext,
        "reader_name": str(output.get("parser_name") or ""),
        "page_count": len(pages),
        "ocr_used": str(output.get("parser_name")) == "aws_textract" or any(
            isinstance(w, dict) and w.get("code") == "ocr_applied" for w in warnings),
        "status": str(output.get("status")),
        "parser_output": output,
    }


class InMemoryParsedTextRepository:
    def __init__(self) -> None:
        self._rows: dict[Key, dict[str, Any]] = {}
        self._lock = threading.Lock()

    def get(self, org_id: str, sha256: str, reader_version: str, page_from: int = 0, page_to: int = 0,
            file_ext: str = "") -> dict[str, Any] | None:
        with self._lock:
            row = self._rows.get(_key(org_id, sha256, reader_version, page_from, page_to, file_ext))
            return copy.deepcopy(usable(row))

    def put(self, org_id: str, sha256: str, reader_version: str, page_from: int, page_to: int,
            output: dict[str, Any], file_ext: str = "") -> None:
        record = build_record(org_id, sha256, reader_version, page_from, page_to,
                              copy.deepcopy(strip_nul(output)), file_ext)
        with self._lock:
            self._rows[_key(org_id, sha256, reader_version, page_from, page_to, file_ext)] = record


class JsonlParsedTextRepository:
    """An append-only file. The first ``get`` indexes it by key (key -> where the newest line is); later
    calls read only what was appended since, and a ``get`` reads one line, never the whole file."""

    def __init__(self, path: str | Path = DEFAULT_JSONL_PATH) -> None:
        self._path = Path(path)
        self._index: dict[Key, tuple[int, int]] = {}
        self._offset = 0
        self._lock = threading.Lock()

    @property
    def path(self) -> Path:
        return self._path

    def _refresh(self) -> None:
        """Index the complete lines appended since the last call. A damaged line is skipped, not fatal."""

        try:
            size = self._path.stat().st_size
        except OSError:
            self._index.clear()
            self._offset = 0
            return
        if size < self._offset:  # the file was replaced: start again
            self._index.clear()
            self._offset = 0
        with self._path.open("rb") as handle:
            handle.seek(self._offset)
            position = self._offset
            for line in handle:
                if not line.endswith(b"\n"):
                    break  # a line still being written
                start, position = position, position + len(line)
                try:
                    record = json.loads(line)
                    key = _key(record["org_id"], record["sha256"], record["reader_version"],
                               record["page_from"], record["page_to"], record.get("file_ext", ""))
                except (ValueError, KeyError, TypeError):
                    continue
                self._index[key] = (start, len(line))
            self._offset = position

    def get(self, org_id: str, sha256: str, reader_version: str, page_from: int = 0, page_to: int = 0,
            file_ext: str = "") -> dict[str, Any] | None:
        with self._lock:
            self._refresh()
            where = self._index.get(_key(org_id, sha256, reader_version, page_from, page_to, file_ext))
            if where is None:
                return None
            try:
                with self._path.open("rb") as handle:
                    handle.seek(where[0])
                    record = json.loads(handle.read(where[1]))
            except (OSError, ValueError):
                return None
        return usable(record)

    def put(self, org_id: str, sha256: str, reader_version: str, page_from: int, page_to: int,
            output: dict[str, Any], file_ext: str = "") -> None:
        record = build_record(org_id, sha256, reader_version, page_from, page_to, strip_nul(output), file_ext)
        line = json.dumps(record, ensure_ascii=False).encode("utf-8") + b"\n"
        key = _key(org_id, sha256, reader_version, page_from, page_to, file_ext)
        if len(line) > MAX_STORED_BYTES:
            too_large(key, len(line))
            return
        with self._lock:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._path.open("ab") as handle:
                handle.write(line)
            self._refresh()


_GET = text(
    "SELECT page_count, status, parser_output FROM s1_parsed_texts "
    "WHERE org_id = :org_id AND sha256 = :sha256 AND reader_version = :reader_version "
    "AND page_from = :page_from AND page_to = :page_to AND file_ext = :file_ext"
)
_PUT = text(
    "INSERT INTO s1_parsed_texts (id, org_id, sha256, reader_version, page_from, page_to, file_ext, "
    "reader_name, page_count, ocr_used, status, parser_output) "
    "VALUES (:id, :org_id, :sha256, :reader_version, :page_from, :page_to, :file_ext, :reader_name, "
    ":page_count, :ocr_used, :status, CAST(:parser_output AS jsonb)) "
    "ON CONFLICT (org_id, sha256, reader_version, page_from, page_to, file_ext) DO UPDATE SET "
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

    def get(self, org_id: str, sha256: str, reader_version: str, page_from: int = 0, page_to: int = 0,
            file_ext: str = "") -> dict[str, Any] | None:
        with tenant_transaction(self._scope(org_id), self._engine or get_sync_engine()) as connection:
            row = connection.execute(_GET, {
                "org_id": str(uuid.UUID(str(org_id))), "sha256": sha256, "reader_version": reader_version,
                "page_from": int(page_from), "page_to": int(page_to), "file_ext": file_ext}).first()
        if row is None:
            return None
        output = row.parser_output
        if isinstance(output, (str, bytes)):
            try:
                output = json.loads(output)
            except ValueError:
                return None
        return usable({"page_count": row.page_count, "parser_output": output})

    def put(self, org_id: str, sha256: str, reader_version: str, page_from: int, page_to: int,
            output: dict[str, Any], file_ext: str = "") -> None:
        record = build_record(org_id, sha256, reader_version, page_from, page_to, strip_nul(output), file_ext)
        payload = json.dumps(record["parser_output"], ensure_ascii=False).encode("utf-8")
        if len(payload) > MAX_STORED_BYTES:
            too_large(_key(org_id, sha256, reader_version, page_from, page_to, file_ext), len(payload))
            return
        with tenant_transaction(self._scope(org_id), self._engine or get_sync_engine()) as connection:
            connection.execute(_PUT, {
                "id": str(uuid.uuid4()), "org_id": str(uuid.UUID(str(org_id))), "sha256": sha256,
                "reader_version": reader_version, "page_from": record["page_from"], "page_to": record["page_to"],
                "file_ext": file_ext, "reader_name": record["reader_name"], "page_count": record["page_count"],
                "ocr_used": record["ocr_used"], "status": record["status"],
                "parser_output": payload.decode("utf-8")})
