"""Account and meter numbers on Setup facilities (PROVISIONAL, see services/facility_identifiers.py):
parsing, limits, normalisation, the matching step, and where placement uses it (Evidence tree,
calculation lines, recalculation)."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from backend.app.api.engagements import EngagementUpdate
from backend.app.services import calculation_lines as cl
from backend.app.services import facility_identifiers as fi
from backend.app.services.reviewed_evidence import match_facility, resolve_setup_facility
from backend.tests.services.test_calculation_lines import (
    GAS_KC,
    GAS_STL,
    KC,
    STL,
    _gas,
    _lines_with_docs,
    _tree,
    _tree_service,
)
from backend.tests.services.test_engagement_recalculation_service import FakeStore, _own

ACCT = "4417-2290-31"
UNKNOWN_PLANT = "Müller Käserei – Zürich 工場"  # a name Setup does not list


def _id(found: fi.IdentifierMatch) -> str | None:
    return found.facility["facilityId"] if found.facility else None


def _with(facility: dict[str, Any], **numbers: list[str]) -> dict[str, Any]:
    return {**facility, **numbers}


# --- parsing and limits -----------------------------------------------------------------------
def test_a_pasted_list_with_mixed_separators_splits_into_clean_values() -> None:
    pasted = "4417-2290-31, 55 0012;  Zürich-№ 7\n\r\n 99.12.34 ;;, \n"
    assert fi.split_pasted(pasted) == ["4417-2290-31", "55 0012", "Zürich-№ 7", "99.12.34"]
    assert fi.split_pasted("   \n ,; ") == []


@pytest.mark.parametrize("value, ok", [("4417-2290-31", True), ("工場 12", True), ("٣٤٥", True)])
def test_a_value_with_a_digit_is_accepted(value: str, ok: bool) -> None:
    assert (fi.check_value(value) is None) is ok


@pytest.mark.parametrize("value", ["", "   ", "Müller", "---", None, 12])
def test_an_empty_or_digit_free_value_is_refused_with_a_sentence(value: Any) -> None:
    problem = fi.check_value(value)
    assert problem is not None and problem.endswith(".") and ("digit" in problem or "empty" in problem)


def test_the_length_limit_is_64_characters() -> None:
    assert fi.check_value("1" * 64) is None
    assert "64" in (fi.check_value("1" * 65) or "")


def test_validation_on_save_enforces_the_list_limits() -> None:
    fi.validate_numbers({"name": "A"})  # an old facility has no field: fine
    fi.validate_numbers({"name": "A", "accountNumbers": ["1"] * 50, "meterNumbers": None})
    with pytest.raises(ValueError, match="at most 50"):
        fi.validate_numbers({"name": "Müller Käserei", "accountNumbers": [f"{i}" for i in range(51)]})
    with pytest.raises(ValueError, match="at most 64"):
        fi.validate_numbers({"name": "A", "meterNumbers": ["9" * 65]})
    with pytest.raises(ValueError, match="must be a list"):
        fi.validate_numbers({"name": "A", "accountNumbers": "4417"})
    with pytest.raises(ValueError, match="digit"):
        fi.validate_numbers({"name": "A", "accountNumbers": ["4417", "Zürich"]})


def test_the_engagement_settings_check_refuses_bad_numbers_and_accepts_good_ones() -> None:
    good = {"facilities": [{"facilityId": "f1", "name": "Zürich", "accountNumbers": [ACCT], "meterNumbers": ["E-1"]}]}
    assert EngagementUpdate(settings=good).settings == good  # stored as typed
    bad = {"facilities": [{"facilityId": "f1", "name": "Zürich", "accountNumbers": ["", "12"]}]}
    with pytest.raises(ValidationError, match="can't be empty"):
        EngagementUpdate(settings=bad)


# --- normalisation ----------------------------------------------------------------------------
def test_normalisation_ignores_case_spaces_dashes_and_dots_only() -> None:
    assert fi.normalise("4417 2290 31") == fi.normalise("4417-2290-31") == fi.normalise(" 4417.2290.31 ")
    assert fi.normalise("ab-12–3") == fi.normalise("AB 12‑3") == "ab123"  # en dash and non-breaking hyphen
    assert fi.normalise("Ⅻ-٣") == "xii٣"  # compatibility forms are folded
    assert fi.normalise("4417/2290") != fi.normalise("44172290")  # a slash is not ignored
    assert fi.normalise(None) == ""


# --- the matching step ------------------------------------------------------------------------
def test_one_facility_with_the_whole_number_places_the_bill() -> None:
    facilities = [_with(KC, accountNumbers=["4417-2290-31 (Zürich)", ACCT]), STL]
    found = fi.match_by_identifier("4417 2290 31", None, facilities)
    assert _id(found) == KC['facilityId'] and found.reason == "Account number in Setup" and found.ambiguous is None


def test_a_partial_number_never_matches() -> None:
    facilities = [_with(KC, accountNumbers=[ACCT], meterNumbers=["E-90412"]), STL]
    for partial in ("4417-2290", "2290-31", "4417-2290-3", "4417-2290-31-1", "44"):
        assert fi.match_by_identifier(partial, partial, facilities) == fi.IdentifierMatch()


def test_a_number_on_two_facilities_places_nothing_and_says_why() -> None:
    facilities = [_with(KC, accountNumbers=[ACCT]), _with(STL, accountNumbers=["4417 2290 31"])]
    found = fi.match_by_identifier("4417-2290-31", None, facilities)
    assert found.facility is None and found.ambiguous == "Account 4417-2290-31 is listed on two facilities"
    assert fi.shared_numbers(facilities, fi.ACCOUNT) == {ACCT: ["Kansas City Plant", "St Louis Plant"]}
    assert fi.shared_numbers(facilities, fi.METER) == {}


def test_a_meter_number_matches_when_no_account_is_read() -> None:
    facilities = [KC, _with(STL, meterNumbers=["Zähler E-55604"])]
    found = fi.match_by_identifier(None, "zähler e 55604", facilities)
    assert _id(found) == STL['facilityId'] and found.reason == "Meter number in Setup"
    assert fi.match_by_identifier("", " ", facilities) == fi.IdentifierMatch()


def test_a_facility_listing_a_number_twice_does_not_count_as_two_facilities() -> None:
    facilities = [_with(KC, accountNumbers=[ACCT, "4417 2290 31"]), STL]
    assert fi.match_by_identifier(ACCT, None, facilities).facility ['facilityId'] == KC['facilityId']
    assert fi.shared_numbers(facilities, fi.ACCOUNT) == {}


def test_old_or_malformed_facilities_read_as_having_no_numbers() -> None:
    facilities = [KC, {**STL, "accountNumbers": "4417-2290-31", "meterNumbers": [None, 5, "  "]}]
    assert fi.match_by_identifier(ACCT, "5", facilities) == fi.IdentifierMatch()


# --- where placement uses it ------------------------------------------------------------------
def test_the_step_runs_only_after_the_name_and_address_steps() -> None:
    facilities = [_with(KC, accountNumbers=[ACCT]), STL]

    def placed(decisions: dict, name: Any, address: Any, **read: Any) -> str | None:
        found = resolve_setup_facility(facilities, decisions, "D", name, address, **read)
        return found["facilityId"] if found else None

    assert match_facility(UNKNOWN_PLANT, None, facilities) is None  # match_facility itself is unchanged
    assert placed({}, UNKNOWN_PLANT, None, account=ACCT) == "fac-kc01"
    # the address wins over the account number
    assert placed({}, UNKNOWN_PLANT, "200 Oak Avenue, St Louis, MO 63101", account=ACCT) == "fac-stl2"
    # so does the facility name
    assert placed({}, "St Louis Plant", None, account=ACCT) == "fac-stl2"
    # and the reviewer's choice
    assert placed({"D": {"facilityId": "fac-stl2"}}, None, None, account=ACCT) == "fac-stl2"
    # nothing read: behaves as before
    assert placed({}, UNKNOWN_PLANT, None) is None


def test_a_bill_is_placed_on_its_line_by_account_number() -> None:
    store = FakeStore()
    store.add_document("D1", "CT-S1-FUELQTY", [_gas(plant=UNKNOWN_PLANT, account_number="4417 2290 31")])
    facilities = [_with(KC, accountNumbers=[ACCT]), STL]
    tree = _tree(store, facilities=facilities)
    assert _lines_with_docs(tree) == {GAS_KC: ["D1"]}
    row = next(r for r in _all_rows(tree))
    assert row["facility_id"] == "fac-kc01" and row["facility_note"] is None


def _all_rows(tree: dict) -> list[dict]:
    rows: list[dict] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            if "document_id" in node and "facility_id" in node:
                rows.append(node)
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(tree)
    return rows


def test_a_shared_number_leaves_the_bill_unplaced_with_the_reason_in_the_tree_and_the_recalculation() -> None:
    facilities = [_with(KC, accountNumbers=[ACCT]), _with(STL, accountNumbers=["4417 2290 31"])]
    store = FakeStore()
    store.add_document("D1", "CT-S1-FUELQTY", [_gas(plant=UNKNOWN_PLANT, account_number=ACCT)])
    tree = _tree(store, facilities=facilities)
    assert _lines_with_docs(tree) == {}
    rows = [r for r in _all_rows(tree) if r["document_id"] == "D1"]
    assert rows and all(r["facility_note"] == "Account 4417-2290-31 is listed on two facilities" for r in rows)


def _recalc(store: FakeStore, facilities: list[dict]) -> dict:
    from backend.app.services.engagement_recalculation_service import EngagementRecalculationService
    engagement = {"id": "ENG-1", "reporting_period_start": "2025-01-01", "reporting_period_end": "2025-12-31",
                  "settings": {"facilities": facilities, "recalculation": {}}}
    return EngagementRecalculationService(store, store, store).recalculate(engagement, _own, None)


def test_the_recalculation_places_by_account_and_reports_a_shared_number_as_unplaced() -> None:
    store = FakeStore()
    store.add_document("D1", "CT-S1-FUELQTY", [_gas(1000, plant=UNKNOWN_PLANT, account_number="4417 2290 31")])
    placed = _recalc(store, [_with(KC, accountNumbers=[ACCT]), STL])
    assert [line["key"] for line in placed["calculation_lines"]] == [GAS_KC] and not placed["calculation_unplaced"]
    shared = _recalc(store, [_with(KC, accountNumbers=[ACCT]), _with(STL, accountNumbers=[ACCT])])
    assert [u["reason"] for u in shared["calculation_unplaced"]] == ["identifier_on_two_facilities"]
    assert not shared["calculation_lines"]
    partial = _recalc(store, [_with(KC, accountNumbers=["4417-2290"]), STL])
    assert [u["reason"] for u in partial["calculation_unplaced"]] == ["no_facility_match"]


def test_an_address_match_still_beats_an_account_number_in_a_calculation() -> None:
    store = FakeStore()
    store.add_document("D1", "CT-S1-FUELQTY", [_gas(1000, plant=UNKNOWN_PLANT, account_number=ACCT,
                                                     service_address="200 Oak Avenue, St Louis, MO 63101")])
    result = _recalc(store, [_with(KC, accountNumbers=[ACCT]), STL])
    assert [line["key"] for line in result["calculation_lines"]] == [GAS_STL]


def test_an_old_engagement_without_the_field_is_calculated_exactly_as_before() -> None:
    def build(with_account: bool) -> FakeStore:
        store = FakeStore()
        extra = {"account_number": "4417 2290 31", "meter_number": "Zähler 7"} if with_account else {}
        store.add_document("D1", "CT-S1-FUELQTY", [_gas(1000, **extra)])
        store.add_document("D2", "CT-S1-FUELQTY", [_gas(50, plant=UNKNOWN_PLANT, **extra)])
        return store

    old_facilities = [KC, STL]  # saved before the field existed
    assert _recalc(build(True), old_facilities) == _recalc(build(False), old_facilities)
    with_empty = [{**KC, "accountNumbers": [], "meterNumbers": []}, STL]
    assert _recalc(build(True), with_empty) == _recalc(build(False), old_facilities)
    tree_old = _tree(build(True), facilities=old_facilities)
    assert _lines_with_docs(tree_old) == {GAS_KC: ["D1"]}


def test_facility_match_names_the_step_that_placed_the_record() -> None:
    store = FakeStore()
    store.add_document("D1", "CT-S1-FUELQTY", [_gas(plant=UNKNOWN_PLANT, meter_number="E 55604")])
    engagement = {"id": "ENG-1", "settings": {"facilities": [KC, _with(STL, meterNumbers=["E-55604"])]}}
    loaded = _tree_service(store).load(engagement, _own)
    found = cl.facility_match(loaded.facilities, {}, "D1", loaded.docs[0].records[0])
    assert found is not None and found[0]["facilityId"] == "fac-stl2" and found[1] == "Account or meter number in Setup"
    assert GAS_STL.endswith("fac-stl2")


# --- one source for placement: the Evidence tree, the calculation lines and the recalculation agree -----------
def _read_store(case: str) -> FakeStore:
    """A bill whose name and address match nothing, with its account number read three ways:
    "rule": read by the rules and not yet reviewed; "ai_only": suggested by Claude, nobody accepted it;
    "accepted": suggested by Claude and accepted by a reviewer."""

    store = FakeStore()
    record = _gas(1000, plant=UNKNOWN_PLANT, account_number="4417 2290 31")
    store.add_document("D1", "CT-S1-FUELQTY", [record], decision="accepted" if case == "accepted" else None)
    if case in ("ai_only", "accepted"):
        for item in store.results["D1"][0]["items"]:
            if item["field_name"] == "account_number":
                item["validation_flags"] = ["ai_suggested"]
    return store


@pytest.mark.parametrize("case, placed", [("rule", True), ("ai_only", False), ("accepted", True)])
def test_the_tree_the_lines_and_the_recalculation_place_a_bill_the_same_way(case: str, placed: bool) -> None:
    facilities = [_with(KC, accountNumbers=[ACCT]), STL]
    store = _read_store(case)
    assert _lines_with_docs(_tree(store, facilities=facilities)) == ({GAS_KC: ["D1"]} if placed else {})
    engagement = {"id": "ENG-1", "settings": {"facilities": facilities}}
    loaded = _tree_service(store).load(engagement, _own)
    found = cl.facility_match(loaded.facilities, {}, "D1", loaded.docs[0].records[0])
    assert (found[0]["facilityId"] if found else None) == ("fac-kc01" if placed else None)
    result = _recalc(_read_store(case), facilities)
    if case == "accepted":  # the recalculation counts reviewed values only
        assert [line["key"] for line in result["calculation_lines"]] == [GAS_KC]
    assert "identifier_on_two_facilities" not in [u["reason"] for u in result["calculation_unplaced"]]
