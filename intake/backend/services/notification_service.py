"""Escalation notifications (Phase D2).

intake/SPEC.md section 3 asks for an email when an escalation opens, a reminder
at 12 hours, and a note to the client when it is answered. Section 11 fixes the
addresses and the SLA. This service owns all three.

The one deliberate departure, founder-approved: routine escalations are
**batched into one digest per client** rather than one email each. Every
boundary answer is human-confirmed by design, so a two-site client generates a
dozen or more; an email apiece would bury the ones that matter. Escalations that
mean a client is actually stuck - a contradiction, a failed reading, an explicit
request for help - still go out immediately.

Nothing here decides anything. It reads escalations, renders copy from
``intake/config/email_templates.json`` and hands messages to the email port,
which by default writes to a local file and sends nothing.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import Any

from intake.backend.config import IntakeSettings, load_settings

QUEUE_PATH = "/intake/review"
INTERVIEW_PATH = "/intake/interview"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _parse(timestamp: str) -> datetime:
    parsed = datetime.fromisoformat(timestamp)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


class NotificationService:
    def __init__(
        self,
        escalation_repository: Any,
        org_repository: Any,
        site_repository: Any,
        email_service: Any,
        settings: IntakeSettings | None = None,
        clock: Callable[[], datetime] = _utcnow,
    ) -> None:
        self._escalations = escalation_repository
        self._orgs = org_repository
        self._sites = site_repository
        self._email = email_service
        self._settings = settings or load_settings()
        self._clock = clock

    # -- addresses ----------------------------------------------------------

    @property
    def team_addresses(self) -> list[str]:
        """SPEC section 11: both named contacts, from config."""
        escalation = self._settings.escalation
        return [escalation.primary_email, escalation.secondary_email]

    # -- on escalation ------------------------------------------------------

    def notify_new(self, escalation: dict[str, Any]) -> dict[str, Any]:
        """Called when an escalation opens.

        Urgent ones go out now; the rest wait for the next digest, which keeps
        routine confirmations out of the way without losing them.
        """
        if escalation["trigger"] in self._settings.escalation.urgent_triggers:
            return self._send_urgent(escalation)
        return {"sent": False, "reason": "batched into the next digest"}

    def _send_urgent(self, escalation: dict[str, Any]) -> dict[str, Any]:
        org = self._orgs.get(escalation["org_id"]) or {}
        context = {
            "legal_name": org.get("legal_name") or escalation["org_id"],
            "question": escalation["question_label"],
            "site": self._site_name(escalation) or "company-wide",
            "reason": escalation.get("seed_context", {}).get("trigger_reason")
            or escalation["trigger"].replace("_", " "),
            "attempts": self._describe_attempts(escalation),
            "review_url": self._review_url(escalation["escalation_id"]),
            "sla_hours": self._settings.escalation.sla_hours,
        }
        for address in self.team_addresses:
            self._email.send_template("escalation_urgent", to=address, context=context)

        self._mark(escalation, notified_at=self._clock().isoformat())
        return {"sent": True, "template": "escalation_urgent", "to": self.team_addresses}

    # -- digests and reminders (run from a schedule) ------------------------

    def send_pending_digests(self) -> list[dict[str, Any]]:
        """One digest per client with escalations that have not been notified."""
        sent = []
        for org_id, items in self._group_open().items():
            pending = [item for item in items if not item.get("notified_at")]
            if not pending:
                continue

            org = self._orgs.get(org_id) or {}
            context = {
                "count": len(pending),
                "legal_name": org.get("legal_name") or org_id,
                "items": self._describe_items(pending),
                "queue_url": self._queue_url(),
                "sla_hours": self._settings.escalation.sla_hours,
            }
            for address in self.team_addresses:
                self._email.send_template("escalation_digest", to=address, context=context)

            now = self._clock().isoformat()
            for item in pending:
                self._mark(item, notified_at=now)
            sent.append({"org_id": org_id, "count": len(pending)})
        return sent

    def send_due_reminders(self) -> list[dict[str, Any]]:
        """Remind the team about anything still open past the reminder window.

        Idempotent: an escalation is reminded about once, so running this twice
        in the same window sends nothing the second time.
        """
        threshold = timedelta(hours=self._settings.escalation.reminder_hours)
        now = self._clock()
        sent = []

        for org_id, items in self._group_open().items():
            due = [
                item
                for item in items
                if not item.get("reminded_at")
                and now - _parse(item["created_at"]) >= threshold
            ]
            if not due:
                continue

            oldest = min(_parse(item["created_at"]) for item in due)
            org = self._orgs.get(org_id) or {}
            context = {
                "count": len(due),
                "legal_name": org.get("legal_name") or org_id,
                "hours_open": int((now - oldest).total_seconds() // 3600),
                "sla_hours": self._settings.escalation.sla_hours,
                "items": self._describe_items(due),
                "queue_url": self._queue_url(),
            }
            for address in self.team_addresses:
                self._email.send_template("escalation_reminder", to=address, context=context)

            stamp = now.isoformat()
            for item in due:
                self._mark(item, reminded_at=stamp)
            sent.append({"org_id": org_id, "count": len(due)})
        return sent

    # -- on resolution ------------------------------------------------------

    def notify_resolved(self, escalation: dict[str, Any]) -> dict[str, Any]:
        """Tell the client their question has been answered, with a link back."""
        org = self._orgs.get(escalation["org_id"]) or {}
        responsible = org.get("responsible_party") or {}
        to = responsible.get("email")
        if not to:
            return {"sent": False, "reason": "no responsible party email on the org"}

        self._email.send_template(
            "escalation_resolved",
            to=to,
            context={
                "name": responsible.get("name") or to,
                "question": escalation["question_label"],
                "resolution": self._describe_resolution(escalation),
                "legal_name": org.get("legal_name") or escalation["org_id"],
                "interview_url": self._interview_url(),
            },
        )
        return {"sent": True, "template": "escalation_resolved", "to": to}

    # -- helpers ------------------------------------------------------------

    def _group_open(self) -> dict[str, list[dict[str, Any]]]:
        grouped: dict[str, list[dict[str, Any]]] = {}
        for record in self._escalations.list_open():
            grouped.setdefault(record["org_id"], []).append(record)
        return grouped

    def _mark(self, escalation: dict[str, Any], **stamps: str) -> None:
        updated = dict(escalation)
        updated.update(stamps)
        updated["updated_at"] = self._clock().isoformat()
        self._escalations.save(updated)

    def _describe_items(self, items: list[dict[str, Any]]) -> str:
        lines = []
        for item in items:
            where = self._site_name(item)
            suffix = f" [{where}]" if where else ""
            lines.append(
                f"  - {item['question_label']}{suffix}\n"
                f"    {item['trigger'].replace('_', ' ')} - "
                f"{self._review_url(item['escalation_id'])}"
            )
        return "\n".join(lines) + "\n"

    @staticmethod
    def _describe_attempts(escalation: dict[str, Any]) -> str:
        attempts = escalation.get("answer_attempts") or []
        if not attempts:
            return "nothing recorded"
        return "; ".join(
            str(attempt.get("answer") or attempt.get("text") or attempt) for attempt in attempts
        )

    @staticmethod
    def _describe_resolution(escalation: dict[str, Any]) -> str:
        value = escalation.get("resolution_value") or {}
        note = escalation.get("resolution_note")
        described = ", ".join(f"{key}: {item}" for key, item in value.items()) or "recorded"
        return f"{described}. {note}" if note else described

    def _site_name(self, escalation: dict[str, Any]) -> str | None:
        scope_ref = escalation.get("scope_ref")
        if not scope_ref:
            return None
        site = self._sites.get(scope_ref)
        return (site or {}).get("site_name") or scope_ref

    def _review_url(self, escalation_id: str) -> str:
        return self._settings.escalation.review_url_template.format(
            escalation_id=escalation_id
        )

    def _queue_url(self) -> str:
        template = self._settings.escalation.review_url_template
        return template.split("{escalation_id}")[0].rstrip("/") or QUEUE_PATH

    def _interview_url(self) -> str:
        base = self._settings.auth.verify_url_template.split("/intake/")[0]
        return f"{base}{INTERVIEW_PATH}"
