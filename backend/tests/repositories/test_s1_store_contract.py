"""The S1 document stores behave the same in memory, in JSONL files and in Postgres.

Every contract test runs against all three. The Postgres runs need TEST_DATABASE_URL (owner,
for seeding) and TEST_APP_DATABASE_URL (app_user, which the stores use, so RLS applies);
without them only the Postgres runs are skipped.
"""

from __future__ import annotations

import json
import os
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

import pytest
from sqlalchemy import create_engine, text

from backend.app.core.db import to_sync_url
from backend.app.core.s1_scope import S1Scope, scoped
from backend.app.repositories.document_repository import (
    InMemoryDocumentRepository,
    JsonlDocumentRepository,
    PostgresDocumentRepository,
)
from backend.app.repositories.evidence_repository import (
    InMemoryApprovedEvidenceRepository,
    JsonlApprovedEvidenceRepository,
    PostgresApprovedEvidenceRepository,
)
from backend.app.repositories.extraction_result_repository import (
    InMemoryExtractionResultRepository,
    JsonlExtractionResultRepository,
    PostgresExtractionResultRepository,
)
from backend.app.repositories.pipeline_repository import (
    InMemoryPipelineRunRepository,
    JsonlPipelineRunRepository,
    PostgresPipelineRunRepository,
)
from backend.app.repositories.review_repository import (
    InMemoryReviewDecisionRepository,
    JsonlReviewDecisionRepository,
    PostgresReviewDecisionRepository,
)
from backend.app.repositories.s1_postgres import COLUMNS, EvidenceOwnedElsewhere, evidence_owner_status

ADMIN_URL = os.environ.get("TEST_DATABASE_URL")
APP_URL = os.environ.get("TEST_APP_DATABASE_URL")
ORG = uuid.UUID("cccccccc-0000-0000-0000-0000000000c3")
OTHER_ORG = uuid.UUID("dddddddd-0000-0000-0000-0000000000d4")


@dataclass
class Stores:
    documents: Any
    runs: Any
    results: Any
    reviews: Any
    approved: Any


@pytest.fixture(scope="module")
def pg_engines() -> Iterator[tuple[Any, Any]]:
    if not (ADMIN_URL and APP_URL):
        pytest.skip("TEST_DATABASE_URL / TEST_APP_DATABASE_URL not set")
    admin = create_engine(to_sync_url(ADMIN_URL), pool_size=1, max_overflow=0)
    app = create_engine(to_sync_url(APP_URL), pool_size=2, max_overflow=0)
    try:
        yield admin, app
    finally:
        admin.dispose()
        app.dispose()


def _reset(admin: Any) -> None:
    with admin.begin() as connection:
        connection.execute(text(f"TRUNCATE {', '.join(COLUMNS)}, s1_evidence_owners"))
        connection.execute(
            text("INSERT INTO organizations (id, name, slug) VALUES (:a, 'Repo A', 's1-repo-a'), "
                 "(:b, 'Repo B', 's1-repo-b') ON CONFLICT DO NOTHING"),
            {"a": ORG, "b": OTHER_ORG},
        )


def _postgres_stores(app: Any) -> Stores:
    return Stores(PostgresDocumentRepository(app), PostgresPipelineRunRepository(app),
                  PostgresExtractionResultRepository(app), PostgresReviewDecisionRepository(app),
                  PostgresApprovedEvidenceRepository(app))


@pytest.fixture(params=["memory", "jsonl", "postgres"])
def stores(request: pytest.FixtureRequest, tmp_path: Any) -> Iterator[Stores]:
    if request.param == "memory":
        yield Stores(InMemoryDocumentRepository(), InMemoryPipelineRunRepository(),
                     InMemoryExtractionResultRepository(), InMemoryReviewDecisionRepository(),
                     InMemoryApprovedEvidenceRepository())
    elif request.param == "jsonl":
        yield Stores(JsonlDocumentRepository(tmp_path / "d.jsonl"), JsonlPipelineRunRepository(tmp_path / "p.jsonl"),
                     JsonlExtractionResultRepository(tmp_path / "e.jsonl"),
                     JsonlReviewDecisionRepository(tmp_path / "r.jsonl"),
                     JsonlApprovedEvidenceRepository(tmp_path / "a.jsonl"))
    else:
        admin, app = request.getfixturevalue("pg_engines")
        _reset(admin)
        with scoped(S1Scope.tenant(ORG)):
            yield _postgres_stores(app)


def _own(**fields: Any) -> dict[str, Any]:
    return {"org_id": str(ORG), **fields}


def _ids(records: list[dict[str, Any]], key: str) -> list[Any]:
    return [r[key] for r in records]


# --- contract: every store -----------------------------------------------------------

def test_a_document_keeps_one_version_in_upload_order(stores: Stores) -> None:
    docs = stores.documents
    docs.save(_own(document_id="D1", engagement_id="ENG", evidence_id="EV1", processing_status="uploaded"))
    docs.save(_own(document_id="D2", engagement_id="ENG", evidence_id="EV1", processing_status="uploaded"))
    docs.save(_own(document_id="D3", engagement_id="ENG-2", evidence_id="EV2", processing_status="uploaded"))
    docs.update_processing_status("D1", "processed")

    assert docs.get_by_id("D1")["processing_status"] == "processed"
    assert [(d["document_id"], d["processing_status"]) for d in docs.list_by_evidence("EV1")] == [
        ("D1", "processed"), ("D2", "uploaded")]
    assert _ids(docs.list_by_engagement("ENG"), "document_id") == ["D1", "D2"]
    assert docs.get_latest_by_evidence("EV1")["document_id"] == "D2"
    assert docs.get_by_id("missing") is None
    assert docs.get_latest_by_evidence("missing") is None
    with pytest.raises(KeyError):
        docs.update_processing_status("missing", "processed")


def test_pipeline_runs_are_listed_oldest_first_and_the_latest_save_wins(stores: Stores) -> None:
    runs = stores.runs
    runs.save(_own(pipeline_run_id="R1", engagement_id="ENG", evidence_id="EV1", document_id="D1", status="running"))
    runs.save(_own(pipeline_run_id="R2", engagement_id="ENG", evidence_id="EV1", document_id="D2", status="done"))
    runs.save(_own(pipeline_run_id="R3", engagement_id="ENG-2", evidence_id="EV2", document_id="D3", status="done"))
    runs.save(_own(pipeline_run_id="R1", engagement_id="ENG", evidence_id="EV1", document_id="D1", status="done"))

    assert runs.get_by_id("R1")["status"] == "done"
    assert _ids(runs.list_by_evidence("EV1"), "pipeline_run_id") == ["R1", "R2", "R1"]
    assert _ids(runs.list_by_engagement("ENG-2"), "pipeline_run_id") == ["R3"]
    assert runs.get_latest_by_evidence("EV1")["status"] == "done"
    assert runs.get_by_id("missing") is None


def test_extraction_results_by_document_and_evidence(stores: Stores) -> None:
    results = stores.results
    results.save(_own(pipeline_run_id="R1", document_id="D1", evidence_id="EV1", items=[{"n": 1}]))
    results.save(_own(pipeline_run_id="R2", document_id="D2", evidence_id="EV1", items=[]))
    results.save(_own(pipeline_run_id="R3", document_id="D1", evidence_id="EV1", items=[{"n": 2}]))

    assert _ids(results.list_by_document("D1"), "pipeline_run_id") == ["R1", "R3"]
    assert _ids(results.list_by_evidence("EV1"), "pipeline_run_id") == ["R1", "R2", "R3"]
    assert results.list_by_document("missing") == []


def test_review_decisions_latest_by_field_and_candidate(stores: Stores) -> None:
    reviews = stores.reviews
    reviews.save(_own(review_decision_id="V1", candidate_id="C1", evidence_id="EV1", document_id="D1",
                      field_name="quantity", decision="accepted"))
    reviews.save(_own(review_decision_id="V2", candidate_id="C2", evidence_id="EV1", document_id="D1",
                      field_name="unit", decision="accepted"))
    reviews.save(_own(review_decision_id="V3", candidate_id="C1", evidence_id="EV1", document_id="D1",
                      field_name="quantity", decision="overridden"))

    assert reviews.get_latest_by_field("EV1", "quantity")["review_decision_id"] == "V3"
    assert reviews.get_latest_by_candidate("C1")["decision"] == "overridden"
    assert _ids(reviews.list_by_candidate("C1"), "review_decision_id") == ["V1", "V3"]
    assert _ids(reviews.list_by_document("D1"), "review_decision_id") == ["V1", "V2", "V3"]
    assert _ids(reviews.list_by_evidence("EV1"), "review_decision_id") == ["V1", "V2", "V3"]
    assert reviews.get_latest_by_field("EV1", "missing") is None


def test_approved_evidence_by_engagement_evidence_and_document(stores: Stores) -> None:
    approved = stores.approved
    approved.save(_own(approved_evidence_id="A1", engagement_id="ENG", evidence_id="EV1", document_id="D1", v=1))
    approved.save(_own(approved_evidence_id="A2", engagement_id="ENG", evidence_id="EV2", document_id="D2", v=1))
    approved.save(_own(approved_evidence_id="A1", engagement_id="ENG", evidence_id="EV1", document_id="D1", v=2))

    assert approved.get_by_id("A1")["v"] == 2
    assert approved.get_latest_by_evidence("EV1")["v"] == 2
    assert _ids(approved.list_by_engagement("ENG"), "approved_evidence_id") == ["A1", "A2", "A1"]
    assert _ids(approved.list_by_document("D2"), "approved_evidence_id") == ["A2"]
    assert approved.get_by_id("missing") is None


def test_a_record_comes_back_exactly_as_saved(stores: Stores) -> None:
    record = _own(
        pipeline_run_id="R1", evidence_id="EV1", document_id=None,
        values={"quantity": 41200.5, "unit": "kWh", "site": "Brauerei Zürich – Halle 2"},
        flags=[True, False, None], nested={"a": [{"b": 0.1}, {"c": -3}]}, empty={},
    )
    stores.runs.save(record)
    assert stores.runs.get_by_id("R1") == record
    assert stores.runs.list_by_evidence("EV1") == [record]


# --- Postgres only --------------------------------------------------------------------

def _admin_insert_document(admin: Any, org: uuid.UUID | None, document_id: str, evidence_id: str) -> None:
    """A row written straight to the table, past the store (and its evidence claim)."""

    record = {"document_id": document_id, "evidence_id": evidence_id, "org_id": str(org) if org else None}
    with admin.begin() as connection:
        connection.execute(text(
            "INSERT INTO s1_documents (org_id, document_id, evidence_id, record) "
            "VALUES (:org, :document_id, :evidence_id, CAST(:record AS jsonb))"),
            {"org": org, "document_id": document_id, "evidence_id": evidence_id, "record": json.dumps(record)})


def test_postgres_stores_see_only_the_bound_organization(pg_engines: tuple[Any, Any]) -> None:
    admin, app = pg_engines
    _reset(admin)
    pg = _postgres_stores(app)
    with scoped(S1Scope.tenant(ORG)):
        pg.documents.save({"org_id": str(ORG), "document_id": "D-own", "evidence_id": "EV-SHARED"})
    _admin_insert_document(admin, OTHER_ORG, "D-other", "EV-SHARED")
    _admin_insert_document(admin, None, "D-legacy", "EV-SHARED")  # from before uploads had an owner

    with scoped(S1Scope.tenant(ORG)):
        assert _ids(pg.documents.list_by_evidence("EV-SHARED"), "document_id") == ["D-own"]
        assert pg.documents.get_by_id("D-other") is None
    with scoped(S1Scope.tenant(OTHER_ORG)):
        assert _ids(pg.documents.list_by_evidence("EV-SHARED"), "document_id") == ["D-other"]
    with scoped(S1Scope.platform()):
        assert _ids(pg.documents.list_by_evidence("EV-SHARED"), "document_id") == ["D-own", "D-other", "D-legacy"]


def test_the_first_organization_to_save_an_evidence_id_owns_it(pg_engines: tuple[Any, Any]) -> None:
    admin, app = pg_engines
    _reset(admin)
    pg = _postgres_stores(app)
    with scoped(S1Scope.tenant(ORG)):
        pg.documents.save({"org_id": str(ORG), "document_id": "D1", "evidence_id": "EV-1"})
        pg.runs.save({"org_id": str(ORG), "pipeline_run_id": "R1", "evidence_id": "EV-1"})
    with scoped(S1Scope.tenant(OTHER_ORG)), pytest.raises(EvidenceOwnedElsewhere):
        pg.reviews.save({"org_id": str(OTHER_ORG), "review_decision_id": "V1", "evidence_id": "EV-1"})

    with admin.begin() as connection:
        assert connection.execute(text("SELECT count(*) FROM s1_review_decisions")).scalar() == 0
        owners = connection.execute(text("SELECT evidence_id, org_id FROM s1_evidence_owners")).all()
    assert [(e, str(o)) for e, o in owners] == [("EV-1", str(ORG))]


def test_evidence_owner_status_tells_free_own_and_taken_apart(pg_engines: tuple[Any, Any]) -> None:
    admin, app = pg_engines
    _reset(admin)
    with scoped(S1Scope.tenant(ORG)):
        assert evidence_owner_status("EV-1", app) == "free"
        PostgresDocumentRepository(app).save({"org_id": str(ORG), "document_id": "D1", "evidence_id": "EV-1"})
        assert evidence_owner_status("EV-1", app) == "own"
    with scoped(S1Scope.tenant(OTHER_ORG)):
        assert evidence_owner_status("EV-1", app) == "taken"
        assert evidence_owner_status("EV-2", app) == "free"
    with scoped(S1Scope.platform()):
        assert evidence_owner_status("EV-1", app) == "taken"
        assert evidence_owner_status("EV-2", app) == "free"
    with admin.begin() as connection:  # asking claimed nothing
        assert connection.execute(text("SELECT count(*) FROM s1_evidence_owners")).scalar() == 1


def test_unowned_legacy_evidence_is_taken_for_every_organization(pg_engines: tuple[Any, Any]) -> None:
    admin, app = pg_engines
    _reset(admin)
    with scoped(S1Scope.platform()):  # the import of records made before uploads had an owner
        PostgresPipelineRunRepository(app).save({"org_id": None, "pipeline_run_id": "R0", "evidence_id": "EV-OLD"})
        PostgresDocumentRepository(app).save({"org_id": None, "document_id": "D0"})  # no evidence id: no claim
    with scoped(S1Scope.tenant(ORG)):
        assert evidence_owner_status("EV-OLD", app) == "taken"
        with pytest.raises(EvidenceOwnedElsewhere):
            PostgresDocumentRepository(app).save({"org_id": str(ORG), "document_id": "D1", "evidence_id": "EV-OLD"})
    with admin.begin() as connection:
        assert connection.execute(text("SELECT count(*) FROM s1_evidence_owners")).scalar() == 1


def test_postgres_stores_refuse_to_work_with_no_organization_bound(pg_engines: tuple[Any, Any]) -> None:
    from backend.app.core.s1_scope import MissingS1Scope

    _admin, app = pg_engines
    with pytest.raises(MissingS1Scope):
        PostgresDocumentRepository(app).get_by_id("D1")
    with pytest.raises(MissingS1Scope):
        PostgresPipelineRunRepository(app).save({"pipeline_run_id": "R1"})


def test_postgres_stores_refuse_a_record_owned_by_another_organization(pg_engines: tuple[Any, Any]) -> None:
    from sqlalchemy.exc import DBAPIError

    admin, app = pg_engines
    _reset(admin)
    with scoped(S1Scope.tenant(ORG)), pytest.raises(DBAPIError):
        PostgresReviewDecisionRepository(app).save({"org_id": str(OTHER_ORG), "review_decision_id": "V1"})


def test_the_filter_columns_match_migration_0013() -> None:
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parents[2] / "migrations" / "versions" / "0013_s1_document_stores.py"
    spec = importlib.util.spec_from_file_location("migration_0013", path)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    assert {table: columns for table, (columns, _indexes) in migration.TABLES.items()} == COLUMNS
