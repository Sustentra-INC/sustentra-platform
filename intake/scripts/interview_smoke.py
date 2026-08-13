"""Play a whole guided interview in one command, start to finish.

No server, no database, no email, no AI. Shows what a client would actually
experience: questions chosen for them, a progress meter that reflects what is
genuinely left, "Not sure" handled gracefully, and answers that route
themselves to a human when the methodology says they must.

    python intake/scripts/interview_smoke.py
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
from intake.backend.services.coverage_service import CoverageService  # noqa: E402
from intake.backend.services.escalation_service import EscalationService  # noqa: E402
from intake.backend.services.interview_engine import InterviewEngine  # noqa: E402
from intake.backend.services.org_service import OrgService  # noqa: E402
from intake.backend.services.profile_state_service import ProfileStateService  # noqa: E402
from intake.backend.services.seed_form_service import SeedFormService  # noqa: E402
from intake.backend.services.state_machine import StateMachine  # noqa: E402

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

# How our imaginary studio answers. Anything not listed is answered "no".
SCRIPTED: dict[str, dict] = {
    "BND-2.1": {"consolidation_approach": "operational_control"},
    "BND-2.3": {"party_role": "lessee", "operational_control_over_asset_flag": True},
    "BND-2.4": {"prior_inventories": False, "base_year": 2025},
    "BND-2.7": {},  # accepts the templated statement
    "S1STC-3.1": {"present": True, "equipment": ["Gas boiler", "Kitchen range"]},
    "S1STC-3.2": {"present": True, "generators": ["Stage 4 standby"], "separately_metered": False,
                  "operating_hours": 40},
    "S1STC-3.3": {"present": True, "blend_source": "B20 renewable diesel"},
    "S1MOB-4.1": {"present": True, "fleet_groups": ["Shuttle vans", "Forklifts"],
                  "vehicle_type": "vans and forklifts"},
    "S1MOB-4.3": {"selected_co2_calculation_method": "fuel_based"},
    "S1FUG-5.1": {"present": True, "equipment_count": 12, "gas_type": "R-410A",
                  "has_service_records": True},
    "S1FUG-5.4": {"present": True, "description": "Small on-site treatment plant"},
    "S2-6.1": {"supplier_name": "Meridian", "utility_account_id": "ACC-99182", "meter_count": 3},
    "S2-6.2": {"present": True, "allocation_basis": "floor_area",
               "reporter_floor_area": 2400, "total_building_area": 6000},
    "S2-6.4": {"present": True, "distribution_scenario": "mixed_onsite_and_grid",
               "sells_energy_or_attributes": True},
    "S2-6.5": {"present": True, "instrument_type": "New Zealand Energy Certificates"},
}

NOT_SURE = {"BND-2.5"}  # the one our studio genuinely does not know


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


def _default_answer(question: dict) -> dict:
    """Everything else: 'no' to screenings, minimum valid values elsewhere."""
    answer = {"present": False} if question["answer_shape"] == "yes_no" else {}
    for field in question["fields"]:
        if not field.get("required") or field.get("reveal_when"):
            continue
        answer[field["field_id"]] = {
            "yes_no": False,
            "number": 1,
            "list": ["Not specified"],
            "date": "2025-06-01",
            "select": (field.get("options") or [{"value": ""}])[0]["value"],
        }.get(field["input"], "Not specified")
    return answer


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
    escalation_service = EscalationService(escalations, states, machine)
    engine = InterviewEngine(
        state_repository=states,
        org_repository=orgs,
        site_repository=sites,
        state_machine=machine,
        applicability=ApplicabilityService(),
        escalations=escalation_service,
        profile_states=profile_states,
        settings=settings,
    )
    coverage_service = CoverageService(engine)

    created = org_service.create_org(
        legal_name="Northlight Studios",
        owner_name="Sam Owner",
        owner_email="sam@northlight.example",
        created_by="internal@sustentra.com",
    )
    org_id, user_id = created["org"]["org_id"], created["owner"]["user_id"]
    seed_form.submit(
        org_id=org_id,
        submitted_by=user_id,
        payload={
            "company": COMPANY,
            "sites": [
                _site("Harbour Stages"),
                _site("Kilbirnie Workshop", ownership="owned", lease_type="",
                      site_type="workshop"),
            ],
        },
    )
    profile_states.initialise(org_id, actor_id=user_id)

    start = coverage_service.coverage(org_id)
    print(f"Two sites. Starting at: {start['label']}\n")

    asked = 0
    while (question := engine.next_question(org_id)) is not None:
        asked += 1
        if asked > 120:
            print("  (stopping: the interview did not converge)")
            break

        where = f" [{question['scope_label']}]" if question["scope_label"] else ""
        print(f"{asked:2}.{where} {question['question']}")

        if question["datapoint_id"] in NOT_SURE:
            result = engine.not_sure(
                org_id, question["datapoint_id"], question["scope_ref"], actor_id=user_id
            )
            print(f"     -> Not sure. {result['message']}")
            continue

        scripted = SCRIPTED.get(question["datapoint_id"])
        answer = {**_default_answer(question), **scripted} if scripted else _default_answer(question)
        result = engine.submit_answer(
            org_id, question["datapoint_id"], question["scope_ref"], answer, actor_id=user_id
        )

        summary = {
            "not_present": "No - recorded as screened, not present",
            "answered": "Answered",
        }.get(result["status"], result["status"])
        print(f"     -> {summary}", end="")
        if result["escalated"]:
            print(" | sent to the Sustentra team (methodology requires a human)", end="")
        if result["created_scopes"]:
            print(f" | {len(result['created_scopes'])} follow-up question(s) added", end="")
        print()

    final = coverage_service.coverage(org_id)
    print(f"\n{final['label']}  ({final['escalated']} with the team)")
    print("\nBy section:")
    for section in final["sections"]:
        print(f"  {section['label']:32} {section['complete']:2}/{section['total']}")

    print("\nWith the Sustentra team:")
    for record in escalation_service.list_open(org_id):
        print(f"  {record['datapoint_id']:10} {record['trigger']:22} {record['title'][:46]}")

    not_present = [s for s in states.list_by_org(org_id) if s["status"] == "not_present"]
    print(f"\nScreened and not present: {len(not_present)} "
          f"(completeness records, not exclusions)")
    print(f"Audit entries written   : {len(audit.list_by_org(org_id))}")
    print("\ninterview smoke complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
