"""Watch the Phase C1 state layer work, end to end, in one command.

No server, no database, no email. Shows the four things C1 adds:

  1) states instantiated per site, and the seed form back-filled
  2) a screening "no" recorded as a completeness record, not an exclusion
  3) applicability switching a follow-up question on, deterministically
  4) an escalation opened and resolved by the team, with the audit trail

    python intake/scripts/interview_state_smoke.py
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from intake.backend.config import load_settings, reset_caches  # noqa: E402
from intake.backend.repositories.audit_log_repository import (  # noqa: E402
    InMemoryAuditLogRepository,
)
from intake.backend.repositories.datapoint_state_repository import (  # noqa: E402
    InMemoryDatapointStateRepository,
)
from intake.backend.repositories.escalation_repository import (  # noqa: E402
    InMemoryEscalationRepository,
)
from intake.backend.repositories.org_repository import InMemoryOrgRepository  # noqa: E402
from intake.backend.repositories.seed_profile_repository import (  # noqa: E402
    InMemorySeedProfileRepository,
)
from intake.backend.repositories.site_repository import InMemorySiteRepository  # noqa: E402
from intake.backend.repositories.user_repository import InMemoryUserRepository  # noqa: E402
from intake.backend.services.applicability_service import ApplicabilityService  # noqa: E402
from intake.backend.services.escalation_service import EscalationService  # noqa: E402
from intake.backend.services.org_service import OrgService  # noqa: E402
from intake.backend.services.profile_state_service import ProfileStateService  # noqa: E402
from intake.backend.services.seed_form_service import SeedFormService  # noqa: E402
from intake.backend.services.state_machine import StateMachine, TransitionError  # noqa: E402

COMPANY = {
    "legal_name": "Northlight Studios Ltd",
    "reporting_year": 2025,
    "responsible_party_name": "Ada Reyes",
    "responsible_party_role": "Facilities Director",
    "responsible_party_email": "ada.reyes@northlight.example",
    "industry": "film_production_facility",
    "reporting_period_start": "2025-01-01",
    "reporting_period_end": "2025-12-31",
    "fiscal_year_basis": "calendar year",
}


def _site(name: str, **overrides) -> dict:
    site = {
        "site_name": name,
        "address_line": "12 Harbour Road",
        "city": "Wellington",
        "state_region": "Wellington",
        "postal_code": "6011",
        "country_region": "New Zealand",
        "operational_status": "operating all year",
        "site_type": "soundstage_complex",
        "ownership": "leased",
        "lease_type": "operating",
    }
    site.update(overrides)
    return site


def main() -> int:
    reset_caches()
    settings = load_settings()

    orgs, users, sites = InMemoryOrgRepository(), InMemoryUserRepository(), InMemorySiteRepository()
    submissions = InMemorySeedProfileRepository()
    states, audit = InMemoryDatapointStateRepository(), InMemoryAuditLogRepository()
    escalations = InMemoryEscalationRepository()

    machine = StateMachine(states, audit)
    org_service = OrgService(orgs, users, sites, settings=settings)
    seed_form = SeedFormService(orgs, sites, submissions, None, settings=settings)
    profile_states = ProfileStateService(machine, states, orgs, sites, submissions)
    applicability = ApplicabilityService()
    escalation_service = EscalationService(escalations, states, machine)

    print("1) company, two sites, seed form submitted")
    created = org_service.create_org(
        legal_name="Northlight Studios",
        owner_name="Sam Owner",
        owner_email="sam@northlight.example",
        created_by="internal@sustentra.com",
    )
    org_id = created["org"]["org_id"]
    user_id = created["owner"]["user_id"]
    seed_form.submit(
        org_id=org_id,
        submitted_by=user_id,
        payload={
            "company": COMPANY,
            "sites": [_site("Harbour Stages"), _site("Kilbirnie Workshop", ownership="owned",
                                                    lease_type="", site_type="workshop")],
        },
    )

    print("2) initialising the profile state")
    summary = profile_states.initialise(org_id, actor_id=user_id)
    print(f"   sites               : {summary['sites']}")
    print(f"   states created      : {len(summary['instantiated'])}")
    print(f"   seed answers filled : {len(summary['backfilled'])}")
    print(f"   system-assigned     : {', '.join(summary['system_assigned'])}")
    print(f"   total states        : {summary['states_total']}")

    site_ids = [site["site_id"] for site in sites.list_by_org(org_id)]
    per_site = len(states.list_by_scope(org_id, site_ids[0]))
    print(f"   each site carries its own copy of {per_site} data points")

    profile = orgs.get(org_id)

    def applicable(condition: str, scope: str | None) -> bool:
        return applicability.is_applicable(
            condition, profile=profile, states=states.list_by_org(org_id), scope_ref=scope
        )

    print("\n3) screening: 'any equipment that burns fuel?'")
    for label, site_id, answer in (
        ("Harbour Stages", site_ids[0], True),
        ("Kilbirnie Workshop", site_ids[1], False),
    ):
        state = machine.mark_asked(states.find(org_id, "S1STC-3.1", site_id), actor_id=user_id)
        if answer:
            machine.record_answer(state, {"present": True}, actor_id=user_id)
            print(f"   {label:20} yes -> status answered")
        else:
            machine.record_not_present(state, actor_id=user_id, source_category="STC")
            print(f"   {label:20} no  -> status not_present "
                  f"(completeness record, NOT an exclusion)")

    print("\n4) applicability decides the biogenic-fuel follow-up (deterministic, no AI)")
    for label, site_id in (("Harbour Stages", site_ids[0]), ("Kilbirnie Workshop", site_ids[1])):
        shown = applicable("stationary_or_mobile_fuel_present", site_id)
        print(f"   S1STC-3.3 at {label:20} -> {'asked' if shown else 'skipped'}")

    print("\n5) 'Not sure' on a boundary question")
    site_id = site_ids[0]
    escalation = escalation_service.open(
        org_id=org_id,
        datapoint_id="S1FUG-5.4",
        scope_ref=site_id,
        trigger="user_requested_help",
        question_label="On-site wastewater treatment or other industrial processes?",
        actor_id=user_id,
        answer_attempts=[{"attempt": 1, "text": "not sure"}],
        seed_context={"legal_name": COMPANY["legal_name"], "site": "Harbour Stages"},
    )
    print(f"   escalation {escalation['escalation_id']} -> {escalation['status']}")
    print(f"   ticket_type          : {escalation['ticket_type']}")
    blocked = escalation_service.blocked_datapoints(org_id)
    print(f"   blocked data points  : {len(blocked)} (the interview itself keeps going)")

    print("\n6) the team resolves it in-platform")
    escalation_service.resolve(
        escalation["escalation_id"],
        value={"present": False},
        actor_id="reviewer@sustentra.com",
        resolution_note="No process sources at this site; confirmed with the client.",
    )
    resolved = states.find(org_id, "S1FUG-5.4", site_id)
    print(f"   status               : {resolved['status']}")
    print(f"   answered by          : {resolved['provenance']['answered_by']}")
    print(f"   open escalations     : {len(escalation_service.list_open(org_id))}")

    print("\n7) illegal transitions are refused")
    try:
        machine.transition(resolved, "answered", actor_id=user_id)
    except TransitionError as exc:
        print(f"   {exc}")

    print("\n8) audit trail for that question")
    for entry in audit.list_for_datapoint(org_id, "S1FUG-5.4", site_id):
        if entry["field"] == "status":
            print(f"   {entry['at'][11:19]}  {entry['old_value']:>10} -> {entry['new_value']:<10}"
                  f"  by {entry['actor_id']}")

    print("\nstate-layer smoke complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
