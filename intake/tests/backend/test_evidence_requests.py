"""Expected documents (Phase E).

The checklist that tells S1 what should arrive. These tests are mostly about the
three things it must never do: ask for documents the client never said existed,
invent an expected count, or let S1 start on something resting on an unconfirmed
boundary decision.
"""

from __future__ import annotations

import pytest

STC = "S1STC-3.1"  # "Is there anything at this site that burns fuel?"
METERS = "S2-6.1"  # electricity supplier + meter count
FUG = "S1FUG-5.1"  # refrigeration equipment
BOUNDARY = "BND-2.3"  # who controls the site - HUMAN class


@pytest.fixture
def seeded(harness):
    result = harness.seeded_org(sites=1)
    result["site_id"] = harness.sites.list_by_org(result["org_id"])[0]["site_id"]
    return result


def _answer(harness, seeded, datapoint: str, value: dict) -> dict:
    """Write an answer straight through the state machine."""
    state = harness.state(seeded["org_id"], datapoint, seeded["site_id"])
    if state["status"] == "unasked":
        state = harness.state_machine.mark_asked(state, actor_id="usr_1")
    return harness.state_machine.record_answer(
        state, value=value, actor_id="usr_1", answered_by="user"
    )


def _screen_out(harness, seeded, datapoint: str) -> dict:
    state = harness.state(seeded["org_id"], datapoint, seeded["site_id"])
    if state["status"] == "unasked":
        state = harness.state_machine.mark_asked(state, actor_id="usr_1")
    return harness.state_machine.record_not_present(state, actor_id="usr_1")


def _compile(harness, seeded) -> list[dict]:
    return harness.evidence_request_service.compile(seeded["org_id"])


def _for_type(items: list[dict], evidence_type_id: str) -> list[dict]:
    return [item for item in items if item["evidence_type_id"] == evidence_type_id]


# -- nothing is requested without an answer ---------------------------------


def test_only_what_the_seed_form_established_is_asked_for(harness, seeded) -> None:
    """We do not chase documents for sources nobody has confirmed exist.

    A freshly seeded client has answered exactly one thing: their sites exist.
    That legitimately calls for a facility register (SEED-1.3 -> J2-007) and
    nothing else - no fuel, no bills, no service records.
    """
    assert {item["evidence_type_id"] for item in _compile(harness, seeded)} == {"J2-007"}


def test_a_screening_no_asks_for_nothing(harness, seeded) -> None:
    """'No, we have none' is a completeness record, not a document request."""
    _screen_out(harness, seeded, STC)
    assert _for_type(_compile(harness, seeded), "J2-001") == []


def test_a_screening_yes_asks_for_the_mapped_documents(harness, seeded) -> None:
    _answer(harness, seeded, STC, {"present": True, "equipment": ["Boiler"]})
    items = _compile(harness, seeded)

    # The mapping gives S1STC-3.1 -> J2-008, J2-001, J2-003. Nothing else.
    # J2-007 is already there from the seed form, so it is excluded here.
    triggered = {
        item["evidence_type_id"]
        for item in items
        if any(entry["datapoint_id"] == STC for entry in item["requested_by"])
    }
    assert triggered == {"J2-008", "J2-001", "J2-003"}
    assert all(item["scope_label"] == "Stage 1" for item in items)


def test_the_document_name_comes_from_the_methodology_library(harness, seeded) -> None:
    """Never restated in intake config - one definition of what a J2 type is."""
    _answer(harness, seeded, METERS, {"supplier_name": "Meridian", "meter_count": 1})
    bills = _for_type(_compile(harness, seeded), "J2-002")
    assert bills and bills[0]["evidence_type_name"] == "Electricity bill"


# -- cadence: sourced where it exists, honest where it does not -------------


def test_electricity_is_monthly_because_the_mapping_says_so(harness, seeded) -> None:
    _answer(harness, seeded, METERS, {"supplier_name": "Meridian", "meter_count": 1})
    bills = _for_type(_compile(harness, seeded), "J2-002")

    assert len(bills) == 12
    assert bills[0]["cadence"] == "monthly"
    assert bills[0]["cadence_provisional"] is False
    assert bills[0]["expected_count_known"] is True
    assert {item["period_label"] for item in bills} >= {"January 2025", "December 2025"}


def test_twelve_months_per_meter(harness, seeded) -> None:
    """Mapping section 6.1: 'J2-002 x12 months per meter'."""
    _answer(harness, seeded, METERS, {"supplier_name": "Meridian", "meter_count": 3})
    bills = _for_type(_compile(harness, seeded), "J2-002")

    assert len(bills) == 36
    assert {item["unit_index"] for item in bills} == {1, 2, 3}
    assert bills[0]["unit_label"] == "meter 1"


def test_an_unknown_cadence_is_one_open_request_flagged_provisional(harness, seeded) -> None:
    """Nothing in the repo says how often fuel is delivered, so we do not guess."""
    _answer(harness, seeded, STC, {"present": True, "equipment": ["Boiler"]})
    deliveries = _for_type(_compile(harness, seeded), "J2-003")

    assert len(deliveries) == 1
    assert deliveries[0]["cadence"] == "as_available"
    assert deliveries[0]["cadence_provisional"] is True
    assert deliveries[0]["expected_count_known"] is False


def test_a_missing_meter_count_asks_for_one_rather_than_none(harness, seeded) -> None:
    _answer(harness, seeded, METERS, {"supplier_name": "Meridian"})
    bills = _for_type(_compile(harness, seeded), "J2-002")
    assert len(bills) == 12
    assert {item["unit_index"] for item in bills} == {1}


# -- recompiling ------------------------------------------------------------


def test_recompiling_does_not_duplicate(harness, seeded) -> None:
    _answer(harness, seeded, METERS, {"supplier_name": "Meridian", "meter_count": 1})
    first = _compile(harness, seeded)
    second = _compile(harness, seeded)

    assert len(first) == len(second)
    assert [item["evidence_request_id"] for item in first] == [
        item["evidence_request_id"] for item in second
    ]


def test_recompiling_writes_nothing_when_nothing_changed(harness, seeded) -> None:
    """Otherwise the history fills with records saying nothing happened."""
    _answer(harness, seeded, METERS, {"supplier_name": "Meridian", "meter_count": 1})
    _compile(harness, seeded)
    before = len(harness.evidence_requests.list_records())

    _compile(harness, seeded)
    assert len(harness.evidence_requests.list_records()) == before


def test_recompiling_keeps_a_status_someone_set(harness, seeded) -> None:
    """A received document must not be forgotten because a later answer arrived."""
    _answer(harness, seeded, METERS, {"supplier_name": "Meridian", "meter_count": 1})
    first = _compile(harness, seeded)[0]
    harness.evidence_requests.save({**first, "status": "received"})

    _answer(harness, seeded, STC, {"present": True, "equipment": ["Boiler"]})
    again = harness.evidence_requests.get(first["evidence_request_id"])
    _compile(harness, seeded)

    assert again["status"] == "received"
    assert (
        harness.evidence_requests.get(first["evidence_request_id"])["status"] == "received"
    )


def test_a_later_answer_adds_to_the_list(harness, seeded) -> None:
    _answer(harness, seeded, METERS, {"supplier_name": "Meridian", "meter_count": 1})
    before = len(_compile(harness, seeded))

    _answer(harness, seeded, FUG, {"present": True, "equipment_count": 2})
    assert len(_compile(harness, seeded)) > before


def test_one_document_serving_two_questions_is_one_request(harness, seeded) -> None:
    """J2-008 is triggered by fuel equipment and by refrigeration alike."""
    _answer(harness, seeded, STC, {"present": True, "equipment": ["Boiler"]})
    _answer(harness, seeded, FUG, {"present": True, "equipment_count": 2})

    equipment_lists = _for_type(_compile(harness, seeded), "J2-008")
    assert len(equipment_lists) == 1
    assert {item["datapoint_id"] for item in equipment_lists[0]["requested_by"]} == {STC, FUG}


# -- Stage 5: what S1 may start on ------------------------------------------


def test_a_plain_answer_is_safe_to_parse(harness, seeded) -> None:
    _answer(harness, seeded, METERS, {"supplier_name": "Meridian", "meter_count": 1})
    bills = _for_type(_compile(harness, seeded), "J2-002")
    assert all(item["safe_to_parse"] for item in bills)
    assert all(item["blocked_by"] == [] for item in bills)


def test_an_open_escalation_holds_its_own_documents(harness, seeded) -> None:
    _answer(harness, seeded, METERS, {"supplier_name": "Meridian", "meter_count": 1})
    harness.escalation_service.open(
        org_id=seeded["org_id"],
        datapoint_id=METERS,
        scope_ref=seeded["site_id"],
        trigger="contradiction",
        question_label="Who supplies electricity?",
        actor_id="usr_1",
    )
    bills = _for_type(_compile(harness, seeded), "J2-002")
    assert bills and not any(item["safe_to_parse"] for item in bills)
    assert "with our team" in bills[0]["blocked_by"][0]["reason"]


def test_an_unconfirmed_boundary_holds_everything_at_that_site(harness, seeded) -> None:
    """SPEC Stage 5: boundary answers are human-confirmed before anything depends on them."""
    _answer(harness, seeded, METERS, {"supplier_name": "Meridian", "meter_count": 1})
    harness.escalation_service.open(
        org_id=seeded["org_id"],
        datapoint_id=BOUNDARY,
        scope_ref=seeded["site_id"],
        trigger="human_class_datapoint",
        question_label="Who controls this site?",
        actor_id="usr_1",
    )
    bills = _for_type(_compile(harness, seeded), "J2-002")
    assert not any(item["safe_to_parse"] for item in bills)
    assert any("boundary decision" in block["reason"] for block in bills[0]["blocked_by"])


def test_resolving_the_boundary_releases_the_documents(harness, seeded) -> None:
    _answer(harness, seeded, METERS, {"supplier_name": "Meridian", "meter_count": 1})
    record = harness.escalation_service.open(
        org_id=seeded["org_id"],
        datapoint_id=BOUNDARY,
        scope_ref=seeded["site_id"],
        trigger="human_class_datapoint",
        question_label="Who controls this site?",
        actor_id="usr_1",
    )
    assert not any(item["safe_to_parse"] for item in _compile(harness, seeded))

    harness.escalation_service.resolve(
        record["escalation_id"],
        value={"party_role": "lessee", "operational_control_over_asset_flag": True},
        actor_id="reviewer@sustentra.com",
    )
    bills = _for_type(_compile(harness, seeded), "J2-002")
    assert all(item["safe_to_parse"] for item in bills)


def test_a_human_class_answer_is_not_safe_until_confirmed(harness, seeded) -> None:
    """Answered by the client is not the same as confirmed by a person."""
    _answer(
        harness,
        seeded,
        BOUNDARY,
        {"party_role": "lessee", "operational_control_over_asset_flag": True},
    )
    registers = _for_type(_compile(harness, seeded), "J2-007")
    assert registers and not any(item["safe_to_parse"] for item in registers)


def test_a_blocked_request_always_says_why(harness, seeded) -> None:
    """The contract requires it; an unexplained block is unactionable."""
    _answer(harness, seeded, METERS, {"supplier_name": "Meridian", "meter_count": 1})
    harness.escalation_service.open(
        org_id=seeded["org_id"],
        datapoint_id=BOUNDARY,
        scope_ref=seeded["site_id"],
        trigger="human_class_datapoint",
        question_label="Who controls this site?",
        actor_id="usr_1",
    )
    for item in _compile(harness, seeded):
        if not item["safe_to_parse"]:
            assert item["blocked_by"]


# -- the completeness spec --------------------------------------------------


def test_the_spec_counts_what_it_knows(harness, seeded) -> None:
    _answer(harness, seeded, METERS, {"supplier_name": "Meridian", "meter_count": 2})
    _compile(harness, seeded)
    spec = harness.evidence_request_service.completeness_spec(seeded["org_id"])

    electricity = next(
        item
        for scope in spec["scopes"]
        for item in scope["expected"]
        if item["evidence_type_id"] == "J2-002"
    )
    assert electricity["expected_documents"] == 24  # 12 months x 2 meters
    # Plus the site's facility register, which is annual and therefore counted.
    assert spec["totals"]["expected_documents_known"] == 25


def test_an_unknown_cadence_is_null_not_zero(harness, seeded) -> None:
    """A gate that reads null as zero would pass a client who sent nothing."""
    _answer(harness, seeded, STC, {"present": True, "equipment": ["Boiler"]})
    _compile(harness, seeded)
    spec = harness.evidence_request_service.completeness_spec(seeded["org_id"])

    deliveries = next(
        item
        for scope in spec["scopes"]
        for item in scope["expected"]
        if item["evidence_type_id"] == "J2-003"
    )
    assert deliveries["expected_documents"] is None
    assert deliveries["cadence_provisional"] is True
    assert "not zero" in spec["caveat"]


def test_the_spec_is_grouped_by_site(harness) -> None:
    seeded = harness.seeded_org(sites=2)
    sites = harness.sites.list_by_org(seeded["org_id"])
    for site in sites:
        state = harness.state(seeded["org_id"], METERS, site["site_id"])
        state = harness.state_machine.mark_asked(state, actor_id="usr_1")
        harness.state_machine.record_answer(
            state,
            value={"supplier_name": "Meridian", "meter_count": 1},
            actor_id="usr_1",
        )

    harness.evidence_request_service.compile(seeded["org_id"])
    spec = harness.evidence_request_service.completeness_spec(seeded["org_id"])
    assert {scope["scope_label"] for scope in spec["scopes"]} == {"Stage 1", "Stage 2"}


def test_no_reporting_period_means_no_requests(harness) -> None:
    """An org created but never seeded has no period to request documents for."""
    created = harness.create_org()
    assert harness.evidence_request_service.compile(created["org"]["org_id"]) == []
