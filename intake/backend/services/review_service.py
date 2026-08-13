"""Shapes escalations for the reviewer queue (Phase D2).

A reviewer should be able to answer without opening three other screens, so
each item carries the client, the site, the question as the client saw it, what
they tried, and how long it has been waiting against the SLA.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from intake.backend.config import IntakeSettings, load_settings
from intake.backend.services.question_content import load_question_content


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _parse(timestamp: str) -> datetime:
    parsed = datetime.fromisoformat(timestamp)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


class ReviewService:
    def __init__(
        self,
        escalation_repository: Any,
        state_repository: Any,
        org_repository: Any,
        site_repository: Any,
        audit_repository: Any,
        settings: IntakeSettings | None = None,
        clock: Callable[[], datetime] = _utcnow,
    ) -> None:
        self._escalations = escalation_repository
        self._states = state_repository
        self._orgs = org_repository
        self._sites = site_repository
        self._audit = audit_repository
        self._settings = settings or load_settings()
        self._clock = clock
        self._content = load_question_content()

    def summarise(self, record: dict[str, Any]) -> dict[str, Any]:
        """One row in the queue."""
        org = self._orgs.get(record["org_id"]) or {}
        opened = _parse(record["created_at"])
        hours_open = (self._clock() - opened).total_seconds() / 3600
        sla = self._settings.escalation.sla_hours

        return {
            "escalation_id": record["escalation_id"],
            "org_id": record["org_id"],
            "client": org.get("legal_name") or record["org_id"],
            "site": self._site_name(record),
            "datapoint_id": record["datapoint_id"],
            "question": record["question_label"],
            "trigger": record["trigger"],
            "why": record.get("seed_context", {}).get("trigger_reason"),
            "created_at": record["created_at"],
            "hours_open": round(hours_open, 1),
            "past_sla": hours_open > sla,
            "notified": bool(record.get("notified_at")),
            "reminded": bool(record.get("reminded_at")),
        }

    def detail(self, escalation_id: str) -> dict[str, Any] | None:
        """Everything needed to answer one question."""
        record = self._escalations.get(escalation_id)
        if record is None:
            return None

        content = self._content.get(record["datapoint_id"], {})
        state = self._states.find(
            record["org_id"], record["datapoint_id"], record.get("scope_ref")
        )
        history = self._audit.list_for_datapoint(
            record["org_id"], record["datapoint_id"], record.get("scope_ref")
        )

        return {
            **self.summarise(record),
            "status": record["status"],
            "explainer": content.get("explainer"),
            "answer_fields": content.get("fields", []),
            "answer_shape": content.get("answer_shape"),
            "attempts": record.get("answer_attempts", []),
            "seed_context": record.get("seed_context", {}),
            "current_value": (state or {}).get("value"),
            "resolution_value": record.get("resolution_value"),
            "resolution_note": record.get("resolution_note"),
            "audit_trail": record.get("audit_trail", []),
            "history": [
                {
                    "at": entry["at"],
                    "actor": entry["actor_id"],
                    "field": entry.get("field"),
                    "from": entry.get("old_value"),
                    "to": entry.get("new_value"),
                }
                for entry in history
            ],
        }

    def _site_name(self, record: dict[str, Any]) -> str | None:
        scope_ref = record.get("scope_ref")
        if not scope_ref:
            return None
        site = self._sites.get(scope_ref)
        return (site or {}).get("site_name") or scope_ref
