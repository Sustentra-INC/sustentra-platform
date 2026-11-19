"""A re-read can renumber a document's records. A reviewer's decision then applies only to the
value it was made on (S1-BE-014): same field, same record, and, for an accept, the same value."""

from __future__ import annotations

import copy
import json
from typing import Any

import pytest

from backend.app.services import reviewed_evidence as re_
from backend.app.services.approved_evidence_service import ApprovedEvidenceService
from backend.app.repositories.evidence_repository import InMemoryApprovedEvidenceRepository
from backend.app.services.reviewed_evidence import (
    REREAD_NOTE,
    VALUE_CHANGED,
    applicable_decisions,
    effective_decision,
    group_reviewed_records,
    mark_review_targets,
    mark_reread_items,
    record_identity,
    resolve_decisions,
    stale_decision_ids,
)
from backend.tests.services.test_calculation_lines import GAS_KC, _tree_service
from backend.tests.services.test_calculation_lines import _engagement as _tree_engagement
from backend.tests.services.test_engagement_recalculation_service import (
    ORG,
    FakeStore,
    _engagement,
    _own,
    _service,
)

DOC = "BILL-1"
PLANT = "Müller Käserei – Zürich"  # non-ASCII on purpose: names, hints and values must survive
FIELDS = ("fuel_type", "activity_quantity", "activity_unit", "service_period_start", "service_period_end",
          "facility_name")


def _read(*records: tuple[str, str, str, float], plant: str = PLANT, keyed: bool = True) -> list[dict[str, Any]]:
    """One read of the document: records of (hint, start, end, MMBtu), numbered from 1 as the extractor does."""

    items: list[dict[str, Any]] = []
    for index, (hint, start, end, quantity) in enumerate(records, start=1):
        key = f"r{index}:{hint.replace(' ', '_')}:{start}..{end}"
        values: dict[str, tuple[Any, str | None]] = {
            "fuel_type": ("natural_gas", None), "activity_quantity": (quantity, "MMBtu"),
            "activity_unit": ("MMBtu", None), "service_period_start": (start, None),
            "service_period_end": (end, None), "facility_name": (plant, None)}
        for name in FIELDS:
            value, unit = values[name]
            items.append({
                "candidate_id": f"candidate::EV-1::{DOC}::{name}::r{index}", "evidence_id": "EV-1",
                "document_id": DOC, "field_name": name, "normalized_value": value, "unit": unit,
                "validation_flags": [], "record_index": index, "record_key": key if keyed else None,
                "source_reference": {"document_id": DOC, "page_number": index, "text_snippet": f"{hint} · {quantity}",
                                     **({"record_key": key} if keyed else {})}})
    return items


def _decide(items: list[dict[str, Any]], decision: str = "accepted", *, fields: tuple[str, ...] = FIELDS,
            record: int | None = None, value: Any = None, at: int = 1, keyed: bool = True) -> list[dict[str, Any]]:
    """The decisions a reviewer would have stored on those items (the snapshot is a copy of the item)."""

    out = []
    for item in items:
        if item["field_name"] not in fields or (record is not None and item["record_index"] != record):
            continue
        snapshot = copy.deepcopy(item)
        # What the review screen posts: the candidate token carries the record key only inside source_reference.
        snapshot.pop("record_key", None)
        snapshot.pop("record_index", None)
        if not keyed:
            snapshot["source_reference"].pop("record_key", None)
        reviewed = {"accepted": item["normalized_value"], "edited": value}.get(decision)
        out.append({
            "review_decision_id": f"rd-{at}-{item['candidate_id']}", "candidate_id": item["candidate_id"],
            "evidence_id": "EV-1", "document_id": DOC, "field_name": item["field_name"], "decision": decision,
            "reviewed_value": reviewed, "reviewed_unit": item["unit"] if reviewed is not None else None,
            "reviewer_id": "k.lee@example.com", "reviewed_at": f"2025-05-0{at}T10:00:00+00:00",
            "candidate_snapshot": snapshot, "source_reference": copy.deepcopy(item["source_reference"]), "org_id": ORG})
    return out


def _fields(items: list[dict[str, Any]], reviews: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    records = group_reviewed_records({"document_id": DOC}, "CT-S1-FUELQTY", items, reviews, with_history=True)
    return {r.record_index: r.fields for r in records}  # type: ignore[misc]


JAN = ("On-peak", "2025-01-01", "2025-01-31", 58.92)
FEB = ("On-peak", "2025-02-01", "2025-02-28", 135.63)
MAR = ("Off-peak", "2025-03-01", "2025-03-31", 71.5)


# --- the probe: record 2 accepted, then a re-read shifts what record 2 is ------------------------
def test_the_probe_a_shifted_record_does_not_inherit_the_accept() -> None:
    first = _read(MAR, JAN)
    accepted = _decide(first)
    second = _read(MAR, FEB)  # the extractor changed: record 2 is now February
    fields = _fields(second, accepted)
    assert fields[1]["activity_quantity"].status == "accepted"  # record 1 did not change
    quantity = fields[2]["activity_quantity"]
    assert quantity.status == "unreviewed" and quantity.value is None and quantity.reread_changed
    assert quantity.extracted == 135.63  # the new value is shown for review, not the old 58.92
    assert quantity.history == []  # the line's history lists decisions on this value; the old one is not deleted:
    assert len(accepted) == 12  # it stays stored, and in the document's reviews
    assert any(t["candidate_id"].endswith("activity_quantity::r2") and t["applies_to_candidate_id"] is None
               for t in mark_review_targets(second, accepted))
    assert all(f.status == "unreviewed" for f in fields[2].values())  # the whole record, not one field
    assert len(accepted) == 12  # nothing was removed from the stored decisions


def test_the_probe_is_not_counted_in_the_totals_and_the_old_value_is_not_either() -> None:
    first = _read(MAR, JAN)
    store = FakeStore()
    store.add_document(DOC, "CT-S1-FUELQTY", [], decision=None)
    store.results[DOC][0]["items"] = _read(MAR, FEB)
    store.reviews[DOC] = _decide(first)
    result = _service(store).recalculate(_engagement(), _own)
    lines = result["categories"]["stationary_combustion"]["lines"]
    assert sum(line["mass_t"]["CO2"] for line in lines) == pytest.approx(71.5 * 53.06 / 1000)
    assert {a["document_id"] for a in result["awaiting_review"]} == {DOC}  # record 2 waits for review


# --- the same record at a new index: the accept carries over -------------------------------------
def test_the_same_record_at_a_new_index_keeps_its_accept() -> None:
    accepted = _decide(_read(JAN, MAR))
    fields = _fields(_read(MAR, JAN), accepted)  # records swapped places
    assert fields[2]["activity_quantity"].status == "accepted" and fields[2]["activity_quantity"].value == 58.92
    assert fields[1]["activity_quantity"].status == "accepted" and fields[1]["activity_quantity"].value == 71.5
    assert not any(f.reread_changed for rec in fields.values() for f in rec.values())


def test_two_records_with_the_same_hint_and_period_never_swap_decisions() -> None:
    twin = ("Zähler 7", "2025-01-01", "2025-01-31", 10.0)
    accepted = _decide(_read(twin, twin, JAN), record=1)
    # the twins cannot be told apart by key: only the matching index may keep a decision, and only if the value matches
    fields = _fields(_read(twin, twin, JAN), accepted)
    assert fields[1]["activity_quantity"].status == "accepted"
    assert fields[2]["activity_quantity"].status == "unreviewed"


# --- an accept where the value changed ----------------------------------------------------------
def test_an_accept_does_not_carry_when_the_value_changed() -> None:
    accepted = _decide(_read(JAN))
    fields = _fields(_read(("On-peak", "2025-01-01", "2025-01-31", 61.0)), accepted)
    quantity = fields[1]["activity_quantity"]
    assert quantity.status == "unreviewed" and quantity.reread_changed and quantity.value is None
    assert fields[1]["fuel_type"].status == "accepted"  # the unchanged values keep their accept


def test_an_accept_does_not_carry_when_only_the_unit_changed() -> None:
    accepted = _decide(_read(JAN))
    reread = _read(JAN)
    for item in reread:
        if item["field_name"] == "activity_quantity":
            item["unit"] = "therm"
    assert _fields(reread, accepted)[1]["activity_quantity"].status == "unreviewed"


def test_numbers_compare_numerically_not_as_text() -> None:
    accepted = _decide(_read(JAN))
    for decision in accepted:
        if decision["field_name"] == "activity_quantity":
            decision["candidate_snapshot"]["normalized_value"] = "58.920"  # stored as text with a trailing zero
    assert _fields(_read(JAN), accepted)[1]["activity_quantity"].status == "accepted"


# --- an edit or a reject where the value changed ---------------------------------------------------
@pytest.mark.parametrize("decision,value", [("edited", 55.0), ("rejected", None)])
def test_an_edit_or_reject_carries_over_a_changed_value_and_is_flagged(decision: str, value: Any) -> None:
    reviews = _decide(_read(JAN), decision, fields=("activity_quantity",), value=value)
    reread = _read(("On-peak", "2025-01-01", "2025-01-31", 61.0))
    quantity = _fields(reread, reviews)[1]["activity_quantity"]
    assert quantity.status == decision and not quantity.reread_changed
    assert quantity.value == value  # the reviewer's value stands
    assert quantity.flags == [VALUE_CHANGED]
    items = mark_reread_items(reread, reviews)
    flagged = next(i for i in items if i["field_name"] == "activity_quantity")
    assert VALUE_CHANGED in flagged["validation_flags"] and "review_reread_changed" not in flagged


def test_an_edit_whose_record_changed_does_not_carry() -> None:
    reviews = _decide(_read(JAN), "edited", fields=("activity_quantity",), value=55.0)
    quantity = _fields(_read(FEB), reviews)[1]["activity_quantity"]
    assert quantity.status == "unreviewed" and quantity.reread_changed


def test_an_unchanged_edit_is_not_flagged() -> None:
    reviews = _decide(_read(JAN), "edited", fields=("activity_quantity",), value=55.0)
    quantity = _fields(_read(JAN), reviews)[1]["activity_quantity"]
    assert quantity.status == "edited" and quantity.flags == []


# --- a record removed ------------------------------------------------------------------------------
def test_a_removed_record_matches_nothing_and_nothing_crashes() -> None:
    reviews = _decide(_read(JAN, MAR))
    fields = _fields(_read(MAR), reviews)  # January disappeared; March moved to index 1
    assert fields[1]["activity_quantity"].status == "accepted" and fields[1]["activity_quantity"].value == 71.5
    assert len(fields[1]["activity_quantity"].history) == 1
    assert _fields([], reviews) == {}  # a read that found nothing
    on_march = [d for d in reviews if d["candidate_id"].endswith("::r2")]
    assert applicable_decisions(_read(MAR), reviews) == on_march
    assert stale_decision_ids(_read(MAR), reviews) == {d["review_decision_id"] for d in reviews
                                                       if d["candidate_id"].endswith("::r1")}


def test_a_removed_record_leaves_the_totals_of_the_others() -> None:
    store = FakeStore()
    store.add_document(DOC, "CT-S1-FUELQTY", [], decision=None)
    store.results[DOC][0]["items"] = _read(MAR)
    store.reviews[DOC] = _decide(_read(JAN, MAR))
    lines = _service(store).recalculate(_engagement(), _own)["categories"]["stationary_combustion"]["lines"]
    assert sum(line["mass_t"]["CO2"] for line in lines) == pytest.approx(71.5 * 53.06 / 1000)


# --- old decisions without a snapshot record_key: the service period decides ---------------------------
def test_old_decisions_without_a_record_key_use_the_service_period() -> None:
    first = _read(JAN, FEB, keyed=False)
    old = _decide(first, keyed=False)
    reread = _read(JAN, ("On-peak", "2025-03-01", "2025-03-31", 135.63))  # record 2 now covers March
    fields = _fields(reread, old)
    assert fields[1]["activity_quantity"].status == "accepted"  # the same period: carried
    assert fields[2]["activity_quantity"].status == "unreviewed" and fields[2]["activity_quantity"].reread_changed


def test_old_decisions_without_a_period_to_compare_on_a_multi_record_read_do_not_apply() -> None:
    old = _decide(_read(JAN, FEB), fields=("activity_quantity",), keyed=False)  # the reviewer never decided the period
    quantity = _fields(_read(JAN, FEB), old)[1]["activity_quantity"]
    assert quantity.status == "unreviewed" and quantity.reread_changed


def test_a_single_record_document_keeps_its_decision_by_id() -> None:
    single = [{**i, "record_index": None, "record_key": None,
               "candidate_id": f"candidate::EV-1::{DOC}::{i['field_name']}"} for i in _read(JAN)]
    reviews = _decide(single)
    assert all(f.status == "accepted" for f in _fields(single, reviews)[None].values())


def test_a_decision_with_no_snapshot_applies_only_under_its_own_candidate_id() -> None:
    item = _read(JAN)[1]
    bare = {"candidate_id": item["candidate_id"], "decision": "accepted", "reviewed_value": 58.92}
    assert effective_decision(item, bare).applies
    assert not effective_decision({**item, "candidate_id": "other"}, bare).applies


# --- effective_decision itself ----------------------------------------------------------------------
def test_effective_decision_rules() -> None:
    item = _read(JAN)[1]
    decision = _decide([item])[0]
    assert effective_decision(item, decision).decision is decision
    other_field = {**item, "field_name": "activity_unit"}
    assert not effective_decision(other_field, decision).applies
    moved = {**item, "record_index": 5, "record_key": "r5:On-peak:2025-01-01..2025-01-31",
             "source_reference": {**item["source_reference"], "record_key": "r5:On-peak:2025-01-01..2025-01-31"}}
    assert effective_decision(moved, decision).applies  # r2 -> r5: hint and period are the same
    changed = {**item, "record_key": "r2:On-peak:2025-01-02..2025-01-31",
               "source_reference": {**item["source_reference"], "record_key": "r2:On-peak:2025-01-02..2025-01-31"}}
    assert not effective_decision(changed, decision).applies
    assert record_identity("r12:Zähler_3:2025-01-01..2025-01-31") == "Zähler_3:2025-01-01..2025-01-31"
    assert record_identity("r3") is None and record_identity(None) is None and record_identity("") is None


# --- every consumer uses it -----------------------------------------------------------------------------
def test_the_review_screen_marks_decisions_and_items() -> None:
    reviews = _decide(_read(JAN, MAR))
    reread = _read(MAR, FEB)  # March moved to 1, January became February
    targets = mark_review_targets(reread, reviews)
    assert len(targets) == len(reviews)  # none removed
    by_id = {t["candidate_id"]: t for t in targets}
    moved = by_id[f"candidate::EV-1::{DOC}::activity_quantity::r2"]  # March's decision, made at r2
    assert moved["applies_to_candidate_id"] == f"candidate::EV-1::{DOC}::activity_quantity::r1"
    gone = by_id[f"candidate::EV-1::{DOC}::activity_quantity::r1"]  # January's decision, made at r1
    assert gone["applies_to_candidate_id"] is None
    marked = {i["candidate_id"]: i for i in mark_reread_items(reread, reviews)}
    assert marked[f"candidate::EV-1::{DOC}::activity_quantity::r2"]["review_reread_changed"] is True
    assert "review_reread_changed" not in marked[f"candidate::EV-1::{DOC}::activity_quantity::r1"]
    assert REREAD_NOTE == "The document was re-read and this value changed. Review it again."


def test_unchanged_reads_leave_the_review_screen_payloads_untouched() -> None:
    items = _read(JAN, MAR)
    reviews = _decide(items)
    assert mark_reread_items(items, reviews) == items
    assert mark_review_targets(items, reviews) == reviews


def _approved_service(decisions: list[dict[str, Any]]) -> ApprovedEvidenceService:
    class Reviews:
        def list_by_evidence(self, evidence_id: str) -> list[dict]:
            return copy.deepcopy(decisions)

    return ApprovedEvidenceService(review_repository=Reviews(), approved_repository=InMemoryApprovedEvidenceRepository(),
                                   clock=lambda: "2026-01-01T00:00:00+00:00")


def test_approved_evidence_projects_only_decisions_that_still_apply() -> None:
    reviews = _decide(_read(JAN))
    fields = _approved_service(reviews).project_by_evidence(
        "EV-1", "ENG-1", "utility_bill", ORG, current_items=_read(FEB))
    assert fields["fields"] == [] and fields["review_status"] == "in_review"  # nothing counted, nothing crashed
    kept = _approved_service(reviews).project_by_evidence("EV-1", "ENG-1", "utility_bill", ORG, current_items=_read(JAN))
    assert {f["field_name"] for f in kept["fields"]} == set(FIELDS)
    legacy = _approved_service(reviews).project_by_evidence("EV-1", "ENG-1", "utility_bill", ORG)
    assert {f["field_name"] for f in legacy["fields"]} == set(FIELDS)  # no read given: as before


def test_the_schedule_row_says_it_must_be_reviewed_again() -> None:
    plant = ("Kansas City Plant", "2025-01-01", "2025-01-31")
    store = FakeStore()
    store.add_document(DOC, "CT-S1-FUELQTY", [], decision=None)
    store.results[DOC][0]["items"] = _read((plant[0], "2025-01-01", "2025-01-31", 61.0), plant="Kansas City Plant")
    store.reviews[DOC] = _decide(_read((plant[0], "2025-01-01", "2025-01-31", 58.92), plant="Kansas City Plant"))
    schedule = _tree_service(store).schedule(_tree_engagement(), _own, GAS_KC, None)
    assert schedule is not None
    row = schedule["rows"][0]
    assert row["decision"] == "not_reviewed" and row["accepted"] is False and row["reread_changed"] is True


def test_the_workpaper_register_says_a_value_was_not_reviewed_after_a_reread() -> None:
    store = FakeStore()
    store.add_document(DOC, "CT-S1-FUELQTY", [], decision=None)
    store.results[DOC][0]["items"] = _read(FEB)
    store.reviews[DOC] = _decide(_read(JAN))
    register = _service(store).evidence_register("ENG-1", _own)
    assert {v["decision"] for v in register["values"]} == {"not reviewed (re-read, value changed)"}


# --- no behaviour change when nothing was re-read -----------------------------------------------------------
def _legacy_resolve(items: list[dict[str, Any]], reviews: list[dict[str, Any]]) -> list[re_.Resolution]:
    """What the code did before the guard: the latest decision under the candidate id, whatever it was made on."""

    latest = re_.latest_decisions(reviews)
    every = re_.all_decisions(reviews)
    return [re_.Resolution(latest.get(str(i.get("candidate_id"))), False, False, every.get(str(i.get("candidate_id")), []))
            for i in items]


def _unchanged_engagement() -> FakeStore:
    store = FakeStore()
    store.add_document("BILL-A", "CT-S1-FUELQTY", [], decision=None)
    store.add_document("BILL-B", "CT-S1-FUELQTY", [], decision=None)
    store.add_document("ELEC-1", "CT-S2-ELEC", [{
        "activity_quantity": (700, "MWh"), "activity_unit": ("MWh", None), "energy_type": ("electricity", None),
        "facility_name": (PLANT, None), "service_address": ("Seestraße 1, Zürich", None),
        "service_period_start": ("2025-01-01", None), "service_period_end": ("2025-06-30", None)}])
    records = [JAN, FEB, MAR]
    store.results["BILL-A"][0]["items"] = _read(*records)
    store.reviews["BILL-A"] = [*_decide(_read(*records)), *_decide(_read(*records), "edited", fields=("activity_quantity",),
                                                                  value=50.0, at=2, record=2)]
    store.results["BILL-B"][0]["items"] = _read(*records, plant="Plant 2")
    store.reviews["BILL-B"] = _decide(_read(*records, plant="Plant 2"), "rejected", fields=("activity_quantity",), record=3)
    return store


def test_a_full_recalculation_is_identical_before_and_after_the_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    store = _unchanged_engagement()
    settings = {"recalculation": {"grid_regions": {PLANT: "NYUP"}}}
    after = _service(store).recalculate(_engagement(**settings), _own)
    schedule_after = _tree_service(store).schedule(_tree_engagement(), _own, GAS_KC, None)
    monkeypatch.setattr(re_, "resolve_decisions", _legacy_resolve)
    before = _service(store).recalculate(_engagement(**settings), _own)
    schedule_before = _tree_service(store).schedule(_tree_engagement(), _own, GAS_KC, None)
    assert json.dumps(after, sort_keys=True, default=str) == json.dumps(before, sort_keys=True, default=str)
    assert json.dumps(schedule_after, sort_keys=True, default=str) == json.dumps(schedule_before, sort_keys=True, default=str)
    assert after["categories"]["stationary_combustion"] is not None  # the engagement really counted something


def test_hostile_data_never_fails_a_page() -> None:
    items = _read(JAN)
    items.append({"field_name": None, "candidate_id": None, "normalized_value": "x", "record_index": "oops"})
    items.append({"candidate_id": "c-1", "field_name": "activity_quantity", "record_key": 5, "record_index": 9,
                  "normalized_value": float("nan"), "unit": 3})
    reviews = _decide(_read(JAN))
    reviews.append({"candidate_id": None, "decision": "accepted", "candidate_snapshot": "not a dict"})
    reviews.append({"candidate_id": "c-1", "decision": "edited", "candidate_snapshot": {"record_key": ["x"]}})
    assert len(resolve_decisions(items, reviews)) == len(items)
    assert group_reviewed_records({"document_id": DOC}, "CT-S1-FUELQTY", items, reviews)
