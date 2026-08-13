"""The datapoint state machine (intake Stage 2).

The only thing in the system allowed to change a datapoint's status. Transitions
are declared in ``ALLOWED`` and anything not listed is rejected - per
intake/SPEC.md section 4, transitions are enforced in application code, and from
Phase D the LLM only ever *proposes* an update while the app writes it.

Every accepted change appends an audit entry (who, when, old, new).

Two rules are enforced here rather than left to callers:

* ``not_present`` is a completeness record, never an exclusion. Writing EXC-010
  from this path is rejected outright.
* ``escalated`` is not terminal for the interview. It blocks dependants only,
  which is a question-selection concern (Phase C2), not a state concern.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from intake.backend.domain.audit_log import AuditLogEntry
from intake.backend.domain.datapoint_state import DatapointState, Provenance
from intake.backend.repositories.audit_log_repository import AuditLogRepository
from intake.backend.repositories.datapoint_state_repository import DatapointStateRepository

TERMINAL_FOR_INTERVIEW = {"answered", "not_present", "resolved"}

#: status -> statuses it may move to. Re-entry (x -> x) is allowed where a value
#: may legitimately be revised without changing status.
ALLOWED: dict[str, set[str]] = {
    "unasked": {"asked", "not_present"},
    "asked": {
        "asked",
        "answered",
        "unknown",
        "not_present",
        "pending_documents",
        "escalated",
    },
    "answered": {"answered", "escalated", "pending_documents", "not_present"},
    "unknown": {"answered", "escalated", "pending_documents", "not_present"},
    "not_present": {"answered", "escalated"},
    "pending_documents": {"answered", "escalated", "pending_documents", "unknown"},
    "escalated": {"resolved", "escalated"},
    "resolved": set(),
}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class TransitionError(Exception):
    """Raised when a status change is not permitted."""


class StateMachine:
    def __init__(
        self,
        state_repository: DatapointStateRepository,
        audit_repository: AuditLogRepository,
        clock: Callable[[], datetime] = _utcnow,
    ) -> None:
        self._states = state_repository
        self._audit = audit_repository
        self._clock = clock

    # -- creation -----------------------------------------------------------

    def create(
        self,
        org_id: str,
        datapoint_id: str,
        grain: str,
        scope_ref: str | None,
        actor_id: str,
        status: str = "unasked",
    ) -> dict[str, Any]:
        """Create a state, or return the existing one. Idempotent by (org, datapoint, scope)."""
        existing = self._states.find(org_id, datapoint_id, scope_ref)
        if existing is not None:
            return existing

        now = self._clock().isoformat()
        state = DatapointState(
            state_id=f"dps_{uuid.uuid4().hex[:12]}",
            org_id=org_id,
            datapoint_id=datapoint_id,
            grain=grain,  # type: ignore[arg-type]
            scope_ref=scope_ref,
            status=status,  # type: ignore[arg-type]
            created_at=now,
            updated_at=now,
            updated_by=actor_id,
        )
        record = self._states.save(state)
        self._log(
            org_id=org_id,
            action="state_created",
            entity_id=state.state_id,
            datapoint_id=datapoint_id,
            scope_ref=scope_ref,
            old=None,
            new=status,
            actor_id=actor_id,
        )
        return record

    # -- transitions --------------------------------------------------------

    def transition(
        self,
        state: dict[str, Any],
        to_status: str,
        actor_id: str,
        value: dict | None = None,
        provenance: Provenance | dict | None = None,
        escalation_id: str | None = None,
        uncertainty_tier: str | None = None,
        reason: str | None = None,
        actor_role: str | None = None,
    ) -> dict[str, Any]:
        """Move a state to ``to_status``, recording the change."""
        current = state["status"]
        allowed = ALLOWED.get(current)
        if allowed is None:
            raise TransitionError(f"Unknown current status {current!r}.")
        if to_status not in allowed:
            raise TransitionError(
                f"{state['datapoint_id']}: cannot move from {current!r} to {to_status!r}. "
                f"Allowed: {sorted(allowed) or 'none (terminal)'}."
            )

        now = self._clock().isoformat()
        updated = dict(state)
        updated["status"] = to_status
        updated["updated_at"] = now
        updated["updated_by"] = actor_id

        old_value = state.get("value")
        if value is not None:
            updated["value"] = value
        if provenance is not None:
            updated["provenance"] = (
                provenance.model_dump() if isinstance(provenance, Provenance) else provenance
            )
        if escalation_id is not None:
            updated["escalation_id"] = escalation_id
        if uncertainty_tier is not None:
            updated["uncertainty_tier"] = uncertainty_tier

        record = self._states.save(updated)

        if current != to_status:
            self._log(
                org_id=state["org_id"],
                action="status_changed",
                entity_id=state["state_id"],
                datapoint_id=state["datapoint_id"],
                scope_ref=state.get("scope_ref"),
                old=current,
                new=to_status,
                actor_id=actor_id,
                actor_role=actor_role,
                reason=reason,
                field="status",
            )
        if value is not None and value != old_value:
            self._log(
                org_id=state["org_id"],
                action="value_changed",
                entity_id=state["state_id"],
                datapoint_id=state["datapoint_id"],
                scope_ref=state.get("scope_ref"),
                old=old_value,
                new=value,
                actor_id=actor_id,
                actor_role=actor_role,
                reason=reason,
                field="value",
            )
        return record

    # -- convenience --------------------------------------------------------

    def mark_asked(self, state: dict[str, Any], actor_id: str) -> dict[str, Any]:
        if state["status"] != "unasked":
            return state
        return self.transition(state, "asked", actor_id=actor_id)

    def record_answer(
        self,
        state: dict[str, Any],
        value: dict,
        actor_id: str,
        answered_by: str = "user",
        value_basis: str | None = None,
        actor_role: str | None = None,
    ) -> dict[str, Any]:
        provenance = Provenance(
            answered_by=answered_by,  # type: ignore[arg-type]
            actor_id=actor_id,
            value_basis=value_basis,  # type: ignore[arg-type]
        )
        return self.transition(
            state,
            "answered",
            actor_id=actor_id,
            value=value,
            provenance=provenance,
            actor_role=actor_role,
        )

    def record_clarification_attempt(
        self, state: dict[str, Any], actor_id: str, attempts: int
    ) -> dict[str, Any]:
        """Count a failed attempt to read a free-text answer.

        Status is untouched: the question is still open with the client until
        the attempts run out, at which point the caller escalates it.
        """
        updated = dict(state)
        updated["clarification_attempts"] = attempts
        updated["updated_at"] = self._clock().isoformat()
        updated["updated_by"] = actor_id
        record = self._states.save(updated)
        self._log(
            org_id=state["org_id"],
            action="value_changed",
            entity_id=state["state_id"],
            datapoint_id=state["datapoint_id"],
            scope_ref=state.get("scope_ref"),
            old=state.get("clarification_attempts", 0),
            new=attempts,
            actor_id=actor_id,
            field="clarification_attempts",
            reason="free-text answer could not be read confidently",
        )
        return record

    def record_not_present(
        self,
        state: dict[str, Any],
        actor_id: str,
        source_category: str | None = None,
        also_supplied: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Record a screening 'no' as a completeness statement, never an exclusion.

        ``also_supplied`` carries anything else the client sent with that "no".
        It is kept rather than dropped: silently discarding what someone typed
        loses information, and an answer that contradicts the "no" is exactly
        what the contradiction rules exist to catch.
        """
        value = {
            "present": False,
            "screened_source_category": source_category,
            **(also_supplied or {}),
        }
        return self.transition(
            state,
            "not_present",
            actor_id=actor_id,
            value=value,
            provenance=Provenance(answered_by="user", actor_id=actor_id),
            reason="screened, not present (completeness record, not an EXC-010 exclusion)",
        )

    def resolve(
        self,
        state: dict[str, Any],
        value: dict,
        actor_id: str,
        resolution_note: str | None = None,
    ) -> dict[str, Any]:
        """Reviewer resolution: the answer is written in, tagged resolved_by_team."""
        return self.transition(
            state,
            "resolved",
            actor_id=actor_id,
            value=value,
            provenance=Provenance(answered_by="team", actor_id=actor_id, note=resolution_note),
            actor_role="sustentra_reviewer",
            reason=resolution_note or "resolved_by_team",
        )

    # -- internals ----------------------------------------------------------

    def _log(
        self,
        org_id: str,
        action: str,
        entity_id: str,
        datapoint_id: str | None,
        scope_ref: str | None,
        old: object,
        new: object,
        actor_id: str,
        actor_role: str | None = None,
        reason: str | None = None,
        field: str | None = None,
    ) -> None:
        self._audit.save(
            AuditLogEntry(
                audit_id=f"aud_{uuid.uuid4().hex[:12]}",
                org_id=org_id,
                action=action,  # type: ignore[arg-type]
                entity_type="datapoint_state",
                entity_id=entity_id,
                datapoint_id=datapoint_id,
                scope_ref=scope_ref,
                field=field,
                old_value=old,
                new_value=new,
                actor_id=actor_id,
                actor_role=actor_role,
                reason=reason,
                at=self._clock().isoformat(),
            )
        )
