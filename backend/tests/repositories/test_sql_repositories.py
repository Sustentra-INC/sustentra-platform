from __future__ import annotations

from pathlib import Path

from backend.app.repositories.sql_repositories import (
    SqlDocumentRepository,
    SqlEngagementRepository,
    SqlExtractionResultRepository,
    SqlPipelineRunRepository,
    SqlReviewDecisionRepository,
    build_sql_session_factory,
)


def _session_factory(tmp_path: Path):
    return build_sql_session_factory(f"sqlite+pysqlite:///{tmp_path / 's1.db'}")


def test_sql_document_repository_updates_current_document(tmp_path: Path):
    session_factory = _session_factory(tmp_path)
    SqlEngagementRepository(session_factory).save(_engagement())
    repository = SqlDocumentRepository(session_factory)

    repository.save(_document())
    updated = repository.update_processing_status("DOC-1", "completed")

    assert updated["processing_status"] == "completed"
    assert repository.get_by_id("DOC-1")["processing_status"] == "completed"
    assert len(repository.list_by_engagement("ENG-1")) == 1


def test_sql_pipeline_and_extraction_repositories_return_latest(tmp_path: Path):
    session_factory = _session_factory(tmp_path)
    SqlEngagementRepository(session_factory).save(_engagement())
    SqlDocumentRepository(session_factory).save(_document())
    pipeline_repository = SqlPipelineRunRepository(session_factory)
    extraction_repository = SqlExtractionResultRepository(session_factory)

    first_run = _pipeline_run("PIPE-1", "2026-01-01T00:00:00+00:00", "partial")
    second_run = _pipeline_run("PIPE-2", "2026-01-02T00:00:00+00:00", "completed")
    pipeline_repository.save(first_run)
    pipeline_repository.save(second_run)

    first_result = _extraction_result("PIPE-1", "2026-01-01T00:00:00+00:00", [])
    second_result = _extraction_result("PIPE-2", "2026-01-02T00:00:00+00:00", [{"candidate_id": "C-1"}])
    extraction_repository.save(first_result)
    extraction_repository.save(second_result)

    assert pipeline_repository.get_latest_by_evidence("EV-1")["pipeline_run_id"] == "PIPE-2"
    assert extraction_repository.get_latest_by_document("DOC-1")["pipeline_run_id"] == "PIPE-2"
    updated = SqlDocumentRepository(session_factory).update_processing_status("DOC-1", "completed")
    assert updated["processing_status"] == "completed"


def test_sql_review_repository_returns_latest_decision(tmp_path: Path):
    session_factory = _session_factory(tmp_path)
    SqlEngagementRepository(session_factory).save(_engagement())
    SqlDocumentRepository(session_factory).save(_document())
    repository = SqlReviewDecisionRepository(session_factory)
    repository.save(_review_decision("REV-1", "2026-01-01T00:00:00+00:00", "accepted"))
    repository.save(_review_decision("REV-2", "2026-01-02T00:00:00+00:00", "edited"))

    latest = repository.get_latest_by_candidate("CAND-1")

    assert latest["review_decision_id"] == "REV-2"
    assert latest["decision"] == "edited"
    assert len(repository.list_by_document("DOC-1")) == 2


def _pipeline_run(pipeline_run_id: str, created_at: str, status: str) -> dict:
    return {
        "pipeline_run_id": pipeline_run_id,
        "engagement_id": "ENG-1",
        "evidence_id": "EV-1",
        "document_id": "DOC-1",
        "processing_run_id": "PROC-1",
        "status": status,
        "stage_statuses": {
            "parse": "completed",
            "classify": "completed",
            "target_plan": "completed",
            "candidate_generation": "completed",
        },
        "input_file_name": "sample.pdf",
        "canonical_type_id": "CT-S1-FUELQTY",
        "canonical_type_source": "override",
        "classification_status": "classified",
        "parser_status": "parsed",
        "target_count": 1,
        "candidate_count": 1,
        "found_candidate_count": 1,
        "missing_candidate_count": 0,
        "low_confidence_candidate_count": 0,
        "warnings": [],
        "errors": [],
        "created_at": created_at,
        "completed_at": created_at,
        "artifacts": {},
    }


def _engagement() -> dict:
    return {
        "engagement_id": "ENG-1",
        "engagement_name": "Test Engagement",
        "client_name": "Test Client",
        "created_by": "dev@example.com",
        "created_at": "2026-01-01T00:00:00+00:00",
        "status": "active",
        "reporting_period": {},
        "facilities": [],
        "regulation": None,
        "conclusion_type": None,
        "assurance_level": None,
        "boundary_approach": None,
        "scope_boundary_statement": None,
    }


def _document() -> dict:
    return {
        "document_id": "DOC-1",
        "engagement_id": "ENG-1",
        "evidence_id": "EV-1",
        "file_name": "sample.pdf",
        "mime_type": "application/pdf",
        "storage_uri": "s3://bucket/sample.pdf",
        "document_role": "source_evidence",
        "document_type": None,
        "uploaded_by": "dev@example.com",
        "uploaded_at": "2026-01-01T00:00:00+00:00",
        "processing_status": "not_started",
    }


def _extraction_result(pipeline_run_id: str, created_at: str, items: list[dict]) -> dict:
    return {
        "pipeline_run_id": pipeline_run_id,
        "engagement_id": "ENG-1",
        "evidence_id": "EV-1",
        "document_id": "DOC-1",
        "canonical_type_id": "CT-S1-FUELQTY",
        "candidate_count": len(items),
        "items": items,
        "created_at": created_at,
    }


def _review_decision(review_decision_id: str, reviewed_at: str, decision: str) -> dict:
    return {
        "review_decision_id": review_decision_id,
        "candidate_id": "CAND-1",
        "evidence_id": "EV-1",
        "document_id": "DOC-1",
        "field_name": "fuel_quantity",
        "decision": decision,
        "reviewed_value": "42",
        "reviewed_unit": "therm",
        "reviewer_id": "reviewer@example.com",
        "reviewed_at": reviewed_at,
        "reviewer_note": None,
        "candidate_snapshot": {},
        "source_reference": {},
    }
