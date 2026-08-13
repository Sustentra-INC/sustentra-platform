"""Compile the client's answers into a list of expected documents (Phase E).

intake/SPEC.md Stage 4: on sufficient completion, compile the expected-document
checklist (doc types x sites x months, from the J2 evidence types per the
mapping) and the expected-completeness spec for S1's gate.

This is a shopping list, not a second pipeline. Nothing here opens, parses or
extracts a file - that is S1's job, and S1 is untouched. What S1 cannot know is
what *should* arrive; only the interview knows that, which is the whole reason
this exists.

Three rules it follows strictly:

* **A request exists only because the client said the source exists.** "Yes, we
  have generators" produces generator records. "No, we have none" produces a
  completeness record and no request at all.
* **It never invents an expected count.** Cadence comes from
  ``intake/config/evidence_cadence.json``, which sources exactly one entry from
  the mapping (electricity, monthly per meter) and flags the rest provisional.
  Where the cadence is unknown the request covers the whole period and says so,
  so a completeness gate cannot mistake unknown for zero.
* **It says what S1 may safely start on.** SPEC Stage 5: documents resting on a
  boundary decision wait until a human has confirmed it.
"""

from __future__ import annotations

import calendar
from collections.abc import Callable
from datetime import date, datetime, timezone
from typing import Any

from intake.backend.config import (
    IntakeSettings,
    evidence_type_names,
    load_evidence_cadence,
    load_profile_schema,
    load_settings,
)
from intake.backend.domain.evidence_request import (
    BlockedBy,
    EvidenceRequest,
    RequestedBy,
    request_id,
)
from intake.backend.services.interview_engine import ANSWERED_STATUSES

MONTH_NAMES = list(calendar.month_name)

# A screening "no" is a completeness record, never a request.
NOT_PRESENT = "not_present"

BOUNDARY_SECTION = "boundary"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _parse_date(value: str) -> date:
    return date.fromisoformat(str(value)[:10])


def _month_end(start: date) -> date:
    last = calendar.monthrange(start.year, start.month)[1]
    return date(start.year, start.month, last)


def _next_month(start: date) -> date:
    return (
        date(start.year + 1, 1, 1) if start.month == 12 else date(start.year, start.month + 1, 1)
    )


class EvidenceRequestService:
    def __init__(
        self,
        evidence_request_repository: Any,
        state_repository: Any,
        org_repository: Any,
        site_repository: Any,
        escalation_repository: Any,
        settings: IntakeSettings | None = None,
        clock: Callable[[], datetime] = _utcnow,
    ) -> None:
        self._requests = evidence_request_repository
        self._states = state_repository
        self._orgs = org_repository
        self._sites = site_repository
        self._escalations = escalation_repository
        self._settings = settings or load_settings()
        self._clock = clock

        schema = load_profile_schema()
        self._datapoints = {item["datapoint_id"]: item for item in schema["datapoints"]}
        cadence = load_evidence_cadence()
        self._cadences = cadence["cadences"]
        self._by_type = cadence["evidence_types"]
        self._default_cadence = cadence["default_cadence"]
        self._names = evidence_type_names()

    # -- compiling ----------------------------------------------------------

    def compile(self, org_id: str) -> list[dict[str, Any]]:
        """Recompute the checklist from the client's current answers.

        Safe to run after every answer: request IDs are derived from identity, so
        a rerun updates the same records rather than duplicating them, and a
        status someone already set survives.
        """
        org = self._orgs.get(org_id)
        if org is None:
            return []

        period = self._reporting_period(org)
        if period is None:
            # No reporting period yet means no period to request documents for.
            return []

        blockers = self._blockers(org_id)
        existing = {
            record["evidence_request_id"]: record for record in self._requests.list_by_org(org_id)
        }
        now = self._clock().isoformat()
        compiled: dict[str, EvidenceRequest] = {}

        for state in self._states.list_by_org(org_id):
            for request in self._requests_for_state(state, org, period, blockers, now):
                key = request.evidence_request_id
                if key in compiled:
                    # Two questions can ask for the same document - a fuel
                    # delivery ticket serves both the boiler and the generator.
                    # One request, both reasons.
                    compiled[key] = self._merge(compiled[key], request)
                else:
                    compiled[key] = request

        saved = []
        for request in compiled.values():
            previous = existing.get(request.evidence_request_id)
            payload = request.model_dump(by_alias=True)
            if previous is not None:
                # Never reset what a person or a later stage has recorded.
                payload["status"] = previous.get("status", payload["status"])
                payload["created_at"] = previous.get("created_at", payload["created_at"])
                if self._unchanged(previous, payload):
                    saved.append(previous)
                    continue
            saved.append(self._requests.save(payload))

        return sorted(saved, key=self._sort_key)

    def list_for_org(self, org_id: str) -> list[dict[str, Any]]:
        return sorted(self._requests.list_by_org(org_id), key=self._sort_key)

    # -- the completeness spec S1 can adopt ---------------------------------

    def completeness_spec(self, org_id: str) -> dict[str, Any]:
        """Expected documents per scope, for S1's completeness gate.

        SPEC Stage 4 asks for this to replace hardcoded assumptions in the
        existing pipeline - exposed as an API the pipeline can adopt later,
        never by editing S1.

        ``expected_documents`` is null, not zero, wherever the cadence is
        unknown. A gate that reads null as zero would pass a client who sent
        nothing.
        """
        org = self._orgs.get(org_id) or {}
        requests = self.list_for_org(org_id)

        scopes: dict[str, dict[str, Any]] = {}
        for record in requests:
            scope_key = record["scope_ref"] or "org"
            scope = scopes.setdefault(
                scope_key,
                {
                    "scope_ref": record["scope_ref"],
                    "scope_label": record["scope_label"],
                    "grain": record["grain"],
                    "expected": {},
                },
            )
            bucket = scope["expected"].setdefault(
                record["evidence_type_id"],
                {
                    "evidence_type_id": record["evidence_type_id"],
                    "evidence_type_name": record["evidence_type_name"],
                    "cadence": record["cadence"],
                    "cadence_provisional": record["cadence_provisional"],
                    "expected_documents": 0 if record["expected_count_known"] else None,
                    "requests": 0,
                    "safe_to_parse_now": 0,
                },
            )
            bucket["requests"] += 1
            if record["expected_count_known"] and bucket["expected_documents"] is not None:
                bucket["expected_documents"] += 1
            if record["safe_to_parse"]:
                bucket["safe_to_parse_now"] += 1

        known = [item for item in requests if item["expected_count_known"]]
        return {
            "org_id": org_id,
            "legal_name": org.get("legal_name"),
            "reporting_period_start": org.get("reporting_period_start"),
            "reporting_period_end": org.get("reporting_period_end"),
            "generated_at": self._clock().isoformat(),
            "scopes": [
                {**scope, "expected": list(scope["expected"].values())}
                for scope in scopes.values()
            ],
            "totals": {
                "requests": len(requests),
                "expected_documents_known": len(known),
                "expected_documents_unknown": len(requests) - len(known),
                "safe_to_parse_now": sum(1 for item in requests if item["safe_to_parse"]),
                "awaiting_human_confirmation": sum(
                    1 for item in requests if not item["safe_to_parse"]
                ),
            },
            "caveat": (
                "expected_documents is null where the cadence has not been signed off. "
                "Unknown is not zero: a completeness gate must not pass a scope on a null."
            ),
        }

    # -- one state ----------------------------------------------------------

    def _requests_for_state(
        self,
        state: dict[str, Any],
        org: dict[str, Any],
        period: tuple[date, date],
        blockers: dict[tuple[str, str | None], str],
        now: str,
    ) -> list[EvidenceRequest]:
        datapoint = self._datapoints.get(state["datapoint_id"])
        if datapoint is None:
            return []

        evidence_types = datapoint.get("evidence_triggered") or []
        if not evidence_types:
            return []
        if not self._source_exists(state):
            return []

        scope_ref = state.get("scope_ref")
        scope_label = self._scope_label(scope_ref, org)
        safe, blocked = self._safety(state, datapoint, scope_ref, blockers)
        requested_by = [
            RequestedBy(
                datapoint_id=state["datapoint_id"],
                scope_ref=scope_ref,
                **{"class": datapoint["class"]},
            )
        ]

        out: list[EvidenceRequest] = []
        for evidence_type_id in evidence_types:
            rule = self._by_type.get(evidence_type_id, {})
            cadence = rule.get("cadence", self._default_cadence)
            units = self._unit_count(rule, state)

            for unit_index in range(1, units + 1):
                unit_label = (
                    f"{rule['per_unit_label']} {unit_index}"
                    if units > 1 or rule.get("per_unit_field")
                    else "all"
                )
                for start, end, label in self._periods(cadence, period):
                    out.append(
                        EvidenceRequest(
                            evidence_request_id=request_id(
                                org["org_id"],
                                evidence_type_id,
                                scope_ref,
                                start.isoformat(),
                                unit_index,
                            ),
                            org_id=org["org_id"],
                            evidence_type_id=evidence_type_id,
                            evidence_type_name=self._names.get(
                                evidence_type_id, evidence_type_id
                            ),
                            grain=state["grain"],
                            scope_ref=scope_ref,
                            scope_label=scope_label,
                            period_start=start.isoformat(),
                            period_end=end.isoformat(),
                            period_label=label,
                            unit_index=unit_index,
                            unit_label=unit_label,
                            cadence=cadence,
                            cadence_provisional=bool(rule.get("provisional", True)),
                            expected_count_known=cadence != "as_available",
                            requested_by=requested_by,
                            safe_to_parse=safe,
                            blocked_by=blocked,
                            created_at=now,
                            updated_at=now,
                        )
                    )
        return out

    @staticmethod
    def _source_exists(state: dict[str, Any]) -> bool:
        """Did the client's answer say this source is actually there?

        A screening "no" is a completeness record, not a request. An unanswered
        question asks for nothing - we do not chase documents for sources we have
        not established.
        """
        if state["status"] == NOT_PRESENT:
            return False
        if state["status"] not in ANSWERED_STATUSES and state["status"] != "escalated":
            return False
        value = state.get("value")
        if value is None:
            return False
        # Screening questions carry an explicit present flag; composite ones
        # (supplier, meter count) exist by virtue of being answered at all.
        return value.get("present", True) is not False

    def _unit_count(self, rule: dict[str, Any], state: dict[str, Any]) -> int:
        """How many copies of this document per period - e.g. one per meter."""
        field = rule.get("per_unit_field")
        if not field:
            return 1
        raw = (state.get("value") or {}).get(field)
        try:
            count = int(raw)
        except (TypeError, ValueError):
            # The client has not told us how many yet: ask for one and let the
            # count correct itself on the next compile.
            return 1
        return max(1, count)

    def _periods(
        self, cadence: str, period: tuple[date, date]
    ) -> list[tuple[date, date, str]]:
        start, end = period
        if cadence != "monthly":
            return [(start, end, f"{start.isoformat()} to {end.isoformat()}")]

        months: list[tuple[date, date, str]] = []
        cursor = date(start.year, start.month, 1)
        while cursor <= end:
            month_end = _month_end(cursor)
            months.append(
                (
                    max(cursor, start),
                    min(month_end, end),
                    f"{MONTH_NAMES[cursor.month]} {cursor.year}",
                )
            )
            cursor = _next_month(cursor)
        return months

    # -- Stage 5: what S1 may start on --------------------------------------

    def _blockers(self, org_id: str) -> dict[tuple[str, str | None], str]:
        """Open escalations, keyed by the answer they are holding up."""
        return {
            (record["datapoint_id"], record.get("scope_ref")): record["trigger"]
            for record in self._escalations.list_open(org_id)
        }

    def _safety(
        self,
        state: dict[str, Any],
        datapoint: dict[str, Any],
        scope_ref: str | None,
        blockers: dict[tuple[str, str | None], str],
    ) -> tuple[bool, list[BlockedBy]]:
        """SPEC Stage 5. Boundary answers are always human-confirmed first."""
        blocked: list[BlockedBy] = []

        own = blockers.get((state["datapoint_id"], scope_ref))
        if own is not None:
            blocked.append(
                BlockedBy(
                    datapoint_id=state["datapoint_id"],
                    scope_ref=scope_ref,
                    reason=f"the answer itself is with our team ({own.replace('_', ' ')})",
                )
            )

        for (datapoint_id, blocked_scope), trigger in blockers.items():
            boundary = self._datapoints.get(datapoint_id) or {}
            if boundary.get("section") != BOUNDARY_SECTION:
                continue
            if blocked_scope not in (None, scope_ref):
                continue
            blocked.append(
                BlockedBy(
                    datapoint_id=datapoint_id,
                    scope_ref=blocked_scope,
                    reason=(
                        "a boundary decision covering this scope is not confirmed yet "
                        f"({trigger.replace('_', ' ')})"
                    ),
                )
            )

        if datapoint["class"] == "HUMAN" and state["status"] != "resolved":
            blocked.append(
                BlockedBy(
                    datapoint_id=state["datapoint_id"],
                    scope_ref=scope_ref,
                    reason="this answer needs a person to confirm it before anything depends on it",
                )
            )

        return (not blocked), blocked

    # -- helpers ------------------------------------------------------------

    def _reporting_period(self, org: dict[str, Any]) -> tuple[date, date] | None:
        start = org.get("reporting_period_start")
        end = org.get("reporting_period_end")
        if not start or not end:
            return None
        try:
            parsed = (_parse_date(start), _parse_date(end))
        except ValueError:
            return None
        return parsed if parsed[0] <= parsed[1] else None

    def _scope_label(self, scope_ref: str | None, org: dict[str, Any]) -> str:
        if scope_ref is None:
            return org.get("legal_name") or "Company-wide"
        site = self._sites.get(scope_ref)
        if site:
            return site.get("site_name") or scope_ref
        return scope_ref

    @staticmethod
    def _merge(first: EvidenceRequest, second: EvidenceRequest) -> EvidenceRequest:
        """One document, several reasons. The strictest safety verdict wins."""
        seen = {(item.datapoint_id, item.scope_ref) for item in first.requested_by}
        merged = list(first.requested_by) + [
            item for item in second.requested_by if (item.datapoint_id, item.scope_ref) not in seen
        ]
        blocked = list(first.blocked_by)
        blocked_seen = {(item.datapoint_id, item.scope_ref, item.reason) for item in blocked}
        for item in second.blocked_by:
            if (item.datapoint_id, item.scope_ref, item.reason) not in blocked_seen:
                blocked.append(item)
        return first.model_copy(
            update={
                "requested_by": merged,
                "blocked_by": blocked,
                "safe_to_parse": first.safe_to_parse and second.safe_to_parse,
            }
        )

    @staticmethod
    def _unchanged(previous: dict[str, Any], payload: dict[str, Any]) -> bool:
        """True when a recompile produced exactly what is already stored.

        Without this, every compile would append an identical record and the
        history would fill with noise that says nothing happened.
        """
        ignore = {"updated_at"}
        return all(
            previous.get(key) == value for key, value in payload.items() if key not in ignore
        ) and set(previous) - ignore == set(payload) - ignore

    @staticmethod
    def _sort_key(record: dict[str, Any]) -> tuple:
        return (
            record.get("scope_label") or "",
            record.get("evidence_type_id") or "",
            record.get("unit_index") or 1,
            record.get("period_start") or "",
        )
