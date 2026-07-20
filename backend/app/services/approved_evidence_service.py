"""Approved evidence projection service (PR8)."""

from __future__ import annotations

import copy
from datetime import datetime, timezone
from typing import Any, Callable
from uuid import uuid4

from backend.app.domain.evidence import ApprovedEvidence, ApprovedEvidenceField
from backend.app.repositories.evidence_repository import (
    JsonlApprovedEvidenceRepository,
)
from backend.app.repositories.review_repository import (
    DEFAULT_JSONL_PATH as REVIEW_JSONL_PATH,
    JsonlReviewDecisionRepository,
)

REQUIRED_REVIEW_DECISION_FIELDS = (
    "review_decision_id",
    "candidate_id",
    "evidence_id",
    "document_id",
    "field_name",
    "decision",
    "reviewed_value",
    "reviewed_unit",
    "reviewer_id",
    "reviewed_at",
    "candidate_snapshot",
    "source_reference",
)

APPROVED_DECISIONS = {"accepted", "edited"}
NON_APPROVED_DECISIONS = {"rejected", "needs_more_evidence"}
VALID_DECISIONS = APPROVED_DECISIONS | NON_APPROVED_DECISIONS


class ApprovedEvidenceService:
    """Projects latest review decisions into downstream approved evidence."""

    def __init__(
        self,
        review_repository: Any | None = None,
        approved_repository: Any | None = None,
        clock: Callable[[], str] | None = None,
        id_factory: Callable[[str, str], str] | None = None,
    ) -> None:
        self._review_repository = review_repository or JsonlReviewDecisionRepository(
            REVIEW_JSONL_PATH
        )
        self._approved_repository = (
            approved_repository or JsonlApprovedEvidenceRepository()
        )
        self._clock = clock or (lambda: datetime.now(timezone.utc).isoformat())
        self._id_factory = id_factory or self._default_id_factory

    @staticmethod
    def _default_id_factory(engagement_id: str, evidence_id: str) -> str:
        return f"approved::{engagement_id}::{evidence_id}::{uuid4().hex[:12]}"

    def project_from_review_decisions(
        self,
        review_decisions: list[dict],
        engagement_id: str,
        evidence_type: str,
    ) -> dict:
        if not isinstance(review_decisions, list):
            raise ValueError("review_decisions must be a list of dictionaries.")
        if not engagement_id or not str(engagement_id).strip():
            raise ValueError("engagement_id is required.")
        if not evidence_type or not str(evidence_type).strip():
            raise ValueError("evidence_type is required.")

        decisions = [copy.deepcopy(item) for item in review_decisions]

        if not decisions:
            return self._approved_repository.save(
                self._build_aggregate(
                    evidence_id="evidence-unknown",
                    document_id="document-unknown",
                    engagement_id=engagement_id,
                    evidence_type=evidence_type,
                    latest_decisions=[],
                )
            )

        self._validate_decision_group(decisions)
        latest_decisions = self._latest_decision_per_field(decisions)
        return self._approved_repository.save(
            self._build_aggregate(
                evidence_id=latest_decisions[0]["evidence_id"],
                document_id=latest_decisions[0]["document_id"],
                engagement_id=engagement_id,
                evidence_type=evidence_type,
                latest_decisions=latest_decisions,
            )
        )

    def project_by_evidence(
        self,
        evidence_id: str,
        engagement_id: str,
        evidence_type: str,
    ) -> dict:
        decisions = self._review_repository.list_by_evidence(evidence_id)
        if not decisions:
            return self._approved_repository.save(
                self._build_aggregate(
                    evidence_id=evidence_id,
                    document_id="document-unknown",
                    engagement_id=engagement_id,
                    evidence_type=evidence_type,
                    latest_decisions=[],
                )
            )
        return self.project_from_review_decisions(
            review_decisions=decisions,
            engagement_id=engagement_id,
            evidence_type=evidence_type,
        )

    def list_by_engagement(self, engagement_id: str) -> list[dict]:
        return self._approved_repository.list_by_engagement(engagement_id)

    def get_latest_by_evidence(self, evidence_id: str) -> dict | None:
        return self._approved_repository.get_latest_by_evidence(evidence_id)

    def get_by_id(self, approved_evidence_id: str) -> dict | None:
        return self._approved_repository.get_by_id(approved_evidence_id)

    @staticmethod
    def _parse_reviewed_at(value: Any) -> datetime:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("reviewed_at must be a non-empty date-time string.")
        text = value.strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError as exc:  # pragma: no cover - error path covered by caller tests
            raise ValueError(f"Invalid reviewed_at timestamp: {value}") from exc
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed

    def _validate_one_decision(self, decision: Any) -> None:
        if not isinstance(decision, dict):
            raise ValueError("Each review decision must be a dictionary.")
        missing = [
            field
            for field in REQUIRED_REVIEW_DECISION_FIELDS
            if field not in decision
        ]
        if missing:
            raise ValueError(
                f"review_decision is missing required field(s): {missing}."
            )
        if decision["decision"] not in VALID_DECISIONS:
            raise ValueError(
                "review_decision.decision must be one of "
                f"{sorted(VALID_DECISIONS)}."
            )
        if not isinstance(decision.get("candidate_snapshot"), dict):
            raise ValueError("review_decision.candidate_snapshot must be an object.")
        if not isinstance(decision.get("source_reference"), dict):
            raise ValueError("review_decision.source_reference must be an object.")
        self._parse_reviewed_at(decision["reviewed_at"])

    def _validate_decision_group(self, decisions: list[dict]) -> None:
        for decision in decisions:
            self._validate_one_decision(decision)

        evidence_ids = {d["evidence_id"] for d in decisions}
        if len(evidence_ids) != 1:
            raise ValueError(
                "All review decisions in one projection must have the same evidence_id."
            )

        document_ids = {d["document_id"] for d in decisions}
        if len(document_ids) != 1:
            raise ValueError(
                "All review decisions in one projection must have the same document_id."
            )

    def _latest_decision_per_field(self, decisions: list[dict]) -> list[dict]:
        latest_by_field: dict[str, tuple[datetime, int, dict]] = {}

        for index, decision in enumerate(decisions):
            field_name = str(decision["field_name"])
            reviewed_at = self._parse_reviewed_at(decision["reviewed_at"])

            previous = latest_by_field.get(field_name)
            if (
                previous is None
                or reviewed_at > previous[0]
                or (reviewed_at == previous[0] and index > previous[1])
            ):
                latest_by_field[field_name] = (reviewed_at, index, copy.deepcopy(decision))

        ordered = sorted(latest_by_field.values(), key=lambda item: item[1])
        return [copy.deepcopy(item[2]) for item in ordered]

    def _build_aggregate(
        self,
        evidence_id: str,
        document_id: str,
        engagement_id: str,
        evidence_type: str,
        latest_decisions: list[dict],
    ) -> dict:
        approved_fields: list[ApprovedEvidenceField] = []
        source_ids: list[str] = []

        for decision in latest_decisions:
            source_ids.append(decision["review_decision_id"])

            if decision["decision"] not in APPROVED_DECISIONS:
                continue

            snapshot = decision.get("candidate_snapshot") or {}
            validation_flags = snapshot.get("validation_flags")
            if not isinstance(validation_flags, list):
                validation_flags = []

            approved_fields.append(
                ApprovedEvidenceField(
                    field_name=decision["field_name"],
                    display_label=str(
                        snapshot.get("display_label") or decision["field_name"]
                    ),
                    extracted_value=snapshot.get("raw_value"),
                    approved_value=decision.get("reviewed_value"),
                    approved_unit=decision.get("reviewed_unit"),
                    decision=decision["decision"],
                    source_reference=copy.deepcopy(decision["source_reference"]),
                    review_decision_id=decision["review_decision_id"],
                    candidate_id=decision["candidate_id"],
                    reviewer_id=decision["reviewer_id"],
                    reviewed_at=decision["reviewed_at"],
                    confidence=snapshot.get("confidence"),
                    validation_flags=[str(flag) for flag in validation_flags],
                )
            )

        field_count = len(latest_decisions)
        approved_field_count = len(approved_fields)

        if not latest_decisions:
            review_status = "in_review"
        elif approved_field_count == 0:
            review_status = "no_approved_fields"
        elif approved_field_count == field_count:
            review_status = "approved"
        else:
            review_status = "partially_approved"

        aggregate = ApprovedEvidence(
            approved_evidence_id=self._id_factory(engagement_id, evidence_id),
            evidence_id=evidence_id,
            engagement_id=engagement_id,
            document_id=document_id,
            evidence_type=evidence_type,
            review_status=review_status,
            field_count=field_count,
            approved_field_count=approved_field_count,
            fields=approved_fields,
            created_at=self._clock(),
            source_review_decision_ids=source_ids,
        )
        return aggregate.model_dump()
