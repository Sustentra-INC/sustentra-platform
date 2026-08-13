"""Instantiate and back-fill datapoint states (intake Stage 2, Phase C1).

Three jobs, all deterministic and all idempotent so they can be re-run whenever
a site is added or the schema grows:

1. **Instantiate.** Create one ``unasked`` state per interview question per grain
   instance. Site-grain questions get a copy per site - "each site instantiates
   its own copy of the applicable screening tree" (SPEC section 3).
2. **Back-fill.** Turn the Phase B seed-form submission into ``answered`` states
   for SEED-1.1 to SEED-1.7. Phase B deliberately did not write states; this is
   where that debt is paid.
3. **System assignments.** Record the values the platform assigns rather than
   asks for: the GWP set (BND-2.6) and the five method-route defaults (MRT-7.x).
   All are marked provisional pending expert sign-off - they are proposals, not
   settled methodology (CLAUDE.md rule 6).

Vehicle-group states are NOT created here: they depend on the fleet answer to
S1MOB-4.1 and are instantiated when that answer arrives (Phase C2).
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from intake.backend.config import default_gwp_set, load_profile_schema
from intake.backend.repositories.datapoint_state_repository import DatapointStateRepository
from intake.backend.repositories.org_repository import OrgRepository
from intake.backend.repositories.seed_profile_repository import SeedProfileRepository
from intake.backend.repositories.site_repository import SiteRepository
from intake.backend.services.state_machine import StateMachine

SYSTEM_ACTOR = "system"

INTERVIEW_SECTIONS = (
    "boundary",
    "scope1_stationary",
    "scope1_mobile",
    "scope1_fugitive",
    "scope2",
)

# Seed-form answers are spread across the org record and each site record, so the
# back-fill reads them from those rather than re-parsing the raw submission.
ORG_SEED_FIELDS: dict[str, tuple[str, ...]] = {
    "SEED-1.1": ("legal_name", "reporting_year"),
    "SEED-1.2": ("responsible_party",),
    "SEED-1.4": ("industry", "industry_overlay_id"),
    "SEED-1.6": ("reporting_period_start", "reporting_period_end", "fiscal_year_basis"),
}
SITE_SEED_FIELDS: dict[str, tuple[str, ...]] = {
    "SEED-1.3": (
        "site_name",
        "address",
        "operational_status",
        "period_in_scope_start",
        "period_in_scope_end",
    ),
    "SEED-1.5": ("site_type",),
    "SEED-1.7": ("ownership", "lease_type", "ownership_note"),
}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ProfileStateService:
    def __init__(
        self,
        state_machine: StateMachine,
        state_repository: DatapointStateRepository,
        org_repository: OrgRepository,
        site_repository: SiteRepository,
        seed_profile_repository: SeedProfileRepository,
        clock: Callable[[], datetime] = _utcnow,
    ) -> None:
        self._machine = state_machine
        self._states = state_repository
        self._orgs = org_repository
        self._sites = site_repository
        self._submissions = seed_profile_repository
        self._clock = clock
        self._schema = load_profile_schema()

    # -- entry point --------------------------------------------------------

    def has_states(self, org_id: str) -> bool:
        """Has the interview been started for this org?

        Phase E uses this to decide whether editing a seed-form fact should push
        the change back into the answers derived from it.
        """
        return bool(self._states.list_by_org(org_id))

    def initialise(self, org_id: str, actor_id: str = SYSTEM_ACTOR) -> dict[str, Any]:
        """Create every state this org should have. Safe to call repeatedly."""
        org = self._orgs.get(org_id)
        if org is None:
            raise ValueError(f"Unknown org {org_id}.")

        before = len(self._states.list_by_org(org_id))
        sites = self._sites.list_by_org(org_id)

        instantiated = self._instantiate_questions(org_id, sites, actor_id)
        backfilled = self._backfill_seed_answers(org, sites, actor_id)
        assigned = self._apply_system_assignments(org_id, actor_id)

        after = self._states.list_by_org(org_id)
        return {
            "org_id": org_id,
            "sites": len(sites),
            "states_before": before,
            "states_total": len(after),
            "instantiated": instantiated,
            "backfilled": backfilled,
            "system_assigned": assigned,
        }

    # -- 1. instantiation ---------------------------------------------------

    def interview_datapoints(self) -> list[dict[str, Any]]:
        """Active Stage 2 questions, in schema order."""
        return [
            datapoint
            for datapoint in self._schema["datapoints"]
            if datapoint["section"] in INTERVIEW_SECTIONS
            and datapoint["kind"] == "question"
            and datapoint["v1_status"] == "active"
        ]

    def _instantiate_questions(
        self, org_id: str, sites: list[dict[str, Any]], actor_id: str
    ) -> list[str]:
        created: list[str] = []
        for datapoint in self.interview_datapoints():
            grain = datapoint["grain"]
            if grain == "site":
                scopes: list[str | None] = [site["site_id"] for site in sites]
            elif grain in {"org", "entity"}:
                # v1 is single-entity (SPEC section 8), so the entity is the org.
                scopes = [None]
            else:
                # vehicle_group and finer grains are created from their parent answer.
                continue

            for scope_ref in scopes:
                if self._states.find(org_id, datapoint["datapoint_id"], scope_ref) is None:
                    self._machine.create(
                        org_id=org_id,
                        datapoint_id=datapoint["datapoint_id"],
                        grain=grain,
                        scope_ref=scope_ref,
                        actor_id=actor_id,
                    )
                    created.append(f"{datapoint['datapoint_id']}@{scope_ref or 'org'}")
        return created

    def instantiate_vehicle_groups(
        self, org_id: str, group_ids: list[str], actor_id: str = SYSTEM_ACTOR
    ) -> list[str]:
        """Create vehicle-group-grain states once a fleet has been described."""
        created: list[str] = []
        for datapoint in self.interview_datapoints():
            if datapoint["grain"] != "vehicle_group":
                continue
            for group_id in group_ids:
                if self._states.find(org_id, datapoint["datapoint_id"], group_id) is None:
                    self._machine.create(
                        org_id=org_id,
                        datapoint_id=datapoint["datapoint_id"],
                        grain="vehicle_group",
                        scope_ref=group_id,
                        actor_id=actor_id,
                    )
                    created.append(f"{datapoint['datapoint_id']}@{group_id}")
        return created

    # -- 2. back-fill -------------------------------------------------------

    def _backfill_seed_answers(
        self, org: dict[str, Any], sites: list[dict[str, Any]], actor_id: str
    ) -> list[str]:
        org_id = org["org_id"]
        submission = self._submissions.latest_for_org(org_id)
        if submission is None:
            # Nothing to back-fill until the seed form has been submitted.
            return []

        submitter = submission.get("submitted_by") or actor_id
        provisional = {value["field_id"] for value in submission.get("provisional_values", [])}
        filled: list[str] = []

        for datapoint_id, fields in ORG_SEED_FIELDS.items():
            value = {field: org.get(field) for field in fields}
            if self._write_seed_state(
                org_id, datapoint_id, "org", None, value, submitter, provisional
            ):
                filled.append(f"{datapoint_id}@org")

        for site in sites:
            for datapoint_id, fields in SITE_SEED_FIELDS.items():
                value = {field: site.get(field) for field in fields}
                if self._write_seed_state(
                    org_id,
                    datapoint_id,
                    "site",
                    site["site_id"],
                    value,
                    submitter,
                    provisional,
                ):
                    filled.append(f"{datapoint_id}@{site['site_id']}")
        return filled

    def _write_seed_state(
        self,
        org_id: str,
        datapoint_id: str,
        grain: str,
        scope_ref: str | None,
        value: dict[str, Any],
        actor_id: str,
        provisional: set[str],
    ) -> bool:
        """Create-or-update one seed-derived state. Returns True if it changed."""
        state = self._states.find(org_id, datapoint_id, scope_ref)
        if state is None:
            state = self._machine.create(
                org_id=org_id,
                datapoint_id=datapoint_id,
                grain=grain,
                scope_ref=scope_ref,
                actor_id=actor_id,
            )
        elif state["status"] == "answered" and state.get("value") == value:
            return False  # already back-filled with the same answer

        if state["status"] == "unasked":
            state = self._machine.mark_asked(state, actor_id=actor_id)

        updated = self._machine.record_answer(
            state,
            value=value,
            actor_id=actor_id,
            answered_by="user",
            value_basis="asserted",
        )
        flags = sorted(field for field in value if field in provisional)
        if flags:
            record = dict(updated)
            record["provisional_fields"] = flags
            self._states.save(record)
        return True

    # -- 3. system assignments ---------------------------------------------

    def _apply_system_assignments(self, org_id: str, actor_id: str) -> list[str]:
        assigned: list[str] = []
        for datapoint in self._schema["datapoints"]:
            if datapoint["kind"] not in {"system_assignment", "method_route"}:
                continue
            if datapoint["v1_status"] != "active":
                continue

            value = self._system_value(datapoint)
            if value is None:
                continue

            state = self._states.find(org_id, datapoint["datapoint_id"], None)
            if state is None:
                state = self._machine.create(
                    org_id=org_id,
                    datapoint_id=datapoint["datapoint_id"],
                    grain=datapoint["grain"],
                    scope_ref=None,
                    actor_id=actor_id,
                )
            elif state["status"] == "answered" and state.get("value") == value:
                continue

            if state["status"] == "unasked":
                state = self._machine.mark_asked(state, actor_id=actor_id)

            updated = self._machine.record_answer(
                state,
                value=value,
                actor_id=actor_id,
                answered_by="system",
                value_basis="derived",
            )
            if datapoint.get("provisional"):
                record = dict(updated)
                record["provisional_fields"] = sorted(value)
                self._states.save(record)
            assigned.append(datapoint["datapoint_id"])
        return assigned

    @staticmethod
    def _system_value(datapoint: dict[str, Any]) -> dict[str, Any] | None:
        """The value the platform assigns for a SYSTEM-class data point."""
        if datapoint["kind"] == "method_route":
            route = datapoint["method_route"]
            return {
                "source": route["source"],
                "default_route": route["default_route"],
                "conditional_routes": route["conditional_routes"],
                "routes_not_exposed": route["routes_not_exposed"],
                "verifier_overridable": True,
            }

        if datapoint["datapoint_id"] == "BND-2.6":
            # Taken from the emission factor library rather than invented. Still
            # provisional: Todd signs off the default before it is settled.
            gwp = default_gwp_set()
            return {
                "gwp_set_id": gwp["gwp_set_id"],
                "gwp_ar_edition": gwp["assessment_report"],
                "gwp_time_horizon": gwp["time_horizon_years"],
                "gwp_source": "reference-data/config/libraries/emission_factor_library.json",
                "gases_included": [
                    entry["chemical_formula"] for entry in gwp.get("values", [])
                ],
            }
        return None
