from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

ReviewDecisionType = Literal[
    "accepted",
    "rejected",
    "edited",
    "needs_more_evidence",
]


class ReviewDecision(BaseModel):
    """A persisted reviewer decision on one extraction candidate (PR7).

    Records the reviewer's action using ``reviewed_value`` / ``reviewed_unit``.
    Approved evidence projection (``approved_value``) is intentionally deferred
    to PR8.
    """

    review_decision_id: str
    candidate_id: str
    evidence_id: str
    document_id: str
    field_name: str
    decision: ReviewDecisionType
    reviewed_value: str | float | int | bool | None = None
    reviewed_unit: str | None = None
    reviewer_id: str
    reviewed_at: str
    reviewer_note: str | None = None
    candidate_snapshot: dict
    source_reference: dict
