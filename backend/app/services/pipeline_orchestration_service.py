from __future__ import annotations

import copy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from backend.app.domain.pipeline import PipelineRun, PipelineStageStatuses
from backend.app.repositories.extraction_result_repository import (
    JsonlExtractionResultRepository,
)
from backend.app.repositories.pipeline_repository import JsonlPipelineRunRepository
from backend.app.services.approved_evidence_service import ApprovedEvidenceService
from backend.app.services.classification_service import ClassificationService
from backend.app.services.extraction_service import ExtractionService
from backend.app.services.extraction_target_service import ExtractionTargetService
from backend.app.services.llm_extraction_service import LlmExtractionService
from backend.app.services.parser_service import ParserService
from backend.app.services.review_decision_service import ReviewDecisionService

CLASSIFIER_TARGET_STATUSES = {"classified", "multi_type_candidate"}
LOW_CONFIDENCE_THRESHOLD = 0.5


class PipelineOrchestrationService:
    def __init__(
        self,
        parser_service: Any | None = None,
        classification_service: Any | None = None,
        target_service: Any | None = None,
        extraction_service: Any | None = None,
        llm_extraction_service: Any | None = None,
        review_service: Any | None = None,
        approved_evidence_service: Any | None = None,
        pipeline_repository: Any | None = None,
        extraction_result_repository: Any | None = None,
        clock: Callable[[], str] | None = None,
        id_factory: Callable[[str, str], str] | None = None,
    ) -> None:
        self._parser_service = parser_service or ParserService()
        self._classification_service = classification_service or ClassificationService()

        self._target_service = target_service or ExtractionTargetService()
        self._extraction_service = extraction_service or ExtractionService(
            target_service=self._target_service
        )
        self._llm_extraction_service = llm_extraction_service or LlmExtractionService()

        self._review_service = review_service or ReviewDecisionService()
        self._approved_evidence_service = (
            approved_evidence_service or ApprovedEvidenceService()
        )
        self._pipeline_repository = pipeline_repository or JsonlPipelineRunRepository()
        self._extraction_result_repository = (
            extraction_result_repository or JsonlExtractionResultRepository()
        )

        self._clock = clock or (lambda: datetime.now(timezone.utc).isoformat())
        self._id_factory = id_factory or self._default_id_factory

    @staticmethod
    def _default_id_factory(prefix: str, seed: str) -> str:
        return f"{prefix}::{seed}::{uuid4().hex[:12]}"

    def process_local_document(
        self,
        local_file_path: str,
        engagement_id: str,
        evidence_id: str | None = None,
        document_id: str | None = None,
        processing_run_id: str | None = None,
        file_name: str | None = None,
        mime_type: str | None = None,
        canonical_type_id_override: str | None = None,
        include_optional: bool = True,
        include_deprecated: bool = False,
        persist_run: bool = True,
    ) -> dict:
        path = Path(local_file_path)
        if not path.exists() or not path.is_file():
            raise ValueError(f"local_file_path does not exist or is not a file: {local_file_path}")
        if not engagement_id or not str(engagement_id).strip():
            raise ValueError("engagement_id is required.")

        resolved_document_id = str(document_id or self._id_factory("document", engagement_id))
        resolved_evidence_id = str(evidence_id or self._id_factory("evidence", resolved_document_id))
        resolved_processing_run_id = str(
            processing_run_id or self._id_factory("processing", resolved_document_id)
        )
        resolved_pipeline_run_id = self._id_factory("pipeline", resolved_evidence_id)
        resolved_file_name = file_name or path.name

        created_at = self._clock()
        stage_statuses = PipelineStageStatuses()
        warnings: list[str] = []
        errors: list[str] = []

        parser_output: dict = {}
        classification_result: dict = {}
        extraction_targets: list[dict] = []
        extraction_result: dict = {
            "evidence_id": resolved_evidence_id,
            "document_id": resolved_document_id,
            "candidate_count": 0,
            "items": [],
        }

        parser_status: str | None = None
        classification_status: str | None = None
        canonical_type_id: str | None = None
        canonical_type_source = "none"

        try:
            parser_output = self._parser_service.parse_document(
                file_path=str(path),
                document_id=resolved_document_id,
                processing_run_id=resolved_processing_run_id,
                mime_type=mime_type,
            )
            parser_status = str(parser_output.get("status") or "") or None
            stage_statuses.parse = self._parser_stage_status(parser_status)

            if parser_status == "failed":
                errors.append("Parser stage returned failed status.")
                run = self._build_pipeline_run(
                    pipeline_run_id=resolved_pipeline_run_id,
                    engagement_id=engagement_id,
                    evidence_id=resolved_evidence_id,
                    document_id=resolved_document_id,
                    processing_run_id=resolved_processing_run_id,
                    status="failed",
                    stage_statuses=stage_statuses,
                    input_file_name=resolved_file_name,
                    canonical_type_id=None,
                    canonical_type_source="none",
                    classification_status=None,
                    parser_status=parser_status,
                    extraction_targets=[],
                    extraction_result=extraction_result,
                    warnings=warnings,
                    errors=errors,
                    created_at=created_at,
                    completed_at=self._clock(),
                )
                saved_run = self._persist_run_if_needed(run, persist_run)
                self._persist_extraction_result_if_needed(
                    extraction_result=extraction_result,
                    pipeline_run=saved_run,
                    canonical_type_id=canonical_type_id,
                    persist_run=persist_run,
                )
                return {
                    "pipeline_run": saved_run,
                    "parser_output": parser_output,
                    "classification_result": classification_result,
                    "extraction_targets": extraction_targets,
                    "extraction_result": extraction_result,
                }

            classification_result = self._classification_service.classify(
                {
                    "document_id": resolved_document_id,
                    "engagement_id": engagement_id,
                    "processing_run_id": resolved_processing_run_id,
                    "file_name": resolved_file_name,
                    "parser_output": parser_output,
                }
            )
            classification_result = self._apply_s1_fallback_classification(
                classification_result=classification_result,
                parser_output=parser_output,
                file_name=resolved_file_name,
            )
            classification_status = str(classification_result.get("status") or "") or None
            stage_statuses.classify = self._classification_stage_status(classification_status)

            if canonical_type_id_override:
                canonical_type_id = canonical_type_id_override
                canonical_type_source = "override"
                extraction_targets = self._get_target_service().get_targets_for_canonical_type(
                    canonical_type_id,
                    include_optional=include_optional,
                    include_deprecated=include_deprecated,
                )
            else:
                primary = classification_result.get("primary_canonical_type_id")
                if (
                    classification_status in CLASSIFIER_TARGET_STATUSES
                    and isinstance(primary, str)
                    and primary.strip()
                ):
                    canonical_type_id = primary.strip()
                    canonical_type_source = "classifier"
                    extraction_targets = (
                        self._get_target_service().get_targets_for_classification_result(
                            classification_result,
                            include_optional=include_optional,
                            include_deprecated=include_deprecated,
                        )
                    )
                else:
                    canonical_type_id = None
                    canonical_type_source = "none"
                    warnings.append(
                        "No confident canonical_type_id available; target planning and candidate generation were skipped."
                    )

            if canonical_type_id is None:
                stage_statuses.target_plan = "skipped"
                stage_statuses.candidate_generation = "skipped"
                run = self._build_pipeline_run(
                    pipeline_run_id=resolved_pipeline_run_id,
                    engagement_id=engagement_id,
                    evidence_id=resolved_evidence_id,
                    document_id=resolved_document_id,
                    processing_run_id=resolved_processing_run_id,
                    status="partial",
                    stage_statuses=stage_statuses,
                    input_file_name=resolved_file_name,
                    canonical_type_id=None,
                    canonical_type_source="none",
                    classification_status=classification_status,
                    parser_status=parser_status,
                    extraction_targets=[],
                    extraction_result=extraction_result,
                    warnings=warnings,
                    errors=errors,
                    created_at=created_at,
                    completed_at=self._clock(),
                )
                saved_run = self._persist_run_if_needed(run, persist_run)
                self._persist_extraction_result_if_needed(
                    extraction_result=extraction_result,
                    pipeline_run=saved_run,
                    canonical_type_id=canonical_type_id,
                    persist_run=persist_run,
                )
                return {
                    "pipeline_run": saved_run,
                    "parser_output": parser_output,
                    "classification_result": classification_result,
                    "extraction_targets": extraction_targets,
                    "extraction_result": extraction_result,
                }

            if extraction_targets:
                stage_statuses.target_plan = "completed"
            else:
                stage_statuses.target_plan = "partial"
                warnings.append(
                    "No extraction targets were generated for the resolved canonical type."
                )

            if extraction_targets:
                extraction_result = self._extraction_service.extract(
                    {
                        "parser_output": parser_output,
                        "extraction_targets": extraction_targets,
                        "evidence_id": resolved_evidence_id,
                    }
                )
                llm_candidates = self._run_llm_extraction(
                    parser_output=parser_output,
                    extraction_targets=extraction_targets,
                    evidence_id=resolved_evidence_id,
                    warnings=warnings,
                )
                if llm_candidates:
                    extraction_result = self._merge_llm_candidates(
                        extraction_result=extraction_result,
                        llm_candidates=llm_candidates,
                    )
                stage_statuses.candidate_generation = "completed"
                overall_status = "completed"
            else:
                stage_statuses.candidate_generation = "skipped"
                overall_status = "partial"

            run = self._build_pipeline_run(
                pipeline_run_id=resolved_pipeline_run_id,
                engagement_id=engagement_id,
                evidence_id=resolved_evidence_id,
                document_id=resolved_document_id,
                processing_run_id=resolved_processing_run_id,
                status=overall_status,
                stage_statuses=stage_statuses,
                input_file_name=resolved_file_name,
                canonical_type_id=canonical_type_id,
                canonical_type_source=canonical_type_source,
                classification_status=classification_status,
                parser_status=parser_status,
                extraction_targets=extraction_targets,
                extraction_result=extraction_result,
                warnings=warnings,
                errors=errors,
                created_at=created_at,
                completed_at=self._clock(),
            )
            saved_run = self._persist_run_if_needed(run, persist_run)
            self._persist_extraction_result_if_needed(
                extraction_result=extraction_result,
                pipeline_run=saved_run,
                canonical_type_id=canonical_type_id,
                persist_run=persist_run,
            )
            return {
                "pipeline_run": saved_run,
                "parser_output": parser_output,
                "classification_result": classification_result,
                "extraction_targets": extraction_targets,
                "extraction_result": extraction_result,
            }
        except Exception as exc:
            errors.append(f"Pipeline orchestration failed: {exc}")
            if stage_statuses.parse == "not_started":
                stage_statuses.parse = "failed"
            elif stage_statuses.classify == "not_started":
                stage_statuses.classify = "failed"
            elif stage_statuses.target_plan == "not_started":
                stage_statuses.target_plan = "failed"
            elif stage_statuses.candidate_generation == "not_started":
                stage_statuses.candidate_generation = "failed"

            run = self._build_pipeline_run(
                pipeline_run_id=resolved_pipeline_run_id,
                engagement_id=engagement_id,
                evidence_id=resolved_evidence_id,
                document_id=resolved_document_id,
                processing_run_id=resolved_processing_run_id,
                status="failed",
                stage_statuses=stage_statuses,
                input_file_name=resolved_file_name,
                canonical_type_id=canonical_type_id,
                canonical_type_source=canonical_type_source,
                classification_status=classification_status,
                parser_status=parser_status,
                extraction_targets=extraction_targets,
                extraction_result=extraction_result,
                warnings=warnings,
                errors=errors,
                created_at=created_at,
                completed_at=self._clock(),
            )
            saved_run = self._persist_run_if_needed(run, persist_run)
            self._persist_extraction_result_if_needed(
                extraction_result=extraction_result,
                pipeline_run=saved_run,
                canonical_type_id=canonical_type_id,
                persist_run=persist_run,
            )
            return {
                "pipeline_run": saved_run,
                "parser_output": parser_output,
                "classification_result": classification_result,
                "extraction_targets": extraction_targets,
                "extraction_result": extraction_result,
            }

    def get_pipeline_run(self, pipeline_run_id: str) -> dict | None:
        return self._pipeline_repository.get_by_id(pipeline_run_id)

    def get_latest_run_by_evidence(self, evidence_id: str) -> dict | None:
        return self._pipeline_repository.get_latest_by_evidence(evidence_id)

    def get_latest_extraction_result_by_document(self, document_id: str) -> dict | None:
        return self._extraction_result_repository.get_latest_by_document(document_id)

    def get_latest_extraction_result_by_evidence(self, evidence_id: str) -> dict | None:
        return self._extraction_result_repository.get_latest_by_evidence(evidence_id)

    def get_evidence_status(self, evidence_id: str) -> dict:
        latest_pipeline_run = self._pipeline_repository.get_latest_by_evidence(evidence_id)
        review_decisions = self._review_service.list_by_evidence(evidence_id)
        latest_approved_evidence = self._approved_evidence_service.get_latest_by_evidence(
            evidence_id
        )

        approved_field_count = 0
        review_status = "in_review"
        if latest_approved_evidence:
            approved_field_count = int(latest_approved_evidence.get("approved_field_count") or 0)
            review_status = str(latest_approved_evidence.get("review_status") or "in_review")

        return {
            "evidence_id": evidence_id,
            "latest_pipeline_run": latest_pipeline_run,
            "review_decision_count": len(review_decisions),
            "latest_approved_evidence": latest_approved_evidence,
            "approved_field_count": approved_field_count,
            "review_status": review_status,
        }

    @staticmethod
    def _parser_stage_status(parser_status: str | None) -> str:
        if parser_status == "parsed":
            return "completed"
        if parser_status in {"partial", "empty"}:
            return "partial"
        if parser_status == "failed":
            return "failed"
        return "partial"

    @staticmethod
    def _classification_stage_status(classification_status: str | None) -> str:
        if classification_status in {"classified", "multi_type_candidate", "low_confidence"}:
            return "completed"
        if classification_status in {"unclassified", None, ""}:
            return "partial"
        if classification_status == "failed":
            return "partial"
        return "partial"

    def _get_target_service(self):
        return self._target_service

    def _run_llm_extraction(
        self,
        *,
        parser_output: dict,
        extraction_targets: list[dict],
        evidence_id: str,
        warnings: list[str],
    ) -> list[dict]:
        service = self._llm_extraction_service
        try:
            if not service.is_enabled():
                return []
            return service.extract_candidates(
                parser_output=parser_output,
                extraction_targets=extraction_targets,
                evidence_id=evidence_id,
            )
        except Exception as exc:
            warnings.append(f"LLM structured extraction was skipped after failure: {type(exc).__name__}.")
            return []

    @staticmethod
    def _merge_llm_candidates(*, extraction_result: dict, llm_candidates: list[dict]) -> dict:
        merged = copy.deepcopy(extraction_result)
        existing_items = merged.get("items") or []
        if not isinstance(existing_items, list):
            existing_items = []

        llm_by_field = {
            str(candidate.get("field_name") or ""): candidate
            for candidate in llm_candidates
            if candidate.get("field_name")
        }
        next_items: list[dict] = []
        seen_fields: set[str] = set()
        for item in existing_items:
            field_name = str(item.get("field_name") or "")
            seen_fields.add(field_name)
            llm_item = llm_by_field.get(field_name)
            if llm_item and PipelineOrchestrationService._should_prefer_llm_candidate(item):
                next_items.append(llm_item)
            else:
                next_items.append(item)

        for field_name, llm_item in llm_by_field.items():
            if field_name not in seen_fields:
                next_items.append(llm_item)

        merged["items"] = next_items
        merged["candidate_count"] = len(next_items)
        return merged

    @staticmethod
    def _should_prefer_llm_candidate(candidate: dict) -> bool:
        flags = set(candidate.get("validation_flags") or [])
        value = candidate.get("normalized_value")
        if value is None or value == "":
            return True
        if "field_not_found" in flags or "unsupported_extraction_method" in flags:
            return True
        raw = str(candidate.get("raw_value") or "")
        return len(raw) > 220

    @staticmethod
    def _apply_s1_fallback_classification(
        *,
        classification_result: dict,
        parser_output: dict,
        file_name: str,
    ) -> dict:
        status = classification_result.get("status")
        if status in CLASSIFIER_TARGET_STATUSES:
            return classification_result

        text_parts = [file_name]
        for collection_name in ("pages", "text_blocks", "tables", "key_value_pairs"):
            collection = parser_output.get(collection_name) or []
            if not isinstance(collection, list):
                continue
            for item in collection:
                text_parts.append(str(item))
        search_text = " ".join(text_parts).lower()

        fallback_type: str | None = None
        if any(term in search_text for term in ("diesel", "gasoline", "gallon", "fuel ticket")):
            fallback_type = "CT-S1-MOBFUEL"
        elif any(term in search_text for term in ("shell", "natural gas", "therm", "utility bill", "fuel")):
            fallback_type = "CT-S1-FUELQTY"

        if fallback_type is None:
            return classification_result

        updated = copy.deepcopy(classification_result)
        updated.update(
            {
                "status": "classified",
                "primary_canonical_type_id": fallback_type,
                "primary_variant_id": "S1-FALLBACK-FUEL",
                "confidence": None,
                "threshold": None,
                "review_required": True,
                "notes": (
                    "Fallback S1 classifier selected a fuel evidence type from "
                    "filename/text terms after the vocabulary classifier did not meet threshold."
                ),
            }
        )
        updated["candidate_matches"] = [
            {
                "canonical_type_id": fallback_type,
                "variant_id": "S1-FALLBACK-FUEL",
                "confidence": None,
                "threshold": None,
                "matched_signals": {"fallback_terms": ["fuel evidence"]},
                "reason": "Fallback S1 fuel evidence match.",
                "review_required": True,
            }
        ]
        return updated

    def _persist_run_if_needed(self, run: dict, persist_run: bool) -> dict:
        if not persist_run:
            return copy.deepcopy(run)
        return self._pipeline_repository.save(run)

    def _persist_extraction_result_if_needed(
        self,
        *,
        extraction_result: dict,
        pipeline_run: dict,
        canonical_type_id: str | None,
        persist_run: bool,
    ) -> dict | None:
        if not persist_run:
            return None

        items = extraction_result.get("items") or []
        if not isinstance(items, list):
            items = []

        record = copy.deepcopy(extraction_result)
        record["pipeline_run_id"] = pipeline_run["pipeline_run_id"]
        record["engagement_id"] = pipeline_run["engagement_id"]
        record["evidence_id"] = pipeline_run["evidence_id"]
        record["document_id"] = pipeline_run["document_id"]
        record["canonical_type_id"] = canonical_type_id
        record["candidate_count"] = int(record.get("candidate_count") or len(items))
        record["items"] = items
        record["created_at"] = pipeline_run.get("completed_at") or pipeline_run.get("created_at")
        return self._extraction_result_repository.save(record)

    def _build_pipeline_run(
        self,
        *,
        pipeline_run_id: str,
        engagement_id: str,
        evidence_id: str,
        document_id: str,
        processing_run_id: str,
        status: str,
        stage_statuses: PipelineStageStatuses,
        input_file_name: str | None,
        canonical_type_id: str | None,
        canonical_type_source: str,
        classification_status: str | None,
        parser_status: str | None,
        extraction_targets: list[dict],
        extraction_result: dict,
        warnings: list[str],
        errors: list[str],
        created_at: str,
        completed_at: str,
    ) -> dict:
        items = extraction_result.get("items") or []
        if not isinstance(items, list):
            items = []

        candidate_count = int(extraction_result.get("candidate_count") or len(items))
        found_candidate_count = sum(1 for item in items if self._candidate_has_value(item))
        missing_candidate_count = max(candidate_count - found_candidate_count, 0)
        low_confidence_candidate_count = sum(
            1 for item in items if self._candidate_is_low_confidence(item)
        )

        model = PipelineRun(
            pipeline_run_id=pipeline_run_id,
            engagement_id=engagement_id,
            evidence_id=evidence_id,
            document_id=document_id,
            processing_run_id=processing_run_id,
            status=status,
            stage_statuses=PipelineStageStatuses(**stage_statuses.model_dump()),
            input_file_name=input_file_name,
            canonical_type_id=canonical_type_id,
            canonical_type_source=canonical_type_source,
            classification_status=classification_status,
            parser_status=parser_status,
            target_count=len(extraction_targets),
            candidate_count=candidate_count,
            found_candidate_count=found_candidate_count,
            missing_candidate_count=missing_candidate_count,
            low_confidence_candidate_count=low_confidence_candidate_count,
            warnings=[str(item) for item in warnings],
            errors=[str(item) for item in errors],
            created_at=created_at,
            completed_at=completed_at,
            artifacts={
                "parser_output_path": None,
                "candidate_output_path": None,
                "approved_evidence_id": None,
            },
        )
        return model.model_dump()

    @staticmethod
    def _candidate_has_value(candidate: Any) -> bool:
        if not isinstance(candidate, dict):
            return False
        value = candidate.get("normalized_value")
        if value is None:
            value = candidate.get("raw_value")
        if value is None:
            return False
        if isinstance(value, str):
            return bool(value.strip())
        return True

    @staticmethod
    def _candidate_is_low_confidence(candidate: Any) -> bool:
        if not isinstance(candidate, dict):
            return False
        confidence = candidate.get("confidence")
        try:
            value = float(confidence)
        except (TypeError, ValueError):
            return True
        return value < LOW_CONFIDENCE_THRESHOLD
