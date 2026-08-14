"""The two success metrics (intake Stage 6, Phase F).

intake/SPEC.md section 2 names them: **% of profiles completed with zero
escalations** and **median time-to-complete**, instrumented from day one.

Nothing new is tracked to produce these. Every timestamp already exists - the
audit log is an event stream by construction, and sessions, submissions and
escalations carry their own times. So there is no analytics service, no
tracking script, and nothing about a client leaves this machine.

Two definitions the spec leaves open, both founder-decided:

* **Started** is the client's first sign-in. Their clock starts when they first
  see the product, not when we created their record internally.
* **Complete** means their questions are actually *resolved* - every applicable
  data point settled and nothing still sitting with our team. A client who
  answered everything but has eight questions open with us is not finished.
  A consequence worth stating: time-to-complete therefore includes how fast we
  answer escalations, so this measures Sustentra as much as the client.

And one honesty problem in the metric itself. Taken literally, "zero
escalations" can never rise above zero: ten of the thirty-eight data points are
HUMAN class and the policy escalates every one for confirmation, so a client who
sails through still generates a handful. Both numbers are therefore reported -
the literal one, and the one that measures what the metric is for, which is
whether the client got stuck. Which triggers count as which is config.
"""

from __future__ import annotations

import statistics
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from intake.backend.config import IntakeSettings, load_settings

#: A data point nobody has to do anything more about.
SETTLED_STATUSES = {"answered", "not_present", "resolved"}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _parse(timestamp: str | None) -> datetime | None:
    if not timestamp:
        return None
    try:
        parsed = datetime.fromisoformat(timestamp)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


class MetricsService:
    def __init__(
        self,
        org_repository: Any,
        session_repository: Any,
        state_repository: Any,
        escalation_repository: Any,
        audit_repository: Any,
        interview_engine: Any,
        settings: IntakeSettings | None = None,
        clock: Callable[[], datetime] = _utcnow,
    ) -> None:
        self._orgs = org_repository
        self._sessions = session_repository
        self._states = state_repository
        self._escalations = escalation_repository
        self._audit = audit_repository
        self._engine = interview_engine
        self._settings = settings or load_settings()
        self._clock = clock

    # -- one client ---------------------------------------------------------

    def journey(self, org_id: str) -> dict[str, Any] | None:
        """One client's onboarding, start to finish."""
        org = self._orgs.get(org_id)
        if org is None:
            return None

        started_at = self._started_at(org)
        applicable = self._engine.applicable_states(org_id)
        open_escalations = {
            (record["datapoint_id"], record.get("scope_ref"))
            for record in self._escalations.list_open(org_id)
        }

        # The status check alone is normally enough: the state machine only
        # lets an escalated point move to resolved, so status and escalation
        # stay in lockstep. The second clause is a guard against the two
        # records drifting apart, which would otherwise report a client as
        # finished while a question was still sitting with us. Tested by
        # constructing that drift directly.
        unsettled = [
            state
            for state in applicable
            if state["status"] not in SETTLED_STATUSES
            or (state["datapoint_id"], state.get("scope_ref")) in open_escalations
        ]
        completed_at = (
            None if unsettled or not applicable else self._settled_at(org_id, applicable)
        )

        counts = self._escalation_counts(org_id)
        started = _parse(started_at)
        finished = _parse(completed_at)
        hours = (
            round((finished - started).total_seconds() / 3600, 2)
            if started and finished and finished >= started
            else None
        )

        return {
            "org_id": org_id,
            "legal_name": org.get("legal_name"),
            "started_at": started_at,
            "completed_at": completed_at,
            "is_complete": completed_at is not None,
            "hours_to_complete": hours,
            "datapoints_total": len(applicable),
            "datapoints_settled": len(applicable) - len(unsettled),
            "still_open": len(unsettled),
            "escalations_total": counts["total"],
            "escalations_routine": counts["routine"],
            "escalations_stuck": counts["stuck"],
            "escalations_open": counts["open"],
            "got_stuck": counts["stuck"] > 0,
        }

    # -- everyone -----------------------------------------------------------

    def summary(self) -> dict[str, Any]:
        """The two headline numbers, with the sample size beside them."""
        journeys = [
            journey
            for journey in (self.journey(org["org_id"]) for org in self._orgs.list_latest())
            if journey is not None
        ]
        started = [item for item in journeys if item["started_at"]]
        complete = [item for item in started if item["is_complete"]]
        durations = [
            item["hours_to_complete"] for item in complete if item["hours_to_complete"] is not None
        ]

        minimum = self._settings.metrics.minimum_sample
        return {
            "generated_at": self._clock().isoformat(),
            "clients_total": len(journeys),
            "clients_started": len(started),
            "clients_complete": len(complete),
            "sample_size": len(complete),
            "enough_data": len(complete) >= minimum,
            "minimum_sample": minimum,
            "completion_rate": self._rate(len(complete), len(started)),
            # The metric SPEC section 2 asks for, word for word.
            "zero_escalation_rate": self._rate(
                sum(1 for item in complete if item["escalations_total"] == 0), len(complete)
            ),
            # The one that measures what it is for: did anyone get stuck?
            "no_stuck_rate": self._rate(
                sum(1 for item in complete if not item["got_stuck"]), len(complete)
            ),
            "median_hours_to_complete": (
                round(statistics.median(durations), 2) if durations else None
            ),
            "fastest_hours": min(durations) if durations else None,
            "slowest_hours": max(durations) if durations else None,
            "caveats": self._caveats(len(complete), minimum),
            "clients": sorted(
                journeys, key=lambda item: (item["is_complete"], item["legal_name"] or "")
            ),
        }

    # -- internals ----------------------------------------------------------

    def _started_at(self, org: dict[str, Any]) -> str | None:
        """First sign-in by anyone at this company.

        Falls back to the seed-form submission for a client whose session
        records have since expired out of the store, and to nothing at all for
        a company created internally that has never signed in - which is
        correct: they have not started.
        """
        sessions = self._sessions.filter_latest(org_id=org["org_id"])
        times = sorted(item["created_at"] for item in sessions if item.get("created_at"))
        if times:
            return times[0]
        return None

    def _settled_at(self, org_id: str, applicable: list[dict[str, Any]]) -> str | None:
        """When the last applicable question was settled.

        Read from the audit log rather than a state's ``updated_at``: the log
        records exactly when a status became final, and is not moved by a later
        unrelated write to the same record.
        """
        wanted = {(state["datapoint_id"], state.get("scope_ref")) for state in applicable}
        last: dict[tuple[str, str | None], str] = {}

        for entry in self._audit.list_by_org(org_id):
            if entry.get("field") != "status" or entry.get("new_value") not in SETTLED_STATUSES:
                continue
            key = (entry.get("datapoint_id"), entry.get("scope_ref"))
            if key not in wanted:
                continue
            at = entry.get("at")
            if at and at > last.get(key, ""):
                last[key] = at

        # Every applicable point must have a recorded settling moment for the
        # completion time to mean anything.
        return max(last.values()) if len(last) == len(wanted) and last else None

    def _escalation_counts(self, org_id: str) -> dict[str, int]:
        records = self._escalations.list_by_org(org_id)
        stuck = set(self._settings.metrics.stuck_triggers)
        return {
            "total": len(records),
            "stuck": sum(1 for item in records if item.get("trigger") in stuck),
            "routine": sum(1 for item in records if item.get("trigger") not in stuck),
            "open": sum(
                1 for item in records if item.get("status") == "pending_auditor_review"
            ),
        }

    @staticmethod
    def _rate(part: int, whole: int) -> float | None:
        """A percentage, or None when there is nothing to divide by.

        None rather than 0.0 deliberately: "no clients yet" and "no clients
        succeeded" are different facts and must not read the same.
        """
        return round(100 * part / whole, 1) if whole else None

    def _caveats(self, sample: int, minimum: int) -> list[str]:
        notes = []
        if sample == 0:
            notes.append("No client has finished onboarding yet, so there is nothing to average.")
        elif sample < minimum:
            notes.append(
                f"Only {sample} completed profile{'s' if sample != 1 else ''}. "
                f"A median needs at least {minimum} to mean anything - read these as "
                "individual cases, not as a trend."
            )
        notes.append(
            "'Completed with no escalations at all' counts the routine confirmations "
            "every client generates by design, so it will read low. 'Completed without "
            "getting stuck' is the number that measures onboarding."
        )
        notes.append(
            "Time-to-complete runs until the last question is resolved, so it includes "
            "how quickly the Sustentra team answered escalations."
        )
        return notes
