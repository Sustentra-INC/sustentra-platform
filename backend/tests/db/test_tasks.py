"""Tasks + in-app notifications + emails, through the real app and Postgres (RLS on).

Needs TEST_DATABASE_URL (owner, for seeding/inspection) and TEST_APP_DATABASE_URL (app_user).
Task emails are captured by overriding the sender, so no mail leaves the test.
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.api import documents as documents_api
from backend.app.core import db
from urllib.parse import quote

from backend.app.core.config import Settings, get_settings
from backend.app.core.rate_limit import limiter
from backend.app.repositories.document_repository import InMemoryDocumentRepository
from backend.app.services import calculation_lines as cl
from backend.app.services import task_service
from backend.app.services.document_upload_service import DocumentUploadService
from backend.app.services.local_storage_service import LocalStorageService
from backend.app.core.security_primitives import hash_token
from backend.app.main import create_app
from backend.app.services.otp_delivery import get_task_email_sender
from backend.app.services.sessions import SESSION_COOKIE

asyncpg = pytest.importorskip("asyncpg")
httpx = pytest.importorskip("httpx")

ADMIN_URL = os.environ.get("TEST_DATABASE_URL")
APP_URL = os.environ.get("TEST_APP_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not (ADMIN_URL and APP_URL), reason="TEST_DATABASE_URL / TEST_APP_DATABASE_URL not set"
)

ORIGIN = "https://app.sustentra.test"
ORG_A = uuid.UUID("aaaaaaaa-0000-0000-0000-0000000000b1")
ORG_B = uuid.UUID("bbbbbbbb-0000-0000-0000-0000000000b1")
ANN = uuid.UUID("aaaaaaaa-0001-0000-0000-0000000000b1")    # org admin
ZED = uuid.UUID("aaaaaaaa-0002-0000-0000-0000000000b1")    # second org admin
DEBO = uuid.UUID("aaaaaaaa-0003-0000-0000-0000000000b1")   # member
VIVIAN = uuid.UUID("aaaaaaaa-0004-0000-0000-0000000000b1")  # member
SUSPENDED = uuid.UUID("aaaaaaaa-0005-0000-0000-0000000000b1")
INVITED = uuid.UUID("aaaaaaaa-0006-0000-0000-0000000000b1")
BEN = uuid.UUID("bbbbbbbb-0001-0000-0000-0000000000b1")    # org B admin
BELLA = uuid.UUID("bbbbbbbb-0002-0000-0000-0000000000b1")  # org B member
PROVIDER = uuid.UUID("cccccccc-0001-0000-0000-0000000000b1")
ENG_A = uuid.UUID("aaaaaaaa-00e0-0000-0000-0000000000b1")
ENG_B = uuid.UUID("bbbbbbbb-00e0-0000-0000-0000000000b1")
TOKENS = {"ann": (ANN, ORG_A), "zed": (ZED, ORG_A), "debo": (DEBO, ORG_A), "vivian": (VIVIAN, ORG_A),
          "ben": (BEN, ORG_B), "bella": (BELLA, ORG_B), "provider": (PROVIDER, None)}
EMAILS = {"ann": "ann@acme.test", "zed": "zed@acme.test", "debo": "debo@acme.test", "vivian": "vivian@acme.test"}

SENT: list[tuple[str, str, dict[str, Any]]] = []
SENDER_MODE = {"mode": "ok"}  # ok | false | raise


def _sender(template: str, to: str, variables: dict[str, Any]) -> bool:
    if SENDER_MODE["mode"] == "raise":
        raise RuntimeError("smtp is down")
    if SENDER_MODE["mode"] == "false":
        return False
    SENT.append((template, to, variables))
    return True


def tasks_url(org: uuid.UUID | str = ORG_A, tail: str = "") -> str:
    return f"/api/v1/orgs/{org}/tasks{tail}"


def notifications_url(org: uuid.UUID | str = ORG_A, tail: str = "") -> str:
    return f"/api/v1/orgs/{org}/notifications{tail}"


async def _admin(sql: str, *args: Any) -> list[Any]:
    conn = await asyncpg.connect(ADMIN_URL)
    try:
        return list(await conn.fetch(sql, *args))
    finally:
        await conn.close()


async def _seed() -> None:
    conn = await asyncpg.connect(ADMIN_URL)
    try:
        await conn.execute("TRUNCATE sessions, auth_tokens, engagements, users, organizations CASCADE")
        await conn.execute("TRUNCATE audit_logs")
        await conn.execute("INSERT INTO organizations (id, name, slug) VALUES ($1, 'Acme Foods', 'acme'), "
                           "($2, 'Beta', 'beta')", ORG_A, ORG_B)
        await conn.execute(
            """
            INSERT INTO users (id, org_id, email, first_name, last_name, role, status) VALUES
              ($1, $2, 'ann@acme.test', 'Ann', 'Admin', 'org_admin', 'active'),
              ($3, $2, 'zed@acme.test', 'Zed', 'Admin', 'org_admin', 'active'),
              ($4, $2, 'debo@acme.test', 'Debo', 'Okafor', 'org_member', 'active'),
              ($5, $2, 'vivian@acme.test', 'Vivian', 'Reyes', 'org_member', 'active'),
              ($6, $2, 'gone@acme.test', 'Gone', 'Person', 'org_member', 'suspended'),
              ($7, $2, 'new@acme.test', 'New', 'Person', 'org_member', 'invited'),
              ($8, $9, 'ben@beta.test', 'Ben', 'Beta', 'org_admin', 'active'),
              ($10, $9, 'bella@beta.test', 'Bella', 'Beta', 'org_member', 'active'),
              ($11, NULL, 'ops@sustentra.test', 'Op', 'S', 'provider_admin', 'active')
            """,
            ANN, ORG_A, ZED, DEBO, VIVIAN, SUSPENDED, INVITED, BEN, ORG_B, BELLA, PROVIDER,
        )
        await conn.execute("INSERT INTO engagements (id, org_id, name) VALUES ($1, $2, 'FY25 Footprint'), "
                           "($3, $4, 'Beta FY25')", ENG_A, ORG_A, ENG_B, ORG_B)
        now = datetime.now(UTC)
        for token, (user_id, org_id) in TOKENS.items():
            await conn.execute(
                "INSERT INTO sessions (user_id, org_id, token_hash, created_at, expires_at, last_seen_at) "
                "VALUES ($1, $2, $3, $4, $5, $4)",
                user_id, org_id, hash_token(token), now, now + timedelta(days=1),
            )
    finally:
        await conn.close()


DOCS = InMemoryDocumentRepository()
LINE = {"category": "stationary", "level2_label": "Propane", "anchor_kind": "facility", "anchor_id": "F1",
        "label": "Propane at the cannery"}
LINE_KEY = cl.normalize_line(LINE)["key"]


@pytest.fixture(autouse=True)
def seeded(tmp_path: Any) -> Any:
    limiter.reset()
    SENT.clear()
    SENDER_MODE["mode"] = "ok"
    asyncio.run(_seed())
    asyncio.run(_admin("UPDATE engagements SET settings = CAST($2 AS jsonb) WHERE id = $1", ENG_A,
                       json.dumps({"evidenceLines": [LINE]})))
    original = documents_api.current_upload_service()
    DOCS._store.clear()
    DOCS.save({"document_id": "doc-1", "engagement_id": str(ENG_A), "org_id": str(ORG_A), "file_name": "secret.pdf"})
    DOCS.save({"document_id": "doc-b", "engagement_id": str(ENG_B), "org_id": str(ORG_B), "file_name": "b.pdf"})
    DOCS.save({"document_id": "doc-other", "engagement_id": "someone-else", "org_id": str(ORG_A), "file_name": "o.pdf"})
    documents_api.configure_services(upload_service=DocumentUploadService(
        storage_service=LocalStorageService(tmp_path / "uploads"), document_repository=DOCS))
    yield
    documents_api.configure_services(upload_service=original)


def _app(engine: Any) -> Any:
    app = create_app(Settings(environment="test", git_sha="t", ALLOWED_ORIGINS=ORIGIN))  # type: ignore[call-arg]
    sessionmaker = db.build_sessionmaker(engine)

    async def session_dep() -> AsyncIterator[AsyncSession]:
        async with sessionmaker() as session, session.begin():
            yield session

    app.dependency_overrides[db.get_db_session] = session_dep
    app.dependency_overrides[db.get_sessionmaker_dependency] = lambda: sessionmaker
    app.dependency_overrides[get_task_email_sender] = lambda: _sender
    return app


def run(scenario: Callable[[Any], Awaitable[Any]]) -> Any:
    async def main() -> Any:
        engine = db.create_engine(APP_URL or "", pool_size=3, max_overflow=0)
        try:
            transport = httpx.ASGITransport(app=_app(engine))
            async with httpx.AsyncClient(transport=transport, base_url="https://testserver",
                                         headers={"Origin": ORIGIN}) as client:
                return await scenario(client)
        finally:
            await engine.dispose()

    return asyncio.run(main())


def call(method: str, path: str, token: str | None = "ann", body: Any = None, params: Any = None) -> Any:
    async def scenario(client: Any) -> Any:
        if token:
            client.cookies.set(SESSION_COOKIE, token)
        return await client.request(method, path, json=body, params=params)

    return run(scenario)


def admin(sql: str, *args: Any) -> list[Any]:
    return asyncio.run(_admin(sql, *args))


def assign(as_: str, to: uuid.UUID, title: str = "Review the boiler fuel invoice", **extra: Any) -> dict[str, Any]:
    response = call("POST", tasks_url(), as_, {"title": title, "assignee_user_id": str(to), **extra})
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


def recipients(template: str) -> list[str]:
    return sorted(to for t, to, _ in SENT if t == template)


def events() -> list[str]:
    return [r["event_type"] for r in admin("SELECT event_type FROM audit_logs ORDER BY created_at, event_type")]


# --- create ---------------------------------------------------------------------------------

def test_admin_assigns_debo_who_gets_a_notification_and_an_email() -> None:
    task = assign("ann", DEBO, note="Please check the totals", engagement_id=str(ENG_A),
                  target={"kind": "document", "item_id": "doc-1"}, due_date="2026-12-01")
    assert (task["status"], task["assignee_name"], task["requested_by_name"], task["engagement_name"]) == (
        "open", "Debo Okafor", "Ann Admin", "FY25 Footprint")
    assert task["due_date"] == "2026-12-01" and task["link"] == f"/?view=review&e={ENG_A}&doc=doc-1"

    assert recipients("task_assigned") == ["debo@acme.test"] and recipients("task_completed") == []
    [(_, _, variables)] = SENT
    # The email says who did what and links to the app: no title, file, client, engagement or note.
    assert variables["email_subject"] == "Ann Admin assigned you a task in Sustentra"
    assert variables["link"] == get_settings().public_base_url.rstrip("/") + "/org/acme/tasks"
    assert not {"title", "engagement", "note", "due_date"} & set(variables)
    for text in map(str, variables.values()):
        for secret in ("boiler", "FY25", "Acme", "secret.pdf", "Please check", "doc-1"):
            assert secret not in text
    [n] = admin("SELECT user_id, kind, title, link, read_at, email_status FROM notifications")
    assert (n["user_id"], n["kind"], n["read_at"], n["email_status"]) == (DEBO, "task_assigned", None, "sent")
    assert n["title"] == "Ann Admin assigned you: Review the boiler fuel invoice"
    assert events() == ["task_created"]


def test_the_server_builds_every_kind_of_link_from_a_checked_target() -> None:
    eng = str(ENG_A)
    links = {
        "engagement": assign("ann", DEBO, engagement_id=eng, target={"kind": "engagement"})["link"],
        "line": assign("ann", DEBO, engagement_id=eng, target={"kind": "line", "item_id": LINE_KEY})["link"],
        "row": assign("ann", DEBO, engagement_id=eng, target={"kind": "methodology_row",
                                                               "item_id": "consolidation_approach"})["link"],
        "none": assign("ann", DEBO)["link"],
    }
    assert links["engagement"] == f"/?view=dashboard&e={eng}"
    assert links["line"] == f"/?view=schedule&e={eng}&line={quote(LINE_KEY, safe='')}"
    assert links["row"] == f"/?view=methodology&e={eng}&row=consolidation_approach"
    assert links["none"] is None
    # Whatever the target, the email only points at the tasks page.
    assert {v["link"] for _, _, v in SENT} == {get_settings().public_base_url.rstrip("/") + "/org/acme/tasks"}


def test_a_target_that_is_not_in_this_engagement_is_refused() -> None:
    eng = str(ENG_A)
    bad = [
        {"engagement_id": eng, "target": {"kind": "document", "item_id": "nope"}},
        {"engagement_id": eng, "target": {"kind": "document", "item_id": "doc-other"}},  # another engagement
        {"engagement_id": eng, "target": {"kind": "document", "item_id": "doc-b"}},  # another org's document
        {"engagement_id": eng, "target": {"kind": "line", "item_id": "s1:stationary:propane:facility:zzz"}},
        {"engagement_id": eng, "target": {"kind": "methodology_row", "item_id": "not-a-field"}},
        {"engagement_id": str(ENG_B), "target": {"kind": "engagement"}},  # another org's engagement
        {"engagement_id": str(ENG_B), "target": {"kind": "document", "item_id": "doc-b"}},
        {"engagement_id": eng, "target": {"kind": "document"}},  # no item
        {"target": {"kind": "engagement"}},  # no engagement
        {"engagement_id": eng, "target": {"kind": "engagement", "path": "/x"}},
    ]
    for extra in bad:
        response = call("POST", tasks_url(), "ann", {"title": "x", "assignee_user_id": str(DEBO), **extra})
        assert response.status_code in (404, 422), (extra, response.text)
    assert admin("SELECT count(*) AS n FROM tasks")[0]["n"] == 0 and SENT == []


def test_a_client_cannot_send_its_own_link() -> None:
    for link in ("https://evil.example/phish", "//evil.example", "/org/beta/anything"):
        response = call("POST", tasks_url(), "ann", {"title": "x", "assignee_user_id": str(DEBO), "link": link})
        assert response.status_code == 422
    assert admin("SELECT count(*) AS n FROM tasks")[0]["n"] == 0


def test_debo_asks_vivian_and_everyone_who_should_hear_is_told() -> None:
    task = assign("debo", VIVIAN)
    assert recipients("task_assigned") == ["vivian@acme.test"]  # the admins are not told about the assignment

    SENT.clear()
    response = call("POST", tasks_url(tail=f"/{task['id']}/done"), "vivian")
    assert response.status_code == 200 and response.json()["status"] == "done"
    assert response.json()["completed_by_name"] == "Vivian Reyes"
    # Debo asked, so Debo is told; both admins are told too; Vivian did it and is not.
    assert recipients("task_completed") == ["ann@acme.test", "debo@acme.test", "zed@acme.test"]
    assert {r["user_id"] for r in admin("SELECT user_id FROM notifications WHERE kind = 'task_completed'")} == {
        ANN, ZED, DEBO}
    assert events() == ["task_created", "task_completed"]


def test_admin_assigns_debo_and_debo_completes_it() -> None:
    task = assign("ann", DEBO)
    SENT.clear()
    assert call("POST", tasks_url(tail=f"/{task['id']}/done"), "debo").status_code == 200
    # Ann asked (and is an admin): she gets ONE email, not two. Zed is the other admin.
    assert recipients("task_completed") == ["ann@acme.test", "zed@acme.test"]


def test_admin_completing_a_task_nobody_else_hears_twice() -> None:
    # Debo asks Ann: Ann finishes it. Debo (requester) and Zed (the other admin) are told; Ann is not.
    task = assign("debo", ANN)
    SENT.clear()
    assert call("POST", tasks_url(tail=f"/{task['id']}/done"), "ann").status_code == 200
    assert recipients("task_completed") == ["debo@acme.test", "zed@acme.test"]

    # Ann's own note to herself: finishing it tells only the other admin.
    mine = assign("ann", ANN, title="Chase the supplier")
    assert recipients("task_assigned") == []  # no "assigned" email for a note to self
    SENT.clear()
    assert call("POST", tasks_url(tail=f"/{mine['id']}/done"), "ann").status_code == 200
    assert recipients("task_completed") == ["zed@acme.test"]


def test_an_admin_can_complete_someone_elses_task() -> None:
    task = assign("debo", VIVIAN)
    SENT.clear()
    assert call("POST", tasks_url(tail=f"/{task['id']}/done"), "zed").status_code == 200
    assert recipients("task_completed") == ["ann@acme.test", "debo@acme.test"]


def test_assignee_must_be_an_active_member_of_the_same_org() -> None:
    for assignee in (BELLA, BEN, SUSPENDED, INVITED, PROVIDER, uuid.uuid4()):
        response = call("POST", tasks_url(), "ann", {"title": "x", "assignee_user_id": str(assignee)})
        assert response.status_code == 422, (assignee, response.text)
    assert SENT == [] and events() == []
    assert admin("SELECT count(*) AS n FROM tasks")[0]["n"] == 0


def test_engagement_must_belong_to_the_org() -> None:
    response = call("POST", tasks_url(), "ann", {"title": "x", "assignee_user_id": str(DEBO),
                                                 "engagement_id": str(ENG_B)})
    assert response.status_code == 422 and SENT == []


def test_cross_org_access_looks_like_the_org_does_not_exist() -> None:
    assert call("POST", tasks_url(), "ben", {"title": "x", "assignee_user_id": str(DEBO)}).status_code == 404
    assert call("GET", tasks_url(tail="/mine"), "bella").status_code == 404
    assert call("GET", notifications_url(), "bella").status_code == 404
    assert call("POST", tasks_url(), None, {"title": "x", "assignee_user_id": str(DEBO)}).status_code == 401


def test_platform_admins_have_no_tasks_of_their_own() -> None:
    assert call("POST", tasks_url(), "provider", {"title": "x", "assignee_user_id": str(DEBO)}).status_code == 403
    assert call("GET", notifications_url(), "provider").status_code == 403


def test_validation() -> None:
    base = {"assignee_user_id": str(DEBO)}
    for bad in ({"title": "  "}, {"title": "x" * 201}, {"title": "x", "note": "n" * 2001},
                {"title": "x", "due_date": "soon"},
                {"title": "x", "surprise": 1}):
        assert call("POST", tasks_url(), "ann", {**base, **bad}).status_code == 422, bad
    assert SENT == []


def test_non_ascii_titles_are_stored_but_never_emailed() -> None:
    title = "Überprüfen: Rechnung \u2014 排放数据 \U0001F69B\nBcc: attacker@evil.test"
    task = assign("ann", DEBO, title=title)
    assert task["title"] == "Überprüfen: Rechnung \u2014 排放数据 \U0001F69B Bcc: attacker@evil.test"
    [(_, _, variables)] = SENT
    assert "排放数据" not in str(variables) and "Überprüfen" not in str(variables)
    assert admin("SELECT title FROM notifications")[0]["title"].endswith("排放数据 \U0001F69B Bcc: attacker@evil.test")


def _limits(monkeypatch: pytest.MonkeyPatch, **limits: int) -> None:
    monkeypatch.setattr(task_service, "get_settings", lambda: Settings(**limits))  # type: ignore[arg-type]


def test_creating_tasks_is_limited_per_person_from_the_database(monkeypatch: pytest.MonkeyPatch) -> None:
    _limits(monkeypatch, task_create_per_hour=3, task_per_assignee_per_hour=50)
    body = {"title": "x", "assignee_user_id": str(DEBO)}
    # A fresh app (a second process) and a reset in-process limiter change nothing: the count is in Postgres.
    codes = []
    for _ in range(4):
        limiter.reset()
        codes.append(call("POST", tasks_url(), "ann", body).status_code)
    assert codes == [201, 201, 201, 429]
    assert call("POST", tasks_url(), "vivian", body).status_code == 201  # someone else's allowance
    # An hour later it is open again.
    admin("UPDATE tasks SET created_at = now() - interval '61 minutes'")
    assert call("POST", tasks_url(), "ann", body).status_code == 201
    assert len(SENT) == 5  # the refused one sent nothing


def test_one_person_cannot_flood_one_assignee_with_emails(monkeypatch: pytest.MonkeyPatch) -> None:
    _limits(monkeypatch, task_create_per_hour=50, task_per_assignee_per_hour=2)
    to_debo = {"title": "x", "assignee_user_id": str(DEBO)}
    assert [call("POST", tasks_url(), "ann", to_debo).status_code for _ in range(3)] == [201, 201, 429]
    assert call("POST", tasks_url(), "ann", {"title": "x", "assignee_user_id": str(VIVIAN)}).status_code == 201
    assert call("POST", tasks_url(), "zed", to_debo).status_code == 201  # another requester
    assert len(recipients("task_assigned")) == 4


def test_completing_and_cancelling_are_limited_per_person(monkeypatch: pytest.MonkeyPatch) -> None:
    _limits(monkeypatch, task_action_per_hour=2)
    ids = [assign("ann", DEBO)["id"] for _ in range(4)]
    assert call("POST", tasks_url(tail=f"/{ids[0]}/done"), "debo").status_code == 200
    assert call("POST", tasks_url(tail=f"/{ids[1]}/cancel"), "ann").status_code == 200
    assert call("POST", tasks_url(tail=f"/{ids[2]}/done"), "debo").status_code == 200
    assert call("POST", tasks_url(tail=f"/{ids[3]}/done"), "debo").status_code == 429  # Debo's third
    assert call("POST", tasks_url(tail=f"/{ids[3]}/cancel"), "ann").status_code == 200  # Ann has used one of two


# --- email failures -------------------------------------------------------------------------

@pytest.mark.parametrize("mode", ["false", "raise"])
def test_an_email_failure_does_not_fail_the_action(mode: str) -> None:
    SENDER_MODE["mode"] = mode
    task = assign("ann", DEBO)  # still 201
    assert admin("SELECT email_status FROM notifications")[0]["email_status"] == "failed"
    assert call("GET", notifications_url(), "debo").json()["unread_count"] == 1  # the bell still has it

    response = call("POST", tasks_url(tail=f"/{task['id']}/done"), "debo")
    assert response.status_code == 200 and response.json()["status"] == "done"
    rows = admin("SELECT email_status FROM notifications WHERE kind = 'task_completed'")
    assert len(rows) == 2 and {r["email_status"] for r in rows} == {"failed"}


# --- who sees / changes what ------------------------------------------------------------------

def test_org_wide_list_is_for_admins_only() -> None:
    assign("debo", VIVIAN)
    assign("vivian", ANN, title="Second")
    assert call("GET", tasks_url(), "debo").status_code == 403
    assert call("GET", tasks_url(), None).status_code == 401
    assert call("GET", tasks_url(), "ben").status_code == 404  # another org's admin
    body = call("GET", tasks_url(), "zed").json()
    assert body["total"] == 2 and {t["title"] for t in body["items"]} == {"Review the boiler fuel invoice", "Second"}
    assert call("GET", tasks_url(), "provider").status_code == 200

    only = call("GET", tasks_url(), "ann", params={"assignee_user_id": str(ANN)}).json()
    assert [t["title"] for t in only["items"]] == ["Second"]
    assert call("GET", tasks_url(), "ann", params={"requested_by_user_id": str(DEBO), "status": "done"}).json()[
        "total"] == 0
    assert call("GET", tasks_url(), "ann", params={"engagement_id": str(ENG_B)}).json()["total"] == 0
    assert call("GET", tasks_url(), "ann", params={"status": "bogus"}).status_code == 422


def test_my_tasks_assigned_and_requested() -> None:
    assign("debo", VIVIAN, title="For Vivian")
    assign("ann", DEBO, title="For Debo")
    mine = call("GET", tasks_url(tail="/mine"), "debo").json()["items"]
    assert [t["title"] for t in mine] == ["For Debo"]
    asked = call("GET", tasks_url(tail="/mine"), "debo", params={"relation": "requested"}).json()["items"]
    assert [t["title"] for t in asked] == ["For Vivian"]
    assert call("GET", tasks_url(tail="/mine"), "zed").json()["items"] == []  # admins see theirs here, the rest in the org list
    assert call("GET", tasks_url(tail="/mine"), "debo", params={"status": "done"}).json()["items"] == []


def test_complete_and_cancel_permissions_and_states() -> None:
    task = assign("debo", VIVIAN)
    tid = task["id"]
    stranger = "bella"  # other org
    assert call("POST", tasks_url(tail=f"/{tid}/done"), stranger).status_code == 404
    # The requester asked for it but is not the assignee: cannot mark it done, can cancel it.
    assert call("POST", tasks_url(tail=f"/{tid}/done"), "debo").status_code == 403
    assert call("POST", tasks_url(tail=f"/{tid}/cancel"), "vivian").status_code == 403
    assert call("POST", tasks_url(tail="/not-a-uuid/done"), "vivian").status_code == 404
    assert call("POST", tasks_url(tail=f"/{uuid.uuid4()}/done"), "vivian").status_code == 404

    cancelled = call("POST", tasks_url(tail=f"/{tid}/cancel"), "debo")
    assert cancelled.status_code == 200 and cancelled.json()["status"] == "cancelled"
    assert call("POST", tasks_url(tail=f"/{tid}/done"), "vivian").status_code == 409
    assert call("POST", tasks_url(tail=f"/{tid}/cancel"), "ann").status_code == 409
    assert events() == ["task_created", "task_cancelled"]
    assert recipients("task_completed") == []  # cancelling sends no email


def test_a_member_who_is_not_involved_cannot_even_see_the_task() -> None:
    task = assign("ann", DEBO)
    for action in ("done", "cancel"):
        assert call("POST", tasks_url(tail=f"/{task['id']}/{action}"), "vivian").status_code == 404
    assert admin("SELECT status FROM tasks")[0]["status"] == "open"
    assert call("POST", tasks_url(tail=f"/{task['id']}/cancel"), "zed").status_code == 200  # an admin can


def test_done_twice_is_a_conflict_and_sends_nothing_new() -> None:
    task = assign("debo", VIVIAN)
    assert call("POST", tasks_url(tail=f"/{task['id']}/done"), "vivian").status_code == 200
    SENT.clear()
    assert call("POST", tasks_url(tail=f"/{task['id']}/done"), "vivian").status_code == 409
    assert SENT == []


def test_assignees_are_the_active_members_of_my_org() -> None:
    names = {m["name"] for m in call("GET", tasks_url(tail="/assignees"), "debo").json()["items"]}
    assert names == {"Ann Admin", "Zed Admin", "Debo Okafor", "Vivian Reyes"}


# --- notifications ----------------------------------------------------------------------------

def test_the_bell_lists_counts_and_marks_read() -> None:
    assign("ann", DEBO, title="One")
    assign("zed", DEBO, title="Two")
    assert call("GET", notifications_url(tail="/unread-count"), "debo").json() == {"unread_count": 2}
    listing = call("GET", notifications_url(), "debo").json()
    assert listing["unread_count"] == 2 and [n["title"].split(": ")[1] for n in listing["items"]] == ["Two", "One"]
    first = listing["items"][0]
    assert first["kind"] == "task_assigned" and first["read_at"] is None

    # Someone else cannot read my notification, nor see it.
    assert call("POST", notifications_url(tail=f"/{first['id']}/read"), "vivian").status_code == 404
    assert call("GET", notifications_url(), "vivian").json() == {"items": [], "unread_count": 0}

    read = call("POST", notifications_url(tail=f"/{first['id']}/read"), "debo")
    assert read.status_code == 200 and read.json()["read_at"] is not None
    assert call("POST", notifications_url(tail=f"/{first['id']}/read"), "debo").status_code == 200  # idempotent
    assert call("GET", notifications_url(tail="/unread-count"), "debo").json() == {"unread_count": 1}
    assert len(call("GET", notifications_url(), "debo", params={"unread_only": "true"}).json()["items"]) == 1

    assert call("POST", notifications_url(tail="/read-all"), "debo").json() == {"updated": 1}
    assert call("GET", notifications_url(tail="/unread-count"), "debo").json() == {"unread_count": 0}
    assert call("POST", notifications_url(tail="/not-a-uuid/read"), "debo").status_code == 404


def test_admins_see_every_notification_in_the_company() -> None:
    assign("debo", VIVIAN)
    assert call("GET", notifications_url(tail="/org"), "debo").status_code == 403
    body = call("GET", notifications_url(tail="/org"), "ann").json()
    assert body["total"] == 1 and body["items"][0]["user_name"] == "Vivian Reyes"
    assert body["items"][0]["email_status"] == "sent"
    assert call("GET", notifications_url(tail="/org"), "ann", params={"user_id": str(DEBO)}).json()["total"] == 0
    assert call("GET", notifications_url(tail="/org"), "ben").status_code == 404


# --- database-level isolation -----------------------------------------------------------------

def test_row_level_security_keeps_orgs_apart() -> None:
    assign("debo", VIVIAN)

    async def count_as(org: uuid.UUID) -> tuple[int, int]:
        conn = await asyncpg.connect(APP_URL)
        try:
            async with conn.transaction():
                await conn.execute("SELECT set_config('app.tenant_id', $1, true), "
                                   "set_config('app.is_provider', 'false', true)", str(org))
                tasks = await conn.fetchval("SELECT count(*) FROM tasks")
                notes = await conn.fetchval("SELECT count(*) FROM notifications")
                return int(tasks), int(notes)
        finally:
            await conn.close()

    assert asyncio.run(count_as(ORG_A)) == (1, 1)
    assert asyncio.run(count_as(ORG_B)) == (0, 0)

    async def cross_org_insert() -> None:
        conn = await asyncpg.connect(APP_URL)
        try:
            async with conn.transaction():
                await conn.execute("SELECT set_config('app.tenant_id', $1, true)", str(ORG_B))
                await conn.execute("INSERT INTO tasks (org_id, title, assignee_user_id, requested_by_user_id) "
                                   "VALUES ($1, 'x', $2, $2)", ORG_A, DEBO)
        finally:
            await conn.close()

    with pytest.raises(asyncpg.PostgresError):
        asyncio.run(cross_org_insert())
