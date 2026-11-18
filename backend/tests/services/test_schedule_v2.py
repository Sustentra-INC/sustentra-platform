"""The line schedule v2 (Claire's supporting-schedule spec): one row per record, every extracted
value flagged accepted or not, a dynamic column set, the activity note, identifiers by value."""

from __future__ import annotations

import dataclasses

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
from backend.tests.services.test_engagement_recalculation_service import ORG, FakeStore, _own


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


def _decided(decision: str | None, **extra: object) -> FakeStore:
    store = FakeStore()
    store.add_document("A", "CT-S1-FUELQTY", [_gas(310)], decision=None)
    if decision:
        store.reviews["A"] = [{"candidate_id": "A:1:activity_quantity", "decision": decision, "org_id": ORG,
                               "reviewer_id": "ana@example.com", "reviewed_at": "2025-04-02T10:00:00Z", **extra},
                              {"candidate_id": "A:1:fuel_type", "decision": "accepted", "org_id": ORG,
                               "reviewed_value": "natural_gas"}]
    return store


def test_an_edited_quantity_shows_the_reviewed_value() -> None:
    row = _schedule(_decided("edited", reviewed_value=999, reviewed_unit="MMBtu"))["rows"][0]
    assert row["activity_quantity"] == {"value": 999, "unit": "MMBtu"}
    assert row["accepted"] is True and row["decision"] == "edited"
    assert row["saved_by"] == {"name": "ana@example.com", "at": "2025-04-02T10:00:00Z"}


def test_a_rejected_quantity_is_flagged_and_unsaved() -> None:
    row = _schedule(_decided("rejected"))["rows"][0]
    assert row["accepted"] is False and row["decision"] == "rejected" and row["saved_by"] is None
    assert row["activity_quantity"]["value"] == 310


def test_row_decision_values() -> None:
    assert _schedule(_decided("accepted", reviewed_value=310))["rows"][0]["decision"] == "accepted"
    assert _schedule(_decided("needs_more_evidence"))["rows"][0]["decision"] == "needs_more_evidence"
    assert _schedule(_decided(None))["rows"][0]["decision"] == "not_reviewed"


def test_an_empty_line_has_the_two_fixed_columns_and_no_rows() -> None:
    mine = cl.normalize_evidence_lines([_line()])
    schedule = _tree_service(FakeStore()).schedule(_engagement(evidenceLines=mine), _own,
                                                   "s1:stationary:propane:fac-kc01")
    assert schedule is not None and schedule["rows"] == []
    assert [c["key"] for c in schedule["columns"]] == ["date", "activity_quantity"]
    assert schedule["activity_quantity_note"] == "Activity quantity: fuel quantity combusted"
    assert all(g["values"] == [] and g["documents_total"] == 0 for g in schedule["identifier_groups"])


def _fuel_unreviewed() -> FakeStore:
    """A quantity that is accepted while the record's fuel type is not."""

    store = FakeStore()
    store.add_document("A", "CT-S1-FUELQTY", [_gas(212, "2025-03-14", "2025-03-14")])
    store.reviews["A"] = [r for r in store.reviews["A"] if not r["candidate_id"].endswith(":fuel_type")]
    return store


def test_an_accepted_quantity_with_an_unreviewed_fuel_type_does_not_count() -> None:
    schedule = _schedule(_fuel_unreviewed())
    row = schedule["rows"][0]
    assert row["accepted"] is False and row["decision"] == "awaiting_other_fields"
    assert row["waiting_on"] == ["Fuel type"]
    assert schedule["values"][0]["decision"] == "awaiting_other_fields"
    assert schedule["values"][0]["waiting_on"] == ["Fuel type"]
    assert schedule["calculated"] is False


def test_a_rejected_other_field_is_listed_as_rejected_not_waiting() -> None:
    store = FakeStore()
    store.add_document("A", "CT-S1-FUELQTY", [_gas(212, "2025-03-14", "2025-03-14")])
    store.reviews["A"] = [{**r, "decision": "rejected", "reviewed_value": None, "reviewed_unit": None}
                          if r["candidate_id"].endswith(":fuel_type") else r for r in store.reviews["A"]]
    row = _schedule(store)["rows"][0]
    assert row["accepted"] is False and row["decision"] == "awaiting_other_fields"
    assert row["rejected_fields"] == ["Fuel type"] and row["waiting_on"] == []


def test_the_coverage_month_follows_the_same_rule() -> None:
    months = {m["month"]: m for m in _schedule(_fuel_unreviewed())["coverage"]}
    assert months["2025-03"]["status"] == "not_reviewed" and months["2025-03"]["quantity"] is None
    assert months["2025-03"]["waiting_on"] == ["Fuel type"]
    assert months["2025-01"]["waiting_on"] == []


def test_a_fully_reviewed_record_counts_and_the_line_is_calculated() -> None:
    store = FakeStore()
    store.add_document("A", "CT-S1-FUELQTY", [_gas(212, "2025-03-14", "2025-03-14")])
    schedule = _schedule(store)
    row = schedule["rows"][0]
    assert row["accepted"] is True and row["decision"] == "accepted" and row["waiting_on"] == []
    assert schedule["calculated"] is True
    month = {m["month"]: m for m in schedule["coverage"]}["2025-03"]
    assert month["status"] == "counted_in_part" and month["waiting_on"] == []


# --- C2: identifiers apply per line type ------------------------------------------------------
def _labels(schedule: dict) -> list[str]:
    return [g["label"] for g in schedule["identifier_groups"]]


def test_a_mobile_line_shows_facility_only() -> None:
    from backend.tests.services.test_calculation_lines import _group, _mobile

    store = FakeStore()
    store.add_document("M1", "CT-S1-MOBFUEL", [{**_mobile(), "meter_number": ("M-1", None)}])
    engagement = _engagement(recalculation={"vehicle_groups": [_group("Diesel Fuel", "Delivery trucks")]})
    key = "s1:mobile:diesel-fuel:vg-delivery-trucks"
    schedule = _tree_service(store).schedule(engagement, _own, key)
    assert schedule is not None
    assert _labels(schedule) == ["Facility"]
    assert {i["label"] for i in schedule["identifiers"]} <= {"Facility"}  # no "Meter number: Not found"


def test_identifiers_by_category_facility_only_except_utility_lines() -> None:
    def labels(category: str, level2: str) -> list[str]:
        line = cl.make_line(category, level2, level2, "company", "company", "x", created_by_user=False)
        return [label for label, _ in EvidenceTreeService._identifier_defs(line)]

    four = ["Facility", "Service address", "Account number", "Meter number"]
    assert labels("stationary", "natural-gas") == four
    assert labels("purchased_energy", "electricity") == four
    for thermal in ("steam", "heating", "cooling"):
        assert labels("purchased_energy", thermal) == four
    for category, level2 in (("mobile", "diesel-fuel"), ("fugitive", "r410a"), ("process", "x"),
                             ("contractual", "x"), ("stationary", "propane")):
        assert labels(category, level2) == ["Facility"]
    unknown = dataclasses.replace(cl.make_line("mobile", "x", "x", "company", "company", "x", created_by_user=False),
                                  category="something-new")
    assert [label for label, _ in EvidenceTreeService._identifier_defs(unknown)] == ["Facility"]  # never crashes


def test_a_line_with_no_documents_lists_its_identifiers_with_zero_counts() -> None:
    mine = cl.normalize_evidence_lines([{"category": "stationary", "level2_label": "Natural gas",
                                         "anchor_kind": "facility", "anchor_id": "fac-kc01", "label": "KC gas"}])
    schedule = _tree_service(FakeStore()).schedule(_engagement(evidenceLines=mine), _own, GAS_KC)
    assert schedule is not None
    assert _labels(schedule) == ["Facility", "Service address", "Account number", "Meter number"]
    assert all(g["documents_total"] == 0 and g["values"] == [] for g in schedule["identifier_groups"])


def _meter_group(*meters: str) -> dict:
    store = FakeStore()
    for i, meter in enumerate(meters):
        store.add_document(f"B{i}", "CT-S1-FUELQTY", [_gas(10, meter_number=meter)])
    return {g["label"]: g for g in _schedule(store)["identifier_groups"]}["Meter number"]


def test_nfc_and_nfd_spellings_group_together_and_keep_the_first_spelling() -> None:
    nfc, nfd = "Rue de l'Église 12", "Rue de l'Église 12"
    assert nfc != nfd
    group = _meter_group(nfc, nfd)
    assert len(group["values"]) == 1 and len(group["values"][0]["documents"]) == 2
    assert group["values"][0]["value"] in (nfc, nfd)
    assert (group["documents_with"], group["documents_total"]) == (2, 2)


def test_case_and_spacing_do_not_split_a_group() -> None:
    group = _meter_group("M-4471", "m-4471", "  M-4471  ")
    assert [v["value"] for v in group["values"]] == ["M-4471"]
    assert (group["documents_with"], group["documents_total"]) == (3, 3)


def test_non_ascii_and_full_width_identifiers_work() -> None:
    group = _meter_group("№ 4471-Ж", "№ 4471-ж", "４４７１")
    assert len(group["values"]) == 2  # the case variants group; "4471" is a different meter
    assert group["documents_with"] == 3


def test_full_width_digits_group_with_ascii_and_keep_the_first_spelling() -> None:
    group = _meter_group("４４７１", "4471", "Ｍ-4471", "M-4471")
    assert [(v["value"], len(v["documents"])) for v in group["values"]] in (
        [("４４７１", 2), ("Ｍ-4471", 2)], [("Ｍ-4471", 2), ("４４７１", 2)])
    assert (group["documents_with"], group["documents_total"]) == (4, 4)


def test_a_whitespace_only_value_is_not_found_and_counts_read_n_of_total() -> None:
    store = FakeStore()
    store.add_document("A", "CT-S1-FUELQTY", [_gas(10, meter_number="M-1")])
    store.add_document("B", "CT-S1-FUELQTY", [_gas(10, meter_number="   ")])
    store.add_document("C", "CT-S1-FUELQTY", [_gas(10)])
    schedule = _schedule(store)
    group = {g["label"]: g for g in schedule["identifier_groups"]}["Meter number"]
    assert (group["documents_with"], group["documents_total"]) == (1, 3)
    assert sorted(d["document_id"] for d in group["not_found"]) == ["B", "C"]
    assert [i for i in schedule["identifiers"] if i["label"] == "Meter number"] == [
        {"label": "Meter number", "value": "M-1", "documents_with": 1, "documents_total": 3}]


def test_electricity_lines_show_all_four_identifiers() -> None:
    store = FakeStore()
    store.add_document("E", "CT-S2-ELEC", [_elec(10)])
    assert _labels(_schedule(store, ELEC_KC)) == ["Facility", "Service address", "Account number", "Meter number"]


# --- C4: line history ---------------------------------------------------------------------
def _review(candidate: str, decision: str, who: str | None, at: str | None, value: object = None,
            unit: str | None = "MMBtu", found: object = 100) -> dict:
    return {"candidate_id": candidate, "decision": decision, "org_id": ORG, "reviewed_value": value,
            "reviewed_unit": unit if value is not None else None, "reviewer_id": who, "reviewed_at": at,
            "candidate_snapshot": {"normalized_value": found, "unit": "MMBtu", "validation_flags": []}}


def _history(store: FakeStore, **kwargs):  # type: ignore[no-untyped-def]
    return _schedule(store, **kwargs)["history"]


def test_accept_then_edit_then_accept_again_gives_three_entries_newest_first() -> None:
    store = FakeStore()
    store.add_document("A", "CT-S1-FUELQTY", [_gas(100)], decision=None)
    q = "A:1:activity_quantity"
    store.reviews["A"] = [_review(q, "accepted", "kl", "2025-04-01T10:00:00Z", 100),
                          _review(q, "edited", "kl", "2025-04-02T10:00:00Z", 90),
                          _review(q, "accepted", "kl", "2025-04-03T10:00:00Z", 90)]
    entries = [h for h in _history(store) if h["action"] != "extracted"]
    assert [(h["action"], h["value"], h["at"][:10]) for h in entries] == [
        ("accepted", "90", "2025-04-03"), ("corrected", "90", "2025-04-02"), ("accepted", "100", "2025-04-01")]
    assert all(h["field"] == "Activity quantity" and h["unit"] == "MMBtu" and h["file_name"] == "A.pdf" and h["page"] == 1
               for h in entries)


def test_a_value_the_reviewer_keyed_where_nothing_was_extracted_is_an_added_entry() -> None:
    store = FakeStore()
    store.add_document("A", "CT-S1-FUELQTY", [{**_gas(0), "activity_quantity": (None, "MMBtu")}], decision=None)
    store.reviews["A"] = [_review("A:1:activity_quantity", "edited", "jp", "2025-04-04T09:12:00Z", 55700, found=None)]
    added = [h for h in _history(store) if h["action"] == "added"]
    assert [(h["actor_name"], h["value"], h["unit"], h["field"]) for h in added] == [
        ("jp", "55700", "MMBtu", "Activity quantity")]
    # a correction of a value that was read stays "corrected"
    store.reviews["A"] = [_review("A:1:activity_quantity", "edited", "jp", "2025-04-04T09:12:00Z", 55700, found=100)]
    assert [h["action"] for h in _history(store) if h["action"] != "extracted"] == ["corrected"]


def test_reviewer_names_with_non_ascii_letters_come_through() -> None:
    store = FakeStore()
    store.add_document("A", "CT-S1-FUELQTY", [_gas(100)], decision=None)
    store.reviews["A"] = [_review("A:1:activity_quantity", "rejected", "zoe@example.com", "2025-04-01T10:00:00Z")]
    history = _history(store, name_of=lambda login: "Zoë Ångström")
    rejected = next(h for h in history if h["action"] == "rejected")
    assert rejected["actor_name"] == "Zoë Ångström" and rejected["value"] == "100"  # the value read


def test_a_decision_without_a_time_sorts_last_and_a_missing_reviewer_is_none() -> None:
    store = FakeStore()
    store.add_document("A", "CT-S1-FUELQTY", [_gas(100)], decision=None)
    store.reviews["A"] = [_review("A:1:activity_quantity", "needs_more_evidence", None, None)]
    store.results["A"][0]["created_at"] = "2025-04-01T08:00:00Z"
    history = _history(store)
    assert [h["action"] for h in history] == ["extracted", "asked_for_more_evidence"]
    assert history[-1]["at"] is None and history[-1]["actor_name"] is None


def test_history_is_capped_at_200_newest_first_and_reports_the_total() -> None:
    store = FakeStore()
    for i in range(250):
        store.add_document(f"D{i:03}", "CT-S1-FUELQTY", [_gas(10)], decision=None)
        store.reviews[f"D{i:03}"] = [_review(f"D{i:03}:1:activity_quantity", "edited", f"u{i}",
                                             f"2025-{1 + i // 28:02}-{1 + i % 28:02}T10:00:00Z", 9)]
    schedule = _schedule(store)
    assert len(schedule["history"]) == 200 and schedule["history_total"] == 251  # 250 edits + the extraction
    times = [h["at"] for h in schedule["history"]]
    assert times == sorted(times, reverse=True)


def test_a_line_with_no_values_has_an_empty_history_and_no_system_entry() -> None:
    mine = cl.normalize_evidence_lines([{"category": "stationary", "level2_label": "Natural gas",
                                         "anchor_kind": "facility", "anchor_id": "fac-kc01", "label": "KC gas"}])
    schedule = _tree_service(FakeStore()).schedule(_engagement(evidenceLines=mine), _own, GAS_KC)
    assert schedule is not None and schedule["history"] == [] and schedule["history_total"] == 0


def test_a_bulk_accept_in_one_minute_is_one_entry_but_the_same_value_twice_is_not_folded() -> None:
    store = FakeStore()
    for i in range(9):
        store.add_document(f"D{i}", "CT-S1-FUELQTY", [_gas(10)], decision=None)
        store.reviews[f"D{i}"] = [_review(f"D{i}:1:activity_quantity", "accepted", "kl", f"2025-04-02T10:00:{i:02}Z", 10)]
    bulk = [h for h in _history(store, name_of=lambda login: "K. Lee") if h["action"] == "accepted"]
    assert len(bulk) == 1 and bulk[0]["count"] == 9 and bulk[0]["actor_name"] == "K. Lee"
    twice = FakeStore()
    twice.add_document("A", "CT-S1-FUELQTY", [_gas(10)], decision=None)
    q = "A:1:activity_quantity"
    twice.reviews["A"] = [_review(q, "accepted", "kl", "2025-04-02T10:00:01Z", 10),
                          _review(q, "accepted", "kl", "2025-04-02T10:00:30Z", 10)]
    assert [h["count"] for h in _history(twice) if h["action"] == "accepted"] == [1, 1]


def test_every_field_is_logged_not_only_the_quantity_heat_content_and_meter() -> None:
    store = FakeStore()
    store.add_document("A", "CT-S1-FUELQTY", [_gas(10, heat_content=1.03, meter_number="M-1")], decision=None)
    store.reviews["A"] = [_review("A:1:heat_content", "edited", "kl", "2025-04-02T10:00:00Z", 1.04, "MMBtu/Mcf", 1.03),
                          _review("A:1:meter_number", "rejected", "ana", "2025-04-03T10:00:00Z", None, None, "M-1")]
    seen = {(h["field"], h["action"], h["value"]) for h in _history(store) if h["action"] != "extracted"}
    assert seen == {("Heat content (HHV)", "corrected", "1.04"), ("Meter number", "rejected", "M-1")}
