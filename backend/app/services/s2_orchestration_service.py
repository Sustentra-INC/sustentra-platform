"""Subsystem 2 backend orchestration smoke runtime for PR14."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable
from uuid import NAMESPACE_URL, uuid5

from backend.app.reference.approved_evidence_mapping_loader import (
    load_default_approved_evidence_mappings,
)
from backend.app.reference.methodology_loader import load_default_methodology_bundle
from backend.app.reference.verification_rule_loader import load_verification_rules
from backend.app.services.approved_evidence_mapping_service import (
    ApprovedEvidenceMappingService,
)
from backend.app.services.completeness_tracker_service import CompletenessTrackerService
from backend.app.services.condition_evaluator import ConditionEvaluator
from backend.app.services.derivation_service import DerivationService
from backend.app.services.methodology_registry_service import MethodologyRegistryService
from backend.app.services.methodology_value_service import MethodologyValueService
from backend.app.services.s2_gap_record_service import S2GapRecordService
from backend.app.services.verification_engine_service import VerificationEngineService


class S2OrchestrationService:
    """Coordinates the PR5-PR13 S2 backend services for one approved evidence set."""

    def __init__(
        self,
        *,
        methodology_value_service: MethodologyValueService,
        completeness_tracker: CompletenessTrackerService,
        derivation_service: DerivationService,
        verification_engine: VerificationEngineService,
        verification_rules: tuple,
        gap_record_service: S2GapRecordService,
        clock: Callable[[], str] | None = None,
    ) -> None:
        self._methodology_value_service = methodology_value_service
        self._completeness_tracker = completeness_tracker
        self._derivation_service = derivation_service
        self._verification_engine = verification_engine
        self._verification_rules = verification_rules
        self._gap_record_service = gap_record_service
        self._clock = clock or (lambda: datetime.now(timezone.utc).isoformat())

    def run(
        self,
        approved_evidence: dict,
        *,
        runtime_condition_values: dict[str, object] | None = None,
        persist_methodology_values: bool = False,
    ) -> dict:
        """Run the S2 methodology smoke flow for one ApprovedEvidence aggregate."""

        methodology_run_id = self._methodology_run_id(approved_evidence)
        generated_at = self._clock()

        projection = self._methodology_value_service.project_approved_evidence(
            approved_evidence,
            persist=persist_methodology_values,
        )
        engagement_id = str(projection["engagement_id"])
        methodology_values = projection["methodology_values"]
        condition_values = runtime_condition_values or _condition_values(methodology_values)

        completeness = self._completeness_tracker.evaluate(
            engagement_id=engagement_id,
            methodology_values=methodology_values,
            runtime_condition_values=condition_values,
        )
        derivations = self._derivation_service.derive_all(methodology_values)
        verification = self._verification_engine.evaluate(
            engagement_id=engagement_id,
            rules=self._verification_rules,
            methodology_values=methodology_values,
        )
        gap_records = [
            *self._gap_record_service.from_completeness_result(completeness),
            *self._gap_record_service.from_derivation_results(
                derivations,
                engagement_id=engagement_id,
            ),
            *self._gap_record_service.from_verification_result(
                verification,
                engagement_id=engagement_id,
            ),
        ]

        summary = {
            "methodology_run_id": methodology_run_id,
            "engagement_id": engagement_id,
            "field_value_count": len(methodology_values),
            "missing_required_count": _count_status(
                completeness,
                "missing_required",
            ),
            "not_applicable_count": _count_status(
                completeness,
                "not_applicable",
            )
            + _count_status(verification, "not_applicable"),
            "verification_result_count": len(verification["results"]),
            "gap_record_count": len(gap_records),
            "provisional_count": _count_status(
                completeness,
                "provisional_condition_unknown",
            )
            + _count_status(verification, "provisional"),
        }
        return {
            "methodology_run_id": methodology_run_id,
            "generated_at": generated_at,
            "summary": summary,
            "projection": projection,
            "completeness": completeness,
            "derivations": derivations,
            "verification": verification,
            "gap_records": gap_records,
        }

    @staticmethod
    def _methodology_run_id(approved_evidence: dict) -> str:
        raw_key = "::".join(
            [
                str(approved_evidence.get("engagement_id", "")),
                str(approved_evidence.get("approved_evidence_id", "")),
                str(approved_evidence.get("evidence_id", "")),
                str(approved_evidence.get("document_id", "")),
            ]
        )
        return f"methodology-run::{uuid5(NAMESPACE_URL, raw_key).hex}"


def build_default_s2_orchestration_service(
    *,
    clock: Callable[[], str] | None = None,
) -> S2OrchestrationService:
    """Build an orchestration service from checked-in methodology reference data."""

    bundle = load_default_methodology_bundle()
    registry = MethodologyRegistryService(bundle)
    mapping_service = ApprovedEvidenceMappingService(
        load_default_approved_evidence_mappings(),
        registry,
    )
    return S2OrchestrationService(
        methodology_value_service=MethodologyValueService(
            mapping_service,
            registry,
            clock=clock,
        ),
        completeness_tracker=CompletenessTrackerService(
            registry,
            ConditionEvaluator(),
        ),
        derivation_service=DerivationService(registry),
        verification_engine=VerificationEngineService(),
        verification_rules=load_verification_rules(bundle),
        gap_record_service=S2GapRecordService(clock=clock),
        clock=clock,
    )


def _condition_values(methodology_values: list[dict]) -> dict[str, object]:
    values: dict[str, object] = {}
    for value in methodology_values:
        field_id = value.get("methodology_field_id")
        approved_value = value.get("approved_value")
        if field_id and field_id not in values and approved_value is not None:
            values[str(field_id)] = approved_value
    return values


def _count_status(result: dict, status: str) -> int:
    return int((result.get("status_counts") or {}).get(status, 0))
