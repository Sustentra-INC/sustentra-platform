"""A large engagement for the Evidence page's scale checks (MVP-160), seeded straight into Postgres and
read back through the real app, counting the SQL statements each request runs.

``seed(admin_url, documents)`` writes one engagement: the documents are of mixed types (stationary fuel,
purchased electricity, refrigerant service, mobile fuel), about 20 records each, spread over 3 facilities
and 4 categories, plus 30 summary documents (Evidence Block 1) and 10 documents no facility claims
(unassigned). Most values are accepted; a few have a reviewer's decision on the document.

Run it as a benchmark (needs a migrated, disposable test database)::

    TEST_DATABASE_URL=... TEST_APP_DATABASE_URL=... python -m backend.tests.db._evidence_scale --documents 500

It prints, for each read, the server time and the number of SQL statements. The tests in
``test_evidence_scale_db.py`` use the same seed to assert that the statement count does not grow with the
number of documents.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import time
import uuid
from collections.abc import AsyncIterator, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import AsyncSession

ORG = uuid.UUID("aaaaaaaa-0000-0000-0000-000000160001")
OTHER_ORG = uuid.UUID("bbbbbbbb-0000-0000-0000-000000160002")
USER = uuid.UUID("aaaaaaaa-2222-0000-0000-000000160001")
OTHER_USER = uuid.UUID("bbbbbbbb-2222-0000-0000-000000160002")
TOKEN = "scale-member-token"
OTHER_TOKEN = "scale-other-member-token"
ORIGIN = "https://app.sustentra.test"
FACILITIES = [
    {"facilityId": "fac-kc01", "name": "Kansas City Plant", "address": "100 Main Street, Kansas City, MO 64105"},
    {"facilityId": "fac-stl2", "name": "St Louis Plant", "address": "200 Oak Avenue, St Louis, MO 63101"},
    {"facilityId": "fac-den3", "name": "Denver Plant", "address": "300 Pine Road, Denver, CO 80202"},
]
VEHICLE_GROUPS = [{"group_id": "vg-trucks", "fuel": "Diesel Fuel", "vehicle_type": "Medium- and Heavy-Duty Vehicles",
                   "factor_fuel_type": "Diesel", "on_road": True, "label": "Delivery trucks"}]
GAS_LINE = "s1:stationary:natural-gas:fac-kc01"
RECORDS_PER_DOCUMENT = 20
SUMMARY_DOCUMENTS = 30
UNASSIGNED_DOCUMENTS = 10
REVIEWER = "ana@example.com"


def _day(index: int) -> tuple[str, str]:
    """A one-day service period, a different day for every record of a facility's source: the engine compares
    every pair of records of one facility and source for overlapping periods, so records that all cover the
    same months would measure that comparison (and flood the page with findings), not the page."""

    day = (datetime(2023, 1, 1) + timedelta(days=index % 1000)).date().isoformat()
    return day, day


def _records(kind: str, number: int, facility: str, offset: int) -> list[dict[str, tuple[Any, str | None]]]:
    out: list[dict[str, tuple[Any, str | None]]] = []
    for i in range(RECORDS_PER_DOCUMENT):
        start, end = _day(offset + i)
        if kind == "CT-S1-FUELQTY":
            out.append({"fuel_type": ("natural_gas", None), "activity_quantity": (100 + number + i, "MMBtu"),
                        "activity_unit": ("MMBtu", None), "service_period_start": (start, None),
                        "service_period_end": (end, None), "facility_name": (facility, None)})
        elif kind == "CT-S2-ELEC":
            out.append({"activity_quantity": (50 + number + i, "MWh"), "activity_unit": ("MWh", None),
                        "energy_type": ("electricity", None), "service_period_start": (start, None),
                        "service_period_end": (end, None), "facility_name": (facility, None)})
        elif kind == "CT-S1-REFRSVC":
            out.append({"refrigerant_type": ("R-410A", None), "service_date": (start, None),
                        "equipment_id": (f"RTU-{i}", None), "service_type": ("service", None),
                        "refrigerant_added": (2.5 + i / 10, "lb"), "facility_name": (facility, None)})
        else:  # CT-S1-MOBFUEL
            out.append({"fuel_type": ("diesel", None), "activity_quantity": (40 + i, "gal"),
                        "activity_unit": ("gal", None), "transaction_date": (start, None),
                        "facility_name": (facility, None)})
    return out


def _plan(documents: int) -> list[tuple[str, str, int, int]]:
    """(canonical type, facility name, record count, first day) of every document."""

    summaries = min(SUMMARY_DOCUMENTS, documents)
    unassigned = min(UNASSIGNED_DOCUMENTS, max(documents - summaries, 0))
    sourced = max(documents - summaries - unassigned, 0)
    kinds = ["CT-S1-FUELQTY", "CT-S2-ELEC", "CT-S1-FUELQTY", "CT-S1-REFRSVC", "CT-S1-MOBFUEL", "CT-S2-ELEC"]
    plan = [("CT-GHG-FACSRCLIST", FACILITIES[i % 3]["name"], 3, 0) for i in range(summaries)]
    plan += [("CT-S1-FUELQTY", "Unknown Site", RECORDS_PER_DOCUMENT, i * RECORDS_PER_DOCUMENT)
             for i in range(unassigned)]
    seen: dict[tuple[str, str], int] = {}
    for i in range(sourced):
        kind, facility = kinds[i % len(kinds)], str(FACILITIES[i % 3]["name"])
        turn = seen[(kind, facility)] = seen.get((kind, facility), -1) + 1
        plan.append((kind, facility, RECORDS_PER_DOCUMENT, turn * RECORDS_PER_DOCUMENT))
    return plan


def _document_rows(engagement_id: str, org_id: uuid.UUID, documents: int, prefix: str
                   ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    docs, results, reviews = [], [], []
    now = datetime.now(UTC).isoformat()
    for number, (kind, facility, count, offset) in enumerate(_plan(documents)):
        document_id = f"{prefix}-{number:04d}"
        evidence_id = f"EV-{document_id}"
        docs.append({
            "document_id": document_id, "engagement_id": engagement_id, "evidence_id": evidence_id,
            "file_name": f"{document_id}.pdf", "mime_type": "application/pdf", "storage_uri": f"mem://{document_id}",
            "document_role": "source_evidence", "document_type": None, "uploaded_by": REVIEWER, "uploaded_at": now,
            "processing_status": "processed", "org_id": str(org_id)})
        records = _records(kind, number, facility, offset)[:count] if kind != "CT-GHG-FACSRCLIST" else [
            {"facility_name": (facility, None)} for _ in range(count)]
        items: list[dict[str, Any]] = []
        for index, record in enumerate(records, start=1):
            for field_name, (value, unit) in record.items():
                # as the extractors write them: a multi-record document's items carry the record's key
                key = f"r{index}:{facility}:{record.get('service_period_start', record.get('service_date', ('', 0)))[0]}"
                items.append({"candidate_id": f"{document_id}:{index}:{field_name}", "field_name": field_name,
                              "normalized_value": value, "unit": unit, "record_index": index,
                              "source_reference": {"document_id": document_id, "page_number": 1 + index // 10,
                                                   "record_key": key}})
        results.append({"pipeline_run_id": f"run-{document_id}", "document_id": document_id,
                        "evidence_id": evidence_id, "canonical_type_id": kind, "status": "completed",
                        "candidate_count": len(items), "items": items, "org_id": str(org_id), "created_at": now})
        for position, item in enumerate(items):
            if position % 10 == 9:  # one value in ten is still waiting for a reviewer
                continue
            snapshot = {k: v for k, v in item.items() if k != "record_index"}
            reviews.append({
                "review_decision_id": f"rd-{item['candidate_id']}", "candidate_id": item["candidate_id"],
                "evidence_id": evidence_id, "document_id": document_id, "field_name": item["field_name"],
                "decision": "accepted", "reviewed_value": item["normalized_value"], "reviewed_unit": item["unit"],
                "reviewer_id": REVIEWER, "reviewed_at": now, "candidate_snapshot": snapshot,
                "source_reference": item["source_reference"], "org_id": str(org_id)})
    return docs, results, reviews


def _insert(connection: Any, table: str, columns: tuple[str, ...], rows: list[dict[str, Any]]) -> None:
    names = ("org_id", *columns, "record")
    statement = text(
        f"INSERT INTO {table} ({', '.join(names)}) VALUES "
        f"({', '.join('CAST(:record AS jsonb)' if n == 'record' else f':{n}' for n in names)})")
    for start in range(0, len(rows), 2000):
        connection.execute(statement, [
            {"org_id": r.get("org_id"), **{c: r.get(c) for c in columns}, "record": json.dumps(r)}
            for r in rows[start:start + 2000]])


def seed(admin_url: str, documents: int, *, clean: bool = True) -> str:
    """One engagement of ``documents`` documents for ``ORG`` (and a user and session for it, and for
    ``OTHER_ORG``), as the owner role. Returns the engagement id."""

    from backend.app.core.db import to_sync_url
    from backend.app.core.security_primitives import hash_token

    engine = create_engine(to_sync_url(admin_url))
    now = datetime.now(UTC)
    engagement_id = str(uuid.uuid4())
    with engine.begin() as c:
        if clean:
            c.execute(text("TRUNCATE sessions, auth_tokens, users, organizations CASCADE"))
            c.execute(text("TRUNCATE s1_documents, s1_pipeline_runs, s1_extraction_results, s1_review_decisions, "
                           "s1_evidence_owners, s1_document_files, s1_processing_runs"))
        for org, slug in ((ORG, "scale-a"), (OTHER_ORG, "scale-b")):
            c.execute(text("INSERT INTO organizations (id, name, slug) VALUES (:id, :name, :slug)"),
                      {"id": org, "name": slug, "slug": slug})
        for user, org, email, token in ((USER, ORG, "member@scale-a.test", TOKEN),
                                        (OTHER_USER, OTHER_ORG, "member@scale-b.test", OTHER_TOKEN)):
            c.execute(text("INSERT INTO users (id, org_id, email, role) VALUES (:id, :org, :email, 'org_member')"),
                      {"id": user, "org": org, "email": email})
            c.execute(text("INSERT INTO sessions (user_id, org_id, token_hash, created_at, expires_at, last_seen_at) "
                           "VALUES (:u, :o, :t, :now, :exp, :now)"),
                      {"u": user, "o": org, "t": hash_token(token), "now": now, "exp": now + timedelta(days=1)})
        settings = {"facilities": FACILITIES, "recalculation": {"vehicle_groups": VEHICLE_GROUPS}}
        c.execute(text(
            "INSERT INTO engagements (id, org_id, name, client_name, reporting_period_start, reporting_period_end, "
            "status, settings) VALUES (:id, :org, 'FY2023-25 GHG', 'Scale Client', '2023-01-01', '2025-12-31', "
            "'active', CAST(:settings AS jsonb))"),
            {"id": engagement_id, "org": ORG, "settings": json.dumps(settings)})
        docs, results, reviews = _document_rows(engagement_id, ORG, documents, "SC")
        _insert(c, "s1_documents", ("document_id", "engagement_id", "evidence_id", "processing_status", "batch_id"),
                docs)
        _insert(c, "s1_extraction_results", ("pipeline_run_id", "document_id", "evidence_id"), results)
        _insert(c, "s1_review_decisions", ("review_decision_id", "candidate_id", "evidence_id", "document_id",
                                           "field_name"), reviews)
        # a reviewer's decision on one document in ten: a facility choice with a note
        for number in range(0, documents, 10):
            c.execute(text(
                "INSERT INTO workpaper_items (org_id, engagement_id, kind, item_key, payload) VALUES "
                "(:org, :eng, 'document', :key, CAST(:payload AS jsonb))"),
                {"org": ORG, "eng": engagement_id, "key": f"SC-{number:04d}",
                 "payload": json.dumps({"documentId": f"SC-{number:04d}", "note": "checked"})})
    engine.dispose()
    return engagement_id


def run_admin(admin_url: str, sql: str, **params: Any) -> list[Any]:
    """One statement as the owner role (what a writer outside the request would do), committed at once."""

    from backend.app.core.db import to_sync_url

    engine = create_engine(to_sync_url(admin_url))
    try:
        with engine.begin() as c:
            result = c.execute(text(sql), params)
            return list(result.fetchall()) if result.returns_rows else []
    finally:
        engine.dispose()


def add_gas_document(admin_url: str, engagement_id: str, name: str = "NEW") -> str:
    """One more stationary-fuel document at Kansas City (the document, its extraction result and decisions)."""

    from backend.app.core.db import to_sync_url

    docs, results, reviews = _document_rows(engagement_id, ORG, 41, name)
    last = f"{name}-0040"  # the plan's 41st document is a sourced one
    engine = create_engine(to_sync_url(admin_url))
    try:
        with engine.begin() as c:
            _insert(c, "s1_documents", ("document_id", "engagement_id", "evidence_id", "processing_status", "batch_id"),
                    [d for d in docs if d["document_id"] == last])
            _insert(c, "s1_extraction_results", ("pipeline_run_id", "document_id", "evidence_id"),
                    [r for r in results if r["document_id"] == last])
            _insert(c, "s1_review_decisions", ("review_decision_id", "candidate_id", "evidence_id", "document_id",
                                               "field_name"), [r for r in reviews if r["document_id"] == last])
    finally:
        engine.dispose()
    return last


class StatementCounter:
    """Counts the SQL statements every engine in the process runs while it is installed."""

    def __init__(self) -> None:
        self.statements: list[str] = []

    def _count(self, conn: Any, cursor: Any, statement: str, *rest: Any) -> None:  # noqa: ANN401
        self.statements.append(statement)

    @property
    def total(self) -> int:
        return len(self.statements)

    @property
    def queries(self) -> int:
        """The statements that read or write data (not the per-transaction tenant ``set_config``)."""

        return sum(1 for s in self.statements if "set_config" not in s and not s.lstrip().upper().startswith(
            ("BEGIN", "COMMIT", "ROLLBACK", "SET ")))

    @contextmanager
    def counting(self) -> Iterator[StatementCounter]:
        event.listen(Engine, "before_cursor_execute", self._count)
        try:
            yield self
        finally:
            event.remove(Engine, "before_cursor_execute", self._count)


@contextmanager
def wired_app(app_url: str) -> Iterator[Any]:
    """The real app over the Postgres S1 stores as ``app_user`` (RLS on); yields a ``get(path, token)``."""

    import httpx

    from backend.app.api import documents as documents_api
    from backend.app.api import reviews as reviews_api
    from backend.app.core import db
    from backend.app.core.config import Settings
    from backend.app.core.db import to_sync_url
    from backend.app.core.rate_limit import limiter
    from backend.app.main import create_app
    from backend.app.repositories.document_repository import PostgresDocumentRepository
    from backend.app.repositories.extraction_result_repository import PostgresExtractionResultRepository
    from backend.app.repositories.pipeline_repository import PostgresPipelineRunRepository
    from backend.app.repositories.review_repository import PostgresReviewDecisionRepository
    from backend.app.services.document_upload_service import DocumentUploadService
    from backend.app.services.pipeline_orchestration_service import PipelineOrchestrationService
    from backend.app.services.review_decision_service import ReviewDecisionService
    from backend.app.services.sessions import SESSION_COOKIE

    limiter.reset()
    sync_engine = create_engine(to_sync_url(app_url), pool_size=4, max_overflow=0)
    uploads = DocumentUploadService(document_repository=PostgresDocumentRepository(sync_engine))
    pipeline = PipelineOrchestrationService(
        pipeline_repository=PostgresPipelineRunRepository(sync_engine),
        extraction_result_repository=PostgresExtractionResultRepository(sync_engine))
    reviews = ReviewDecisionService(repository=PostgresReviewDecisionRepository(sync_engine))
    original = (documents_api.current_upload_service(), documents_api.current_pipeline_service(),
                reviews_api.current_service())
    documents_api.configure_services(upload_service=uploads, pipeline_service=pipeline)
    reviews_api.configure_service(reviews)
    loop = asyncio.new_event_loop()
    async_engine = db.create_engine(app_url, pool_size=2, max_overflow=0)
    sessionmaker = db.build_sessionmaker(async_engine)
    app = create_app(Settings(environment="test", git_sha="t", ALLOWED_ORIGINS=ORIGIN))  # type: ignore[call-arg]

    async def session_dep() -> AsyncIterator[AsyncSession]:
        async with sessionmaker() as session, session.begin():
            yield session

    app.dependency_overrides[db.get_db_session] = session_dep

    async def request(path: str, token: str) -> Any:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="https://testserver") as client:
            return await client.get(path, cookies={SESSION_COOKIE: token}, headers={"Origin": ORIGIN})

    def get(path: str, token: str = TOKEN) -> Any:
        return loop.run_until_complete(request(path, token))

    try:
        yield get
    finally:
        loop.run_until_complete(async_engine.dispose())
        loop.close()
        documents_api.configure_services(upload_service=original[0], pipeline_service=original[1])
        reviews_api.configure_service(original[2])
        sync_engine.dispose()


def measure(get: Any, engagement_id: str, path: str, runs: int = 3, token: str = TOKEN) -> dict[str, Any]:
    """Server time (median of ``runs``, ms) and SQL statements of one GET, after a warm-up."""

    base = f"/api/v1/engagements/{engagement_id}"
    start = time.perf_counter()
    first = get(base + path, token)
    cold = round((time.perf_counter() - start) * 1000)
    assert first.status_code == 200, (path, first.status_code, first.text[:300])
    times, counter = [], StatementCounter()
    for _ in range(runs):
        with counter.counting():
            start = time.perf_counter()
            response = get(base + path, token)
            times.append((time.perf_counter() - start) * 1000)
        assert response.status_code == 200
    return {"cold_ms": cold, "ms": round(statistics.median(times)), "statements": counter.total // runs,
            "queries": counter.queries // runs, "bytes": len(response.content)}


def benchmark(admin_url: str, app_url: str, documents: int) -> dict[str, dict[str, Any]]:
    engagement_id = seed(admin_url, documents)
    with wired_app(app_url) as get:
        return {
            "evidence-tree": measure(get, engagement_id, "/evidence-tree"),
            "schedule": measure(get, engagement_id, f"/calculation-lines/{GAS_LINE}/schedule"),
            "recalculation": measure(get, engagement_id, "/recalculation"),
        }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0] if __doc__ else None)
    parser.add_argument("--documents", type=int, nargs="+", default=[50, 500])
    args = parser.parse_args()
    admin, app_url = os.environ["TEST_DATABASE_URL"], os.environ["TEST_APP_DATABASE_URL"]
    for documents in args.documents:
        print(f"--- {documents} documents")
        for name, numbers in benchmark(admin, app_url, documents).items():
            print(f"{name:14} first {numbers['cold_ms']:6} ms, then {numbers['ms']:5} ms  {numbers['queries']:5} queries  "
                  f"({numbers['statements']} statements)  {numbers['bytes']:>9} bytes")


if __name__ == "__main__":
    main()
