"""The line schedule v2 (Claire's supporting-schedule spec): one row per record, every extracted
value flagged accepted or not, a dynamic column set, the activity note, identifiers by value."""

from __future__ import annotations

from backend.app.services import calculation_lines as cl
from backend.app.services.evidence_tree_service import EvidenceTreeService
from backend.tests.services.test_calculation_lines import (
    ELEC_KC,
    GAS_KC,
    _elec,
    _engagement,
    _gas,
    _line,
    _schedule_store,
    _tree_service,
)
from backend.tests.services.test_engagement_recalculation_service import FakeStore, _own


def _schedule(store: FakeStore, key: str = GAS_KC, decisions: dict | None = None, **kwargs):  # type: ignore[no-untyped-def]
    schedule = _tree_service(store).schedule(_engagement(), _own, key, decisions, **kwargs)
    assert schedule is not None
    return schedule


def test_rows_carry_every_value_and_flag_the_unaccepted() -> None:
    store = _schedule_store()
    store.reviews["BILL-A"] = [{**r, "reviewer_id": "ana@example.com", "reviewed_at": "2025-04-02T10:00:00Z"}
                               for r in store.reviews["BILL-A"]]
    schedule = _schedule(store, name_of=lambda login: "Ana Reyes")
    rows = {r["document_id"]: r for r in schedule["rows"]}
    assert [r["document_id"] for r in schedule["rows"]] == ["BILL-C", "BILL-A", "BILL-B"]
    assert [rows[d]["accepted"] for d in ("BILL-A", "BILL-B", "BILL-C")] == [True, False, True]
    a = rows["BILL-A"]
    assert a["date"] == {"start": "2025-01-16", "end": "2025-02-15", "days": 31, "label": "Service period"}
    assert a["activity_quantity"] == {"value": 310, "unit": "MMBtu"} and a["cells"] == {}
    assert a["saved_by"] == {"name": "Ana Reyes", "at": "2025-04-02T10:00:00Z"}
    assert (a["file_name"], a["page"], a["candidate_id"]) == ("BILL-A.pdf", 1, "BILL-A:1:activity_quantity")
    assert a["record_key"] == "BILL-A:0" and a["record_index"] is None
    assert rows["BILL-B"]["activity_quantity"]["value"] == 280 and rows["BILL-B"]["saved_by"] is None
    assert "values" in schedule and "coverage" in schedule  # the old keys stay


def test_one_row_per_record_of_a_document() -> None:
    store = FakeStore()
    store.add_document("TWO", "CT-S1-FUELQTY", [_gas(100), _gas(40, "2025-02-01", "2025-02-28")])
    schedule = _schedule(store)
    assert [(r["record_key"], r["activity_quantity"]["value"]) for r in schedule["rows"]] == [
        ("TWO:1", 100), ("TWO:2", 40)]


def test_columns_show_only_with_a_value_and_in_the_spec_order() -> None:
    store = FakeStore()
    store.add_document("A", "CT-S1-FUELQTY", [_gas(100)])
    assert _schedule(store)["columns"] == [{"key": "date", "label": "Date", "unit_in_cells": True},
                                           {"key": "activity_quantity", "label": "Activity quantity",
                                            "unit_in_cells": True}]
    store = FakeStore()
    store.add_document("A", "CT-S1-FUELQTY", [{**_gas(100), "distance": (12, "mi"),
                                               "heat_content": (1.03, "MMBtu/Mscf")}])
    # an unaccepted row with no extra value: its cells stay blank
    store.add_document("B", "CT-S1-FUELQTY", [_gas(50, "2025-02-01", "2025-02-28")], decision=None)
    schedule = _schedule(store)
    assert [c["key"] for c in schedule["columns"]] == ["date", "activity_quantity", "heat_content", "distance"]
    rows = {r["document_id"]: r for r in schedule["rows"]}
    assert rows["A"]["cells"] == {"heat_content": {"value": 1.03, "unit": "MMBtu/Mscf"},
                                  "distance": {"value": 12, "unit": "mi"}}
    assert rows["B"]["cells"] == {}


def test_an_unaccepted_value_still_opens_its_column() -> None:
    store = FakeStore()
    store.add_document("A", "CT-S1-FUELQTY", [{**_gas(100), "model_year": (2019, None)}], decision=None)
    schedule = _schedule(store)
    assert [c["key"] for c in schedule["columns"]][-1] == "model_year"
    assert schedule["rows"][0]["accepted"] is False
    assert schedule["rows"][0]["cells"] == {"model_year": {"value": 2019, "unit": None}}


def test_activity_note_by_category() -> None:
    store = FakeStore()
    store.add_document("G", "CT-S1-FUELQTY", [_gas()])
    store.add_document("E", "CT-S2-ELEC", [_elec(10)])
    assert _schedule(store)["activity_quantity_note"] == "Activity quantity: fuel quantity combusted"
    assert _schedule(store, ELEC_KC)["activity_quantity_note"] == "Activity quantity: electricity quantity purchased"

    def note(category: str, level2: str) -> str | None:
        line = cl.make_line(category, level2, level2, "company", "company", "x", created_by_user=False)
        return EvidenceTreeService._activity_note(line)

    assert note("mobile", "diesel-fuel") == "Activity quantity: fuel use quantity"
    assert note("purchased_energy", "steam") == "Activity quantity: thermal energy purchased"
    assert note("fugitive", "r410a") == "Activity quantity: refrigerant quantity added or recovered"
    assert note("contractual", "x") is None


def test_date_label_follows_the_document() -> None:
    assert cl.date_label("CT-S1-FUELQTY") == "Service period"
    assert cl.date_label("CT-S1-MOBFUEL") == "Transaction date"
    assert cl.date_label("CT-S1-REFRSVC") == "Service date"


def test_identifiers_group_documents_by_value_with_not_found() -> None:
    store = _schedule_store()
    store.add_document("BILL-D", "CT-S1-FUELQTY", [_gas(10, "2025-03-01", "2025-03-10")])
    groups = {g["label"]: g for g in _schedule(store)["identifier_groups"]}
    assert list(groups) == ["Facility", "Service address", "Account number", "Meter number"]
    account = groups["Account number"]
    assert [(v["value"], [d["document_id"] for d in v["documents"]]) for v in account["values"]] == [
        ("ACC-7", ["BILL-C"]), ("ACC-9", ["BILL-A", "BILL-B"])]
    assert account["not_found"] == [{"document_id": "BILL-D", "file_name": "BILL-D.pdf"}]
    assert (account["documents_with"], account["documents_total"]) == (3, 4)
    meter = groups["Meter number"]  # no extractor produces it: every document is Not found
    assert meter["values"] == [] and len(meter["not_found"]) == 4 and meter["documents_with"] == 0


def test_facility_group_says_how_the_match_was_made() -> None:
    store = FakeStore()
    store.add_document("BY-NAME", "CT-S1-FUELQTY", [_gas()])
    store.add_document("BY-ADDRESS", "CT-S1-FUELQTY",
                       [{**_gas(5, "2025-02-01", "2025-02-10", plant="Unlisted"),
                         "service_address": ("100 Main Street, Kansas City, MO", None)}])
    store.add_document("BY-CHOICE", "CT-S1-FUELQTY", [_gas(7, "2025-03-01", "2025-03-05", plant="Unlisted")])
    decisions = {"BY-CHOICE": {"documentId": "BY-CHOICE", "facilityId": "fac-kc01"}}
    facility = _schedule(store, decisions=decisions)["identifier_groups"][0]
    assert [v["value"] for v in facility["values"]] == ["Kansas City Plant"]
    how = {d["document_id"]: d["matched_by"] for d in facility["values"][0]["documents"]}
    assert how == {"BY-NAME": "Facility name in Setup", "BY-ADDRESS": "Service address in Setup",
                   "BY-CHOICE": "Chosen by the reviewer"}
    assert facility["matched_by"] == ["Chosen by the reviewer", "Facility name in Setup", "Service address in Setup"]


def test_an_empty_line_has_the_two_fixed_columns_and_no_rows() -> None:
    mine = cl.normalize_evidence_lines([_line()])
    schedule = _tree_service(FakeStore()).schedule(_engagement(evidenceLines=mine), _own,
                                                   "s1:stationary:propane:fac-kc01")
    assert schedule is not None and schedule["rows"] == []
    assert [c["key"] for c in schedule["columns"]] == ["date", "activity_quantity"]
    assert schedule["activity_quantity_note"] == "Activity quantity: fuel quantity combusted"
    assert all(g["values"] == [] and g["documents_total"] == 0 for g in schedule["identifier_groups"])
