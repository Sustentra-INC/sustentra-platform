"""Records written by the services must satisfy their JSON contracts.

Contracts that nothing validates against are decoration. These tests run real
flows and check every persisted record, so the contracts stay honest.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from intake.tests.conftest import company_payload, site_payload

jsonschema = pytest.importorskip("jsonschema")

REPO_ROOT = Path(__file__).resolve().parents[3]
CONTRACTS = REPO_ROOT / "intake/contracts"


def _schema(name: str) -> dict:
    return json.loads((CONTRACTS / f"{name}.schema.json").read_text(encoding="utf-8"))


def _validate(name: str, record: dict) -> None:
    jsonschema.validate(instance=record, schema=_schema(name))


@pytest.fixture
def populated(harness):
    """Run a full flow so every record type exists."""
    created = harness.create_org()
    harness.sign_in()
    harness.seed_form_service.submit(
        org_id=created["org"]["org_id"],
        submitted_by=created["owner"]["user_id"],
        payload={"company": company_payload(), "sites": [site_payload()]},
    )
    return harness


@pytest.mark.parametrize(
    "name",
    ["org", "site", "user", "magic_link_token", "session", "seed_profile"],
)
def test_contracts_are_valid_json_schema(name: str) -> None:
    schema = _schema(name)
    jsonschema.validators.validator_for(schema).check_schema(schema)


def test_org_records_match_the_contract(populated) -> None:
    records = populated.orgs.list_records()
    assert records
    for record in records:
        _validate("org", record)


def test_org_before_the_seed_form_matches_the_contract(harness) -> None:
    """The awaiting_seed_form shape, with null seed fields, must be valid."""
    created = harness.create_org()
    _validate("org", created["org"])
    assert created["org"]["profile_status"] == "awaiting_seed_form"


def test_site_records_match_the_contract(populated) -> None:
    records = populated.sites.list_records()
    assert records
    for record in records:
        _validate("site", record)


def test_user_records_match_the_contract(populated) -> None:
    for record in populated.users.list_records():
        _validate("user", record)


def test_token_records_match_the_contract(populated) -> None:
    records = populated.tokens.list_records()
    assert records
    for record in records:
        _validate("magic_link_token", record)


def test_session_records_match_the_contract(populated) -> None:
    records = populated.sessions.list_records()
    assert records
    for record in records:
        _validate("session", record)


def test_seed_profile_records_match_the_contract(populated) -> None:
    records = populated.submissions.list_records()
    assert records
    for record in records:
        _validate("seed_profile", record)


def test_contract_rejects_an_invented_lease_type() -> None:
    """The contract enforces the workbook vocabulary, not just the service."""
    with pytest.raises(jsonschema.ValidationError):
        _validate(
            "site",
            {
                "site_id": "ste_0123456789ab",
                "org_id": "org_0123456789ab",
                "site_name": "X",
                "address": {
                    "address_line": "1 Road",
                    "city": "Town",
                    "state_region": "Region",
                    "postal_code": "0000",
                    "country_region": "Country",
                },
                "operational_status": "operating",
                "period_in_scope_start": "2025-01-01",
                "period_in_scope_end": "2025-12-31",
                "site_type": "office",
                "ownership": "leased",
                "lease_type": "peppercorn",
                "ownership_note": None,
                "created_at": "2026-08-13T09:00:00+00:00",
                "updated_at": "2026-08-13T09:00:00+00:00",
                "provisional_fields": [],
                "deferred_boundary_fields": [],
            },
        )


def test_contract_rejects_a_raw_token_in_place_of_a_hash() -> None:
    with pytest.raises(jsonschema.ValidationError):
        _validate(
            "magic_link_token",
            {
                "token_id": "mlt_" + "a" * 32,
                "email": "a@b.com",
                "token_hash": "this-is-clearly-a-raw-token",
                "created_at": "2026-08-13T09:00:00+00:00",
                "expires_at": "2026-08-13T09:15:00+00:00",
                "consumed_at": None,
            },
        )


# -- Phase C1 records -------------------------------------------------------


@pytest.fixture
def with_states(harness):
    """A fully initialised org with an escalation opened and resolved."""
    seeded = harness.seeded_org(sites=2)
    org_id = seeded["org_id"]
    site_id = harness.sites.list_by_org(org_id)[0]["site_id"]
    record = harness.escalation_service.open(
        org_id=org_id,
        datapoint_id="S1FUG-5.4",
        scope_ref=site_id,
        trigger="user_requested_help",
        question_label="On-site wastewater treatment?",
        actor_id="usr_1",
    )
    harness.escalation_service.resolve(
        record["escalation_id"], value={"present": False}, actor_id="rev_1", resolution_note="ok"
    )
    # A second, still-open escalation so both statuses are covered.
    harness.escalation_service.open(
        org_id=org_id,
        datapoint_id="S1FUG-5.4",
        scope_ref=harness.sites.list_by_org(org_id)[1]["site_id"],
        trigger="condition_met",
        question_label="On-site wastewater treatment?",
        actor_id="usr_1",
    )
    return harness


@pytest.mark.parametrize("name", ["datapoint_state", "audit_log", "escalation"])
def test_phase_c_contracts_are_valid_json_schema(name: str) -> None:
    schema = _schema(name)
    jsonschema.validators.validator_for(schema).check_schema(schema)


def test_datapoint_state_records_match_the_contract(with_states) -> None:
    records = with_states.states.list_records()
    assert records
    for record in records:
        _validate("datapoint_state", record)


def test_audit_log_records_match_the_contract(with_states) -> None:
    records = with_states.audit.list_records()
    assert records
    for record in records:
        _validate("audit_log", record)


def test_escalation_records_match_the_contract(with_states) -> None:
    records = with_states.escalations.list_records()
    assert records
    for record in records:
        _validate("escalation", record)


def test_contract_rejects_an_invented_status() -> None:
    with pytest.raises(jsonschema.ValidationError):
        _validate(
            "datapoint_state",
            {
                "state_id": "dps_0123456789ab",
                "org_id": "org_0123456789ab",
                "datapoint_id": "S1STC-3.1",
                "grain": "site",
                "scope_ref": "ste_0123456789ab",
                "status": "sort_of_answered",
                "value": None,
                "provenance": None,
                "uncertainty_tier": None,
                "escalation_id": None,
                "provisional_fields": [],
                "created_at": "2026-08-13T09:00:00+00:00",
                "updated_at": "2026-08-13T09:00:00+00:00",
                "updated_by": "usr_1",
            },
        )


def test_contract_requires_a_resolved_escalation_to_name_its_resolver() -> None:
    with pytest.raises(jsonschema.ValidationError):
        _validate(
            "escalation",
            {
                "escalation_id": "esc_0123456789ab",
                "ticket_version": 2,
                "org_id": "org_0123456789ab",
                "datapoint_id": "S1FUG-5.4",
                "scope_ref": None,
                "title": "x",
                "ticket_type": "clarification_request",
                "status": "resolved",
                "detection_origin": "system_detected",
                "trigger": "condition_met",
                "question_label": "x",
                "answer_attempts": [],
                "seed_context": {},
                "resolution_value": None,
                "resolved_by": None,
                "resolution_note": None,
                "audit_trail": [],
                "created_by": "usr_1",
                "created_at": "2026-08-13T09:00:00+00:00",
                "updated_at": "2026-08-13T09:00:00+00:00",
                "resolved_at": None,
            },
        )
