"""Escalations (intake Stage 2, Phase C1).

Opens and resolves the records behind an ``escalated`` datapoint. Phase D adds
the reviewer queue screen and the email pipeline on top; nothing here sends mail.

Per intake/SPEC.md section 3, an escalation carries what a reviewer needs to
answer without digging: the question, what the client tried, and the seed-form
context. Resolution is written back into the profile as the data point's answer,
attributed to the team - never silently discarded.

An escalation blocks only what depends on it. It never stops the interview; that
is a question-selection concern handled in Phase C2.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from intake.backend.domain.escalation import Escalation, EscalationAuditEntry
from intake.backend.repositories.datapoint_state_repository import DatapointStateRepository
from intake.backend.repositories.escalation_repository import EscalationRepository
from intake.backend.services.state_machine import StateMachine


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class EscalationError(Exception):
    """Raised when an escalation cannot be opened or resolved."""


class EscalationService:
    def __init__(
        self,
        escalation_repository: EscalationRepository,
        state_repository: DatapointStateRepository,
        state_machine: StateMachine,
        clock: Callable[[], datetime] = _utcnow,
    ) -> None:
        self._escalations = escalation_repository
        self._states = state_repository
        self._machine = state_machine
        self._clock = clock

    def open(
        self,
        org_id: str,
        datapoint_id: str,
        scope_ref: str | None,
        trigger: str,
        question_label: str,
        actor_id: str,
        answer_attempts: list[dict] | None = None,
        seed_context: dict | None = None,
    ) -> dict[str, Any]:
        """Escalate a data point, or return the escalation already open for it."""
        existing = self._escalations.find_open_for_datapoint(org_id, datapoint_id, scope_ref)
        if existing is not None:
            return existing

        state = self._states.find(org_id, datapoint_id, scope_ref)
        if state is None:
            raise EscalationError(
                f"No state for {datapoint_id} (scope {scope_ref!r}) in {org_id}."
            )

        now = self._clock().isoformat()
        escalation = Escalation(
            escalation_id=f"esc_{uuid.uuid4().hex[:12]}",
            org_id=org_id,
            datapoint_id=datapoint_id,
            scope_ref=scope_ref,
            title=question_label,
            trigger=trigger,  # type: ignore[arg-type]
            detection_origin=(
                "user_requested" if trigger == "user_requested_help" else "system_detected"
            ),
            question_label=question_label,
            answer_attempts=answer_attempts or [],
            seed_context=seed_context or {},
            created_by=actor_id,
            created_at=now,
            updated_at=now,
            audit_trail=[
                EscalationAuditEntry(at=now, actor_id=actor_id, action="opened", note=trigger)
            ],
        )
        record = self._escalations.save(escalation)

        if state["status"] == "unasked":
            state = self._machine.mark_asked(state, actor_id=actor_id)
        self._machine.transition(
            state,
            "escalated",
            actor_id=actor_id,
            escalation_id=escalation.escalation_id,
            reason=f"escalated: {trigger}",
        )
        return record

    def resolve(
        self,
        escalation_id: str,
        value: dict,
        actor_id: str,
        resolution_note: str | None = None,
    ) -> dict[str, Any]:
        """Reviewer resolution: write the answer into the profile as resolved_by_team."""
        escalation = self._escalations.get(escalation_id)
        if escalation is None:
            raise EscalationError(f"Unknown escalation {escalation_id}.")
        if escalation["status"] != "pending_auditor_review":
            raise EscalationError(
                f"Escalation {escalation_id} is {escalation['status']}, not open."
            )

        state = self._states.find(
            escalation["org_id"], escalation["datapoint_id"], escalation["scope_ref"]
        )
        if state is None:
            raise EscalationError("The escalated data point no longer has a state.")

        now = self._clock().isoformat()
        self._machine.resolve(
            state, value=value, actor_id=actor_id, resolution_note=resolution_note
        )

        updated = dict(escalation)
        updated.update(
            {
                "status": "resolved",
                "ticket_version": int(escalation.get("ticket_version", 1)) + 1,
                "resolution_value": value,
                "resolved_by": actor_id,
                "resolution_note": resolution_note,
                "resolved_at": now,
                "updated_at": now,
                "audit_trail": [
                    *escalation.get("audit_trail", []),
                    EscalationAuditEntry(
                        at=now, actor_id=actor_id, action="resolved", note=resolution_note
                    ).model_dump(),
                ],
            }
        )
        return self._escalations.save(updated)

    def list_open(self, org_id: str | None = None) -> list[dict[str, Any]]:
        return self._escalations.list_open(org_id)

    def blocked_datapoints(self, org_id: str) -> set[tuple[str, str | None]]:
        """(datapoint_id, scope_ref) pairs with an open escalation.

        Phase C2 uses this to hold dependent questions while letting the
        interview continue past them.
        """
        return {
            (record["datapoint_id"], record.get("scope_ref"))
            for record in self._escalations.list_open(org_id)
        }
