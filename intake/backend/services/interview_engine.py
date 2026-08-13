"""The deterministic interview engine (intake Stage 2, Phase C2).

Picks the next question, validates the answer, and moves the state. Question
selection, applicability, ordering and status transitions are all ordinary code
- SPEC section 6 reserves the LLM for parsing free text and rephrasing
explainers, which arrive in Phase D. Nothing here calls one.

Ordering follows how a person would actually work through it: the company-level
questions first, then the fleet, then each site in turn, then each vehicle
group. Within a block, questions keep their schema order.

"Not sure" is never a failure. It shows the canned explainer, escalates to the
Sustentra team, and the interview moves on - an escalation blocks only the
things that depend on it.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from intake.backend.config import IntakeSettings, load_profile_schema, load_settings
from intake.backend.repositories.datapoint_state_repository import DatapointStateRepository
from intake.backend.repositories.org_repository import OrgRepository
from intake.backend.repositories.site_repository import SiteRepository
from intake.backend.services.applicability_service import ApplicabilityService
from intake.backend.services.escalation_service import EscalationService
from intake.backend.services.field_options import permitted_values, resolve_options
from intake.backend.services.profile_state_service import ProfileStateService
from intake.backend.services.question_content import load_question_content
from intake.backend.services.state_machine import StateMachine

ANSWERED_STATUSES = {"answered", "not_present", "resolved"}
OPEN_STATUSES = {"unasked", "asked", "unknown", "pending_documents"}

GRAIN_ORDER = {"org": 0, "entity": 1, "site": 2, "vehicle_group": 3}

VEHICLE_GROUP_PREFIX = "veh_"
FLEET_DATAPOINT = "S1MOB-4.1"

NOT_SURE_MESSAGE = (
    "We've sent this to the Sustentra team - you'll have an answer within 24 hours. "
    "Let's keep going."
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class AnswerValidationError(Exception):
    """Carries per-field problems so the screen can show them all at once."""

    def __init__(self, errors: list[dict[str, Any]]) -> None:
        super().__init__(f"{len(errors)} validation error(s)")
        self.errors = errors


class InterviewEngine:
    def __init__(
        self,
        state_repository: DatapointStateRepository,
        org_repository: OrgRepository,
        site_repository: SiteRepository,
        state_machine: StateMachine,
        applicability: ApplicabilityService,
        escalations: EscalationService,
        profile_states: ProfileStateService,
        settings: IntakeSettings | None = None,
        clock: Callable[[], datetime] = _utcnow,
    ) -> None:
        self._states = state_repository
        self._orgs = org_repository
        self._sites = site_repository
        self._machine = state_machine
        self._applicability = applicability
        self._escalations = escalations
        self._profile_states = profile_states
        self._settings = settings or load_settings()
        self._clock = clock
        self._schema = load_profile_schema()
        self._content = load_question_content()

        self._datapoints = {
            datapoint["datapoint_id"]: datapoint for datapoint in self._schema["datapoints"]
        }
        self._section_order = {
            section["section_id"]: section["order"] for section in self._schema["sections"]
        }
        self._schema_order = {
            datapoint["datapoint_id"]: index
            for index, datapoint in enumerate(self._schema["datapoints"])
        }

    # -- selection ----------------------------------------------------------

    def applicable_states(self, org_id: str) -> list[dict[str, Any]]:
        """Interview states that currently apply to this client, in ask order."""
        profile = self._orgs.get(org_id) or {}
        states = self._states.list_by_org(org_id)
        site_order = {
            site["site_id"]: index for index, site in enumerate(self._sites.list_by_org(org_id))
        }

        applicable = []
        for state in states:
            datapoint = self._datapoints.get(state["datapoint_id"])
            if datapoint is None or datapoint["datapoint_id"] not in self._content:
                continue  # not an interview question (seed, system assignment, method route)
            if not self._applicability.is_applicable(
                datapoint["applicability"]["condition_ref"],
                profile=profile,
                states=states,
                scope_ref=state.get("scope_ref"),
                self_state=state,
            ):
                continue
            applicable.append(state)

        return sorted(applicable, key=lambda state: self._sort_key(state, site_order))

    def _sort_key(self, state: dict[str, Any], site_order: dict[str, int]) -> tuple:
        datapoint = self._datapoints[state["datapoint_id"]]
        grain = datapoint["grain"]
        scope_ref = state.get("scope_ref")
        return (
            GRAIN_ORDER.get(grain, 9),
            site_order.get(scope_ref, 0) if grain == "site" else 0,
            str(scope_ref or ""),
            self._section_order.get(datapoint["section"], 99),
            self._schema_order.get(state["datapoint_id"], 999),
        )

    def next_question(self, org_id: str) -> dict[str, Any] | None:
        """The next question to ask, or None when nothing is outstanding."""
        blocked = self._escalations.blocked_datapoints(org_id)
        for state in self.applicable_states(org_id):
            if state["status"] not in OPEN_STATUSES:
                continue
            if (state["datapoint_id"], state.get("scope_ref")) in blocked:
                continue  # waiting on the team; the interview moves past it
            return self.render(state)
        return None

    def render(self, state: dict[str, Any]) -> dict[str, Any]:
        """A question ready for the screen: content, options and context."""
        datapoint = self._datapoints[state["datapoint_id"]]
        content = self._content[state["datapoint_id"]]
        fields = [resolve_options(field, self._settings) for field in content["fields"]]

        return {
            "datapoint_id": state["datapoint_id"],
            "state_id": state["state_id"],
            "scope_ref": state.get("scope_ref"),
            "scope_label": self._scope_label(state),
            "section": datapoint["section"],
            "grain": datapoint["grain"],
            "escalation_class": datapoint["class"],
            "question": content["question"],
            "explainer": content["explainer"],
            "answer_shape": content["answer_shape"],
            "fields": fields,
            "status": state["status"],
            "value": state.get("value"),
            "not_sure_allowed": True,
        }

    def _scope_label(self, state: dict[str, Any]) -> str | None:
        """A name the client recognises, not an internal id."""
        scope_ref = state.get("scope_ref")
        if scope_ref is None:
            return None

        site = self._sites.get(scope_ref)
        if site is not None:
            return site["site_name"]

        if scope_ref.startswith(VEHICLE_GROUP_PREFIX):
            # Vehicle groups are named by the client in their fleet answer.
            groups = self._fleet_group_names(state["org_id"])
            index = _vehicle_group_index(scope_ref)
            if index is not None and index < len(groups):
                return groups[index]
        return scope_ref

    def _fleet_group_names(self, org_id: str) -> list[str]:
        fleet = self._states.find(org_id, FLEET_DATAPOINT, None)
        return list((fleet or {}).get("value", {}).get("fleet_groups") or [])

    # -- answering ----------------------------------------------------------

    def submit_answer(
        self, org_id: str, datapoint_id: str, scope_ref: str | None, answer: dict, actor_id: str
    ) -> dict[str, Any]:
        """Validate and record an answer, then advance the interview."""
        state = self._states.find(org_id, datapoint_id, scope_ref)
        if state is None:
            raise AnswerValidationError(
                [{"field": "datapoint_id", "message": f"No such question: {datapoint_id}."}]
            )
        content = self._content.get(datapoint_id)
        if content is None:
            raise AnswerValidationError(
                [{"field": "datapoint_id", "message": f"{datapoint_id} is not asked."}]
            )

        cleaned = self._validate(content, answer)

        if state["status"] == "unasked":
            state = self._machine.mark_asked(state, actor_id=actor_id)

        is_screening = content["answer_shape"] == "yes_no"
        screened_out = is_screening and cleaned.get("present") is False

        if screened_out:
            datapoint = self._datapoints[datapoint_id]
            block = datapoint["populates"][0].get("field_id") if datapoint["populates"] else None
            updated = self._machine.record_not_present(
                state, actor_id=actor_id, source_category=block
            )
        else:
            updated = self._machine.record_answer(
                state, value=cleaned, actor_id=actor_id, answered_by="user", value_basis="asserted"
            )

        created_scopes = self._create_child_scopes(org_id, content, cleaned, actor_id)
        escalation = self._apply_escalation_triggers(org_id, updated, content, actor_id)

        return {
            "state": self._states.find(org_id, datapoint_id, scope_ref),
            "status": updated["status"],
            "escalated": escalation is not None,
            "escalation": escalation,
            "created_scopes": created_scopes,
        }

    def not_sure(
        self, org_id: str, datapoint_id: str, scope_ref: str | None, actor_id: str
    ) -> dict[str, Any]:
        """Show the explainer and escalate. Never a failure state."""
        content = self._content.get(datapoint_id)
        if content is None:
            raise AnswerValidationError(
                [{"field": "datapoint_id", "message": f"{datapoint_id} is not asked."}]
            )

        escalation = self._escalations.open(
            org_id=org_id,
            datapoint_id=datapoint_id,
            scope_ref=scope_ref,
            trigger="user_requested_help",
            question_label=content["question"],
            actor_id=actor_id,
            answer_attempts=[{"attempt": 1, "answer": "not_sure"}],
            seed_context=self._seed_context(org_id, scope_ref),
        )
        return {
            "explainer": content["explainer"],
            "message": NOT_SURE_MESSAGE,
            "escalation": escalation,
        }

    # -- validation ---------------------------------------------------------

    def _validate(self, content: dict[str, Any], answer: dict) -> dict[str, Any]:
        errors: list[dict[str, Any]] = []
        cleaned: dict[str, Any] = {}

        if content["answer_shape"] == "yes_no":
            present = answer.get("present")
            if present not in (True, False):
                errors.append({"field": "present", "message": "Please answer yes or no."})
            else:
                cleaned["present"] = present

        for field in content["fields"]:
            resolved = resolve_options(field, self._settings)
            field_id = resolved["field_id"]

            if not self._is_revealed(resolved, answer, cleaned):
                continue

            raw = answer.get(field_id)
            if raw in (None, "", []):
                if resolved.get("required"):
                    errors.append({"field": field_id, "message": "This field is required."})
                continue

            value, problem = self._coerce(resolved, raw)
            if problem:
                errors.append({"field": field_id, "message": problem})
            else:
                cleaned[field_id] = value

        if errors:
            raise AnswerValidationError(errors)
        return cleaned

    def _is_revealed(
        self, field: dict[str, Any], answer: dict, cleaned: dict[str, Any]
    ) -> bool:
        reveal = field.get("reveal_when")
        if not reveal:
            return True
        source = cleaned.get(reveal["field"], answer.get(reveal["field"]))
        return source == reveal["equals"]

    @staticmethod
    def _coerce(field: dict[str, Any], raw: Any) -> tuple[Any, str | None]:
        kind = field["input"]

        if kind == "yes_no":
            if raw in (True, False):
                return raw, None
            return None, "Please answer yes or no."

        if kind == "number":
            try:
                return float(raw) if isinstance(raw, str) and "." in raw else int(raw), None
            except (TypeError, ValueError):
                return None, "Enter a number."

        if kind == "list":
            if not isinstance(raw, list):
                return None, "Expected a list."
            items = [str(item).strip() for item in raw if str(item).strip()]
            if not items:
                return None, "Add at least one."
            return items, None

        if kind == "select":
            allowed = permitted_values(field)
            value = str(raw).strip()
            if allowed and value not in allowed:
                return None, f"Choose one of: {', '.join(sorted(allowed))}."
            return value, None

        if kind == "date":
            from datetime import date

            try:
                date.fromisoformat(str(raw).strip())
            except ValueError:
                return None, "Use the format YYYY-MM-DD."
            return str(raw).strip(), None

        return str(raw).strip(), None

    # -- side effects -------------------------------------------------------

    def _create_child_scopes(
        self, org_id: str, content: dict[str, Any], cleaned: dict[str, Any], actor_id: str
    ) -> list[str]:
        """Answers that define new grain instances, e.g. vehicle groups."""
        created: list[str] = []
        for field in content["fields"]:
            if field.get("creates_scope") != "vehicle_group":
                continue
            names = cleaned.get(field["field_id"]) or []
            group_ids = [f"veh_{index}_{_slug(name)}" for index, name in enumerate(names)]
            if group_ids:
                created = self._profile_states.instantiate_vehicle_groups(
                    org_id, group_ids, actor_id=actor_id
                )
        return created

    def _apply_escalation_triggers(
        self, org_id: str, state: dict[str, Any], content: dict[str, Any], actor_id: str
    ) -> dict[str, Any] | None:
        datapoint = self._datapoints[state["datapoint_id"]]
        profile = self._orgs.get(org_id) or {}
        states = self._states.list_by_org(org_id)

        for trigger in datapoint["escalation_triggers"]:
            fired = self._applicability.is_applicable(
                trigger["condition_ref"],
                profile=profile,
                states=states,
                scope_ref=state.get("scope_ref"),
                self_state=state,
            )
            if not fired:
                continue
            return self._escalations.open(
                org_id=org_id,
                datapoint_id=state["datapoint_id"],
                scope_ref=state.get("scope_ref"),
                trigger="condition_met",
                question_label=content["question"],
                actor_id=actor_id,
                answer_attempts=[{"answer": state.get("value")}],
                seed_context={
                    **self._seed_context(org_id, state.get("scope_ref")),
                    "trigger_reason": trigger["reason"],
                },
            )
        return None

    def _seed_context(self, org_id: str, scope_ref: str | None) -> dict[str, Any]:
        org = self._orgs.get(org_id) or {}
        context = {
            "legal_name": org.get("legal_name"),
            "reporting_period_start": org.get("reporting_period_start"),
            "reporting_period_end": org.get("reporting_period_end"),
            "industry_overlay_id": org.get("industry_overlay_id"),
        }
        if scope_ref:
            site = self._sites.get(scope_ref)
            if site:
                context["site_name"] = site.get("site_name")
                context["site_type"] = site.get("site_type")
        return context


def _slug(value: str) -> str:
    return "".join(char.lower() if char.isalnum() else "_" for char in value)[:20].strip("_")


def _vehicle_group_index(scope_ref: str) -> int | None:
    """Recover the position a vehicle-group id was created at."""
    parts = scope_ref.split("_", 2)
    if len(parts) < 2:
        return None
    try:
        return int(parts[1])
    except ValueError:
        return None
