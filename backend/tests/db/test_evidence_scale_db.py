"""MVP-160: the Evidence tree, a line's schedule and the recalculation stay cheap with hundreds of documents.

Through the real app with the Postgres S1 stores as ``app_user`` (RLS on):

* the number of SQL statements of a request does not grow with the number of documents (no N+1);
* what the schedule and the recalculation keep is refreshed by every kind of change that could alter a
  total, and a kept answer is always the one a fresh calculation gives;
* another organization never gets a kept answer.

Needs TEST_DATABASE_URL (owner, for seeding) and TEST_APP_DATABASE_URL (app_user). The same seed runs as a
benchmark: ``python -m backend.tests.db._evidence_scale --documents 50 500``.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Iterator
from typing import Any

import pytest

from backend.app.api import evidence_tree as tree_api
from backend.app.services import evidence_cache
from backend.tests.db import _evidence_scale as scale

ADMIN_URL = os.environ.get("TEST_DATABASE_URL")
APP_URL = os.environ.get("TEST_APP_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not (ADMIN_URL and APP_URL), reason="TEST_DATABASE_URL / TEST_APP_DATABASE_URL not set"
)

PATHS = {"tree": "/evidence-tree", "schedule": f"/calculation-lines/{scale.GAS_LINE}/schedule",
         "recalculation": "/recalculation"}
GAS_DOCUMENT = "SC-0040"  # a Kansas City gas document on the line the schedule is read for


@pytest.fixture(scope="module")
def get() -> Iterator[Callable[..., Any]]:
    with scale.wired_app(APP_URL or "") as client:
        yield client


@pytest.fixture
def engagement(get: Callable[..., Any]) -> str:
    """A 60-document engagement, with nothing kept for it."""

    evidence_cache.LOADED.clear()
    evidence_cache.RECALCULATION.clear()
    return scale.seed(ADMIN_URL or "", 60)


def read(get: Callable[..., Any], engagement_id: str, name: str, token: str = scale.TOKEN) -> Any:
    return get(f"/api/v1/engagements/{engagement_id}{PATHS[name]}", token)


def fresh(get: Callable[..., Any], engagement_id: str, name: str) -> Any:
    """What a calculation from scratch answers: nothing kept."""

    evidence_cache.LOADED.clear()
    evidence_cache.RECALCULATION.clear()
    response = read(get, engagement_id, name)
    assert response.status_code == 200, response.text[:300]
    return response.json()


# --- no N+1 ---------------------------------------------------------------------------------------------
def cold_statements(get: Callable[..., Any], engagement_id: str, name: str) -> tuple[int, int]:
    evidence_cache.LOADED.clear()
    evidence_cache.RECALCULATION.clear()
    counter = scale.StatementCounter()
    with counter.counting():
        response = read(get, engagement_id, name)
    assert response.status_code == 200, response.text[:300]
    return counter.queries, counter.total


def test_the_statement_count_does_not_grow_with_the_number_of_documents(get: Callable[..., Any]) -> None:
    counts: dict[int, dict[str, tuple[int, int]]] = {}
    warm = scale.seed(ADMIN_URL or "", 50)  # once-only work (a first connection, a lookup kept for good) is not counted
    for name in PATHS:
        cold_statements(get, warm, name)
    for documents in (50, 500):
        engagement_id = scale.seed(ADMIN_URL or "", documents)
        counts[documents] = {name: cold_statements(get, engagement_id, name) for name in PATHS}
    assert counts[50] == counts[500], counts
    for name, (queries, total) in counts[500].items():
        assert queries <= 40 and total <= 60, (name, queries, total)  # the old code ran 1,000 to 2,500


def test_a_kept_answer_runs_no_more_than_the_stamp(get: Callable[..., Any], engagement: str) -> None:
    for name in PATHS:
        read(get, engagement, name)
    for name in PATHS:
        counter = scale.StatementCounter()
        with counter.counting():
            assert read(get, engagement, name).status_code == 200
        assert counter.queries <= 16, (name, counter.queries)  # the engagement, the stamps, the names: no row reads


# --- every kind of change refreshes what is kept ----------------------------------------------------------
DECIDE = (
    "INSERT INTO s1_review_decisions (org_id, review_decision_id, candidate_id, evidence_id, document_id, "
    "field_name, record) SELECT org_id, review_decision_id || '-new', candidate_id, evidence_id, document_id, "
    "field_name, jsonb_set(jsonb_set(record, '{decision}', to_jsonb(CAST(:value AS text))), "
    "'{review_decision_id}', to_jsonb(review_decision_id || '-new')) FROM s1_review_decisions "
    "WHERE document_id = :doc AND field_name = 'activity_quantity' ORDER BY seq LIMIT 1"
)


def a_reviewer_rejects_a_value(engagement_id: str) -> None:
    scale.run_admin(ADMIN_URL or "", DECIDE, doc=GAS_DOCUMENT, value="rejected")


def a_reviewer_withdraws_a_document(engagement_id: str) -> None:
    scale.run_admin(
        ADMIN_URL or "",
        "INSERT INTO workpaper_items (org_id, engagement_id, kind, item_key, payload) VALUES "
        "(:org, :eng, 'document', :doc, CAST(:payload AS jsonb)) ON CONFLICT (engagement_id, kind, item_key) "
        "DO UPDATE SET payload = EXCLUDED.payload",
        org=scale.ORG, eng=engagement_id, doc=GAS_DOCUMENT,
        payload=json.dumps({"documentId": GAS_DOCUMENT, "disposition": "withdrawn"}))


def a_note_on_a_document_changes(engagement_id: str) -> None:
    scale.run_admin(
        ADMIN_URL or "",
        "UPDATE workpaper_items SET payload = jsonb_set(payload, '{note}', '\"rechecked\"') "
        "WHERE engagement_id = :eng AND kind = 'document' AND item_key = 'SC-0000'", eng=engagement_id)


def the_methodology_review_chooses_a_gwp_set(engagement_id: str) -> None:
    scale.run_admin(
        ADMIN_URL or "",
        "INSERT INTO workpaper_items (org_id, engagement_id, kind, item_key, payload) VALUES "
        "(:org, :eng, 'methodology', 'gwp', CAST(:payload AS jsonb))",
        org=scale.ORG, eng=engagement_id,
        payload=json.dumps({"decision": {"status": "accepted",
                                         "value": {"set": "AR6", "horizon": "100-year", "applies_to": ""}}}))


def setup_drops_a_facility(engagement_id: str) -> None:
    kept = [f for f in scale.FACILITIES if f["facilityId"] != "fac-den3"]
    scale.run_admin(ADMIN_URL or "",
                    "UPDATE engagements SET settings = jsonb_set(settings, '{facilities}', CAST(:f AS jsonb)) "
                    "WHERE id = CAST(:eng AS uuid)", f=json.dumps(kept), eng=engagement_id)


def the_reporting_period_changes(engagement_id: str) -> None:
    scale.run_admin(ADMIN_URL or "", "UPDATE engagements SET reporting_period_end = '2024-06-30' "
                                     "WHERE id = CAST(:eng AS uuid)", eng=engagement_id)


def a_document_is_added(engagement_id: str) -> None:
    scale.add_gas_document(ADMIN_URL or "", engagement_id)


def a_document_is_read_again(engagement_id: str) -> None:
    scale.run_admin(
        ADMIN_URL or "",
        "INSERT INTO s1_extraction_results (org_id, pipeline_run_id, document_id, evidence_id, record) "
        "SELECT org_id, pipeline_run_id || '-again', document_id, evidence_id, "
        "jsonb_set(jsonb_set(record, '{pipeline_run_id}', to_jsonb(pipeline_run_id || '-again')), "
        "'{canonical_type_id}', '\"CT-S2-ELEC\"') FROM s1_extraction_results WHERE document_id = :doc",
        doc=GAS_DOCUMENT)


def _document_item(engagement_id: str, payload: dict[str, Any]) -> None:
    scale.run_admin(
        ADMIN_URL or "",
        "INSERT INTO workpaper_items (org_id, engagement_id, kind, item_key, payload) VALUES "
        "(:org, :eng, 'document', :doc, CAST(:payload AS jsonb)) ON CONFLICT (engagement_id, kind, item_key) "
        "DO UPDATE SET payload = EXCLUDED.payload, updated_at = now()",
        org=scale.ORG, eng=engagement_id, doc=GAS_DOCUMENT, payload=json.dumps({"documentId": GAS_DOCUMENT, **payload}))


def a_document_is_moved(engagement_id: str) -> None:
    _document_item(engagement_id, {"placements": [{"from": scale.GAS_LINE, "to": "block:unassigned"}]})


def a_document_is_set_aside_as_a_duplicate(engagement_id: str) -> None:
    _document_item(engagement_id, {"relationships": [{"kind": "duplicate", "otherDocumentId": "SC-0046"}]})


def reported_totals_are_typed_in(engagement_id: str) -> None:
    scale.run_admin(ADMIN_URL or "",
                    "UPDATE engagements SET settings = jsonb_set(settings, '{recalculation,reported}', "
                    "CAST(:r AS jsonb)) WHERE id = CAST(:eng AS uuid)", r=json.dumps({"scope1_total": 1234.5}),
                    eng=engagement_id)


def the_vehicle_groups_change(engagement_id: str) -> None:
    group = {**scale.VEHICLE_GROUPS[0], "group_id": "vg-two", "label": "Forklifts", "on_road": False,
             "fuel_quantity": 200, "fuel_unit": "gal"}
    scale.run_admin(ADMIN_URL or "",
                    "UPDATE engagements SET settings = jsonb_set(settings, '{recalculation,vehicle_groups}', "
                    "CAST(:g AS jsonb)) WHERE id = CAST(:eng AS uuid)",
                    g=json.dumps([*scale.VEHICLE_GROUPS, group]), eng=engagement_id)


def an_ai_reading_lands(engagement_id: str) -> None:
    """A newer extraction result (what the AI or Textract reader writes) for a document, with another quantity."""

    scale.run_admin(
        ADMIN_URL or "",
        "INSERT INTO s1_extraction_results (org_id, pipeline_run_id, document_id, evidence_id, record) "
        "SELECT org_id, pipeline_run_id || '-ai', document_id, evidence_id, "
        "jsonb_set(jsonb_set(record, '{pipeline_run_id}', to_jsonb(pipeline_run_id || '-ai')), "
        "'{items}', (SELECT jsonb_agg(CASE WHEN i->>'field_name' = 'activity_quantity' "
        "THEN jsonb_set(i, '{normalized_value}', '999') ELSE i END) FROM jsonb_array_elements(record->'items') i)) "
        "FROM s1_extraction_results WHERE document_id = :doc ORDER BY seq DESC LIMIT 1", doc=GAS_DOCUMENT)


def a_document_changes_status(engagement_id: str) -> None:
    scale.run_admin(
        ADMIN_URL or "",
        "UPDATE s1_documents SET processing_status = 'failed', "
        "record = jsonb_set(record, '{processing_status}', '\"failed\"') WHERE document_id = :doc", doc=GAS_DOCUMENT)


# change -> the reads whose answer it must change (every read must still equal a fresh calculation)
CHANGES: dict[str, tuple[Callable[[str], None], set[str]]] = {
    "a reviewer rejects a value": (a_reviewer_rejects_a_value, {"tree", "schedule", "recalculation"}),
    "a reviewer withdraws a document": (a_reviewer_withdraws_a_document, {"tree", "schedule", "recalculation"}),
    "a note on a document": (a_note_on_a_document_changes, set()),
    "the Methodology review chooses a GWP set": (the_methodology_review_chooses_a_gwp_set, {"recalculation"}),
    "Setup drops a facility": (setup_drops_a_facility, {"tree", "recalculation"}),
    "the reporting period changes": (the_reporting_period_changes, {"recalculation"}),
    "a document is added": (a_document_is_added, {"tree", "schedule", "recalculation"}),
    "a document is read again": (a_document_is_read_again, {"tree", "schedule", "recalculation"}),
    "a document changes status": (a_document_changes_status, {"tree"}),
    "a document is moved to another line": (a_document_is_moved, {"tree", "schedule"}),
    "a document is set aside as a duplicate": (a_document_is_set_aside_as_a_duplicate, {"tree", "schedule", "recalculation"}),
    "reported totals are typed in": (reported_totals_are_typed_in, {"recalculation"}),
    "the vehicle groups change": (the_vehicle_groups_change, {"tree", "recalculation"}),
    "an AI or Textract reading lands": (an_ai_reading_lands, {"schedule", "recalculation"}),
}


@pytest.mark.parametrize("change", list(CHANGES))
def test_every_kind_of_change_refreshes_what_is_kept(get: Callable[..., Any], engagement: str, change: str) -> None:
    apply, must_differ = CHANGES[change]
    before = {name: fresh(get, engagement, name) for name in PATHS}
    evidence_cache.LOADED.hits = evidence_cache.RECALCULATION.hits = 0
    for name in PATHS:  # kept now: the reads that follow are answered from what is kept
        assert read(get, engagement, name).json() == before[name]
    assert evidence_cache.LOADED.hits + evidence_cache.RECALCULATION.hits > 0
    apply(engagement)
    for name in PATHS:
        after = read(get, engagement, name)
        assert after.status_code == 200, after.text[:300]
        assert after.json() == fresh(get, engagement, name), f"{name}: kept answer differs from a fresh one"
        if name in must_differ:
            assert after.json() != before[name], f"{name}: the change did not reach the answer"
        # the next read of the fresh answer is kept again (the entry is replaced, not dropped for good)
        read(get, engagement, name)
        assert read(get, engagement, name).json() == after.json()


def test_a_heartbeat_on_a_running_methodology_read_does_not_refresh_what_is_kept(
        get: Callable[..., Any], engagement: str) -> None:
    scale.run_admin(
        ADMIN_URL or "",
        "INSERT INTO workpaper_items (org_id, engagement_id, kind, item_key, payload) VALUES "
        "(:org, :eng, 'methodology', 'gwp', CAST(:payload AS jsonb))",
        org=scale.ORG, eng=engagement, payload=json.dumps({"claim": {"by": "worker-1", "at": "2026-11-26T10:00:00Z"}}))
    read(get, engagement, "recalculation")
    hits = evidence_cache.RECALCULATION.hits
    scale.run_admin(
        ADMIN_URL or "",
        "UPDATE workpaper_items SET payload = jsonb_set(payload, '{claim,at}', '\"2026-11-26T10:00:15Z\"') "
        "WHERE engagement_id = :eng AND kind = 'methodology'", eng=engagement)
    assert read(get, engagement, "recalculation").status_code == 200
    assert evidence_cache.RECALCULATION.hits == hits + 1


# --- organizations ------------------------------------------------------------------------------------------
def test_another_organization_never_gets_a_kept_answer(get: Callable[..., Any], engagement: str) -> None:
    for name in PATHS:
        assert read(get, engagement, name).status_code == 200  # kept for organization A
    before = (evidence_cache.LOADED.hits, evidence_cache.RECALCULATION.hits)
    for name in PATHS:
        other = read(get, engagement, name, scale.OTHER_TOKEN)
        assert other.status_code == 404, (name, other.status_code)
        assert "Kansas" not in other.text and "SC-" not in other.text
    assert (evidence_cache.LOADED.hits, evidence_cache.RECALCULATION.hits) == before
    # and the entries are keyed by organization: B has none, A still has its own
    stamp = "any"
    assert evidence_cache.RECALCULATION.get((f"org:{scale.OTHER_ORG}", engagement), stamp) is None
    assert evidence_cache.LOADED.get((f"org:{scale.OTHER_ORG}", engagement), stamp) is None
    assert read(get, engagement, "recalculation").status_code == 200


# --- hostile data ---------------------------------------------------------------------------------------------
def test_odd_documents_do_not_take_the_pages_down(get: Callable[..., Any], engagement: str) -> None:
    now = "2026-11-26T10:00:00+00:00"
    odd = ["DOC-Müller Käserei – 電気 CO₂ 90°F", "DOC-" + "x" * 3000, "DOC-'; DROP TABLE s1_documents; --", "DOC-empty"]
    for index, document_id in enumerate(odd):
        record = {"document_id": document_id, "engagement_id": engagement, "evidence_id": f"EV-odd-{index}",
                  "file_name": "ü" * 5000 if index == 1 else f"odd {index}.pdf", "mime_type": "application/pdf",
                  "storage_uri": f"mem://odd/{index}", "document_role": "source_evidence", "document_type": None,
                  "uploaded_by": "a@b.test", "uploaded_at": now, "processing_status": "processed",
                  "org_id": str(scale.ORG)}
        scale.run_admin(
            ADMIN_URL or "",
            "INSERT INTO s1_documents (org_id, document_id, engagement_id, evidence_id, processing_status, record) "
            "VALUES (:org, :doc, :eng, :ev, 'processed', CAST(:record AS jsonb))",
            org=scale.ORG, doc=document_id, eng=engagement, ev=f"EV-odd-{index}", record=json.dumps(record))
    # a read with no items at all, one with a decision that names no candidate, one with another org's decision
    scale.run_admin(
        ADMIN_URL or "",
        "INSERT INTO s1_extraction_results (org_id, pipeline_run_id, document_id, evidence_id, record) "
        "VALUES (:org, 'run-odd', :doc, 'EV-odd-0', CAST(:record AS jsonb))",
        org=scale.ORG, doc=odd[0], record=json.dumps({
            "pipeline_run_id": "run-odd", "document_id": odd[0], "evidence_id": "EV-odd-0", "items": [],
            "canonical_type_id": "CT-S1-FUELQTY", "org_id": str(scale.ORG)}))
    for name in PATHS:
        response = read(get, engagement, name)
        assert response.status_code == 200, (name, response.text[:300])
        assert read(get, engagement, name).json() == response.json()  # and kept, the same


# --- a write while a result is being worked out ----------------------------------------------------------------
def test_a_write_between_the_stamp_and_the_load_is_not_kept(
        get: Callable[..., Any], engagement: str, monkeypatch: pytest.MonkeyPatch) -> None:
    original = tree_api.document_decisions

    async def racing(db: Any, eng: dict[str, Any]) -> Any:
        a_reviewer_rejects_a_value(engagement)  # lands after the stamp was taken, before the load finishes
        return await original(db, eng)

    monkeypatch.setattr(tree_api, "document_decisions", racing)
    raced = read(get, engagement, "schedule")
    monkeypatch.setattr(tree_api, "document_decisions", original)
    assert raced.status_code == 200
    assert len(evidence_cache.LOADED) == 0  # not kept under the old stamp
    after = read(get, engagement, "schedule")
    assert after.json() == fresh(get, engagement, "schedule")  # and the next read is the true one


def test_a_change_that_is_undone_still_refreshes(get: Callable[..., Any], engagement: str) -> None:
    """A, then B, then A again: the stamp moved on, so what was kept is not served by luck."""

    _document_item(engagement, {"note": "a"})
    read(get, engagement, "tree")
    kept = (evidence_cache.LOADED.hits, evidence_cache.LOADED.misses)
    _document_item(engagement, {"note": "b"})
    _document_item(engagement, {"note": "a"})
    read(get, engagement, "tree")
    assert evidence_cache.LOADED.misses == kept[1] + 1 and evidence_cache.LOADED.hits == kept[0]


# --- a reviewer's decision on a calculation line (F3b) -------------------------------------------------------------
def workbook(get: Callable[..., Any], engagement_id: str) -> dict[str, list[list[Any]]]:
    """The Excel workpaper's cell values, sheet by sheet."""

    import io

    from openpyxl import load_workbook

    response = get(f"/api/v1/engagements/{engagement_id}/export")
    assert response.status_code == 200, response.text[:300]
    book = load_workbook(io.BytesIO(response.content), data_only=True)
    return {sheet.title: [list(row) for row in sheet.iter_rows(values_only=True)] for sheet in book.worksheets}


def test_a_calc_line_decision_reaches_results_the_schedule_and_the_workpaper_alike(
        get: Callable[..., Any], engagement: str) -> None:
    base = f"/api/v1/engagements/{engagement}"
    before = {name: fresh(get, engagement, name) for name in PATHS}
    sheets_before = workbook(get, engagement)
    for name in PATHS:  # kept now
        read(get, engagement, name)
    kept_before = (len(evidence_cache.RECALCULATION), evidence_cache.RECALCULATION.hits)

    trace = get(f"{base}/recalculation/lines/{scale.GAS_LINE}/trace").json()["trace"]
    target = next((i for i in trace["inputs"].values()
                   if isinstance((i.get("recomputed") or {}).get("value"), (int, float))), None)
    assert target is not None, "the line has an input a reviewer can edit"
    edit = {"action": "edit", "value": target["recomputed"]["value"] * 2, "unit": target["recomputed"].get("unit"),
            "reason": "Invoice shows more"}
    posted = get(f"{base}/calculation-lines/{scale.GAS_LINE}/inputs/{target['id']}/recomputed", scale.TOKEN, edit)
    assert posted.status_code == 200, posted.text[:300]
    # a decision's own check (it carries a proposal) neither reads from nor writes to what is kept
    assert (len(evidence_cache.RECALCULATION), evidence_cache.RECALCULATION.hits) == kept_before

    after = {name: read(get, engagement, name).json() for name in PATHS}  # through what is kept
    sheets_after = workbook(get, engagement)
    uncached = {name: fresh(get, engagement, name) for name in PATHS}
    sheets_uncached = workbook(get, engagement)
    assert after["recalculation"] != before["recalculation"], "the decision moved the totals"
    for name in PATHS:
        assert after[name] == uncached[name], f"{name}: kept answer differs from an uncached one"
    assert sheets_after == sheets_uncached and sheets_after != sheets_before
    assert read(get, engagement, "recalculation").json() == after["recalculation"]
