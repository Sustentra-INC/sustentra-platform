from __future__ import annotations

import copy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, cast
from uuid import uuid4

from backend.app.domain.pipeline import (
    CanonicalTypeSource,
    HaltReason,
    PipelineRun,
    PipelineStageStatus,
    PipelineStageStatuses,
    PipelineStatus,
)
from backend.app.repositories import s1_stores
from backend.app.repositories.extraction_result_repository import InMemoryExtractionResultRepository
from backend.app.services.approved_evidence_service import ApprovedEvidenceService
from backend.app.services.classification_service import ClassificationService
from backend.app.services.electricity_extractor import (
    CANONICAL_TYPE_ID as ELEC_TYPE_ID,
)
from backend.app.services.electricity_extractor import (
    ElectricityExtractor,
)
from backend.app.services.extraction_service import ExtractionService
from backend.app.services.thermal_extractor import CANONICAL_TYPE_ID as THERMAL_TYPE_ID
from backend.app.services.thermal_extractor import ThermalExtractor
from backend.app.services.extraction_target_service import ExtractionTargetService
from backend.app.adapters.parsers.email_parser import PARSER_NAME as EMAIL_PARSER_NAME
from backend.app.adapters.parsers.email_reader import ENCRYPTED_EMAIL
from backend.app.services.parser_service import ParserService
from backend.app.services.mobile_combustion_extractor import (
    CANONICAL_TYPE_ID as MOBFUEL_TYPE_ID,
)
from backend.app.services.mobile_combustion_extractor import (
    MobileCombustionExtractor,
    fuel_use_cues,
    names_combusted_fuel,
)
from backend.app.services.refrigerant_extractor import (
    CANONICAL_TYPE_ID as REFRIGERANT_TYPE_ID,
)
from backend.app.services.refrigerant_extractor import (
    RefrigerantServiceExtractor,
)
from backend.app.services.review_decision_service import ReviewDecisionService
from backend.app.services.stationary_combustion_extractor import (
    CANONICAL_TYPE_ID as FUELQTY_TYPE_ID,
)
from backend.app.services.stationary_combustion_extractor import (
    StationaryCombustionExtractor,
)

CLASSIFIER_TARGET_STATUSES = {"classified", "multi_type_candidate"}
HALT_UNREADABLE = "unreadable_document"
# A photo or a scan without a text layer while OCR (Textract) is off: readable once it is on.
HALT_OCR_REQUIRED = "ocr_required"
# An encrypted file (a reader said ``password_protected``): readable once a copy without one arrives.
HALT_PASSWORD_PROTECTED = "password_protected"
PDF_PARSER_NAMES = {"pymupdf", "pdfplumber", "pdf_parser"}
HALT_UNSUPPORTED = "unsupported_document"
LOW_CONFIDENCE_THRESHOLD = 0.5
# EXT-001/002: a low-confidence Scope 1 fuel match (FUELQTY or MOBFUEL) is accepted when it is the classifier's
# best match overall, scores at least this much (two content signal groups, e.g. header
# terms + layout features), and the stationary-combustion content check passes (a
# combusted fuel is named and a quantity is stated in a non-electric fuel unit).
FUEL_CONTENT_CHECK_FLOOR = 0.4
FUEL_TYPE_IDS = {FUELQTY_TYPE_ID, MOBFUEL_TYPE_ID}
# Types read by a layout-aware extractor. Those extractors take one type's targets, so a
# multi-type candidate gets its primary type's targets only: mixing in a runner-up type's
# targets (e.g. a gas bill that also mentions electricity) would send it to the generic
# fallback, which reads labels without layout.
LAYOUT_EXTRACTOR_TYPE_IDS = FUEL_TYPE_IDS | {ELEC_TYPE_ID, REFRIGERANT_TYPE_ID, THERMAL_TYPE_ID}
# Fluorinated-gas types without an extractor of their own. A document classified as one of
# them that reads as a service record (a refrigerant named, an amount added or recovered)
# is read as CT-S1-REFRSVC: an equipment inventory or leak log with charges is still the
# refrigerant evidence the material balance needs.
FGAS_RELATED_TYPE_IDS = {"CT-S1-FGASINV", "CT-S1-EQUIPLEAK", "CT-S1-ELECSF6", "CT-S1-FGASPROC"}


class PipelineOrchestrationService:
    def __init__(
        self,
        parser_service: Any | None = None,
        classification_service: Any | None = None,
        target_service: Any | None = None,
        extraction_service: Any | None = None,
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

        self._review_service = review_service or ReviewDecisionService()
        self._approved_evidence_service = (
            approved_evidence_service or ApprovedEvidenceService()
        )
        self._pipeline_repository = pipeline_repository or s1_stores.pipeline_runs()
        # Persisted candidates for GET /documents/{id}/extraction-result/latest (S1-BE-001).
        # Follows the run store: S1_STORE's by default, in memory when a run repository is injected.
        if extraction_result_repository is None:
            extraction_result_repository = (
                s1_stores.extraction_results()
                if pipeline_repository is None
                else InMemoryExtractionResultRepository()
            )
        self._extraction_result_repository = extraction_result_repository

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
        org_id: str | None = None,
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
        halt_reason: dict[str, str] | None = None

        try:
            parser_output = self._parser_service.parse_document(
                file_path=str(path),
                document_id=resolved_document_id,
                processing_run_id=resolved_processing_run_id,
                mime_type=mime_type,
            )
            parser_status = str(parser_output.get("status") or "") or None
            stage_statuses.parse = self._parser_stage_status(parser_status)

            if parser_status == "failed" or (parser_status == "empty" and not canonical_type_id_override):
                halt_reason = self._unreadable_halt(parser_output)
                if parser_status == "failed":
                    errors.append("Parser stage returned failed status.")
                else:
                    stage_statuses.classify = "skipped"
                    stage_statuses.target_plan = "skipped"
                    stage_statuses.candidate_generation = "skipped"
                warnings.append(halt_reason["message"])
                run = self._build_pipeline_run(
                    pipeline_run_id=resolved_pipeline_run_id,
                    engagement_id=engagement_id,
                    evidence_id=resolved_evidence_id,
                    document_id=resolved_document_id,
                    processing_run_id=resolved_processing_run_id,
                    status="failed" if parser_status == "failed" else "partial",
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
                    halt_reason=halt_reason,
                )
                saved_run = self._persist_if_needed({**run, "org_id": org_id}, persist_run, extraction_result)
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
                    mobile_cues, stationary_cues = fuel_use_cues(parser_output)
                    if self._fuel_cues_conflict(canonical_type_id, mobile_cues, stationary_cues):
                        other = "mobile (vehicles/fleet)" if canonical_type_id == FUELQTY_TYPE_ID else "stationary"
                        cues = ", ".join(mobile_cues if canonical_type_id == FUELQTY_TYPE_ID else stationary_cues)
                        other_type = MOBFUEL_TYPE_ID if canonical_type_id == FUELQTY_TYPE_ID else FUELQTY_TYPE_ID
                        other_extractor = (MobileCombustionExtractor() if other_type == MOBFUEL_TYPE_ID
                                           else StationaryCombustionExtractor())
                        if other_extractor.confirms(parser_output):
                            # The cues are one-sided and the other fuel type's content check
                            # passes: read it as that type (e.g. a diesel log for a standby
                            # generator that the classifier took for fleet fuel).
                            warnings.append(
                                f"The classifier chose {canonical_type_id}, but the document reads as {other} "
                                f"fuel use ({cues}); using {other_type}."
                            )
                            canonical_type_id = other_type
                            canonical_type_source = "content_check"
                            extraction_targets = self._get_target_service().get_targets_for_canonical_type(
                                canonical_type_id,
                                include_optional=include_optional,
                                include_deprecated=include_deprecated,
                            )
                        else:
                            halt_reason = {
                                "code": HALT_UNSUPPORTED,
                                "message": f"The classifier chose {canonical_type_id}, but the document reads as "
                                f"{other} fuel use ({cues}). Set the document type manually.",
                            }
                            warnings.append(halt_reason["message"])
                            canonical_type_id = None
                            canonical_type_source = "none"
                if canonical_type_id is not None and canonical_type_source == "classifier":
                    if self._electricity_reroute(canonical_type_id, parser_output):
                        warnings.append(
                            f"The classifier chose {canonical_type_id}, but the document's quantities are "
                            f"electricity (kWh/MWh) and it names no combusted fuel; using {ELEC_TYPE_ID} "
                            "(purchased electricity, Scope 2)."
                        )
                        canonical_type_id = ELEC_TYPE_ID
                        canonical_type_source = "content_check"
                        extraction_targets = self._get_target_service().get_targets_for_canonical_type(
                            canonical_type_id,
                            include_optional=include_optional,
                            include_deprecated=include_deprecated,
                        )
                    elif self._thermal_reroute(canonical_type_id, parser_output):
                        warnings.append(
                            f"The classifier chose {canonical_type_id}, but the document is a steam, hot water or "
                            f"chilled water bill and names no combusted fuel; using {THERMAL_TYPE_ID} (purchased "
                            "steam, heat or cooling, Scope 2)."
                        )
                        canonical_type_id = THERMAL_TYPE_ID
                        canonical_type_source = "content_check"
                        extraction_targets = self._get_target_service().get_targets_for_canonical_type(
                            canonical_type_id,
                            include_optional=include_optional,
                            include_deprecated=include_deprecated,
                        )
                    elif (canonical_type_id in FGAS_RELATED_TYPE_IDS
                          and RefrigerantServiceExtractor().confirms(parser_output)):
                        warnings.append(
                            f"The classifier chose {canonical_type_id}; the document names a refrigerant and an "
                            f"amount added or recovered, so it is read as {REFRIGERANT_TYPE_ID} (refrigerant "
                            "service record)."
                        )
                        canonical_type_id = REFRIGERANT_TYPE_ID
                        canonical_type_source = "content_check"
                        extraction_targets = self._get_target_service().get_targets_for_canonical_type(
                            canonical_type_id,
                            include_optional=include_optional,
                            include_deprecated=include_deprecated,
                        )
                    elif canonical_type_id in LAYOUT_EXTRACTOR_TYPE_IDS:
                        extraction_targets = self._get_target_service().get_targets_for_canonical_type(
                            canonical_type_id,
                            include_optional=include_optional,
                            include_deprecated=include_deprecated,
                        )
                    else:
                        extraction_targets = (
                            self._get_target_service().get_targets_for_classification_result(
                                classification_result,
                                include_optional=include_optional,
                                include_deprecated=include_deprecated,
                            )
                        )
                elif canonical_type_id is not None and canonical_type_source == "content_check":
                    pass  # read as the other fuel type above; its targets are already planned
                elif (
                    confirmed := self._fuel_content_confirmed(classification_result, parser_output)
                    or self._electricity_content_confirmed(classification_result, parser_output)
                    or self._refrigerant_content_confirmed(classification_result, parser_output)
                    or self._thermal_content_confirmed(classification_result, parser_output)
                ):
                    canonical_type_id = confirmed
                    canonical_type_source = "content_check"
                    extraction_targets = self._get_target_service().get_targets_for_canonical_type(
                        canonical_type_id,
                        include_optional=include_optional,
                        include_deprecated=include_deprecated,
                    )
                    if confirmed == ELEC_TYPE_ID:
                        reason = "names electricity and a quantity in kWh or MWh."
                    elif confirmed == REFRIGERANT_TYPE_ID:
                        reason = "names a refrigerant and an amount added or recovered."
                    elif confirmed == THERMAL_TYPE_ID:
                        reason = "names steam, hot water or chilled water and a thermal quantity."
                    elif confirmed == MOBFUEL_TYPE_ID:
                        reason = "names a combusted fuel and a quantity in a fuel unit with vehicle/fleet details."
                    else:
                        reason = "names a combusted fuel and a quantity in a fuel unit."
                    warnings.append(
                        f"Classifier confidence {float(classification_result.get('confidence') or 0):.2f} was below "
                        f"its threshold; accepted {confirmed} because the document {reason}"
                    )
                else:
                    canonical_type_id = None
                    canonical_type_source = "none"
                    warnings.append(
                        "No confident canonical_type_id available; target planning and candidate generation were skipped."
                    )
                    if halt_reason is None:
                        halt_reason = self._unsupported_halt(classification_result, parser_output)
                        warnings.append(halt_reason["message"])

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
                    halt_reason=halt_reason,
                )
                saved_run = self._persist_if_needed({**run, "org_id": org_id}, persist_run, extraction_result)
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
                stage_statuses.candidate_generation = "completed"
                overall_status = "completed"
                if extraction_result.get("halt_reason"):
                    halt_reason = dict(extraction_result["halt_reason"])
                    stage_statuses.candidate_generation = "skipped"
                    overall_status = "partial"
                    warnings.append(halt_reason["message"])
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
                halt_reason=halt_reason,
            )
            saved_run = self._persist_if_needed({**run, "org_id": org_id}, persist_run, extraction_result)
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
            saved_run = self._persist_if_needed({**run, "org_id": org_id}, persist_run, extraction_result)
            return {
                "pipeline_run": saved_run,
                "parser_output": parser_output,
                "classification_result": classification_result,
                "extraction_targets": extraction_targets,
                "extraction_result": extraction_result,
            }

    def get_pipeline_run(self, pipeline_run_id: str) -> dict | None:
        return self._pipeline_repository.get_by_id(pipeline_run_id)

    def list_runs_by_evidence(self, evidence_id: str) -> list[dict]:
        return self._pipeline_repository.list_by_evidence(evidence_id)

    def get_latest_run_by_evidence(self, evidence_id: str) -> dict | None:
        return self._pipeline_repository.get_latest_by_evidence(evidence_id)

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
    def _fuel_content_confirmed(classification_result: dict, parser_output: dict) -> str | None:
        """Scope 1 fuel type to accept for a low-confidence classification, or None.

        A fuel type must be the best match overall (ties with non-fuel types are settled
        by its content check, which rejects electricity) and score at least the floor.
        When stationary and mobile tie, explicit context decides (vehicle/fleet/fuel-card
        cues vs boiler/generator/building cues); without one-sided cues nothing is
        accepted. The chosen type must not contradict the cues and must pass its
        extractor's content check.
        """

        if classification_result.get("status") != "low_confidence":
            return None
        matches = [m for m in classification_result.get("candidate_matches") or [] if isinstance(m, dict)]
        if not matches:
            return None
        best = max(float(m.get("confidence") or 0) for m in matches)
        leaders = {m.get("canonical_type_id") for m in matches if float(m.get("confidence") or 0) == best}
        fuel_leaders = leaders & FUEL_TYPE_IDS
        if not fuel_leaders or best < FUEL_CONTENT_CHECK_FLOOR:
            return None
        mobile, stationary = fuel_use_cues(parser_output)
        fuel_type: str
        if len(fuel_leaders) > 1:
            if mobile and not stationary:
                fuel_type = MOBFUEL_TYPE_ID
            elif stationary and not mobile:
                fuel_type = FUELQTY_TYPE_ID
            else:
                return None
        else:
            fuel_type = str(next(iter(fuel_leaders)))
        if PipelineOrchestrationService._fuel_cues_conflict(fuel_type, mobile, stationary):
            return None
        extractor = StationaryCombustionExtractor() if fuel_type == FUELQTY_TYPE_ID else MobileCombustionExtractor()
        return fuel_type if extractor.confirms(parser_output) else None

    @staticmethod
    def _electricity_reroute(canonical_type_id: str | None, parser_output: dict) -> bool:
        """True when a document classified as a stationary fuel bill is really an electricity bill.

        Gas and electric bills share most header vocabulary (account number, service
        address, billing period, usage), so the classifier can pick CT-S1-FUELQTY for an
        electricity bill. The unit decides: kWh/MWh quantities with no combusted fuel
        named mean purchased electricity (Scope 2). Mobile fuel is left alone. A district
        heating or cooling bill in MWh is purchased heat, not electricity: the thermal check
        takes it (and declines any bill that names electricity in words).
        """

        if canonical_type_id != FUELQTY_TYPE_ID:
            return False
        if StationaryCombustionExtractor().confirms(parser_output) or ThermalExtractor().confirms(parser_output):
            return False
        return ElectricityExtractor().confirms(parser_output)

    @staticmethod
    def _thermal_reroute(canonical_type_id: str | None, parser_output: dict) -> bool:
        """True when a document classified as a utility bill (fuel or electricity) is really a
        steam, hot water or chilled water bill: it names one, states a thermal quantity, and
        names neither a combusted fuel nor electricity in words. Heat billed in MWh counts:
        the unit alone does not make it electricity."""

        if canonical_type_id not in (FUELQTY_TYPE_ID, ELEC_TYPE_ID):
            return False
        return ThermalExtractor().confirms(parser_output)

    @staticmethod
    def _utility_guess(classification_result: dict, parser_output: dict, types: set[str]) -> bool:
        """True when a low-confidence classification leads with one of ``types``, or with
        vehicle fuel on a document that does not read as a fleet log. A sparse bill (a phone
        photo with a kWh total and a period) matches vehicle-fuel vocabulary ("period")
        as well as anything, so the weak guess must not keep a utility bill from its check."""

        if classification_result.get("status") != "low_confidence":
            return False
        matches = [m for m in classification_result.get("candidate_matches") or [] if isinstance(m, dict)]
        if not matches:
            return False
        best = max(float(m.get("confidence") or 0) for m in matches)
        if best < FUEL_CONTENT_CHECK_FLOOR:
            return False
        leaders = {m.get("canonical_type_id") for m in matches if float(m.get("confidence") or 0) == best}
        if leaders & types:
            return True
        return MOBFUEL_TYPE_ID in leaders and not MobileCombustionExtractor().confirms(parser_output)

    @staticmethod
    def _thermal_content_confirmed(classification_result: dict, parser_output: dict) -> str | None:
        """CT-S2-THERMAL for a low-confidence classification whose best match is a utility-bill
        type, when the document is a steam, hot water or chilled water bill."""

        if not PipelineOrchestrationService._utility_guess(
            classification_result, parser_output, {FUELQTY_TYPE_ID, ELEC_TYPE_ID, THERMAL_TYPE_ID}
        ):
            return None
        return THERMAL_TYPE_ID if ThermalExtractor().confirms(parser_output) else None

    @staticmethod
    def _electricity_content_confirmed(classification_result: dict, parser_output: dict) -> str | None:
        """CT-S2-ELEC for a low-confidence classification whose best match is a utility-bill
        type (stationary fuel or electricity), when the document's quantities are
        electricity and no combusted fuel is named."""

        if not PipelineOrchestrationService._utility_guess(classification_result, parser_output, {FUELQTY_TYPE_ID, ELEC_TYPE_ID}):
            return None
        if StationaryCombustionExtractor().confirms(parser_output) or ThermalExtractor().confirms(parser_output):
            return None
        return ELEC_TYPE_ID if ElectricityExtractor().confirms(parser_output) else None

    @staticmethod
    def _refrigerant_content_confirmed(classification_result: dict, parser_output: dict) -> str | None:
        """CT-S1-REFRSVC for a low-confidence classification whose best match is a
        fluorinated-gas type, when the document names a refrigerant and an amount."""

        if classification_result.get("status") != "low_confidence":
            return None
        matches = [m for m in classification_result.get("candidate_matches") or [] if isinstance(m, dict)]
        if not matches:
            return None
        best = max(float(m.get("confidence") or 0) for m in matches)
        leaders = {m.get("canonical_type_id") for m in matches if float(m.get("confidence") or 0) == best}
        if not leaders & (FGAS_RELATED_TYPE_IDS | {REFRIGERANT_TYPE_ID}) or best < FUEL_CONTENT_CHECK_FLOOR:
            return None
        return REFRIGERANT_TYPE_ID if RefrigerantServiceExtractor().confirms(parser_output) else None

    @staticmethod
    def _fuel_cues_conflict(fuel_type: str, mobile: list[str], stationary: list[str]) -> bool:
        """True when the document's context clearly says the other kind of fuel use."""

        if fuel_type == FUELQTY_TYPE_ID:
            return bool(mobile) and not stationary
        if fuel_type == MOBFUEL_TYPE_ID:
            return bool(stationary) and not mobile
        return False

    @staticmethod
    def _unreadable_halt(parser_output: dict) -> dict[str, str]:
        details = "; ".join(
            str(w.get("message")) for w in (parser_output.get("warnings") or []) if isinstance(w, dict) and w.get("message")
        )
        message = (
            "Unreadable document: no text could be extracted (for example a scan without a text layer "
            "while OCR is off, a password-protected or corrupt file)."
        )
        codes = {str(w.get("code")) for w in (parser_output.get("warnings") or []) if isinstance(w, dict)}
        if "password_protected" in codes:
            if parser_output.get("parser_name") == EMAIL_PARSER_NAME:
                return {"code": HALT_PASSWORD_PROTECTED, "message": ENCRYPTED_EMAIL}
            return {"code": HALT_PASSWORD_PROTECTED,
                    "message": "This file is password-protected, so it could not be read. Ask the client for "
                               "a copy without a password."}
        scanned_pdf = "empty_page_text" in codes and parser_output.get("parser_name") in PDF_PARSER_NAMES
        if ("ocr_not_implemented" in codes or scanned_pdf) and not ParserService._textract_enabled():
            return {"code": HALT_OCR_REQUIRED,
                    "message": "This is a photo or a scan without a text layer. Its text can be read once OCR "
                               "(Textract) is switched on; until then, ask for a text PDF or the original file."}
        return {"code": HALT_UNREADABLE, "message": f"{message} Parser said: {details}" if details else message}

    @staticmethod
    def _unsupported_halt(classification_result: dict, parser_output: dict | None = None) -> dict[str, str]:
        primary = classification_result.get("primary_canonical_type_id")
        confidence = classification_result.get("confidence")
        threshold = classification_result.get("threshold")
        if primary and confidence is not None and threshold is not None:
            message = (
                f"Unsupported document type: the closest match was {primary} with confidence "
                f"{float(confidence):.2f}, below the {float(threshold):.2f} needed to extract automatically. "
                "Set the document type manually if it is a supported type."
            )
        else:
            message = "Unsupported document type: it does not match any known evidence type."
        fuel_matches = {
            m.get("canonical_type_id") for m in classification_result.get("candidate_matches") or []
            if isinstance(m, dict) and m.get("canonical_type_id") in FUEL_TYPE_IDS
        }
        if fuel_matches and parser_output is not None and names_combusted_fuel(parser_output):
            mobile, stationary = fuel_use_cues(parser_output)
            if mobile and stationary:
                message += f" It mentions both mobile ({', '.join(mobile)}) and stationary ({', '.join(stationary)}) fuel use."
            elif mobile:
                message += f" It reads as mobile fuel use ({', '.join(mobile)}): CT-S1-MOBFUEL is likely."
            elif stationary:
                message += f" It reads as stationary fuel use ({', '.join(stationary)}): CT-S1-FUELQTY is likely."
            else:
                message += " It names a fuel but nothing says whether it was burned in vehicles or on site."
        return {"code": HALT_UNSUPPORTED, "message": message}

    @staticmethod
    def _parser_stage_status(parser_status: str | None) -> PipelineStageStatus:
        if parser_status == "parsed":
            return "completed"
        if parser_status in {"partial", "empty"}:
            return "partial"
        if parser_status == "failed":
            return "failed"
        return "partial"

    @staticmethod
    def _classification_stage_status(classification_status: str | None) -> PipelineStageStatus:
        if classification_status in {"classified", "multi_type_candidate", "low_confidence"}:
            return "completed"
        if classification_status in {"unclassified", None, ""}:
            return "partial"
        if classification_status == "failed":
            return "partial"
        return "partial"

    def _get_target_service(self):
        return self._target_service

    def _persist_if_needed(self, run: dict, persist_run: bool, extraction_result: dict | None = None) -> dict:
        if not persist_run:
            return copy.deepcopy(run)
        saved = self._pipeline_repository.save(run)
        if extraction_result is not None:
            self._extraction_result_repository.save(
                {
                    "pipeline_run_id": run.get("pipeline_run_id"),
                    "engagement_id": run.get("engagement_id"),
                    "evidence_id": run.get("evidence_id"),
                    "document_id": run.get("document_id"),
                    "canonical_type_id": run.get("canonical_type_id"),
                    "status": run.get("status"),
                    "candidate_count": int(extraction_result.get("candidate_count") or 0),
                    "items": copy.deepcopy(extraction_result.get("items") or []),
                    "org_id": run.get("org_id"),
                    "created_at": run.get("completed_at") or run.get("created_at"),
                }
            )
        return saved

    def list_extraction_results_by_document(self, document_id: str) -> list[dict]:
        """Every persisted extraction result for a document, oldest first."""
        return self._extraction_result_repository.list_by_document(document_id)

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
        halt_reason: dict[str, str] | None = None,
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
            status=cast(PipelineStatus, status),
            stage_statuses=PipelineStageStatuses(**stage_statuses.model_dump()),
            input_file_name=input_file_name,
            canonical_type_id=canonical_type_id,
            canonical_type_source=cast(CanonicalTypeSource, canonical_type_source),
            classification_status=classification_status,
            parser_status=parser_status,
            target_count=len(extraction_targets),
            candidate_count=candidate_count,
            found_candidate_count=found_candidate_count,
            missing_candidate_count=missing_candidate_count,
            low_confidence_candidate_count=low_confidence_candidate_count,
            warnings=[str(item) for item in warnings],
            errors=[str(item) for item in errors],
            halt_reason=HaltReason(**halt_reason) if halt_reason else None,
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
            value = float(confidence)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return True
        return value < LOW_CONFIDENCE_THRESHOLD
