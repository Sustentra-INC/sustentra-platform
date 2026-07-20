"""Review decision service (PR7).

Turns an extraction candidate plus a reviewer action into a persisted
``review_decision`` record. Records the reviewer's action using
``reviewed_value`` / ``reviewed_unit``; it does not project approved evidence
(that is PR8). The input candidate is never mutated and no external service is
called.
"""

from __future__ import annotations

import copy
from datetime import datetime, timezone
from typing import Any, Callable
from uuid import uuid4

from backend.app.domain.review import ReviewDecision
from backend.app.repositories.review_repository import InMemoryReviewDecisionRepository

VALID_DECISIONS = {"accepted", "rejected", "edited", "needs_more_evidence"}

REQUIRED_CANDIDATE_FIELDS = (
    "candidate_id",
    "evidence_id",
    "document_id",
    "field_name",
    "display_label",
    "raw_value",
    "normalized_value",
    "unit",
    "confidence",
    "source_reference",
    "validation_flags",
)


class ReviewDecisionService:
    """Validates and persists reviewer decisions on extraction candidates."""

    def __init__(
        self,
        repository: Any | None = None,
        clock: Callable[[], str] | None = None,
        id_factory: Callable[[dict], str] | None = None,
    ) -> None:
        self._repository = repository or InMemoryReviewDecisionRepository()
        self._clock = clock or (lambda: datetime.now(timezone.utc).isoformat())
        self._id_factory = id_factory or self._default_id_factory

    @staticmethod
    def _default_id_factory(candidate: dict) -> str:
        return f"review::{candidate.get('candidate_id')}::{uuid4().hex[:12]}"

    def submit_decision(
        self,
        candidate: dict,
        decision: str,
        reviewer_id: str,
        reviewed_value: str | float | int | bool | None = None,
        reviewed_unit: str | None = None,
        reviewer_note: str | None = None,
    ) -> dict:
        self._validate_candidate(candidate)

        if decision not in VALID_DECISIONS:
            raise ValueError(
                f"Invalid decision '{decision}'. Allowed: {sorted(VALID_DECISIONS)}."
            )
        if not reviewer_id or not str(reviewer_id).strip():
            raise ValueError("reviewer_id is required.")

        resolved_value, resolved_unit = self._resolve_value_unit(
            decision, candidate, reviewed_value, reviewed_unit
        )

        record = {
            "review_decision_id": self._id_factory(candidate),
            "candidate_id": candidate["candidate_id"],
            "evidence_id": candidate["evidence_id"],
            "document_id": candidate["document_id"],
            "field_name": candidate["field_name"],
            "decision": decision,
            "reviewed_value": resolved_value,
            "reviewed_unit": resolved_unit,
            "reviewer_id": reviewer_id,
            "reviewed_at": self._clock(),
            "reviewer_note": reviewer_note,
            "candidate_snapshot": copy.deepcopy(candidate),
            "source_reference": copy.deepcopy(candidate["source_reference"]),
        }

        # Validate against the strict domain model before persisting.
        model = ReviewDecision(**record)
        return self._repository.save(model.model_dump())

    def list_by_evidence(self, evidence_id: str) -> list[dict]:
        return self._repository.list_by_evidence(evidence_id)

    def list_by_document(self, document_id: str) -> list[dict]:
        return self._repository.list_by_document(document_id)

    def get_latest_by_candidate(self, candidate_id: str) -> dict | None:
        return self._repository.get_latest_by_candidate(candidate_id)

    def get_latest_by_field(self, evidence_id: str, field_name: str) -> dict | None:
        return self._repository.get_latest_by_field(evidence_id, field_name)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    @staticmethod
    def _validate_candidate(candidate: Any) -> None:
        if not isinstance(candidate, dict):
            raise ValueError("candidate must be a dictionary.")
        missing = [field for field in REQUIRED_CANDIDATE_FIELDS if field not in candidate]
        if missing:
            raise ValueError(f"candidate is missing required field(s): {missing}.")
        if not isinstance(candidate.get("source_reference"), dict):
            raise ValueError("candidate['source_reference'] must be an object.")

    @staticmethod
    def _resolve_value_unit(
        decision: str,
        candidate: dict,
        reviewed_value: Any,
        reviewed_unit: Any,
    ) -> tuple[Any, Any]:
        if decision == "accepted":
            expected_value = candidate["normalized_value"]
            expected_unit = candidate["unit"]
            if reviewed_value is not None and reviewed_value != expected_value:
                raise ValueError(
                    "accepted decision cannot change the value; use 'edited' instead."
                )
            if reviewed_unit is not None and reviewed_unit != expected_unit:
                raise ValueError(
                    "accepted decision cannot change the unit; use 'edited' instead."
                )
            return expected_value, expected_unit

        if decision == "edited":
            if reviewed_value is None:
                raise ValueError("edited decision requires a reviewed_value.")
            return reviewed_value, reviewed_unit

        # rejected / needs_more_evidence: no reviewed value or unit.
        if reviewed_value is not None or reviewed_unit is not None:
            raise ValueError(
                f"'{decision}' decision must not include reviewed_value or reviewed_unit."
            )
        return None, None
