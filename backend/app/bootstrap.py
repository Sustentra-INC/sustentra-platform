from __future__ import annotations

from backend.app.adapters.storage.s3_storage import S3Storage
import logging

from backend.app.api import documents, engagements, extraction_results, pipeline, reviews
from backend.app.repositories.document_repository import JsonlDocumentRepository
from backend.app.repositories.engagement_repository import JsonlEngagementRepository
from backend.app.repositories.extraction_result_repository import JsonlExtractionResultRepository
from backend.app.repositories.pipeline_repository import JsonlPipelineRunRepository
from backend.app.repositories.review_repository import (
    DEFAULT_JSONL_PATH as REVIEW_JSONL_PATH,
    JsonlReviewDecisionRepository,
)
from backend.app.repositories.sql_repositories import (
    SqlDocumentRepository,
    SqlEngagementRepository,
    SqlExtractionResultRepository,
    SqlPipelineRunRepository,
    SqlReviewDecisionRepository,
    build_sql_session_factory,
)
from backend.app.services.document_upload_service import DocumentUploadService
from backend.app.services.local_storage_service import LocalStorageService
from backend.app.services.pipeline_orchestration_service import PipelineOrchestrationService
from backend.app.services.review_decision_service import ReviewDecisionService
from backend.app.settings import RuntimeSettings, load_runtime_settings

logger = logging.getLogger(__name__)


def configure_runtime_from_env() -> RuntimeSettings:
    settings = load_runtime_settings()
    configure_runtime(settings)
    return settings


def configure_runtime(settings: RuntimeSettings) -> None:
    engagement_repository, document_repository, pipeline_repository, extraction_repository, review_repository = (
        _build_repositories(settings)
    )
    storage_service = _build_storage_service(settings)

    review_service = ReviewDecisionService(repository=review_repository)
    pipeline_service = PipelineOrchestrationService(
        review_service=review_service,
        pipeline_repository=pipeline_repository,
        extraction_result_repository=extraction_repository,
    )
    upload_service = DocumentUploadService(
        storage_service=storage_service,
        document_repository=document_repository,
    )

    engagements.configure_repository(engagement_repository)
    engagement_repository.save(engagements.DEFAULT_S1_ENGAGEMENT)
    documents.configure_services(
        upload_service=upload_service,
        pipeline_service=pipeline_service,
        storage_service=storage_service,
    )
    pipeline.configure_service(pipeline_service)
    extraction_results.configure_service(pipeline_service)
    reviews.configure_service(review_service)
    logger.info("Sustentra persistence backend selected: %s", settings.persistence_backend)
    logger.info("Sustentra storage backend selected: %s", settings.storage_backend)


def _build_repositories(settings: RuntimeSettings):
    if settings.persistence_backend == "postgres":
        if not settings.database_url:
            raise RuntimeError("DATABASE_URL is required when SUSTENTRA_PERSISTENCE_BACKEND=postgres.")
        session_factory = build_sql_session_factory(settings.database_url, create_schema=False)
        return (
            SqlEngagementRepository(session_factory),
            SqlDocumentRepository(session_factory),
            SqlPipelineRunRepository(session_factory),
            SqlExtractionResultRepository(session_factory),
            SqlReviewDecisionRepository(session_factory),
        )
    if settings.persistence_backend != "jsonl":
        raise RuntimeError(
            "SUSTENTRA_PERSISTENCE_BACKEND must be either 'jsonl' or 'postgres'."
        )
    return (
        JsonlEngagementRepository(),
        JsonlDocumentRepository(),
        JsonlPipelineRunRepository(),
        JsonlExtractionResultRepository(),
        JsonlReviewDecisionRepository(REVIEW_JSONL_PATH),
    )


def _build_storage_service(settings: RuntimeSettings):
    if settings.storage_backend in {"s3", "minio"}:
        return S3Storage(
            bucket=settings.s3_bucket,
            endpoint_url=settings.s3_endpoint_url,
            access_key_id=settings.s3_access_key_id,
            secret_access_key=settings.s3_secret_access_key,
            region=settings.s3_region,
        )
    if settings.storage_backend != "local":
        raise RuntimeError("SUSTENTRA_STORAGE_BACKEND must be 'local', 'minio', or 's3'.")
    return LocalStorageService(settings.local_upload_root)
