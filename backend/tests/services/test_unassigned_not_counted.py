"""Values count only when their document is placed on a calculation line.

Claire, Evidence Screen tab I8: accepted values in "Unassigned supporting evidence", and values in a
document moved off its line, feed no calculation until the document is placed on a line. Results lists
what it left out (``uncounted_values``) and the data quality checks do not call it a missing month.
"""

from __future__ import annotations

import pytest

from backend.app.services import calculation_lines as cl
from backend.tests.services.test_calculation_lines import GAS_KC, GAS_STL, KC, STL
from backend.tests.services.test_calculation_lines import _gas
from backend.tests.services.test_engagement_recalculation_service import FakeStore
from backend.tests.services.test_recalculation_lines import _by_key, _engagement, _service
from backend.tests.services.test_engagement_recalculation_service import _own

ZURICH = {"facilityId": "fac-zh03", "name": "Zürich Werk Süd", "address": "Löwenstrasse 1, 8001 Zürich"}
ZH_GAS = "s1:stationary:natural-gas:fac-zh03"
LOST = "Rechnung-北京-été"  # a document id (file name without the extension) in no script of ours


def _run(store: FakeStore, decisions: dict | None = None, facilities: list[dict] | None = None) -> dict:
    engagement = _engagement()
    if facilities is not None:
        engagement["settings"]["facilities"] = facilities
    return _service(store).recalculate(engagement, _own, decisions)


def _total(result: dict) -> float:
    category = result["categories"]["stationary_combustion"]
    return category["total_co2e"] if category else 0.0


def _store(*documents: tuple[str, list[dict]]) -> FakeStore:
    store = FakeStore()
    for document_id, records in documents:
        store.add_document(document_id, "CT-S1-FUELQTY", records)
    return store


def _kc(quantity: float = 30000) -> dict:
    return _gas(quantity, "2025-01-01", "2025-01-31")


def _stl(quantity: float = 500) -> dict:
    return _gas(quantity, "2025-01-01", "2025-01-31", plant="St Louis Plant")


NOWHERE = _gas(200, "2025-02-01", "2025-02-28", plant="Somewhere Else Ltd")  # names no Setup facility


def test_a_document_in_unassigned_supporting_evidence_is_left_out_and_listed() -> None:
    placed_only = _run(_store(("GAS-KC", [_kc()])))
    result = _run(_store(("GAS-KC", [_kc()]), ("GAS-ELSEWHERE", [NOWHERE])))
    assert _total(result) == pytest.approx(_total(placed_only)) and _total(result) > 0
    assert result["categories"]["stationary_combustion"]["total_mass_t"] == placed_only[
        "categories"]["stationary_combustion"]["total_mass_t"]
    assert result["calculation_unplaced"] == []  # nothing is reported beside the lines: it is not counted
    assert set(_by_key(result)) == {GAS_KC}
    uncounted = result["uncounted_values"]
    assert uncounted["accepted_records"] == 1 and uncounted["accepted_records"] > 0
    assert uncounted["documents"] == [{"document_id": "GAS-ELSEWHERE", "file_name": "GAS-ELSEWHERE.pdf",
                                       "reason": "facility_not_in_setup", "accepted_records": 1}]
    assert result["documents_considered"] == 1
    assert placed_only["uncounted_values"] == {"accepted_records": 0, "documents": []}


def test_an_unassigned_bill_is_not_called_a_missing_month() -> None:
    """Data quality checks read every document that exists: a bill not on a line yet is not a gap."""

    store = _store(("GAS-KC-JAN", [_kc()]), ("GAS-FEB", [NOWHERE]))
    result = _run(store)
    assert result["uncounted_values"]["accepted_records"] == 1
    gaps = [c for c in result["quality_checks"] if c["check"] == "Q-001" and c["facility"] == "Somewhere Else Ltd"]
    assert gaps and all("Feb 2025" not in c["message"] for c in gaps)  # February has its bill; Jan and the rest do not
    assert any("Jan 2025" in c["message"] for c in gaps)


def test_moving_the_document_onto_a_line_counts_it_and_moving_it_off_again_leaves_it_out() -> None:
    store = _store(("GAS-KC", [_kc()]), ("GAS-ELSEWHERE", [NOWHERE]))
    base = _total(_run(store))
    onto = {"GAS-ELSEWHERE": {"placements": [{"from": cl.SUPPORTING_UNASSIGNED, "to": GAS_STL}]}}
    counted = _run(store, onto)
    assert _total(counted) > base
    assert counted["uncounted_values"]["accepted_records"] == 0
    assert [r["document_id"] for r in _by_key(counted)[GAS_STL]["step1"]["rows"]] == ["GAS-ELSEWHERE"]
    off_again = {"GAS-ELSEWHERE": {"placements": [{"from": cl.SUPPORTING_UNASSIGNED, "to": GAS_STL},
                                                  {"from": GAS_STL, "to": cl.SUPPORTING_UNASSIGNED}]}}
    left_out = _run(store, off_again)
    assert _total(left_out) == pytest.approx(base)
    assert left_out["uncounted_values"]["accepted_records"] == 1
    # Off a line it already sat on by default, too.
    moved_off = _run(_store(("GAS-KC", [_kc()]), ("GAS-STL", [_stl()])),
                     {"GAS-STL": {"placements": [{"from": GAS_STL, "to": cl.SUPPORTING_UNASSIGNED}]}})
    assert _total(moved_off) == pytest.approx(base) and GAS_STL not in _by_key(moved_off)
    assert moved_off["uncounted_values"]["documents"][0]["document_id"] == "GAS-STL"


def test_a_document_parked_in_unassigned_is_not_on_a_line_either() -> None:
    store = _store(("GAS-KC", [_kc()]), ("GAS-STL", [_stl()]))
    result = _run(store, {"GAS-STL": {"placements": [{"from": GAS_STL, "to": cl.BLOCK_UNASSIGNED}]}})
    assert set(_by_key(result)) == {GAS_KC}
    assert result["uncounted_values"]["accepted_records"] > 0


def test_a_stationary_bill_moved_into_block_1_adds_nothing_and_is_left_out_of_every_count() -> None:
    """Block 1 is reference only, decided by placement: no calculation, no 'left out', no 'to review'."""

    kc_only = _run(_store(("GAS-KC", [_kc()])))
    store = _store(("GAS-KC", [_kc()]), ("GAS-STL", [_stl()]))
    store.add_document("GAS-OPEN", "CT-S1-FUELQTY", [_stl(300)], decision=None)  # an unreviewed bill, to be moved too
    moved = {"GAS-STL": {"placements": [{"from": GAS_STL, "to": cl.BLOCK_SUMMARY}]},
             "GAS-OPEN": {"placements": [{"from": GAS_STL, "to": cl.BLOCK_SUMMARY}]}}
    result = _run(store, moved)
    assert _total(result) == pytest.approx(_total(kc_only))
    assert set(_by_key(result)) == {GAS_KC}
    assert result["uncounted_values"] == {"accepted_records": 0, "documents": []}
    assert result["awaiting_review"] == kc_only["awaiting_review"]  # the unreviewed bill queues nothing
    assert result["documents_considered"] == 1
    assert not any(c.get("facility") == "St Louis Plant" for c in result["quality_checks"])
    # moved back onto its line, the same bill counts again
    back = _run(store, {"GAS-STL": {"placements": [{"from": GAS_STL, "to": cl.BLOCK_SUMMARY},
                                                   {"from": cl.BLOCK_SUMMARY, "to": GAS_STL}]}})
    assert _total(back) > _total(kc_only)


def test_a_document_placed_on_two_lines_counts_on_each_and_not_twice() -> None:
    both = _store(("GAS-BOTH", [_kc(30000), _stl(500)]))
    result = _run(both)
    separate = _run(_store(("GAS-A", [_kc(30000)]), ("GAS-B", [_stl(500)])))
    assert set(_by_key(result)) == {GAS_KC, GAS_STL} == set(_by_key(separate))
    assert _total(result) == pytest.approx(_total(separate))
    assert result["uncounted_values"]["accepted_records"] == 0
    assert _by_key(result)[GAS_KC]["step1"]["total"]["quantity"] == 30000
    assert _by_key(result)[GAS_STL]["step1"]["total"]["quantity"] == 500
    # One of its records on a line, the other on none: the second is left out, the first still counts.
    half = _run(_store(("GAS-HALF", [_kc(30000), NOWHERE])))
    assert set(_by_key(half)) == {GAS_KC}
    assert _by_key(half)[GAS_KC]["step1"]["total"]["quantity"] == 30000
    assert half["uncounted_values"]["documents"][0]["document_id"] == "GAS-HALF"
    assert 0 < half["uncounted_values"]["accepted_records"] <= 1  # only its second record
    assert _total(half) == pytest.approx(_total(_run(_store(("GAS-A", [_kc(30000)])))))


def test_values_accepted_before_the_document_is_placed_count_once_it_is() -> None:
    store = _store(("GAS-ELSEWHERE", [NOWHERE]))  # every value already accepted, the document is on no line
    before = _run(store)
    assert _total(before) == 0 and before["uncounted_values"]["accepted_records"] == 1
    placed = _run(store, {"GAS-ELSEWHERE": {"placements": [{"from": cl.SUPPORTING_UNASSIGNED, "to": GAS_KC}]}})
    assert _total(placed) > 0 and placed["uncounted_values"]["accepted_records"] == 0
    assert _by_key(placed)[GAS_KC]["step1"]["total"]["quantity"] == 200


def test_values_not_yet_accepted_are_not_listed_as_accepted_values_left_out() -> None:
    store = FakeStore()
    store.add_document("GAS-OPEN", "CT-S1-FUELQTY", [NOWHERE], decision=None)
    result = _run(store)
    assert result["uncounted_values"]["accepted_records"] == 0


def test_non_ascii_names_are_kept_whole_in_the_list_of_left_out_documents() -> None:
    elsewhere = _gas(120, "2025-03-01", "2025-03-31", plant="Zürich Werk Süd")  # in no Setup facility yet
    store = _store((LOST, [elsewhere]), ("GAS-KC", [_kc()]))
    result = _run(store)
    assert result["uncounted_values"]["documents"] == [
        {"document_id": LOST, "file_name": f"{LOST}.pdf", "reason": "facility_not_in_setup",
         "accepted_records": 1}]
    # Add the facility to Setup: the document files on its line and counts.
    with_facility = _run(store, facilities=[KC, ZURICH])
    assert with_facility["uncounted_values"]["accepted_records"] == 0
    assert _by_key(with_facility)[ZH_GAS]["label"] == "Zürich Werk Süd"
    assert _total(with_facility) > _total(_run(_store(("GAS-KC", [_kc()])), facilities=[KC, ZURICH]))


def test_documents_are_listed_in_a_stable_order() -> None:
    names = ["éclair", "Zebra", "apple", "Äpfel"]
    store = _store(*[(n, [NOWHERE]) for n in names])
    listed = [d["document_id"] for d in _run(store)["uncounted_values"]["documents"]]
    assert listed == sorted(names, key=str.casefold)


# --- review findings: fail closed, incomplete categories, reasons, workpaper ---------------------------
def _engagement_with(**settings: object) -> dict:
    engagement = _engagement()
    engagement["settings"].update(settings)
    return engagement


def test_a_placement_that_cannot_be_read_counts_nothing_and_every_total_is_incomplete(
        monkeypatch: pytest.MonkeyPatch) -> None:
    from backend.app.services import recalculation_lines
    from backend.app.services.workpaper_export_service import build_workbook
    from io import BytesIO
    from openpyxl import load_workbook

    def boom(*args: object, **kwargs: object) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(recalculation_lines, "file_records", boom)
    store = _store(("GAS-KC", [_kc()]), ("GAS-STL", [_stl()]))
    result = _service(store).recalculate(_engagement(), _own)  # fails closed: not a 500, not "count everything"
    assert result["categories"]["stationary_combustion"] is None
    assert result["calculation_lines"] == [] and result["documents_considered"] == 0
    assert any(i["kind"] == "record_placement" for i in result["needs_input"])
    assert all(c["inputs_incomplete"] for c in result["comparisons"] if c["status"] != "not_recalculated")
    assert not any(c["status"] in ("within_tolerance", "exceeds_tolerance") for c in result["comparisons"])
    assert "unaffected" not in str(result["needs_input"])
    sources = result["rollup"]["categories"]
    for key in ("stationary_combustion", "mobile_combustion", "purchased_electricity", "fugitive_refrigerants"):
        assert sources[key]["open_items"] > 0 and sources[key]["status"] in ("partial", "awaiting_inputs")
    book = build_workbook(engagement={"name": "E", "settings": {}}, recalculation=result, register={}, items=[],
                          exported_by="x")
    summary = {r[0]: r[1] for r in load_workbook(BytesIO(book))["Summary"].iter_rows(min_row=2, values_only=True)}
    assert "could not be read" in str(summary["WARNING"])


def test_accepted_records_on_no_line_leave_their_category_and_every_comparison_incomplete() -> None:
    clean = _run(_store(("GAS-KC", [_kc()])))
    assert not any(i["kind"] == "not_on_a_line" for i in clean["needs_input"])
    assert not _incomplete(clean, "scope1_total")
    result = _run(_store(("GAS-KC", [_kc()]), ("GAS-ELSEWHERE", [NOWHERE])))
    item = next(i for i in result["needs_input"] if i["kind"] == "not_on_a_line")
    assert item["category"] == "stationary_combustion"
    assert _incomplete(result, "scope1_total")
    assert next(c for c in result["comparisons"] if c["key"] == "scope1_total")["status"] != "within_tolerance"


def _incomplete(result: dict, key: str) -> bool:
    return bool(next(c for c in result["comparisons"] if c["key"] == key)["inputs_incomplete"])


def test_each_left_out_document_says_why_and_a_fleet_with_no_vehicle_group_is_named() -> None:
    from backend.tests.services.test_recalculation_lines import GROUP_OFF, GROUP_ROAD, _mobile_store

    def reasons(result: dict) -> list[tuple[str, str]]:
        return [(d["document_id"], d["reason"]) for d in result["uncounted_values"]["documents"]]

    fleet = _service(_mobile_store()).recalculate(_engagement_with(), _own)
    assert reasons(fleet) == [("FLEET", "no_vehicle_group")] and fleet["uncounted_values"]["accepted_records"] == 2
    shared = _service(_mobile_store()).recalculate(
        _engagement_with(recalculation={"vehicle_groups": [GROUP_ROAD, GROUP_OFF]}), _own)
    assert reasons(shared) == [("FLEET", "fuel_shared_by_vehicle_groups")]
    assert reasons(_run(_store(("GAS-ELSEWHERE", [NOWHERE])))) == [("GAS-ELSEWHERE", "facility_not_in_setup")]
    moved = _run(_store(("GAS-STL", [_stl()])), {"GAS-STL": {"placements": [
        {"from": GAS_STL, "to": cl.SUPPORTING_UNASSIGNED}]}})
    assert reasons(moved) == [("GAS-STL", "not_on_a_line")]
    assert [e["reason"] for e in moved["excluded"]] == ["not_on_a_calculation_line"]


def test_records_outside_the_reporting_period_are_not_counted_as_left_out_values() -> None:
    last_year = _gas(200, "2024-02-01", "2024-02-28", plant="Somewhere Else Ltd")
    result = _run(_store(("OLD", [last_year])))
    assert result["uncounted_values"]["accepted_records"] == 0
    assert not any(e["reason"] == "not_on_a_calculation_line" for e in result["excluded"])


def test_the_workpaper_lists_the_left_out_documents() -> None:
    from backend.app.services.workpaper_export_service import build_workbook
    from io import BytesIO
    from openpyxl import load_workbook

    result = _run(_store(("GAS-KC", [_kc()]), (LOST, [NOWHERE])))
    book = load_workbook(BytesIO(build_workbook(engagement={"name": "E", "settings": {}}, recalculation=result,
                                                register={}, items=[], exported_by="x")))
    left = [r for r in book["Left out"].iter_rows(min_row=2, values_only=True)]
    assert (f"{LOST}.pdf", "Not on a calculation line", "") in [tuple(r) for r in left] or any(
        r[0] == f"{LOST}.pdf" and r[1] == "Not on a calculation line" for r in left)
    summary = {r[0]: r[1] for r in book["Summary"].iter_rows(min_row=2, values_only=True)}
    assert summary["Documents left out: not on a calculation line (see Left out)"] == 1
    assert summary["Documents read"] == 1


def _hint(result: dict) -> str:
    (item,) = [i for i in result["needs_input"] if i["kind"] == "not_on_a_line"]
    return item["message"]


def _reason(result: dict) -> str:
    (doc,) = result["uncounted_values"]["documents"]
    return doc["reason"]


def test_the_open_item_hint_matches_each_reason() -> None:
    from backend.tests.services.test_recalculation_lines import GROUP_OFF, GROUP_ROAD, _mobile_store

    # two records, so the hint is plural
    assert _hint(_service(_mobile_store()).recalculate(_engagement_with(), _own)).endswith("Add them in Setup.")
    assert _hint(_run(_store(("X", [NOWHERE])))).endswith("Add it in Setup.")
    shared = _service(_mobile_store()).recalculate(
        _engagement_with(recalculation={"vehicle_groups": [GROUP_ROAD, GROUP_OFF]}), _own)
    assert _hint(shared).endswith("Choose the vehicle group in Evidence.")
    moved = _run(_store(("GAS-STL", [_stl()])), {"GAS-STL": {"placements": [
        {"from": GAS_STL, "to": cl.SUPPORTING_UNASSIGNED}]}})
    assert _hint(moved).endswith("Place it in Evidence.")
    unsettled = _run(_store(("COAL", [_gas(5, fuel="unobtainium")])))
    assert _reason(unsettled) == "no_calculation_line"
    assert _hint(unsettled).endswith("Answer the fuel or energy type question in Evidence.")


def test_a_number_on_several_facilities_is_not_a_facility_missing_from_setup() -> None:
    bill = {**_gas(100), "facility_name": (None, None), "account_number": ("4417 2290 31", None)}
    both = [{**KC, "accountNumbers": ["4417 2290 31"]}, {**STL, "accountNumbers": ["4417-2290-31"]}]
    result = _run(_store(("D", [bill])), facilities=both)
    assert _reason(result) == "identifier_on_several_facilities"
    assert _hint(result).endswith(
        "Choose the facility in Evidence (its account or meter number is on more than one facility in Setup).")
    # the same number on one facility only places the bill: counted, nothing left out
    one = _run(_store(("D", [bill])), facilities=[{**KC, "accountNumbers": ["4417 2290 31"]}, STL])
    assert one["uncounted_values"]["accepted_records"] == 0


def test_a_facility_only_claude_suggested_asks_for_confirmation() -> None:
    store = _store(("D", [{**_gas(100), "facility_name": (None, None)}]))
    store.results["D"][0]["facility_suggestion"] = {"facility_id": "fac-kc01", "quote": "Kent", "source": "file_name"}
    result = _run(store)
    assert _reason(result) == "facility_suggested_not_confirmed"
    assert _hint(result).endswith("Confirm the suggested facility in Evidence.")
    # a suggestion for a facility that left Setup is nothing to confirm; nothing in the bill matches Setup
    gone = _store(("D", [{**_gas(100), "facility_name": (None, None)}]))
    gone.results["D"][0]["facility_suggestion"] = {"facility_id": "fac-gone", "quote": "Kent", "source": "file_name"}
    assert _reason(_run(gone)) == "facility_not_in_setup"
    # the bill names a place Setup does not have: that is for the reviewer, not Claude's suggestion
    named = _store(("D", [NOWHERE]))
    named.results["D"][0]["facility_suggestion"] = {"facility_id": "fac-kc01", "quote": "Kent", "source": "file_name"}
    assert _reason(_run(named)) == "facility_not_in_setup"
