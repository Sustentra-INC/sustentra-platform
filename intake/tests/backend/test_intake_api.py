"""End-to-end API behaviour over the intake surface."""

from __future__ import annotations

import pytest

from intake.tests.conftest import company_payload, site_payload

ADMIN_KEY = "test-admin-key"


@pytest.fixture
def admin_headers(monkeypatch):
    monkeypatch.setenv("INTAKE_ADMIN_API_KEY", ADMIN_KEY)
    return {"X-Intake-Admin-Key": ADMIN_KEY}


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _sign_in(client) -> tuple[str, dict]:
    created = client.harness.create_org()
    token = client.harness.sign_in()
    return token, created["org"]


# -- health & auth ----------------------------------------------------------


def test_intake_health(client) -> None:
    response = client.get("/v1/intake/health")
    assert response.status_code == 200
    assert response.json()["surface"] == "intake"


def test_magic_link_then_verify_then_me(client) -> None:
    client.harness.create_org()

    assert client.post(
        "/v1/intake/auth/magic-link", json={"email": "owner@example.com"}
    ).json() == {"status": "sent"}

    raw = client.harness.mailbox.last_to("owner@example.com").body.split("token=")[1].split()[0]
    verified = client.post("/v1/intake/auth/verify", json={"token": raw})
    assert verified.status_code == 200

    token = verified.json()["session_token"]
    me = client.get("/v1/intake/auth/me", headers=_auth(token))
    assert me.status_code == 200
    assert me.json()["email"] == "owner@example.com"


def test_magic_link_for_unknown_email_still_returns_sent(client) -> None:
    response = client.post("/v1/intake/auth/magic-link", json={"email": "nobody@example.com"})
    assert response.status_code == 200
    assert response.json() == {"status": "sent"}


def test_bad_token_is_unauthorised(client) -> None:
    assert client.post("/v1/intake/auth/verify", json={"token": "nope"}).status_code == 401


@pytest.mark.parametrize(
    "headers",
    [{}, {"Authorization": "Bearer "}, {"Authorization": "Basic abc"}, {"Authorization": "junk"}],
)
def test_protected_routes_require_a_bearer_session(client, headers: dict) -> None:
    assert client.get("/v1/intake/auth/me", headers=headers).status_code == 401


def test_sign_out_invalidates_the_session(client) -> None:
    token, _ = _sign_in(client)
    assert client.post("/v1/intake/auth/sign-out", headers=_auth(token)).status_code == 200
    assert client.get("/v1/intake/auth/me", headers=_auth(token)).status_code == 401


# -- org creation guard -----------------------------------------------------


def test_org_creation_is_refused_when_no_admin_key_is_configured(client, monkeypatch) -> None:
    """Fails closed rather than standing open."""
    monkeypatch.delenv("INTAKE_ADMIN_API_KEY", raising=False)
    response = client.post(
        "/v1/intake/orgs",
        json={
            "legal_name": "X",
            "owner_name": "Y",
            "owner_email": "y@example.com",
            "created_by": "internal@sustentra.com",
        },
    )
    assert response.status_code == 503


def test_org_creation_rejects_a_wrong_admin_key(client, admin_headers) -> None:
    response = client.post(
        "/v1/intake/orgs",
        headers={"X-Intake-Admin-Key": "wrong"},
        json={
            "legal_name": "X",
            "owner_name": "Y",
            "owner_email": "y@example.com",
            "created_by": "internal@sustentra.com",
        },
    )
    assert response.status_code == 403


def test_org_creation_with_the_admin_key(client, admin_headers) -> None:
    response = client.post(
        "/v1/intake/orgs",
        headers=admin_headers,
        json={
            "legal_name": "Northlight Studios",
            "owner_name": "Sam Owner",
            "owner_email": "sam@example.com",
            "created_by": "internal@sustentra.com",
        },
    )
    assert response.status_code == 200
    assert response.json()["owner"]["role"] == "client_owner"


def test_duplicate_owner_email_is_a_bad_request(client, admin_headers) -> None:
    payload = {
        "legal_name": "Northlight",
        "owner_name": "Sam",
        "owner_email": "sam@example.com",
        "created_by": "internal@sustentra.com",
    }
    client.post("/v1/intake/orgs", headers=admin_headers, json=payload)
    second = client.post(
        "/v1/intake/orgs", headers=admin_headers, json={**payload, "legal_name": "Other"}
    )
    assert second.status_code == 400


# -- org scoping ------------------------------------------------------------


def test_a_user_cannot_read_another_org(client) -> None:
    token, _ = _sign_in(client)
    other = client.harness.org_service.create_org(
        legal_name="Other Studio",
        owner_name="Other",
        owner_email="other@example.com",
        created_by="internal@sustentra.com",
    )
    response = client.get(f"/v1/intake/orgs/{other['org']['org_id']}", headers=_auth(token))
    assert response.status_code == 403


def test_org_and_users_are_readable_by_their_own_members(client) -> None:
    token, org = _sign_in(client)
    assert client.get(f"/v1/intake/orgs/{org['org_id']}", headers=_auth(token)).status_code == 200
    users = client.get(f"/v1/intake/orgs/{org['org_id']}/users", headers=_auth(token))
    assert [user["role"] for user in users.json()] == ["client_owner"]


def test_a_member_cannot_add_users(client) -> None:
    token, org = _sign_in(client)
    client.harness.org_service.add_user(
        org_id=org["org_id"], name="Mem", email="mem@example.com", role="client_member"
    )
    member_token = client.harness.sign_in("mem@example.com")
    response = client.post(
        f"/v1/intake/orgs/{org['org_id']}/users",
        headers=_auth(member_token),
        json={"name": "New", "email": "new@example.com", "role": "client_member"},
    )
    assert response.status_code == 403


# -- seed form --------------------------------------------------------------


def test_seed_form_schema_requires_sign_in(client) -> None:
    assert client.get("/v1/intake/seed-form/schema").status_code == 401


def test_seed_form_schema_is_served(client) -> None:
    token, _ = _sign_in(client)
    response = client.get("/v1/intake/seed-form/schema?overlay_id=film", headers=_auth(token))
    assert response.status_code == 200
    assert [step["step_id"] for step in response.json()["steps"]] == ["company", "sites"]


def test_submit_seed_form_end_to_end(client) -> None:
    token, org = _sign_in(client)
    response = client.post(
        "/v1/intake/seed-form",
        headers=_auth(token),
        json={"company": company_payload(), "sites": [site_payload()]},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["org"]["profile_status"] == "seed_form_complete"

    sites = client.get(f"/v1/intake/orgs/{org['org_id']}/sites", headers=_auth(token))
    assert len(sites.json()) == 1

    latest = client.get("/v1/intake/seed-form/submissions/latest", headers=_auth(token))
    assert latest.status_code == 200
    assert latest.json()["org_id"] == org["org_id"]


def test_invalid_submission_returns_field_errors(client) -> None:
    token, _ = _sign_in(client)
    response = client.post(
        "/v1/intake/seed-form",
        headers=_auth(token),
        json={"company": {}, "sites": []},
    )
    assert response.status_code == 400
    errors = response.json()["detail"]["errors"]
    assert {"legal_name", "sites"} <= {error["field"] for error in errors}


def test_reviewer_cannot_submit_the_seed_form(client) -> None:
    token, org = _sign_in(client)
    client.harness.org_service.add_user(
        org_id=org["org_id"],
        name="Rev",
        email="rev@sustentra.com",
        role="sustentra_reviewer",
        actor_role="sustentra_reviewer",  # internal provisioning
    )
    reviewer_token = client.harness.sign_in("rev@sustentra.com")
    response = client.post(
        "/v1/intake/seed-form",
        headers=_auth(reviewer_token),
        json={"company": company_payload(), "sites": [site_payload()]},
    )
    assert response.status_code == 403


def test_latest_submission_is_404_before_any_submission(client) -> None:
    token, _ = _sign_in(client)
    assert (
        client.get("/v1/intake/seed-form/submissions/latest", headers=_auth(token)).status_code
        == 404
    )


def test_site_lookup_is_scoped_to_the_callers_org(client) -> None:
    token, _ = _sign_in(client)
    client.post(
        "/v1/intake/seed-form",
        headers=_auth(token),
        json={"company": company_payload(), "sites": [site_payload()]},
    )
    other_token = client.harness.sign_in()
    site_id = client.harness.sites.list_records()[0]["site_id"]
    assert client.get(f"/v1/intake/sites/{site_id}", headers=_auth(other_token)).status_code == 200
    assert client.get("/v1/intake/sites/ste_nope", headers=_auth(token)).status_code == 404


# -- CORS -------------------------------------------------------------------
#
# The screens run on a different port from the API, so without these headers the
# browser refuses the request before it ever reaches the app. TestClient does not
# enforce CORS, so this is asserted explicitly rather than assumed.


def test_preflight_is_allowed_for_the_configured_origin(client) -> None:
    response = client.options(
        "/v1/intake/auth/me",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization"
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"
    assert "authorization" in response.headers["access-control-allow-headers"].lower()


def test_an_unlisted_origin_is_not_granted_access(client) -> None:
    response = client.get(
        "/v1/intake/health", headers={"Origin": "https://evil.example"}
    )
    assert "access-control-allow-origin" not in {k.lower() for k in response.headers}


def test_cors_origins_are_configurable_and_never_wildcard() -> None:
    from intake.backend.config import load_settings

    origins = load_settings().api.cors_allowed_origins
    assert origins, "at least one origin must be allowed or the screens cannot call the API"
    assert "*" not in origins, "a wildcard would let any site call the API with a user's session"


# -- interview (Phase C2) ---------------------------------------------------


def _start(client):
    token, org = _sign_in(client)
    client.post(
        "/v1/intake/seed-form",
        headers=_auth(token),
        json={"company": company_payload(), "sites": [site_payload()]},
    )
    started = client.post("/v1/intake/interview/start", headers=_auth(token))
    return token, org, started


def test_interview_requires_sign_in(client) -> None:
    assert client.post("/v1/intake/interview/start").status_code == 401
    assert client.get("/v1/intake/interview/next").status_code == 401


def test_starting_the_interview_returns_a_question_and_coverage(client) -> None:
    _, _, started = _start(client)
    assert started.status_code == 200
    body = started.json()
    assert body["next"]["question"]
    assert body["next"]["explainer"]
    assert body["coverage"]["total"] > 0
    assert body["coverage"]["complete"] == 0
    assert body["summary"]["backfilled"]


def test_answering_advances_to_the_next_question(client) -> None:
    token, _, started = _start(client)
    first = started.json()["next"]
    response = client.post(
        "/v1/intake/interview/answer",
        headers=_auth(token),
        json={
            "datapoint_id": first["datapoint_id"],
            "scope_ref": first["scope_ref"],
            "answer": {"consolidation_approach": "operational_control"},
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["coverage"]["complete"] == 1
    assert body["next"]["datapoint_id"] != first["datapoint_id"]


def test_an_invalid_answer_returns_field_errors(client) -> None:
    """party_role is a closed workbook vocabulary, so a made-up value is refused."""
    token, org, _ = _start(client)
    site_id = client.harness.sites.list_by_org(org["org_id"])[0]["site_id"]
    response = client.post(
        "/v1/intake/interview/answer",
        headers=_auth(token),
        json={
            "datapoint_id": "BND-2.3",
            "scope_ref": site_id,
            "answer": {
                "party_role": "chief_vibes_officer",
                "operational_control_over_asset_flag": True,
            },
        },
    )
    assert response.status_code == 400
    assert response.json()["detail"]["errors"][0]["field"] == "party_role"


def test_an_open_vocabulary_accepts_a_value_outside_the_list(client) -> None:
    """consolidation_approach is annotated OPEN in the workbook, and ISO 14064-1
    permits other documented approaches, so intake must not force the named three."""
    token, _, started = _start(client)
    first = started.json()["next"]
    assert first["datapoint_id"] == "BND-2.1"
    response = client.post(
        "/v1/intake/interview/answer",
        headers=_auth(token),
        json={
            "datapoint_id": first["datapoint_id"],
            "scope_ref": first["scope_ref"],
            "answer": {"consolidation_approach": "documented_alternative_approach"},
        },
    )
    assert response.status_code == 200


def test_not_sure_returns_the_explainer_and_keeps_going(client) -> None:
    token, _, started = _start(client)
    first = started.json()["next"]
    response = client.post(
        "/v1/intake/interview/not-sure",
        headers=_auth(token),
        json={"datapoint_id": first["datapoint_id"], "scope_ref": first["scope_ref"]},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["explainer"]
    assert "24 hours" in body["message"]
    assert body["next"]["datapoint_id"] != first["datapoint_id"]


def test_coverage_and_states_endpoints(client) -> None:
    token, _, _ = _start(client)
    coverage = client.get("/v1/intake/interview/coverage", headers=_auth(token))
    assert coverage.status_code == 200
    assert coverage.json()["label"].endswith("complete")

    states = client.get("/v1/intake/interview/states", headers=_auth(token))
    assert states.status_code == 200
    assert any(state["datapoint_id"].startswith("SEED-") for state in states.json())


def test_a_reviewer_cannot_answer_the_interview(client) -> None:
    token, org = _sign_in(client)
    client.post(
        "/v1/intake/seed-form",
        headers=_auth(token),
        json={"company": company_payload(), "sites": [site_payload()]},
    )
    client.post("/v1/intake/interview/start", headers=_auth(token))
    client.harness.org_service.add_user(
        org_id=org["org_id"],
        name="Rev",
        email="rev@sustentra.com",
        role="sustentra_reviewer",
        actor_role="sustentra_reviewer",  # internal provisioning
    )
    reviewer = client.harness.sign_in("rev@sustentra.com")
    response = client.post(
        "/v1/intake/interview/answer",
        headers=_auth(reviewer),
        json={"datapoint_id": "BND-2.1", "scope_ref": None, "answer": {}},
    )
    assert response.status_code == 403


# -- free-text parsing (Phase D1) -------------------------------------------


def test_parse_requires_sign_in(client) -> None:
    assert client.post("/v1/intake/interview/parse", json={
        "datapoint_id": "S1FUG-5.1", "text": "twelve units"
    }).status_code == 401


def test_parse_proposes_a_reading_without_writing_it(client) -> None:
    token, org, _ = _start(client)
    site_id = client.harness.sites.list_by_org(org["org_id"])[0]["site_id"]
    client.harness.llm.queue(
        "parse_answer",
        {
            "fields": {"present": True, "equipment_count": 12, "gas_type": "R-410A"},
            "confidence": 0.93,
            "summary": "Twelve air conditioning units using R-410A.",
            "unresolved": [],
            "clarifying_question": None,
        },
    )
    response = client.post(
        "/v1/intake/interview/parse",
        headers=_auth(token),
        json={
            "datapoint_id": "S1FUG-5.1",
            "scope_ref": site_id,
            "text": "about a dozen aircon units, the R-410A ones",
        },
    )
    assert response.status_code == 200
    outcome = response.json()["outcome"]
    assert outcome["status"] == "proposed"
    assert outcome["summary"].startswith("Twelve air conditioning")
    assert client.harness.state(org["org_id"], "S1FUG-5.1", site_id)["status"] == "unasked"


def test_a_low_confidence_parse_asks_for_clarification(client) -> None:
    token, org, _ = _start(client)
    site_id = client.harness.sites.list_by_org(org["org_id"])[0]["site_id"]
    client.harness.llm.queue(
        "parse_answer",
        {
            "fields": {},
            "confidence": 0.2,
            "summary": "",
            "unresolved": ["gas_type"],
            "clarifying_question": "Do you look after those units yourselves?",
        },
    )
    response = client.post(
        "/v1/intake/interview/parse",
        headers=_auth(token),
        json={"datapoint_id": "S1FUG-5.1", "scope_ref": site_id, "text": "some cooling bits"},
    )
    outcome = response.json()["outcome"]
    assert outcome["status"] == "clarify"
    assert outcome["clarifying_question"].startswith("Do you look after")


def test_parse_is_unavailable_when_no_model_is_configured(client) -> None:
    """Fails clearly rather than pretending to work."""
    from intake.backend.api.context import configure_context

    context = client.harness.context
    configure_context(
        type(context)(**{**context.__dict__, "answer_parser": None})
    )
    token, _ = _sign_in(client)
    response = client.post(
        "/v1/intake/interview/parse",
        headers=_auth(token),
        json={"datapoint_id": "S1FUG-5.1", "text": "twelve"},
    )
    assert response.status_code == 503


def test_a_reviewer_cannot_use_the_parser(client) -> None:
    token, org, _ = _start(client)
    client.harness.org_service.add_user(
        org_id=org["org_id"],
        name="Rev",
        email="rev@sustentra.com",
        role="sustentra_reviewer",
        actor_role="sustentra_reviewer",  # internal provisioning
    )
    reviewer = client.harness.sign_in("rev@sustentra.com")
    response = client.post(
        "/v1/intake/interview/parse",
        headers=_auth(reviewer),
        json={"datapoint_id": "S1FUG-5.1", "text": "twelve"},
    )
    assert response.status_code == 403


def test_a_client_cannot_grant_themselves_the_reviewer_role_over_the_api(client) -> None:
    """The same escalation, closed at the HTTP boundary too."""
    token, org = _sign_in(client)
    response = client.post(
        f"/v1/intake/orgs/{org['org_id']}/users",
        headers=_auth(token),
        json={"name": "Ada (alt)", "email": "ada.alt@example.com", "role": "sustentra_reviewer"},
    )
    assert response.status_code == 400
    assert "Sustentra staff" in response.json()["detail"]


def test_a_client_can_still_add_a_colleague_over_the_api(client) -> None:
    token, org = _sign_in(client)
    response = client.post(
        f"/v1/intake/orgs/{org['org_id']}/users",
        headers=_auth(token),
        json={"name": "Sam", "email": "sam@example.com", "role": "client_member"},
    )
    assert response.status_code == 200
    assert response.json()["role"] == "client_member"
