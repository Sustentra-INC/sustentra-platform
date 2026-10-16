"""Copy the S1 JSONL stores and uploaded files into Postgres, and check that both agree.

``import_stores`` is a sync, run in provider scope while S1_STORE is still ``jsonl``:

- Every line of a store becomes one row, keyed by its line (``legacy_key = <store>:<line>``),
  in file order, so ``seq`` keeps the files' order. Documents keep one row per document
  (its latest version, in upload order).
- Run again, it adds the lines written since and updates rows whose line changed (the
  ownership claim, ``claim-s1-data``, rewrites lines in place): it is safe to repeat.
- Each evidence id gets the owner the JSONL checks see: its organization when every record
  of it has that one owner, otherwise none (provider scope only), so evidence that org users
  cannot see today stays hidden.
- Each document's uploaded file is copied, checked by size and sha256.

It refuses to run once S1_STORE is ``postgres+jsonl`` or ``postgres``: the app then writes
Postgres itself, and the files' new lines are already in it.

``verify_stores`` asks both stores every lookup the API makes (by document, evidence,
engagement, candidate, field, id) and compares the answers, plus every file's checksum and
every evidence owner. It changes nothing and can run in any mode.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine

from backend.app.core.config import get_settings
from backend.app.core.db import get_sync_engine, tenant_transaction
from backend.app.core.s1_scope import S1Scope, scoped
from backend.app.repositories import (
    document_repository,
    evidence_repository,
    extraction_result_repository,
    pipeline_repository,
    review_repository,
)
from backend.app.repositories.s1_postgres import COLUMNS

UPLOADS = "local-data/uploads"

# store name -> (JSONL file under the data root, table)
STORES: dict[str, tuple[str, str]] = {
    "documents": (document_repository.DEFAULT_JSONL_PATH, "s1_documents"),
    "pipeline_runs": (pipeline_repository.DEFAULT_JSONL_PATH, "s1_pipeline_runs"),
    "extraction_results": (extraction_result_repository.DEFAULT_JSONL_PATH, "s1_extraction_results"),
    "review_decisions": (review_repository.DEFAULT_JSONL_PATH, "s1_review_decisions"),
    "approved_evidence": (evidence_repository.DEFAULT_JSONL_PATH, "s1_approved_evidence"),
}


# What verify asks both stores: store -> (record key, lookup) for every value of the key.
LOOKUPS: dict[str, tuple[tuple[str, str], ...]] = {
    "documents": (("document_id", "get_by_id"), ("evidence_id", "list_by_evidence"),
                  ("evidence_id", "get_latest_by_evidence"), ("engagement_id", "list_by_engagement")),
    "pipeline_runs": (("pipeline_run_id", "get_by_id"), ("evidence_id", "list_by_evidence"),
                      ("evidence_id", "get_latest_by_evidence"), ("engagement_id", "list_by_engagement")),
    "extraction_results": (("document_id", "list_by_document"), ("evidence_id", "list_by_evidence")),
    "review_decisions": (("evidence_id", "list_by_evidence"), ("document_id", "list_by_document"),
                         ("candidate_id", "list_by_candidate"), ("candidate_id", "get_latest_by_candidate")),
    "approved_evidence": (("approved_evidence_id", "get_by_id"), ("engagement_id", "list_by_engagement"),
                          ("evidence_id", "list_by_evidence"), ("evidence_id", "get_latest_by_evidence"),
                          ("document_id", "list_by_document")),
}

# The stores whose records decide who owns an evidence id (api/s1_access.evidence_records).
OWNERSHIP_STORES = ("documents", "pipeline_runs", "review_decisions", "approved_evidence")


class ImportRefused(RuntimeError):
    """The import would overwrite data the app now writes to Postgres itself."""


@dataclass
class StoreCounts:
    lines: int = 0
    inserted: int = 0
    updated: int = 0
    unchanged: int = 0


@dataclass
class ImportReport:
    dry_run: bool
    stores: dict[str, StoreCounts] = field(default_factory=dict)
    files_copied: int = 0
    files_unchanged: int = 0
    files_missing: list[str] = field(default_factory=list)
    files_conflicting: list[str] = field(default_factory=list)
    evidence_owners: int = 0
    evidence_hidden: list[str] = field(default_factory=list)


@dataclass
class VerifyReport:
    checks: int = 0
    mismatches: list[str] = field(default_factory=list)
    files_missing_on_disk: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.mismatches


# --- reading the files ----------------------------------------------------------------

def _lines(path: Path) -> list[tuple[int, dict[str, Any]]]:
    """(line number, record) for each non-empty line, numbered from 1."""

    if not path.exists():
        return []
    return [
        (number, json.loads(line))
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1)
        if line.strip()
    ]


def _latest_documents(lines: Iterable[tuple[int, dict[str, Any]]]) -> list[dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for _number, record in lines:
        latest[str(record.get("document_id"))] = record  # first version fixes the order
    return list(latest.values())


def _owner(record: dict[str, Any]) -> str | None:
    owner = record.get("org_id")
    return None if owner in (None, "") else str(owner)


def _evidence_owners(records: Iterable[dict[str, Any]]) -> dict[str, str | None]:
    """Evidence id -> its organization when every record of it has that one owner, else None."""

    seen: dict[str, set[str | None]] = {}
    for record in records:
        evidence_id = record.get("evidence_id")
        if evidence_id not in (None, ""):
            seen.setdefault(str(evidence_id), set()).add(_owner(record))
    return {e: next(iter(owners)) if len(owners) == 1 else None for e, owners in seen.items()}


def _upload_path(root: Path, storage_uri: str) -> Path | None:
    """The file a storage URI names under ``<root>/local-data/uploads``, or None if it is unsafe."""

    uri = PurePosixPath(storage_uri)
    if not storage_uri or uri.is_absolute() or ".." in uri.parts or "\\" in storage_uri:
        return None
    prefix = PurePosixPath(UPLOADS).parts
    suffix = uri.parts[len(prefix):] if uri.parts[: len(prefix)] == prefix else uri.parts
    uploads = (root / UPLOADS).resolve()
    path = uploads.joinpath(*suffix).resolve()
    return path if path.is_relative_to(uploads) and path != uploads else None


# --- import -------------------------------------------------------------------------

def _column_value(value: Any) -> str | None:
    return value if value is None or isinstance(value, str) else json.dumps(value)


def _upsert(connection: Connection, table: str, record: dict[str, Any], legacy_key: str,
            conflict: str) -> str:
    """Insert, or update the row when its record differs: "inserted", "updated" or "unchanged"."""

    columns = COLUMNS[table]
    params: dict[str, Any] = {name: _column_value(record.get(name)) for name in columns}
    params.update(org_id=_owner(record), record=json.dumps(record, ensure_ascii=False), legacy_key=legacy_key)
    names = ("org_id", *columns, "record", "legacy_key")
    values = ", ".join("CAST(:record AS jsonb)" if n == "record" else f":{n}" for n in names)
    updates = ", ".join(f"{n} = EXCLUDED.{n}" for n in names if n != conflict)
    row = connection.execute(
        text(
            f"INSERT INTO {table} ({', '.join(names)}) VALUES ({values}) "
            f"ON CONFLICT ({conflict}) DO UPDATE SET {updates}, updated_at = now() "
            f"WHERE {table}.record IS DISTINCT FROM EXCLUDED.record OR {table}.org_id IS DISTINCT FROM EXCLUDED.org_id "
            "RETURNING (xmax = 0) AS inserted"
        ),
        params,
    ).first()
    if row is None:
        return "unchanged"
    return "inserted" if row.inserted else "updated"


def _copy_file(connection: Connection, root: Path, document: dict[str, Any], report: ImportReport) -> None:
    uri = str(document.get("storage_uri") or "")
    if not uri:
        return
    path = _upload_path(root, uri)
    if path is None or not path.is_file():
        report.files_missing.append(uri)
        return
    content = path.read_bytes()
    if not content:
        report.files_missing.append(uri)
        return
    digest = hashlib.sha256(content).hexdigest()
    existing = connection.execute(
        text("SELECT sha256 FROM s1_document_files WHERE storage_uri = :uri"), {"uri": uri}
    ).first()
    if existing is not None:
        if existing.sha256 == digest:
            report.files_unchanged += 1
        else:
            report.files_conflicting.append(uri)
        return
    connection.execute(
        text(
            "INSERT INTO s1_document_files "
            "(storage_uri, org_id, document_id, file_name, size_bytes, sha256, content, legacy_key) "
            "VALUES (:uri, :org_id, :document_id, :file_name, :size, :sha256, :content, :uri)"
        ),
        {"uri": uri, "org_id": _owner(document), "document_id": document.get("document_id"),
         "file_name": PurePosixPath(uri).name, "size": len(content), "sha256": digest, "content": content},
    )
    report.files_copied += 1


def import_stores(data_root: str | Path = ".", *, dry_run: bool = False, engine: Engine | None = None) -> ImportReport:
    store = get_settings().s1_store
    if store != "jsonl":
        raise ImportRefused(
            f"S1_STORE is {store}: the app writes Postgres itself now, so importing the files again "
            "would duplicate what it wrote. Import only while S1_STORE is jsonl."
        )
    root = Path(data_root)
    report = ImportReport(dry_run=dry_run)
    files = {name: _lines(root / relative) for name, (relative, _table) in STORES.items()}
    documents = _latest_documents(files["documents"])
    owners = _evidence_owners(record for name in OWNERSHIP_STORES for _n, record in files[name])

    with scoped(S1Scope.platform()):
        with tenant_transaction(S1Scope.platform(), engine or get_sync_engine()) as connection:
            for evidence_id, org_id in owners.items():
                connection.execute(
                    text("INSERT INTO s1_evidence_owners (evidence_id, org_id) VALUES (:e, :org) "
                         "ON CONFLICT (evidence_id) DO UPDATE SET org_id = EXCLUDED.org_id "
                         "WHERE s1_evidence_owners.org_id IS DISTINCT FROM EXCLUDED.org_id"),
                    {"e": evidence_id, "org": org_id},
                )
            report.evidence_owners = len(owners)
            report.evidence_hidden = sorted(e for e, org in owners.items() if org is None)

            for name, (_relative, table) in STORES.items():
                counts = report.stores[name] = StoreCounts(lines=len(files[name]))
                if name == "documents":
                    rows: list[tuple[str, dict[str, Any]]] = [
                        (f"documents:{d.get('document_id')}", d) for d in documents
                    ]
                    conflict = "document_id"
                else:
                    rows = [(f"{name}:{number}", record) for number, record in files[name]]
                    conflict = "legacy_key"
                for legacy_key, record in rows:
                    outcome = _upsert(connection, table, record, legacy_key, conflict)
                    setattr(counts, outcome, getattr(counts, outcome) + 1)

            for document in documents:
                _copy_file(connection, root, document, report)

            if dry_run:
                connection.rollback()
    return report


# --- verify -------------------------------------------------------------------------

def verify_stores(data_root: str | Path = ".", *, engine: Engine | None = None) -> VerifyReport:
    root = Path(data_root)
    report = VerifyReport()
    disk: dict[str, Any] = {
        "documents": document_repository.JsonlDocumentRepository(root / document_repository.DEFAULT_JSONL_PATH),
        "pipeline_runs": pipeline_repository.JsonlPipelineRunRepository(root / pipeline_repository.DEFAULT_JSONL_PATH),
        "extraction_results": extraction_result_repository.JsonlExtractionResultRepository(
            root / extraction_result_repository.DEFAULT_JSONL_PATH),
        "review_decisions": review_repository.JsonlReviewDecisionRepository(
            root / review_repository.DEFAULT_JSONL_PATH),
        "approved_evidence": evidence_repository.JsonlApprovedEvidenceRepository(
            root / evidence_repository.DEFAULT_JSONL_PATH),
    }
    db: dict[str, Any] = {
        "documents": document_repository.PostgresDocumentRepository(engine),
        "pipeline_runs": pipeline_repository.PostgresPipelineRunRepository(engine),
        "extraction_results": extraction_result_repository.PostgresExtractionResultRepository(engine),
        "review_decisions": review_repository.PostgresReviewDecisionRepository(engine),
        "approved_evidence": evidence_repository.PostgresApprovedEvidenceRepository(engine),
    }

    def check(store: str, method: str, *args: str) -> None:
        report.checks += 1
        on_disk, in_db = getattr(disk[store], method)(*args), getattr(db[store], method)(*args)
        if on_disk != in_db:
            report.mismatches.append(f"{store} {method}{args}: {_difference(on_disk, in_db)}")

    with scoped(S1Scope.platform()):
        records = {name: repo.list_all() for name, repo in disk.items()}
        for store, lookups in LOOKUPS.items():
            for key, method in lookups:
                for value in sorted({str(r[key]) for r in records[store] if r.get(key) not in (None, "")}):
                    check(store, method, value)
        for evidence_id, field_name in sorted({
            (str(r["evidence_id"]), str(r["field_name"]))
            for r in records["review_decisions"] if r.get("evidence_id") and r.get("field_name")
        }):
            check("review_decisions", "get_latest_by_field", evidence_id, field_name)

        with tenant_transaction(S1Scope.platform(), engine or get_sync_engine()) as connection:
            stored = {row.storage_uri: row.sha256 for row in connection.execute(
                text("SELECT storage_uri, sha256 FROM s1_document_files"))}
            owners = {row.evidence_id: (str(row.org_id) if row.org_id else None) for row in connection.execute(
                text("SELECT evidence_id, org_id FROM s1_evidence_owners"))}

        for document in _latest_documents((0, d) for d in records["documents"]):
            uri = str(document.get("storage_uri") or "")
            if not uri:
                continue
            report.checks += 1
            path = _upload_path(root, uri)
            if path is None or not path.is_file():
                report.files_missing_on_disk.append(uri)
                continue
            if stored.get(uri) != hashlib.sha256(path.read_bytes()).hexdigest():
                report.mismatches.append(f"file {uri}: {'not in the database' if uri not in stored else 'differs'}")

        for evidence_id, org_id in _evidence_owners(r for name in OWNERSHIP_STORES for r in records[name]).items():
            report.checks += 1
            if evidence_id not in owners:
                report.mismatches.append(f"evidence owner {evidence_id}: not in the database")
            elif owners[evidence_id] != org_id:
                report.mismatches.append(f"evidence owner {evidence_id}: files {org_id} != database {owners[evidence_id]}")
    return report


def _difference(on_disk: Any, in_db: Any) -> str:
    if isinstance(on_disk, list) and isinstance(in_db, list):
        if len(on_disk) != len(in_db):
            return f"{len(on_disk)} records in the files, {len(in_db)} in the database"
        return f"{len(on_disk)} records each, but not the same ones in the same order"
    if on_disk is None or in_db is None:
        return "missing in the " + ("files" if on_disk is None else "database")
    return "the record differs"
