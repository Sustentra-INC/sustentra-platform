@pytest.fixture
def quick(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(api, "BUSY_POLL_SECONDS", 0.05)
    monkeypatch.setattr(api, "BUSY_WAIT_SECONDS", 0.3)


def test_a_read_in_flight_causes_a_skip_when_it_does_not_end(claude: FakeClaude, quick: None) -> None:
    eid = create()["id"]
    api._RUNNING.add(eid)
    try:
        result = auto(eid)
    finally:
        api._RUNNING.discard(eid)
    assert result.state == "skipped" and result.reason_code == "busy"
    assert claude.calls == [] and ledger() == []
    assert [e["reason_code"] for e in events()] == ["busy"]


def test_busy_waits_for_the_current_read_to_end_and_then_reads_once(claude: FakeClaude,
                                                                    monkeypatch: pytest.MonkeyPatch) -> None:
    import threading

    monkeypatch.setattr(api, "BUSY_POLL_SECONDS", 0.05)
    monkeypatch.setattr(api, "BUSY_WAIT_SECONDS", 5.0)
    eid = create()["id"]
    api._RUNNING.add(eid)
    threading.Timer(0.4, lambda: api._RUNNING.discard(eid)).start()
    result = auto(eid)
    assert result.state == "done" and len(ledger()) == 1 and len(claude.calls) == 3
    assert [e["outcome"] for e in events()] == ["ok"]  # nothing was lost, nothing skipped


def test_the_busy_guard_is_per_engagement_not_per_organization(claude: FakeClaude, quick: None) -> None:
    one, two = create()["id"], create()["id"]
    api._RUNNING.add(one)
    try:
        assert auto(two).state == "done"  # another engagement of the same organization is not blocked
    finally:
        api._RUNNING.discard(one)


class _Blind:
    """A guard that never knows anyone: only the database claim stands between two callers."""

    def __contains__(self, item: object) -> bool:
        return False

    def add(self, item: str) -> None: ...

    def discard(self, item: str) -> None: ...


def test_two_concurrent_callers_make_exactly_one_ai_call(claude: FakeClaude, monkeypatch: pytest.MonkeyPatch) -> None:
    import time

    eid = create()["id"]
    monkeypatch.setattr(api, "_RUNNING", _Blind())  # as if the other caller were another process
    monkeypatch.setattr(api, "BUSY_WAIT_SECONDS", 0.0)
    original = claude.structured

    def slow(**kw: Any) -> Any:
        time.sleep(0.4)
        return original(**kw)

    monkeypatch.setattr(claude, "structured", slow)

    async def both() -> list[api.AutoReadResult]:
        engine = db.create_engine(APP_URL or "", pool_size=4, max_overflow=0)
        try:
            sessions = db.build_sessionmaker(engine)
            return list(await asyncio.gather(
                api.run_automatic_prefill(str(ORG_A), eid, ["a.pdf"], sessions),
                api.run_automatic_prefill(str(ORG_A), eid, ["b.pdf"], sessions)))
        finally:
            await engine.dispose()

    results = asyncio.run(both())
    assert sorted(r.state for r in results) == ["done", "skipped"]
    assert [r.reason_code for r in results if r.state == "skipped"] == ["busy"]
    assert len(ledger()) == 1 and len(claude.calls) == 3  # one read: its three parts, once
    assert claim_of(eid) is None  # released


def claim_of(eid: str) -> Any:
    rows = asyncio.run(_admin("SELECT payload->'claim' AS c FROM workpaper_items WHERE engagement_id = $1::uuid "
                              "AND item_key = 'meta:state'", eid))
    return json.loads(rows[0]["c"]) if rows and rows[0]["c"] else None


def hold_claim(eid: str, seconds_ago: int = 0) -> None:
    asyncio.run(_admin(
        "INSERT INTO workpaper_items (org_id, engagement_id, kind, item_key, payload) VALUES ($1, $2::uuid, "
        "'methodology', 'meta:state', '{}'::jsonb) ON CONFLICT DO NOTHING", ORG_A, eid))
    asyncio.run(_admin(
        "UPDATE workpaper_items SET payload = jsonb_set(payload, '{claim}', jsonb_build_object('by', 'other', 'at', "
        "to_jsonb(now() - make_interval(secs => $2)))) WHERE engagement_id = $1::uuid AND item_key = 'meta:state'",
        eid, float(seconds_ago)))


def test_the_button_answers_409_while_another_process_holds_the_claim(claude: FakeClaude) -> None:
    eid = create()["id"]
    hold_claim(eid)
    refused = call("POST", f"{BASE}/{eid}/methodology-review/prefill")
    assert refused.status_code == 409 and "already being prepared" in refused.json()["detail"]
    assert claude.calls == [] and ledger() == []
    hold_claim(eid, seconds_ago=120)  # an expired claim (its process stopped) is free
    assert call("POST", f"{BASE}/{eid}/methodology-review/prefill").status_code == 200
    assert len(claude.calls) == 3 and claim_of(eid) is None


def test_the_claim_is_renewed_while_the_read_lasts(claude: FakeClaude, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(api, "HEARTBEAT_SECONDS", 0.1)
    eid = create()["id"]

    async def at() -> Any:
        rows = await _admin("SELECT payload->'claim'->>'at' AS at FROM workpaper_items WHERE engagement_id = $1::uuid "
                            "AND item_key = 'meta:state'", eid)
        return rows[0]["at"]

    async def go() -> list[Any]:
        engine = db.create_engine(APP_URL or "", pool_size=2, max_overflow=0)
        try:
            sessions = db.build_sessionmaker(engine)
            async with api._short_transaction(sessions, ORG_A) as session:
                engagement = await api.engagement_service.get_engagement(session, eid)
            seen = []
            async with api._claimed(sessions, engagement):
                for _ in range(3):
                    await asyncio.sleep(0.25)
                    seen.append(await at())
            return seen
        finally:
            await engine.dispose()

    seen = asyncio.run(go())
    assert len(set(seen)) == 3  # the claim's time moved on at each look
    assert claim_of(eid) is None


def test_a_reading_marker_without_a_heartbeat_reads_as_interrupted(claude: FakeClaude) -> None:
    eid = create()["id"]
    assert prepare(eid)  # a marker exists
    asyncio.run(_admin(
        "UPDATE workpaper_items SET payload = jsonb_set(payload, '{auto_read,state}', '\"reading\"') "
        "WHERE engagement_id = $1::uuid AND item_key = 'meta:state'", eid))
    hold_claim(eid, seconds_ago=5)
    assert review(eid).json()["auto_read"]["state"] == "reading"  # alive: the claim is recent
    hold_claim(eid, seconds_ago=90)
    for shown in (review(eid).json()["auto_read"],
                  call("GET", f"{BASE}/{eid}/methodology-review/auto-read").json()["auto_read"]):
        assert shown["state"] == "failed" and shown["reason"] == "Reading was interrupted. Try again."
    asyncio.run(_admin("UPDATE workpaper_items SET payload = payload - 'claim' WHERE engagement_id = $1::uuid "
                       "AND item_key = 'meta:state'", eid))
    assert review(eid).json()["auto_read"]["state"] == "failed"  # no claim at all: interrupted too
    assert call("POST", f"{BASE}/{eid}/methodology-review/prefill").status_code == 200  # the button works again
    assert (review(eid).json()["auto_read"] or {}).get("state") != "failed"  # and the old failure is gone


def test_a_provider_failure_shows_as_a_failure(claude: FakeClaude) -> None:
    eid = create()["id"]
    claude.fail = True
    result = auto(eid)
    assert result.state == "failed" and "could not be reached" in (result.reason or "")
    shown = review(eid).json()["auto_read"]
    assert shown["state"] == "failed" and "could not be reached" in shown["reason"]
    assert [e["outcome"] for e in events()] == ["failed"]


def test_suggestions_that_could_not_be_saved_show_as_a_failure(claude: FakeClaude,
                                                               monkeypatch: pytest.MonkeyPatch) -> None:
    eid = create()["id"]

    async def broken(*args: Any, **kw: Any) -> Any:
        raise RuntimeError("disk full")

    monkeypatch.setattr(api, "_store", broken)
    result = auto(eid)
    assert result.state == "failed" and result.reason_code == "not_saved" and "could not be saved" in (result.reason or "")
    shown = review(eid).json()["auto_read"]
    assert shown["state"] == "failed" and "could not be saved" in shown["reason"]


