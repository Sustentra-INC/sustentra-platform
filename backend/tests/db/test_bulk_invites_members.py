"""Add-people backend: bulk invite (POST /orgs/{id}/invites/bulk) and the member directory
(GET /orgs/{id}/members). Reuses the seeded orgs, sessions and mail capture of test_invites."""

from __future__ import annotations

import uuid

from backend.tests.db.test_invites import (  # noqa: F401  (autouse fixture + helpers)
    INVITES, ORG_A, ORG_B, call, admin, events, invites_url, seeded,
)

BULK = "/bulk"


def bulk(emails: list[str], role: str = "org_member", as_: str | None = "admin", org: uuid.UUID = ORG_A):
    return call("POST", invites_url(org) + BULK, as_, {"emails": emails, "role": role})


def test_bulk_invites_each_email_once_and_audits_each_and_the_batch() -> None:
    admin("UPDATE organizations SET max_users = 25")
    r = bulk([" Jane.Doe@Acme.test ", "ravi@acme.test"])
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["invited"] == 2
    assert [(x["email"], x["status"]) for x in body["results"]] == [
        ("jane.doe@acme.test", "invited"), ("ravi@acme.test", "invited")]
    assert sorted(to for to, _ in INVITES) == ["jane.doe@acme.test", "ravi@acme.test"]
    [jane] = admin("SELECT first_name, last_name, status, invited_by FROM users WHERE email = 'jane.doe@acme.test'")
    assert (jane["first_name"], jane["last_name"], jane["status"]) == ("Jane", "Doe", "invited")
    ev = events()
    assert ev.count("user_invited") == 2 and ev.count("users_bulk_invited") == 1
    [summary] = admin("SELECT metadata::text AS m FROM audit_logs WHERE event_type = 'users_bulk_invited'")
    assert "acme.test" not in summary["m"] and '"invited": 2' in summary["m"]


def test_bulk_reports_bad_rows_without_failing_the_rest() -> None:
    admin("UPDATE organizations SET max_users = 25")
    body = bulk(["not-an-email", "member@acme.test", "ok@acme.test", "OK@acme.test", "x@y"]).json()
    assert [x["status"] for x in body["results"]] == ["invalid", "already_member", "invited", "duplicate", "invalid"]
    assert body["invited"] == 1 and len(INVITES) == 1


def test_bulk_is_capped_at_50_and_needs_at_least_one() -> None:
    assert bulk([f"p{i}@acme.test" for i in range(51)]).status_code == 422
    assert bulk([]).status_code == 422
    assert bulk(["a@acme.test"], role="provider_admin").status_code == 422
    assert INVITES == [] and events() == []
    # 50 is within the cap (the org's seats stop it: 3 seats, 2 taken).
    r = bulk([f"p{i}@acme.test" for i in range(50)]).json()
    assert r["invited"] == 1
    assert {x["status"] for x in r["results"]} == {"invited", "seat_limit"}


def test_bulk_stops_at_the_seat_limit() -> None:
    r = bulk(["a@acme.test", "b@acme.test"]).json()
    assert [x["status"] for x in r["results"]] == ["invited", "seat_limit"]


def test_bulk_permissions_and_cross_org_guard() -> None:
    assert bulk(["a@acme.test"], as_="member").status_code == 403
    assert bulk(["a@acme.test"], as_=None).status_code == 401
    assert bulk(["a@acme.test"], as_="b_admin").status_code == 404  # another org's admin: org looks absent
    assert bulk(["a@acme.test"], as_="admin", org=ORG_B).status_code == 404
    assert bulk(["a@acme.test"], as_="provider", org=ORG_B).status_code == 201
    assert admin("SELECT org_id FROM users WHERE email = 'a@acme.test'")[0]["org_id"] == ORG_B


def test_members_directory_lists_only_own_org_active_and_invited() -> None:
    call("POST", invites_url(), "admin", {"email": "ivy@acme.test", "role": "org_member", "first_name": "Ivy",
                                          "last_name": "I"})
    r = call("GET", f"/api/v1/orgs/{ORG_A}/members", "member")  # a plain member may search the team
    assert r.status_code == 200
    got = {(m["email"], m["status"]) for m in r.json()["items"]}
    assert got == {("admin@acme.test", "active"), ("member@acme.test", "active"), ("ivy@acme.test", "invited")}
    assert r.json()["org_name"] == "Acme Foods"
    assert set(r.json()["items"][0]) == {"id", "email", "name", "status"}  # no role, no logins


def test_members_search_and_guards() -> None:
    r = call("GET", f"/api/v1/orgs/{ORG_A}/members", "admin", params={"q": "MEG"})
    assert [m["email"] for m in r.json()["items"]] == ["member@acme.test"]
    assert call("GET", f"/api/v1/orgs/{ORG_A}/members", "admin", params={"q": "%"}).json()["items"] == []
    assert call("GET", f"/api/v1/orgs/{ORG_A}/members", "b_admin").status_code == 404
    assert call("GET", f"/api/v1/orgs/{ORG_A}/members", None).status_code == 401
    assert call("GET", "/api/v1/orgs/not-a-uuid/members", "provider").status_code == 404
    assert call("GET", f"/api/v1/orgs/{uuid.uuid4()}/members", "provider").status_code == 404
    assert [m["email"] for m in call("GET", f"/api/v1/orgs/{ORG_B}/members", "b_admin").json()["items"]] == [
        "admin@beta.test"]


# --- email hygiene, display names, rate limits ------------------------------------------

def test_emails_with_header_or_control_characters_are_rejected_everywhere() -> None:
    admin("UPDATE organizations SET max_users = 100")
    bad = ['a,b@acme.test', 'a;b@acme.test', 'a<b@acme.test', 'a>b@acme.test', 'a"b@acme.test', "a'b@acme.test",
           "a\\b@acme.test", "a\tb@acme.test", "a\x00b@acme.test", "a\x7fb@acme.test", "a b@acme.test",
           "a@acme.test\r\nBcc: x@evil.test", "a b@acme.test"]
    body = bulk(bad).json()
    assert {x["status"] for x in body["results"]} == {"invalid"} and body["invited"] == 0
    for email in bad:
        r = call("POST", invites_url(), "admin", {"email": email, "role": "org_member", "first_name": "A",
                                                  "last_name": "B"})
        assert r.status_code == 422, email
    assert INVITES == []


def test_display_names_keep_only_safe_characters() -> None:
    from backend.app.services.invite_service import name_from_email
    assert name_from_email("jane.doe@x.test") == ("Jane", "Doe")
    assert name_from_email("o'brien+x@x.test") == ("Obrienx", "")
    assert name_from_email("a$%^b_c@x.test") == ("Ab", "C")
    assert name_from_email("%%%@x.test") == ("New", "")


def _seed_sends(event: str, n: int, minutes_ago: int, actor: uuid.UUID | None = None) -> None:
    admin("INSERT INTO audit_logs (org_id, actor_user_id, actor_role, event_type, target_type, created_at) "
          "SELECT $1, $2, 'org_admin', $3, 'user', now() - make_interval(mins => $4) FROM generate_series(1, $5)",
          ORG_A, actor, event, minutes_ago, n)


def test_org_hourly_invite_cap_counts_recipients_and_says_when_to_retry() -> None:
    admin("UPDATE organizations SET max_users = 1000")
    _seed_sends("user_invited", 98, 10)
    assert bulk(["a@acme.test", "b@acme.test", "c@acme.test"]).status_code == 429  # 98 + 3 > 100
    r = bulk(["a@acme.test", "b@acme.test"])  # exactly 100: allowed
    assert r.status_code == 201 and r.json()["invited"] == 2
    r = bulk(["z@acme.test"])
    assert r.status_code == 429 and "Try again in about" in r.json()["detail"]
    assert 0 < int(r.headers["retry-after"]) <= 3600
    single = call("POST", invites_url(), "admin", {"email": "q@acme.test", "role": "org_member",
                                                    "first_name": "Q", "last_name": "Q"})
    assert single.status_code == 429


def test_cancel_and_reinvite_loop_does_not_reset_the_count() -> None:
    admin("UPDATE organizations SET max_users = 1000")
    _seed_sends("user_invited", 99, 5)
    first = bulk(["loop@acme.test"])
    assert first.status_code == 201
    uid = first.json()["results"][0]["user_id"]
    assert call("DELETE", f"/api/v1/orgs/{ORG_A}/users/{uid}", "admin").status_code == 204
    assert bulk(["loop@acme.test"]).status_code == 429


def test_org_daily_cap_and_old_sends_age_out() -> None:
    admin("UPDATE organizations SET max_users = 1000")
    _seed_sends("user_invited", 100, 120)  # two hours ago: past the hourly window
    _seed_sends("user_invited", 199, 600)  # ten hours ago: only the daily window sees it
    assert bulk(["a@acme.test", "b@acme.test"]).status_code == 429  # 299 + 2 > 300
    assert bulk(["a@acme.test"]).status_code == 201
    _seed_sends("user_invited", 1000, 60 * 30)  # more than a day ago: ignored
    assert bulk(["b@acme.test"]).status_code == 429  # 300 reached in the day


def test_resends_are_capped_at_30_per_org_per_hour() -> None:
    admin("UPDATE organizations SET max_users = 1000")
    invited = bulk(["r@acme.test"]).json()["results"][0]["user_id"]
    _seed_sends("user_invite_resent", 29, 5, actor=None)
    url = invites_url(ORG_A, invited)
    assert call("POST", url, "admin").status_code == 200
    r = call("POST", url, "admin")
    assert r.status_code == 429 and "retry-after" in r.headers
    assert bulk(["fresh@acme.test"]).status_code == 201  # resends do not block new invites


def test_per_user_hourly_cap() -> None:
    admin("UPDATE organizations SET max_users = 1000")
    from backend.tests.db.test_invites import ADMIN
    _seed_sends("user_invited", 59, 3, actor=ADMIN)
    assert bulk(["a@acme.test", "b@acme.test"]).status_code == 429
    assert bulk(["a@acme.test"]).status_code == 201
