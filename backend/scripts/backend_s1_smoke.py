"""Run an end-to-end local S1 backend smoke flow (no HTTP server required).

Flow:
1) Ensure a synthetic sample exists (or generate one)
2) Upload through DocumentUploadService
3) Process through PipelineOrchestrationService
4) Submit a small set of review decisions
5) Project approved evidence
6) Print a concise summary
"""

from __future__ import annotations

import argparse
import mimetypes
import sys
import tempfile
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from backend.app.repositories.document_repository import (  # noqa: E402
    InMemoryDocumentRepository,
    JsonlDocumentRepository,
)
from backend.app.repositories.evidence_repository import (  # noqa: E402
    InMemoryApprovedEvidenceRepository,
    JsonlApprovedEvidenceRepository,
)
from backend.app.repositories.pipeline_repository import (  # noqa: E402
    InMemoryPipelineRunRepository,
    JsonlPipelineRunRepository,
)
from backend.app.repositories.review_repository import (  # noqa: E402
    InMemoryReviewDecisionRepository,
    JsonlReviewDecisionRepository,
)
from backend.app.services.approved_evidence_service import ApprovedEvidenceService  # noqa: E402
from backend.app.services.document_upload_service import DocumentUploadService  # noqa: E402
from backend.app.services.local_storage_service import LocalStorageService  # noqa: E402
from backend.app.services.pipeline_orchestration_service import (  # noqa: E402
    PipelineOrchestrationService,
)
from backend.app.services.review_decision_service import ReviewDecisionService  # noqa: E402
from backend.scripts.generate_synthetic_evidence import (  # noqa: E402
    DEFAULT_FILE_NAME,
    DEFAULT_OUTPUT_DIR,
    generate_synthetic_evidence,
)

DEFAULT_ENGAGEMENT_ID = "eng-smoke-001"
DEFAULT_CANONICAL_TYPE_ID = "CT-S1-FUELQTY"
DEFAULT_REVIEWER_ID = "smoke-reviewer@example.com"


def run_backend_s1_smoke(
    *,
    sample_file: str | Path | None = None,
    generate_sample: bool = False,
    engagement_id: str = DEFAULT_ENGAGEMENT_ID,
    canonical_type_id: str = DEFAULT_CANONICAL_TYPE_ID,
    reviewer_id: str = DEFAULT_REVIEWER_ID,
    clean_run: bool = False,
    local_data_root: str | Path = "local-data",
) -> dict[str, Any]:
    """Execute the local S1 smoke flow and return summary artifacts."""

    sample_path = _resolve_sample_file(sample_file)
    if not sample_path.exists():
        if not generate_sample:
            raise ValueError(
                f"Sample file does not exist: {sample_path}. Use --generate-sample or provide --sample-file."
            )
        sample_path = generate_synthetic_evidence(
            output_dir=sample_path.parent,
            file_name=sample_path.name,
            overwrite=False,
        )

    if clean_run and str(local_data_root) == "local-data":
        local_data_root = Path(tempfile.mkdtemp(prefix="sustentra-smoke-")) / "local-data"

    local_data_path = Path(local_data_root)

    if clean_run:
        document_repo = InMemoryDocumentRepository()
        pipeline_repo = InMemoryPipelineRunRepository()
        review_repo = InMemoryReviewDecisionRepository()
        approved_repo = InMemoryApprovedEvidenceRepository()
    else:
        document_repo = JsonlDocumentRepository(local_data_path / "documents" / "documents.jsonl")
        pipeline_repo = JsonlPipelineRunRepository(
            local_data_path / "pipeline-runs" / "pipeline_runs.jsonl"
        )
        review_repo = JsonlReviewDecisionRepository(
            local_data_path / "review-decisions" / "review_decisions.jsonl"
        )
        approved_repo = JsonlApprovedEvidenceRepository(
            local_data_path / "approved-evidence" / "approved_evidence.jsonl"
        )

    storage_service = LocalStorageService(storage_root=local_data_path / "uploads")
    upload_service = DocumentUploadService(
        storage_service=storage_service,
        document_repository=document_repo,
    )
    review_service = ReviewDecisionService(repository=review_repo)
    approved_service = ApprovedEvidenceService(
        review_repository=review_repo,
        approved_repository=approved_repo,
    )
    pipeline_service = PipelineOrchestrationService(
        pipeline_repository=pipeline_repo,
        review_service=review_service,
        approved_evidence_service=approved_service,
    )

    mime_type = mimetypes.guess_type(sample_path.name)[0] or "text/plain"

    uploaded = upload_service.upload_document(
        engagement_id=engagement_id,
        file_name=sample_path.name,
        content=sample_path.read_bytes(),
        mime_type=mime_type,
        document_role="source_evidence",
        uploaded_by=reviewer_id,
    )

    upload_service.update_processing_status(uploaded["document_id"], "in_progress")
    local_file_path = storage_service.resolve_storage_uri(uploaded["storage_uri"])

    pipeline_result = pipeline_service.process_local_document(
        local_file_path=str(local_file_path),
        engagement_id=uploaded["engagement_id"],
        evidence_id=uploaded.get("evidence_id"),
        document_id=uploaded["document_id"],
        file_name=uploaded.get("file_name"),
        mime_type=uploaded.get("mime_type"),
        canonical_type_id_override=canonical_type_id,
        include_optional=True,
        include_deprecated=False,
        persist_run=True,
    )

    pipeline_status = pipeline_result["pipeline_run"]["status"]
    if pipeline_status == "failed":
        upload_service.update_processing_status(uploaded["document_id"], "failed")
    else:
        upload_service.update_processing_status(uploaded["document_id"], "completed")

    review_decisions = _submit_smoke_review_decisions(
        review_service=review_service,
        reviewer_id=reviewer_id,
        candidates=pipeline_result.get("extraction_result", {}).get("items") or [],
    )

    approved_evidence = approved_service.project_by_evidence(
        evidence_id=uploaded["evidence_id"],
        engagement_id=uploaded["engagement_id"],
        evidence_type=canonical_type_id,
    )

    pipeline_run = pipeline_result["pipeline_run"]
    summary = {
        "sample_file": str(sample_path).replace("\\", "/"),
        "document_id": uploaded["document_id"],
        "evidence_id": uploaded["evidence_id"],
        "pipeline_run_id": pipeline_run["pipeline_run_id"],
        "pipeline_status": pipeline_run["status"],
        "target_count": pipeline_run["target_count"],
        "candidate_count": pipeline_run["candidate_count"],
        "found_candidate_count": pipeline_run["found_candidate_count"],
        "missing_candidate_count": pipeline_run["missing_candidate_count"],
        "review_decision_count": len(review_decisions),
        "approved_evidence_id": approved_evidence["approved_evidence_id"],
        "approved_field_count": approved_evidence["approved_field_count"],
        "local_data_root": str(local_data_path).replace("\\", "/"),
    }

    return {
        "summary": summary,
        "uploaded_document": uploaded,
        "pipeline_result": pipeline_result,
        "review_decisions": review_decisions,
        "approved_evidence": approved_evidence,
    }


def _resolve_sample_file(sample_file: str | Path | None) -> Path:
    if sample_file is None:
        return Path(DEFAULT_OUTPUT_DIR) / DEFAULT_FILE_NAME
    return Path(sample_file)


def _submit_smoke_review_decisions(
    *,
    review_service: ReviewDecisionService,
    reviewer_id: str,
    candidates: list[dict],
) -> list[dict]:
    accepted_limit = 3
    needs_more_limit = 1
    accepted_count = 0
    needs_more_count = 0
    decisions: list[dict] = []

    for candidate in candidates:
        raw_value = candidate.get("raw_value")

        if raw_value is not None and accepted_count < accepted_limit:
            decisions.append(
                review_service.submit_decision(
                    candidate=candidate,
                    decision="accepted",
                    reviewer_id=reviewer_id,
                )
            )
            accepted_count += 1
            continue

        if raw_value is None and needs_more_count < needs_more_limit:
            decisions.append(
                review_service.submit_decision(
                    candidate=candidate,
                    decision="needs_more_evidence",
                    reviewer_id=reviewer_id,
                )
            )
            needs_more_count += 1

        if accepted_count >= accepted_limit and needs_more_count >= needs_more_limit:
            break

    return decisions


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run local S1 backend smoke flow.")
    parser.add_argument("--sample-file", default=None)
    parser.add_argument("--generate-sample", action="store_true")
    parser.add_argument("--engagement-id", default=DEFAULT_ENGAGEMENT_ID)
    parser.add_argument("--canonical-type-id", default=DEFAULT_CANONICAL_TYPE_ID)
    parser.add_argument("--reviewer-id", default=DEFAULT_REVIEWER_ID)
    parser.add_argument("--clean-run", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    result = run_backend_s1_smoke(
        sample_file=args.sample_file,
        generate_sample=args.generate_sample,
        engagement_id=args.engagement_id,
        canonical_type_id=args.canonical_type_id,
        reviewer_id=args.reviewer_id,
        clean_run=args.clean_run,
    )

    summary = result["summary"]
    print("Backend S1 smoke summary")
    for key in (
        "sample_file",
        "document_id",
        "evidence_id",
        "pipeline_run_id",
        "pipeline_status",
        "target_count",
        "candidate_count",
        "found_candidate_count",
        "missing_candidate_count",
        "review_decision_count",
        "approved_evidence_id",
        "approved_field_count",
        "local_data_root",
    ):
        print(f"- {key}: {summary[key]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
