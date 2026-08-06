from __future__ import annotations

import copy
from typing import Any, Callable

from sqlalchemy import (
    ForeignKey,
    JSON,
    Column,
    MetaData,
    String,
    Table,
    create_engine,
    insert,
    select,
    update,
)
from sqlalchemy.orm import Session, sessionmaker

metadata = MetaData()

engagements_table = Table(
    "s1_engagements",
    metadata,
    Column("engagement_id", String, primary_key=True),
    Column("engagement_name", String, nullable=False),
    Column("client_name", String, nullable=False),
    Column("created_by", String, nullable=False),
    Column("created_at", String, nullable=False),
    Column("status", String, nullable=False),
    Column("payload", JSON, nullable=False),
)

documents_table = Table(
    "s1_documents",
    metadata,
    Column("document_id", String, primary_key=True),
    Column("engagement_id", String, ForeignKey("s1_engagements.engagement_id"), nullable=False, index=True),
    Column("evidence_id", String, nullable=True, index=True),
    Column("file_name", String, nullable=False),
    Column("mime_type", String, nullable=False),
    Column("storage_uri", String, nullable=False),
    Column("document_role", String, nullable=False),
    Column("document_type", String, nullable=True),
    Column("uploaded_by", String, nullable=False),
    Column("uploaded_at", String, nullable=False),
    Column("processing_status", String, nullable=False),
)

pipeline_runs_table = Table(
    "s1_pipeline_runs",
    metadata,
    Column("pipeline_run_id", String, primary_key=True),
    Column("engagement_id", String, nullable=False, index=True),
    Column("evidence_id", String, nullable=False, index=True),
    Column("document_id", String, ForeignKey("s1_documents.document_id"), nullable=False, index=True),
    Column("created_at", String, nullable=False, index=True),
    Column("payload", JSON, nullable=False),
)

extraction_results_table = Table(
    "s1_extraction_results",
    metadata,
    Column("pipeline_run_id", String, ForeignKey("s1_pipeline_runs.pipeline_run_id"), primary_key=True),
    Column("engagement_id", String, nullable=False, index=True),
    Column("evidence_id", String, nullable=False, index=True),
    Column("document_id", String, ForeignKey("s1_documents.document_id"), nullable=False, index=True),
    Column("created_at", String, nullable=False, index=True),
    Column("payload", JSON, nullable=False),
)

review_decisions_table = Table(
    "s1_review_decisions",
    metadata,
    Column("review_decision_id", String, primary_key=True),
    Column("candidate_id", String, nullable=False, index=True),
    Column("evidence_id", String, nullable=False, index=True),
    Column("document_id", String, ForeignKey("s1_documents.document_id"), nullable=False, index=True),
    Column("field_name", String, nullable=False, index=True),
    Column("reviewed_at", String, nullable=False, index=True),
    Column("payload", JSON, nullable=False),
)


def build_sql_session_factory(database_url: str, *, create_schema: bool = True) -> sessionmaker[Session]:
    engine = create_engine(database_url, future=True)
    if create_schema:
        metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


class SqlEngagementRepository:
    def __init__(self, session_factory: Callable[[], Session]) -> None:
        self._session_factory = session_factory

    def save(self, engagement: dict) -> dict:
        record = copy.deepcopy(engagement)
        with self._session_factory() as session:
            with session.begin():
                values = {
                    "engagement_id": record["engagement_id"],
                    "engagement_name": record["engagement_name"],
                    "client_name": record["client_name"],
                    "created_by": record["created_by"],
                    "created_at": record["created_at"],
                    "status": record["status"],
                    "payload": record,
                }
                result = session.execute(
                    update(engagements_table)
                    .where(engagements_table.c.engagement_id == record["engagement_id"])
                    .values(**values)
                )
                if result.rowcount == 0:
                    session.execute(insert(engagements_table).values(**values))
        return record

    def list_all(self) -> list[dict]:
        with self._session_factory() as session:
            rows = session.execute(
                select(engagements_table.c.payload).order_by(engagements_table.c.created_at)
            ).all()
        return [copy.deepcopy(row[0]) for row in rows]

    def get_by_id(self, engagement_id: str) -> dict | None:
        with self._session_factory() as session:
            row = session.execute(
                select(engagements_table.c.payload).where(
                    engagements_table.c.engagement_id == engagement_id
                )
            ).first()
        return copy.deepcopy(row[0]) if row else None


class SqlDocumentRepository:
    def __init__(self, session_factory: Callable[[], Session]) -> None:
        self._session_factory = session_factory

    def save(self, document: dict) -> dict:
        record = copy.deepcopy(document)
        with self._session_factory() as session:
            with session.begin():
                result = session.execute(
                    update(documents_table)
                    .where(documents_table.c.document_id == record["document_id"])
                    .values(**record)
                )
                if result.rowcount == 0:
                    session.execute(insert(documents_table).values(**record))
        return record

    def list_all(self) -> list[dict]:
        with self._session_factory() as session:
            rows = session.execute(select(documents_table)).mappings().all()
        return [dict(row) for row in rows]

    def list_by_engagement(self, engagement_id: str) -> list[dict]:
        with self._session_factory() as session:
            rows = session.execute(
                select(documents_table)
                .where(documents_table.c.engagement_id == engagement_id)
                .order_by(documents_table.c.uploaded_at)
            ).mappings().all()
        return [dict(row) for row in rows]

    def list_by_evidence(self, evidence_id: str) -> list[dict]:
        with self._session_factory() as session:
            rows = session.execute(
                select(documents_table)
                .where(documents_table.c.evidence_id == evidence_id)
                .order_by(documents_table.c.uploaded_at)
            ).mappings().all()
        return [dict(row) for row in rows]

    def get_by_id(self, document_id: str) -> dict | None:
        with self._session_factory() as session:
            row = session.execute(
                select(documents_table).where(documents_table.c.document_id == document_id)
            ).mappings().first()
        return dict(row) if row else None

    def get_latest_by_evidence(self, evidence_id: str) -> dict | None:
        matches = self.list_by_evidence(evidence_id)
        return matches[-1] if matches else None

    def update_processing_status(self, document_id: str, processing_status: str) -> dict:
        existing = self.get_by_id(document_id)
        if existing is None:
            raise KeyError(f"Document not found: {document_id}")
        updated = {**existing, "processing_status": processing_status}
        return self.save(updated)


class SqlPipelineRunRepository:
    def __init__(self, session_factory: Callable[[], Session]) -> None:
        self._session_factory = session_factory

    def save(self, run: dict) -> dict:
        record = copy.deepcopy(run)
        with self._session_factory() as session:
            with session.begin():
                values = {
                    "pipeline_run_id": record["pipeline_run_id"],
                    "engagement_id": record["engagement_id"],
                    "evidence_id": record["evidence_id"],
                    "document_id": record["document_id"],
                    "created_at": record["created_at"],
                    "payload": record,
                }
                result = session.execute(
                    update(pipeline_runs_table)
                    .where(pipeline_runs_table.c.pipeline_run_id == record["pipeline_run_id"])
                    .values(**values)
                )
                if result.rowcount == 0:
                    session.execute(insert(pipeline_runs_table).values(**values))
        return record

    def list_all(self) -> list[dict]:
        return self._payloads(select(pipeline_runs_table).order_by(pipeline_runs_table.c.created_at))

    def list_by_engagement(self, engagement_id: str) -> list[dict]:
        return self._payloads(
            select(pipeline_runs_table)
            .where(pipeline_runs_table.c.engagement_id == engagement_id)
            .order_by(pipeline_runs_table.c.created_at)
        )

    def list_by_evidence(self, evidence_id: str) -> list[dict]:
        return self._payloads(
            select(pipeline_runs_table)
            .where(pipeline_runs_table.c.evidence_id == evidence_id)
            .order_by(pipeline_runs_table.c.created_at)
        )

    def get_by_id(self, pipeline_run_id: str) -> dict | None:
        with self._session_factory() as session:
            row = session.execute(
                select(pipeline_runs_table.c.payload).where(
                    pipeline_runs_table.c.pipeline_run_id == pipeline_run_id
                )
            ).first()
        return copy.deepcopy(row[0]) if row else None

    def get_latest_by_evidence(self, evidence_id: str) -> dict | None:
        matches = self.list_by_evidence(evidence_id)
        return matches[-1] if matches else None

    def _payloads(self, statement: Any) -> list[dict]:
        with self._session_factory() as session:
            rows = session.execute(statement.with_only_columns(pipeline_runs_table.c.payload)).all()
        return [copy.deepcopy(row[0]) for row in rows]


class SqlExtractionResultRepository:
    def __init__(self, session_factory: Callable[[], Session]) -> None:
        self._session_factory = session_factory

    def save(self, result: dict) -> dict:
        record = copy.deepcopy(result)
        with self._session_factory() as session:
            with session.begin():
                values = {
                    "pipeline_run_id": record["pipeline_run_id"],
                    "engagement_id": record["engagement_id"],
                    "evidence_id": record["evidence_id"],
                    "document_id": record["document_id"],
                    "created_at": record["created_at"],
                    "payload": record,
                }
                result = session.execute(
                    update(extraction_results_table)
                    .where(extraction_results_table.c.pipeline_run_id == record["pipeline_run_id"])
                    .values(**values)
                )
                if result.rowcount == 0:
                    session.execute(insert(extraction_results_table).values(**values))
        return record

    def list_by_document(self, document_id: str) -> list[dict]:
        return self._payloads(
            select(extraction_results_table)
            .where(extraction_results_table.c.document_id == document_id)
            .order_by(extraction_results_table.c.created_at)
        )

    def list_by_evidence(self, evidence_id: str) -> list[dict]:
        return self._payloads(
            select(extraction_results_table)
            .where(extraction_results_table.c.evidence_id == evidence_id)
            .order_by(extraction_results_table.c.created_at)
        )

    def get_latest_by_document(self, document_id: str) -> dict | None:
        matches = self.list_by_document(document_id)
        return matches[-1] if matches else None

    def get_latest_by_evidence(self, evidence_id: str) -> dict | None:
        matches = self.list_by_evidence(evidence_id)
        return matches[-1] if matches else None

    def _payloads(self, statement: Any) -> list[dict]:
        with self._session_factory() as session:
            rows = session.execute(statement.with_only_columns(extraction_results_table.c.payload)).all()
        return [copy.deepcopy(row[0]) for row in rows]


class SqlReviewDecisionRepository:
    def __init__(self, session_factory: Callable[[], Session]) -> None:
        self._session_factory = session_factory

    def save(self, decision: dict) -> dict:
        record = copy.deepcopy(decision)
        with self._session_factory() as session:
            with session.begin():
                values = {
                    "review_decision_id": record["review_decision_id"],
                    "candidate_id": record["candidate_id"],
                    "evidence_id": record["evidence_id"],
                    "document_id": record["document_id"],
                    "field_name": record["field_name"],
                    "reviewed_at": record["reviewed_at"],
                    "payload": record,
                }
                result = session.execute(
                    update(review_decisions_table)
                    .where(review_decisions_table.c.review_decision_id == record["review_decision_id"])
                    .values(**values)
                )
                if result.rowcount == 0:
                    session.execute(insert(review_decisions_table).values(**values))
        return record

    def list_all(self) -> list[dict]:
        return self._payloads(select(review_decisions_table).order_by(review_decisions_table.c.reviewed_at))

    def list_by_evidence(self, evidence_id: str) -> list[dict]:
        return self._payloads(
            select(review_decisions_table)
            .where(review_decisions_table.c.evidence_id == evidence_id)
            .order_by(review_decisions_table.c.reviewed_at)
        )

    def list_by_document(self, document_id: str) -> list[dict]:
        return self._payloads(
            select(review_decisions_table)
            .where(review_decisions_table.c.document_id == document_id)
            .order_by(review_decisions_table.c.reviewed_at)
        )

    def list_by_candidate(self, candidate_id: str) -> list[dict]:
        return self._payloads(
            select(review_decisions_table)
            .where(review_decisions_table.c.candidate_id == candidate_id)
            .order_by(review_decisions_table.c.reviewed_at)
        )

    def get_latest_by_candidate(self, candidate_id: str) -> dict | None:
        matches = self.list_by_candidate(candidate_id)
        return matches[-1] if matches else None

    def get_latest_by_field(self, evidence_id: str, field_name: str) -> dict | None:
        matches = self._payloads(
            select(review_decisions_table)
            .where(review_decisions_table.c.evidence_id == evidence_id)
            .where(review_decisions_table.c.field_name == field_name)
            .order_by(review_decisions_table.c.reviewed_at)
        )
        return matches[-1] if matches else None

    def _payloads(self, statement: Any) -> list[dict]:
        with self._session_factory() as session:
            rows = session.execute(statement.with_only_columns(review_decisions_table.c.payload)).all()
        return [copy.deepcopy(row[0]) for row in rows]
