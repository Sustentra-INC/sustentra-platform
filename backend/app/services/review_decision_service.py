"""Review decision service (PR7).

Turns an extraction candidate plus a reviewer action into a persisted
``review_decision`` record. Records the reviewer's action using
``reviewed_value`` / ``reviewed_unit``; it does not project approved evidence
(that is PR8). The input candidate is never mutated and no external service is
called.
"""

from __future__ import annotations

import copy
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable
from uuid import UUID, uuid4

from backend.app.domain.review import ReviewDecision
from backend.app.repositories.review_repository import InMemoryReviewDecisionRepository

logger = logging.getLogger("sustentra.review_audit")

VALID_DECISIONS = {"accepted", "rejected", "edited", "needs_more_evidence"}

# One audit event per decision written through the API. The Activity log screen labels these.
AUDIT_EVENT_TYPES = {
    "accepted": "review_value_accepted",
    "edited": "review_value_edited",
    "rejected": "review_value_rejected",
    "needs_more_evidence": "review_value_more_evidence_requested",
}


@dataclass(frozen=True)
class AuditContext:
    """Who made a decision and where, for its audit event. Ids only: the event never carries the
    value, unit, note or a file name."""

    org_id: str | None
    actor_user_id: UUID | None
    actor_role: str | None
    engagement_id: str | None = None
    pipeline_run_id: str | None = None
    request_id: str | None = None
    ip_address: str | None = None
    user_agent: str | None = None


def audit_event_for(record: dict, context: AuditContext) -> dict[str, Any]:
    """Keyword arguments of ``write_audit_event_sync`` for a saved decision's record."""

    ids = {
        "review_decision_id": record["review_decision_id"],
        "candidate_id": record["candidate_id"],
        "field_name": record["field_name"],
        "document_id": record["document_id"],
        "evidence_id": record["evidence_id"],
        "engagement_id": context.engagement_id,
        "pipeline_run_id": context.pipeline_run_id,
        "decision": record["decision"],
    }
    return {
        "event_type": AUDIT_EVENT_TYPES[record["decision"]],
        "org_id": context.org_id,
        "actor_user_id": context.actor_user_id,
        "actor_role": context.actor_role,
        "target_type": "engagement" if context.engagement_id else "document",
        "target_id": context.engagement_id or record["document_id"],
        "request_id": context.request_id,
        "ip_address": context.ip_address,
        "user_agent": context.user_agent,
        "metadata": {k: v for k, v in ids.items() if v is not None},
    }

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
        audit_writer: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self._repository = repository or InMemoryReviewDecisionRepository()
        self._clock = clock or (lambda: datetime.now(timezone.utc).isoformat())
        self._id_factory = id_factory or self._default_id_factory
        # Writes an audit event on its own, for repositories that cannot write it in the decision's
        # transaction (the files). Raising is allowed: the failure is logged, never silent.
        self._audit_writer = audit_writer

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
        org_id: str | None = None,
        audit: AuditContext | None = None,
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
            "org_id": org_id,
        }

        # Validate against the strict domain model before persisting.
        model = ReviewDecision(**record)
        data = model.model_dump()
        if audit is None:
            return self._repository.save(data)
        event = audit_event_for(data, audit)
        if getattr(self._repository, "audits_atomically", False):
            # Postgres: decision and event commit together; if either fails neither is saved and the
            # caller gets the error, so a decision is never reported as saved without its event.
            return self._repository.save(data, audit=event)
        # Files: the decision is saved first (it must never be lost or reported lost because of the
        # event), then the event. A failed event is logged as an error, with the ids to repair it.
        saved = self._repository.save(data)
        self._write_audit_after(saved, event)
        return saved

    def _write_audit_after(self, saved: dict, event: dict[str, Any]) -> None:
        try:
            if self._audit_writer is None:
                raise RuntimeError("no audit writer is configured")
            self._audit_writer(event)
        except Exception:
            logger.error(
                "Audit event %s missing for saved review decision %s (document %s, field %s)",
                event["event_type"], saved.get("review_decision_id"), saved.get("document_id"),
                saved.get("field_name"), exc_info=True,
            )

    def list_by_evidence(self, evidence_id: str) -> list[dict]:
        return self._repository.list_by_evidence(evidence_id)

    def list_by_document(self, document_id: str) -> list[dict]:
        return self._repository.list_by_document(document_id)

    def list_by_documents(self, document_ids: list[str]) -> dict[str, list[dict]]:
        """The decisions of many documents in one read: oldest first, by document id (every id is a key)."""
        return self._repository.list_by_documents(document_ids)

    def engagement_stamp(self, engagement_id: str) -> str:
        """Changes whenever a review decision on the engagement's documents is added."""
        return self._repository.engagement_stamp(engagement_id)

    def list_by_candidate(self, candidate_id: str) -> list[dict]:
        return self._repository.list_by_candidate(candidate_id)

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
