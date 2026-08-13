"""Seed form definition, validation and persistence."""

from __future__ import annotations

import pytest

from intake.tests.conftest import company_payload, site_payload
from intake.backend.services.seed_form_service import SeedFormValidationError


def _submit(harness, company=None, sites=None):
    org = harness.create_org()["org"]
    return harness.seed_form_service.submit(
        org_id=org["org_id"],
        submitted_by="usr_test",
        payload={
            "company": company_payload() if company is None else company,
            "sites": [site_payload()] if sites is None else sites,
        },
    )


def _errors(harness, company=None, sites=None) -> list[dict]:
    with pytest.raises(SeedFormValidationError) as exc:
        _submit(harness, company, sites)
    return exc.value.errors


def _fields(errors: list[dict]) -> set[str]:
    return {error["field"] for error in errors}


# -- form definition --------------------------------------------------------


def test_form_exposes_both_steps(harness) -> None:
    form = harness.seed_form_service.get_form("film")
    assert [step["step_id"] for step in form["steps"]] == ["company", "sites"]


def test_industry_options_come_from_settings(harness) -> None:
    form = harness.seed_form_service.get_form("film")
    industry = next(
        field
        for step in form["steps"]
        for field in step["fields"]
        if field["field_id"] == "industry"
    )
    assert {option["value"] for option in industry["options"]} == {
        "film_production_facility",
        "general",
    }


def test_lease_type_options_come_from_the_workbook_vocabulary(harness) -> None:
    form = harness.seed_form_service.get_form("film")
    lease = next(
        field
        for step in form["steps"]
        for field in step["fields"]
        if field["field_id"] == "lease_type"
    )
    assert [option["value"] for option in lease["options"]] == ["finance_capital", "operating"]


def test_film_overlay_offers_the_mapped_site_types(harness) -> None:
    form = harness.seed_form_service.get_form("film")
    site_type = next(
        field
        for step in form["steps"]
        for field in step["fields"]
        if field["field_id"] == "site_type"
    )
    assert site_type["input"] == "select"
    assert {option["value"] for option in site_type["options"]} == {
        "soundstage_complex",
        "backlot",
        "office",
        "workshop",
    }


def test_general_overlay_site_type_is_free_text_and_provisional(harness) -> None:
    """The mapping defines site-type values for film only; nothing is invented."""
    form = harness.seed_form_service.get_form("general")
    site_type = next(
        field
        for step in form["steps"]
        for field in step["fields"]
        if field["field_id"] == "site_type"
    )
    assert site_type["input"] == "text"
    assert site_type["provisional"] is True


# -- validation -------------------------------------------------------------


def test_valid_submission_is_accepted(harness) -> None:
    result = _submit(harness)
    assert result["org"]["profile_status"] == "seed_form_complete"
    assert len(result["sites"]) == 1


def test_missing_company_fields_are_all_reported_at_once(harness) -> None:
    errors = _errors(harness, company={})
    assert {"legal_name", "reporting_year", "industry"} <= _fields(errors)


def test_at_least_one_site_is_required(harness) -> None:
    assert "sites" in _fields(_errors(harness, sites=[]))


@pytest.mark.parametrize("bad_email", ["ada", "ada@", "@northlight.example", "a@b"])
def test_invalid_responsible_party_email_is_rejected(harness, bad_email: str) -> None:
    errors = _errors(harness, company=company_payload(responsible_party_email=bad_email))
    assert "responsible_party_email" in _fields(errors)


def test_reporting_period_must_not_end_before_it_starts(harness) -> None:
    errors = _errors(
        harness,
        company=company_payload(
            reporting_period_start="2025-12-31", reporting_period_end="2025-01-01"
        ),
    )
    assert "reporting_period_end" in _fields(errors)


def test_malformed_date_is_rejected(harness) -> None:
    errors = _errors(harness, company=company_payload(reporting_period_start="01/01/2025"))
    assert "reporting_period_start" in _fields(errors)


def test_unknown_industry_is_rejected(harness) -> None:
    errors = _errors(harness, company=company_payload(industry="aerospace"))
    assert "industry" in _fields(errors)


@pytest.mark.parametrize("bad_year", ["not-a-year", 1800, 2200])
def test_implausible_reporting_year_is_rejected(harness, bad_year) -> None:
    errors = _errors(harness, company=company_payload(reporting_year=bad_year))
    assert "reporting_year" in _fields(errors)


def test_invented_lease_type_is_rejected(harness) -> None:
    """Only the workbook's permitted values are accepted."""
    errors = _errors(harness, sites=[site_payload(lease_type="peppercorn")])
    assert "lease_type" in _fields(errors)


def test_lease_type_on_an_owned_site_is_rejected(harness) -> None:
    errors = _errors(harness, sites=[site_payload(ownership="owned", lease_type="operating")])
    assert "lease_type" in _fields(errors)


def test_lease_type_is_optional(harness) -> None:
    """'Not sure' must never be a hard failure."""
    result = _submit(harness, sites=[site_payload(lease_type="")])
    assert result["sites"][0]["lease_type"] is None


def test_invented_site_type_is_rejected_under_the_film_overlay(harness) -> None:
    errors = _errors(harness, sites=[site_payload(site_type="rooftop_helipad")])
    assert "site_type" in _fields(errors)


def test_site_errors_carry_their_index(harness) -> None:
    errors = _errors(harness, sites=[site_payload(), site_payload(site_name="")])
    assert any(error.get("index") == 1 for error in errors)


def test_unknown_org_is_rejected(harness) -> None:
    with pytest.raises(SeedFormValidationError):
        harness.seed_form_service.submit(
            org_id="org_missing",
            submitted_by="usr_test",
            payload={"company": company_payload(), "sites": [site_payload()]},
        )


# -- persistence ------------------------------------------------------------


def test_company_answers_land_on_the_org(harness) -> None:
    org = _submit(harness)["org"]
    assert org["reporting_year"] == 2025
    assert org["industry_overlay_id"] == "film"
    assert org["responsible_party"]["email"] == "ada@northlight.example"


def test_period_in_scope_is_derived_not_asked(harness) -> None:
    site = _submit(harness)["sites"][0]
    assert site["period_in_scope_start"] == "2025-01-01"
    assert site["period_in_scope_end"] == "2025-12-31"


def test_boundary_fields_are_deferred_not_guessed(harness) -> None:
    """Own/lease is a raw fact; control determination is HUMAN class (BND-2.3)."""
    site = _submit(harness)["sites"][0]
    deferred = {entry["schema_field"] for entry in site["deferred_boundary_fields"]}
    assert deferred == {"operational_control_over_asset_flag", "party_role"}
    assert all(
        entry["deferred_to_datapoint"] == "BND-2.3" for entry in site["deferred_boundary_fields"]
    )
    assert "operational_control_over_asset_flag" not in site


def test_provisional_values_are_recorded_for_signoff(harness) -> None:
    submission = _submit(harness)["submission"]
    provisional = {value["field_id"] for value in submission["provisional_values"]}
    assert {"operational_status", "fiscal_year_basis"} <= provisional
    assert all(value["requires_signoff"] == "Todd" for value in submission["provisional_values"])


def test_general_overlay_site_type_is_recorded_as_provisional(harness) -> None:
    result = _submit(
        harness,
        company=company_payload(industry="general"),
        sites=[site_payload(site_type="Warehouse")],
    )
    provisional = {value["field_id"] for value in result["submission"]["provisional_values"]}
    assert "site_type" in provisional
    assert "site_type" in result["sites"][0]["provisional_fields"]


def test_submission_records_the_config_versions_it_used(harness) -> None:
    submission = _submit(harness)["submission"]
    assert submission["form_version"]
    assert submission["profile_schema_version"]
    assert set(submission["datapoint_ids"]) == {f"SEED-1.{n}" for n in range(1, 8)}


def test_submission_history_is_kept(harness) -> None:
    org = harness.create_org()["org"]
    for name in ("First Ltd", "Second Ltd"):
        harness.seed_form_service.submit(
            org_id=org["org_id"],
            submitted_by="usr_test",
            payload={
                "company": company_payload(legal_name=name),
                "sites": [site_payload()],
            },
        )
    assert len(harness.submissions.list_by_org(org["org_id"])) == 2
    assert harness.seed_form_service.latest_submission(org["org_id"])["answers"]["company"][
        "legal_name"
    ] == "Second Ltd"


def test_resubmission_updates_a_site_rather_than_duplicating_it(harness) -> None:
    org = harness.create_org()["org"]
    first = harness.seed_form_service.submit(
        org_id=org["org_id"],
        submitted_by="usr_test",
        payload={"company": company_payload(), "sites": [site_payload()]},
    )
    site_id = first["sites"][0]["site_id"]

    second = harness.seed_form_service.submit(
        org_id=org["org_id"],
        submitted_by="usr_test",
        payload={
            "company": company_payload(),
            "sites": [site_payload(site_id=site_id, site_name="Stage 4 Complex (renamed)")],
        },
    )
    assert second["sites"][0]["site_id"] == site_id
    assert len(harness.sites.list_by_org(org["org_id"])) == 1
    assert second["sites"][0]["site_name"] == "Stage 4 Complex (renamed)"


def test_confirmation_email_is_sent_to_the_responsible_party(harness) -> None:
    _submit(harness)
    message = harness.mailbox.last_to("ada@northlight.example")
    assert message is not None
    assert "Northlight Studios Ltd" in message.body


def test_no_datapoint_states_are_written_in_phase_b(harness) -> None:
    """Phase C owns the state machine; Phase B must not pre-empt it."""
    result = _submit(harness)
    assert "datapoint_states" not in result
    assert not any("datapoint_state" in key for key in result["submission"])


# -- prefill (fixes the duplicate-sites gap) --------------------------------


def test_current_answers_are_empty_before_submission(harness) -> None:
    org = harness.create_org()["org"]
    answers = harness.seed_form_service.current_answers(org["org_id"])
    assert answers["sites"] == []
    assert answers["profile_status"] == "awaiting_seed_form"


def test_current_answers_prefill_the_form(harness) -> None:
    result = _submit(harness)
    answers = harness.seed_form_service.current_answers(result["org"]["org_id"])
    assert answers["company"]["legal_name"] == "Northlight Studios Ltd"
    assert answers["company"]["responsible_party_email"] == "ada@northlight.example"
    assert answers["sites"][0]["site_name"] == "Stage 4 Complex"
    assert answers["sites"][0]["address_line"] == "12 Harbour Road"


def test_prefilled_sites_carry_their_id_so_resubmission_updates(harness) -> None:
    """The site_id is what stops a second submission duplicating every site."""
    result = _submit(harness)
    org_id = result["org"]["org_id"]
    answers = harness.seed_form_service.current_answers(org_id)
    assert answers["sites"][0]["site_id"]

    harness.seed_form_service.submit(
        org_id=org_id,
        submitted_by="usr_test",
        payload={"company": answers["company"], "sites": answers["sites"]},
    )
    assert len(harness.sites.list_by_org(org_id)) == 1


def test_current_answers_for_an_unknown_org_are_empty(harness) -> None:
    assert harness.seed_form_service.current_answers("org_missing") == {
        "company": {},
        "sites": [],
    }
