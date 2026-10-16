"""The one-time move of the S1 JSONL stores into Postgres: import, re-import, verify.

Needs TEST_DATABASE_URL (owner, for seeding and tampering) and TEST_APP_DATABASE_URL
(app_user, which the import uses, so RLS applies); skipped without them.
"""

from __future__ import annotations

import json
import os
import uuid
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import create_engine, text

from backend.app.core.db import to_sync_url
from backend.app.core.s1_scope import S1Scope, scoped
from backend.app.repositories.document_repository import PostgresDocumentRepository
from backend.app.repositories.s1_postgres import COLUMNS, evidence_owner_status
from backend.app.services import s1_store_import
from backend.app.services.s1_store_import import STORES, ImportRefused, import_stores, verify_stores

ADMIN_URL = os.environ.get("TEST_DATABASE_URL")
APP_URL = os.environ.get("TEST_APP_DATABASE_URL")
A = str(uuid.UUID("cccccccc-0000-0000-0000-0000000000c3"))
B = str(uuid.UUID("dddddddd-0000-0000-0000-0000000000d4"))
BILL_URI = f"local-data/uploads/{A}/ENG/EV1/D1/bill.pdf"
BILL = b"%PDF-1.4 March gas bill"


@pytest.fixture(scope="module")
def engines() -> Iterator[tuple[Any, Any]]:
    if not (ADMIN_URL and APP_URL):
        pytest.skip("TEST_DATABASE_URL / TEST_APP_DATABASE_URL not set")
    admin = create_engine(to_sync_url(ADMIN_URL), pool_size=1, max_overflow=0)
    app = create_engine(to_sync_url(APP_URL), pool_size=2, max_overflow=0)
    try:
        yield admin, app
    finally:
        admin.dispose()
        app.dispose()


@pytest.fixture
def admin(engines: tuple[Any, Any], monkeypatch: pytest.MonkeyPatch) -> Any:
    db_admin, _app = engines
    with db_admin.begin() as connection:
        connection.execute(text(f"TRUNCATE {', '.join(COLUMNS)}, s1_document_files, s1_evidence_owners"))
        connection.execute(
            text("INSERT INTO organizations (id, name, slug) VALUES (:a, 'Import A', 's1-import-a'), "
                 "(:b, 'Import B', 's1-import-b') ON CONFLICT DO NOTHING"),
            {"a": A, "b": B},
        )
    monkeypatch.setattr(s1_store_import, "get_settings", lambda: SimpleNamespace(s1_store="jsonl"))
    return db_admin


@pytest.fixture
def app_engine(engines: tuple[Any, Any]) -> Any:
    return engines[1]


def _write(root: Path, store: str, records: list[dict[str, Any]]) -> None:
    path = root / STORES[store][0]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")


def _append(root: Path, store: str, record: dict[str, Any]) -> None:
    with (root / STORES[store][0]).open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record) + "\n")


@pytest.fixture
def data_root(tmp_path: Path) -> Path:
    _write(tmp_path, "documents", [
        {"document_id": "D1", "org_id": A, "engagement_id": "ENG", "evidence_id": "EV1",
         "processing_status": "queued", "storage_uri": BILL_URI},
        {"document_id": "D2", "org_id": None, "engagement_id": "ENG-S1-2025", "evidence_id": "EV-OLD",
         "processing_status": "completed", "storage_uri": "local-data/uploads/ENG-S1-2025/EV-OLD/D2/gone.pdf"},
        {"document_id": "D1", "org_id": A, "engagement_id": "ENG", "evidence_id": "EV1",
         "processing_status": "completed", "storage_uri": BILL_URI},
        {"document_id": "D3", "org_id": A, "engagement_id": "ENG", "evidence_id": "EV-MIX",
         "processing_status": "completed"},
    ])
    _write(tmp_path, "pipeline_runs", [
        {"pipeline_run_id": "R1", "org_id": A, "engagement_id": "ENG", "evidence_id": "EV1", "document_id": "D1",
         "status": "running"},
        {"pipeline_run_id": "R1", "org_id": A, "engagement_id": "ENG", "evidence_id": "EV1", "document_id": "D1",
         "status": "completed"},
        {"pipeline_run_id": "R2", "org_id": None, "engagement_id": "ENG-S1-2025", "evidence_id": "EV-OLD",
         "document_id": "D2", "status": "completed"},
        {"pipeline_run_id": "R3", "org_id": B, "engagement_id": "ENG-B", "evidence_id": "EV-MIX",
         "document_id": "D3", "status": "completed"},
    ])
    _write(tmp_path, "extraction_results", [
        {"pipeline_run_id": "R1", "org_id": A, "document_id": "D1", "evidence_id": "EV1",
         "items": [{"field_name": "quantity", "normalized_value": 1284.5, "unit": "therm"}]},
    ])
    _write(tmp_path, "review_decisions", [
        {"review_decision_id": "V1", "org_id": A, "candidate_id": "C1", "evidence_id": "EV1", "document_id": "D1",
         "field_name": "quantity", "decision": "accepted"},
        {"review_decision_id": "V2", "org_id": A, "candidate_id": "C1", "evidence_id": "EV1", "document_id": "D1",
         "field_name": "quantity", "decision": "overridden"},
    ])
    _write(tmp_path, "approved_evidence", [
        {"approved_evidence_id": "AE1", "org_id": A, "engagement_id": "ENG", "evidence_id": "EV1",
         "document_id": "D1", "fields": {"quantity": 1284.5}},
    ])
    bill = tmp_path / BILL_URI
    bill.parent.mkdir(parents=True)
    bill.write_bytes(BILL)
    return tmp_path


def _count(admin: Any, table: str) -> int:
    with admin.begin() as connection:
        return int(connection.execute(text(f"SELECT count(*) FROM {table}")).scalar() or 0)


def test_the_files_are_imported_and_verify_finds_them_identical(
    admin: Any, app_engine: Any, data_root: Path
) -> None:
    report = import_stores(data_root, engine=app_engine)

    documents = report.stores["documents"]
    assert (documents.lines, documents.inserted) == (4, 3)  # one row per document
    assert {name: c.inserted for name, c in report.stores.items() if name != "documents"} == {
        "pipeline_runs": 4, "extraction_results": 1, "review_decisions": 2, "approved_evidence": 1}
    assert (report.files_copied, report.files_missing) == (1, ["local-data/uploads/ENG-S1-2025/EV-OLD/D2/gone.pdf"])
    assert report.evidence_hidden == ["EV-MIX", "EV-OLD"]  # two owners / no owner: provider scope only, as today

    verified = verify_stores(data_root, engine=app_engine)
    assert verified.mismatches == []
    assert verified.checks > 30
    assert verified.files_missing_on_disk == ["local-data/uploads/ENG-S1-2025/EV-OLD/D2/gone.pdf"]

    with scoped(S1Scope.tenant(A)):
        documents_repo = PostgresDocumentRepository(app_engine)
        assert documents_repo.get_by_id("D1")["processing_status"] == "completed"
        assert documents_repo.get_by_id("D2") is None  # unowned: provider scope only
        assert evidence_owner_status("EV1", app_engine) == "own"
        assert evidence_owner_status("EV-MIX", app_engine) == "taken"
    with admin.begin() as connection:
        assert bytes(connection.execute(text("SELECT content FROM s1_document_files")).scalar()) == BILL


def test_importing_again_changes_nothing(admin: Any, app_engine: Any, data_root: Path) -> None:
    import_stores(data_root, engine=app_engine)
    again = import_stores(data_root, engine=app_engine)
    assert all(c.inserted == c.updated == 0 for c in again.stores.values())
    assert (again.files_copied, again.files_unchanged) == (0, 1)
    assert _count(admin, "s1_pipeline_runs") == 4


def test_a_later_import_catches_up_new_lines_and_claimed_records(
    admin: Any, app_engine: Any, data_root: Path
) -> None:
    import_stores(data_root, engine=app_engine)
    _append(data_root, "pipeline_runs", {"pipeline_run_id": "R4", "org_id": A, "engagement_id": "ENG",
                                         "evidence_id": "EV1", "document_id": "D1", "status": "completed"})
    # claim-s1-data rewrites lines in place: the legacy run and document now belong to A.
    for store in ("pipeline_runs", "documents"):
        path = data_root / STORES[store][0]
        lines = [json.loads(line) for line in path.read_text().splitlines()]
        for record in lines:
            if record.get("evidence_id") == "EV-OLD":
                record["org_id"] = A
        _write(data_root, store, lines)

    report = import_stores(data_root, engine=app_engine)
    assert (report.stores["pipeline_runs"].inserted, report.stores["pipeline_runs"].updated) == (1, 1)
    assert report.stores["documents"].updated == 1
    assert report.evidence_hidden == ["EV-MIX"]
    assert verify_stores(data_root, engine=app_engine).mismatches == []
    with scoped(S1Scope.tenant(A)):
        assert evidence_owner_status("EV-OLD", app_engine) == "own"


def test_a_dry_run_writes_nothing(admin: Any, app_engine: Any, data_root: Path) -> None:
    report = import_stores(data_root, dry_run=True, engine=app_engine)
    assert report.stores["review_decisions"].inserted == 2 and report.files_copied == 1
    for table in (*COLUMNS, "s1_document_files", "s1_evidence_owners"):
        assert _count(admin, table) == 0


@pytest.mark.parametrize("store", ["postgres+jsonl", "postgres"])
def test_the_import_is_refused_once_the_app_writes_postgres(
    monkeypatch: pytest.MonkeyPatch, data_root: Path, store: str
) -> None:
    monkeypatch.setattr(s1_store_import, "get_settings", lambda: SimpleNamespace(s1_store=store))
    with pytest.raises(ImportRefused):
        import_stores(data_root)


def test_verify_reports_what_differs(admin: Any, app_engine: Any, data_root: Path) -> None:
    import_stores(data_root, engine=app_engine)
    with admin.begin() as connection:
        connection.execute(text(
            "UPDATE s1_review_decisions SET record = record || '{\"decision\": \"accepted\"}'::jsonb "
            "WHERE review_decision_id = 'V2'"))
        connection.execute(text("TRUNCATE s1_document_files"))
        connection.execute(text("UPDATE s1_evidence_owners SET org_id = :b WHERE evidence_id = 'EV1'"), {"b": B})

    mismatches = verify_stores(data_root, engine=app_engine).mismatches
    assert any(m.startswith("review_decisions get_latest_by_field('EV1', 'quantity')") for m in mismatches)
    assert f"file {BILL_URI}: not in the database" in mismatches
    assert any(m.startswith("evidence owner EV1:") for m in mismatches)
