"""Watch the Phase D1 AI layer work, without calling a model.

Uses the scripted client, so this makes no paid calls and needs no API key. It
shows the four behaviours that matter:

  1) a confident reading is played back for the client, and nothing is stored
     until they confirm it
  2) an invented field is thrown away rather than written into the inventory
  3) a vague answer gets one clarifying question, and a second failure goes to
     a person
  4) a conflicting answer is caught by a rule, not by a model

    python intake/scripts/answer_parsing_smoke.py
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from intake.backend.adapters.llm import ScriptedLLMClient  # noqa: E402
from intake.backend.config import load_llm_config, load_settings, reset_caches  # noqa: E402
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
from intake.backend.services.answer_parser import AnswerParser  # noqa: E402
from intake.backend.services.applicability_service import ApplicabilityService  # noqa: E402
from intake.backend.services.contradiction_service import ContradictionService  # noqa: E402
from intake.backend.services.escalation_service import EscalationService  # noqa: E402
from intake.backend.services.explainer_service import ExplainerService  # noqa: E402
from intake.backend.services.interview_engine import InterviewEngine  # noqa: E402
from intake.backend.services.org_service import OrgService  # noqa: E402
from intake.backend.services.profile_state_service import ProfileStateService  # noqa: E402
from intake.backend.services.question_content import load_question_content  # noqa: E402
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
SITE = {
    "site_name": "Harbour Stages",
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
AC = "S1FUG-5.1"


def main() -> int:
    reset_caches()
    settings = load_settings()
    llm_config = load_llm_config()

    orgs, users, sites = InMemoryOrgRepository(), InMemoryUserRepository(), InMemorySiteRepository()
    submissions = InMemorySeedProfileRepository()
    states, audit = InMemoryDatapointStateRepository(), InMemoryAuditLogRepository()
    escalations = InMemoryEscalationRepository()

    machine = StateMachine(states, audit)
    applicability = ApplicabilityService()
    content = load_question_content()
    llm = ScriptedLLMClient()

    escalation_service = EscalationService(escalations, states, machine)
    profile_states = ProfileStateService(machine, states, orgs, sites, submissions)
    parser = AnswerParser(
        llm_client=llm,
        state_repository=states,
        org_repository=orgs,
        site_repository=sites,
        state_machine=machine,
        escalations=escalation_service,
        question_content=content,
    )
    engine = InterviewEngine(
        state_repository=states,
        org_repository=orgs,
        site_repository=sites,
        state_machine=machine,
        applicability=applicability,
        escalations=escalation_service,
        profile_states=profile_states,
        settings=settings,
        contradictions=ContradictionService(applicability),
        explainers=ExplainerService(llm, orgs, sites, content),
    )

    created = OrgService(orgs, users, sites, settings=settings).create_org(
        legal_name="Northlight Studios",
        owner_name="Sam Owner",
        owner_email="sam@northlight.example",
        created_by="internal@sustentra.com",
    )
    org_id, user_id = created["org"]["org_id"], created["owner"]["user_id"]
    SeedFormService(orgs, sites, submissions, None, settings=settings).submit(
        org_id=org_id, submitted_by=user_id, payload={"company": COMPANY, "sites": [SITE]}
    )
    profile_states.initialise(org_id, actor_id=user_id)
    site_id = sites.list_by_org(org_id)[0]["site_id"]

    print(f"model adapter: {llm_config['adapter']} (default) - this run uses a scripted "
          f"stand-in and makes no paid calls")
    print(f"accept threshold: {llm_config['confidence']['accept_threshold']}  |  "
          f"call budget: {llm_config['max_calls_per_turn']} per turn\n")

    print("1) the client types an answer in their own words")
    typed = "we've got about a dozen aircon units, the R-410A ones, and we get them serviced"
    print(f'   "{typed}"')
    llm.queue("parse_answer", {
        "fields": {"present": True, "equipment_count": 12, "gas_type": "R-410A",
                   "has_service_records": True},
        "confidence": 0.93,
        "summary": "Twelve air conditioning units using R-410A, with service records.",
        "unresolved": [],
        "clarifying_question": None,
    })
    outcome = parser.parse(org_id, AC, site_id, typed, actor_id=user_id, settings=settings)
    print(f"   -> {outcome.status} (confidence {outcome.confidence})")
    print(f"   -> played back to them: \"{outcome.summary}\"")
    print(f"   -> stored so far: {states.find(org_id, AC, site_id)['status']} "
          f"(nothing is written until they confirm)")

    print("\n2) they confirm, and only then is it recorded")
    engine.submit_answer(org_id, AC, site_id, outcome.proposal, actor_id=user_id, ai_assisted=True)
    state = states.find(org_id, AC, site_id)
    print(f"   -> {state['status']}, answered_by {state['provenance']['answered_by']}, "
          f"ai_assisted {state['ai_assisted']}")

    print("\n3) a model that invents a field gets it thrown away")
    llm.queue("parse_answer", {
        "fields": {"present": True, "annual_emissions_tco2e": 41.2, "gas_type": "R-134a"},
        "confidence": 0.95,
        "summary": "Refrigerant R-134a.",
        "unresolved": [],
        "clarifying_question": None,
    })
    invented = parser.parse(org_id, AC, site_id, "the R-134a ones", actor_id=user_id,
                            settings=settings)
    print(f"   proposed fields kept   : {sorted(invented.proposal)}")
    print(f"   dropped as not real    : {invented.dropped_fields}")

    print("\n4) a vague answer gets one clarifying question, then a person")
    fug = "S1FUG-5.2"
    llm.queue("parse_answer", {
        "fields": {}, "confidence": 0.25, "summary": "",
        "unresolved": ["present"],
        "clarifying_question": "Is it a sprinkler system, or one that releases a gas?",
    })
    first = parser.parse(org_id, fug, site_id, "there's some fire thing", actor_id=user_id,
                         settings=settings)
    print(f"   attempt 1 -> {first.status}: \"{first.clarifying_question}\"")

    llm.queue("parse_answer", {
        "fields": {}, "confidence": 0.3, "summary": "", "unresolved": ["present"],
        "clarifying_question": None,
    })
    second = parser.parse(org_id, fug, site_id, "honestly not sure", actor_id=user_id,
                          settings=settings)
    print(f"   attempt 2 -> {second.status}: {second.message}")
    print(f"   escalation trigger      : {second.escalation['trigger']}")

    print("\n5) a conflicting answer is caught by a rule, not by a model")
    calls_before = len(llm.calls)
    result = engine.submit_answer(
        org_id, "S2-6.2", site_id,
        {"present": False, "allocation_basis": "floor_area"}, actor_id=user_id,
    )
    print(f"   -> escalated: {result['escalated']} ({result['escalation']['trigger']})")
    print(f"   -> we tell them: \"{result['escalation']['client_message']}\"")
    print(f"   -> model calls used to detect it: {len(llm.calls) - calls_before}")

    print("\n6) boundary answers always go to a person for confirmation")
    boundary = engine.submit_answer(
        org_id, "BND-2.1", None,
        {"consolidation_approach": "operational_control"}, actor_id=user_id,
    )
    print(f"   -> {boundary['escalation']['trigger']} "
          f"(policy: {settings.escalation.human_class_policy})")

    print(f"\nopen with the team: {len(escalation_service.list_open(org_id))}")
    print(f"model calls this run: {len(llm.calls)}")
    print("\nparsing smoke complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
