"""The profile page and its history (Phase E).

The living record a verifier reads. Two things matter more than the rest here:
the record must show *who* answered each thing, and it must never blur "we
screened for this and it is not here" with "this exists and we excluded it".
"""

from __future__ import annotations

import pytest

from intake.tests.conftest import company_payload, site_payload

STC = "S1STC-3.1"
BOUNDARY = "BND-2.3"
EXCLUSIONS = "BND-2.7"


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def seeded(harness):
    result = harness.seeded_org(sites=1)
    result["site_id"] = harness.sites.list_by_org(result["org_id"])[0]["site_id"]
    return result


def _answer(harness, org_id, datapoint, scope_ref, value, **kwargs) -> dict:
    state = harness.state(org_id, datapoint, scope_ref)
    if state["status"] == "unasked":
        state = harness.state_machine.mark_asked(state, actor_id="usr_1")
    return harness.state_machine.record_answer(
        state, value=value, actor_id="usr_1", **kwargs
    )


def _profile(harness, seeded) -> dict:
    return harness.profile_service.profile(seeded["org_id"])


def _entries(profile: dict, datapoint_id: str) -> list[dict]:
    return [
        entry
        for section in profile["sections"]
        for entry in section["datapoints"]
        if entry["datapoint_id"] == datapoint_id
    ]


# -- the company record -----------------------------------------------------


def test_an_unknown_company_has_no_profile(harness) -> None:
    assert harness.profile_service.profile("org_000000000000") is None


def test_the_company_block_is_the_seed_form_facts(harness, seeded) -> None:
    company = _profile(harness, seeded)["company"]
    assert company["legal_name"] == "Northlight Studios Ltd"
    assert company["reporting_period_start"] == "2025-01-01"
    assert company["responsible_party"]["email"] == "ada@northlight.example"
    assert company["profile_status"] == "seed_form_complete"


def test_sites_carry_what_was_deliberately_left_unset(harness, seeded) -> None:
    """Boundary fields are deferred on purpose; the page must say so."""
    site = _profile(harness, seeded)["sites"][0]
    assert site["site_name"] == "Stage 1"
    assert site["ownership"] == "leased"
    assert site["deferred_boundary_fields"]


def test_provisional_values_are_surfaced_with_who_signs_them_off(harness, seeded) -> None:
    provisional = _profile(harness, seeded)["provisional_values"]
    assert {item["field_id"] for item in provisional} >= {
        "fiscal_year_basis",
        "operational_status",
    }
    assert all(item["requires_signoff"] for item in provisional)


# -- every data point, with who answered it ---------------------------------


def test_each_answer_says_who_gave_it(harness, seeded) -> None:
    _answer(harness, seeded["org_id"], STC, seeded["site_id"], {"present": True})
    entry = _entries(_profile(harness, seeded), STC)[0]

    assert entry["status"] == "answered"
    assert entry["answered_by"] == "user"
    assert entry["answered_by_label"] == "the client"
    assert entry["actor_id"] == "usr_1"


def test_a_team_answer_is_attributed_to_the_team(harness, seeded) -> None:
    record = harness.escalation_service.open(
        org_id=seeded["org_id"],
        datapoint_id=STC,
        scope_ref=seeded["site_id"],
        trigger="user_requested_help",
        question_label="Does anything burn fuel here?",
        actor_id="usr_1",
    )
    harness.escalation_service.resolve(
        record["escalation_id"], value={"present": False}, actor_id="reviewer@sustentra.com"
    )
    entry = _entries(_profile(harness, seeded), STC)[0]

    assert entry["status"] == "resolved"
    assert entry["answered_by_label"] == "the Sustentra team"
    assert entry["actor_id"] == "reviewer@sustentra.com"
    assert entry["status_label"] == "Answered by the Sustentra team"


def test_a_question_with_the_team_shows_since_when(harness, seeded) -> None:
    harness.escalation_service.open(
        org_id=seeded["org_id"],
        datapoint_id=STC,
        scope_ref=seeded["site_id"],
        trigger="user_requested_help",
        question_label="Does anything burn fuel here?",
        actor_id="usr_1",
    )
    profile = _profile(harness, seeded)
    assert [entry["datapoint_id"] for entry in profile["with_the_team"]] == [STC]
    assert profile["with_the_team"][0]["with_team_since"]


def test_sections_are_ordered_and_counted(harness, seeded) -> None:
    profile = _profile(harness, seeded)
    orders = [section["order"] for section in profile["sections"]]
    assert orders == sorted(orders)
    for section in profile["sections"]:
        assert section["complete"] <= section["total"]


def test_the_coverage_meter_matches_the_interview(harness, seeded) -> None:
    profile = _profile(harness, seeded)
    assert profile["coverage"] == harness.coverage_service.coverage(seeded["org_id"])


# -- completeness records vs exclusions -------------------------------------


def test_a_screened_out_source_is_a_completeness_record(harness, seeded) -> None:
    state = harness.state(seeded["org_id"], STC, seeded["site_id"])
    state = harness.state_machine.mark_asked(state, actor_id="usr_1")
    harness.state_machine.record_not_present(state, actor_id="usr_1")

    profile = _profile(harness, seeded)
    assert [item["datapoint_id"] for item in profile["completeness_records"]] == [STC]
    assert profile["completeness_records"][0]["status_label"] == "Screened - not present here"


def test_a_screened_out_source_is_never_listed_as_an_exclusion(harness, seeded) -> None:
    """The distinction is the whole point: one means absent, one means omitted."""
    state = harness.state(seeded["org_id"], STC, seeded["site_id"])
    state = harness.state_machine.mark_asked(state, actor_id="usr_1")
    harness.state_machine.record_not_present(state, actor_id="usr_1")

    assert _profile(harness, seeded)["exclusions"] == []


def test_a_genuine_exclusion_is_listed_with_its_methodology_field(harness, seeded) -> None:
    _answer(
        harness,
        seeded["org_id"],
        EXCLUSIONS,
        None,
        {
            "excluded_source_id": "commuting",
            "exclusion_rationale": "Below the 5% significance threshold.",
        },
    )
    exclusions = _profile(harness, seeded)["exclusions"]

    assert len(exclusions) == 1
    assert exclusions[0]["methodology_field"] == "EXC-010"
    assert exclusions[0]["value"]["exclusion_rationale"].startswith("Below")


# -- boundary and uncertainty -----------------------------------------------


def test_boundary_decisions_are_pulled_out_for_the_verifier(harness, seeded) -> None:
    profile = _profile(harness, seeded)
    assert profile["boundary_decisions"]
    assert all(entry["section"] == "boundary" for entry in profile["boundary_decisions"])


def test_uncertainty_reports_how_a_value_was_obtained(harness, seeded) -> None:
    """ISO 14064-1 8.3: metered / invoiced / estimated is the input to the roll-up."""
    _answer(
        harness,
        seeded["org_id"],
        STC,
        seeded["site_id"],
        {"present": True},
        value_basis="invoiced",
    )
    uncertainty = _profile(harness, seeded)["uncertainty"]
    assert any(
        item["datapoint_id"] == STC and item["value_basis"] == "invoiced"
        for item in uncertainty
    )


# -- history ----------------------------------------------------------------


def test_history_reads_oldest_first(harness, seeded) -> None:
    _answer(harness, seeded["org_id"], STC, seeded["site_id"], {"present": True})
    entries = harness.profile_service.history(seeded["org_id"])["entries"]
    assert [entry["at"] for entry in entries] == sorted(entry["at"] for entry in entries)


def test_history_records_an_answer_changing(harness, seeded) -> None:
    _answer(harness, seeded["org_id"], STC, seeded["site_id"], {"present": True})
    entries = harness.profile_service.history(seeded["org_id"])["entries"]

    changes = [(entry["old_value"], entry["new_value"]) for entry in entries]
    assert ("asked", "answered") in changes


def test_history_records_a_changed_company_fact(harness, seeded) -> None:
    """The gap Phase E closes: facts were never audited, only answers."""
    harness.seed_form_service.submit(
        org_id=seeded["org_id"],
        submitted_by=seeded["owner"]["user_id"],
        payload={
            "company": company_payload(reporting_period_end="2025-11-30"),
            "sites": [site_payload(site_name="Stage 1")],
        },
    )
    entries = harness.profile_service.history(seeded["org_id"])["entries"]
    changed = [entry for entry in entries if entry["field"] == "reporting_period_end"]

    assert changed
    assert changed[-1]["old_value"] == "2025-12-31"
    assert changed[-1]["new_value"] == "2025-11-30"
    assert changed[-1]["action"] == "org_fact_changed"


def test_history_records_a_changed_site_fact(harness, seeded) -> None:
    site = harness.sites.list_by_org(seeded["org_id"])[0]
    harness.seed_form_service.submit(
        org_id=seeded["org_id"],
        submitted_by=seeded["owner"]["user_id"],
        payload={
            "company": company_payload(),
            "sites": [
                site_payload(
                    site_id=site["site_id"],
                    site_name="Stage 1",
                    ownership="owned",
                    lease_type=None,
                )
            ],
        },
    )
    entries = harness.profile_service.history(seeded["org_id"])["entries"]
    changed = [entry for entry in entries if entry["field"] == "ownership"]

    assert changed and changed[-1]["old_value"] == "leased"
    assert changed[-1]["new_value"] == "owned"
    assert changed[-1]["scope_label"] == "Stage 1"


def test_a_new_site_is_one_entry_not_nine(harness, seeded) -> None:
    entries = harness.profile_service.history(seeded["org_id"])["entries"]
    created = [entry for entry in entries if entry["action"] == "site_created"]
    assert len(created) == 1
    assert created[0]["new_value"] == "Stage 1"


def test_resubmitting_unchanged_records_nothing(harness, seeded) -> None:
    """Only real changes are history. Noise would bury the ones that matter."""
    site = harness.sites.list_by_org(seeded["org_id"])[0]
    before = harness.profile_service.history(seeded["org_id"])["count"]

    harness.seed_form_service.submit(
        org_id=seeded["org_id"],
        submitted_by=seeded["owner"]["user_id"],
        payload={
            "company": company_payload(),
            "sites": [site_payload(site_id=site["site_id"], site_name="Stage 1")],
        },
    )
    assert harness.profile_service.history(seeded["org_id"])["count"] == before


def test_history_can_be_limited_to_the_most_recent(harness, seeded) -> None:
    result = harness.profile_service.history(seeded["org_id"], limit=3)
    assert result["returned"] == 3
    assert result["count"] > 3


# -- over the API -----------------------------------------------------------


def test_the_profile_needs_a_sign_in(client) -> None:
    assert client.get("/v1/intake/profile").status_code == 401


def test_a_client_sees_their_own_profile(client) -> None:
    harness = client.harness
    harness.seeded_org(sites=1)
    token = harness.sign_in()

    body = client.get("/v1/intake/profile", headers=_auth(token)).json()
    assert body["company"]["legal_name"] == "Northlight Studios Ltd"


def test_a_client_cannot_read_another_companys_profile(client) -> None:
    harness = client.harness
    harness.seeded_org(sites=1)
    other = harness.create_org(legal_name="Harbour Post", email="two@example.com")
    token = harness.sign_in()

    response = client.get(
        f"/v1/intake/profile?org_id={other['org']['org_id']}", headers=_auth(token)
    )
    assert response.status_code == 403


def test_a_reviewer_can_read_any_profile(client) -> None:
    harness = client.harness
    seeded = harness.seeded_org(sites=1)
    other = harness.create_org(legal_name="Harbour Post", email="two@example.com")
    token = harness.reviewer_token(seeded["org_id"])

    response = client.get(
        f"/v1/intake/profile?org_id={other['org']['org_id']}", headers=_auth(token)
    )
    assert response.status_code == 200
    assert response.json()["company"]["legal_name"] == "Harbour Post"


def test_history_over_the_api(client) -> None:
    harness = client.harness
    harness.seeded_org(sites=1)
    token = harness.sign_in()

    body = client.get("/v1/intake/profile/history?limit=5", headers=_auth(token)).json()
    assert body["returned"] <= 5
    assert body["entries"]


def test_editing_a_fact_updates_the_answer_derived_from_it(harness, seeded) -> None:
    """The profile page must never show two different reporting periods.

    Seed-form answers are back-filled into datapoint states when the interview
    starts. Editing a fact afterwards used to update the company record and
    leave the derived answer behind, so the page showed the new period in the
    company block and the old one in the seed-form section.
    """
    harness.seed_form_service.submit(
        org_id=seeded["org_id"],
        submitted_by=seeded["owner"]["user_id"],
        payload={
            "company": company_payload(reporting_period_end="2025-11-30"),
            "sites": [site_payload(site_name="Stage 1")],
        },
    )
    profile = _profile(harness, seeded)
    period = _entries(profile, "SEED-1.6")[0]

    assert profile["company"]["reporting_period_end"] == "2025-11-30"
    assert period["value"]["reporting_period_end"] == "2025-11-30"


def test_a_derived_answer_is_not_attributed_to_a_person(harness, seeded) -> None:
    """The GWP set comes from the factor library, not from anybody's judgment."""
    entry = _entries(_profile(harness, seeded), "BND-2.6")[0]
    assert entry["answered_by"] == "system"
    assert entry["answered_by_label"] == "derived automatically"
