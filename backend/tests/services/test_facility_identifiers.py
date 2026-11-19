"""Account and meter numbers on Setup facilities (PROVISIONAL, see services/facility_identifiers.py):
parsing, limits, normalisation, the matching step, and where placement uses it (Evidence tree,
calculation lines, recalculation)."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from backend.app.api.engagements import EngagementUpdate
from backend.app.services import facility_identifiers as fi
from backend.tests.services.test_calculation_lines import GAS_KC, KC, STL, _gas, _lines_with_docs, _tree
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


def test_the_paste_parser_keeps_a_quoted_value_whole_and_drops_its_quotes() -> None:
    assert fi.split_pasted('"4417, 22";"55;0012", 99-1234\n"Müller, Zürich 7"') == [
        "4417, 22", "55;0012", "99-1234", "Müller, Zürich 7"]


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
    assert fi.normalise("ẞ12") == "ss12"  # case folding, not just lower-casing
    assert fi.normalise("\ufeff4417\u200b-2290") == "44172290"  # a BOM and a zero-width space are dropped
    assert fi.normalise("4417/2290") != fi.normalise("44172290")  # a slash is not ignored
    assert fi.normalise(None) == ""


def test_the_same_number_needs_the_same_groups_or_no_separators_on_one_side() -> None:
    assert fi.same_number("4417 2290 31", "4417-2290-31")
    assert fi.same_number("442290", "44-2290") and fi.same_number("44.2290", "442290")
    assert not fi.same_number("12-345", "1234-5")  # both have dashes, different groups
    assert not fi.same_number("4417-2290", "4417-2290-31") and not fi.same_number("", "")


# --- the matching step ------------------------------------------------------------------------
def test_one_facility_with_the_whole_number_places_the_bill() -> None:
    facilities = [_with(KC, accountNumbers=["4417-2290-31 (Zürich)", ACCT]), STL]
    found = fi.match_by_identifier("4417 2290 31", None, facilities)
    assert _id(found) == KC["facilityId"] and found.reason == fi.REASON and found.ambiguous is None
    assert found.what == "Account 4417 2290 31"


def test_a_partial_number_never_matches() -> None:
    facilities = [_with(KC, accountNumbers=[ACCT], meterNumbers=["E-90412"]), STL]
    for partial in ("4417-2290", "2290-31", "4417-2290-3", "4417-2290-31-1", "44"):
        assert fi.match_by_identifier(partial, partial, facilities) == fi.IdentifierMatch()


def test_a_number_with_fewer_than_four_digits_never_matches_either_way() -> None:
    facilities = [_with(KC, accountNumbers=["123", "E-12"], meterNumbers=["77"])]
    assert fi.match_by_identifier("123", "77", facilities) == fi.IdentifierMatch()
    assert fi.match_by_identifier("E-12", None, facilities) == fi.IdentifierMatch()
    assert fi.check_value("123") is None  # it can still be saved


def test_a_number_on_two_facilities_places_nothing_and_says_why() -> None:
    facilities = [_with(KC, accountNumbers=[ACCT]), _with(STL, accountNumbers=["4417 2290 31"])]
    found = fi.match_by_identifier("4417-2290-31", None, facilities)
    assert found.facility is None and found.ambiguous == "Account 4417-2290-31 is listed on two facilities"
    assert fi.shared_numbers(facilities, fi.ACCOUNT) == {ACCT: ["Kansas City Plant", "St Louis Plant"]}
    assert fi.shared_numbers(facilities, fi.METER) == {}


def test_an_account_and_a_meter_on_different_facilities_place_nothing() -> None:
    facilities = [_with(KC, accountNumbers=[ACCT]), _with(STL, meterNumbers=["E-55604"])]
    found = fi.match_by_identifier(ACCT, "E 55604", facilities)
    assert found.facility is None and found.ambiguous == (
        "Account 4417-2290-31 and meter E 55604 are listed on different facilities")
    same = [_with(KC, accountNumbers=[ACCT], meterNumbers=["E-55604"]), STL]
    assert _id(fi.match_by_identifier(ACCT, "E 55604", same)) == KC["facilityId"]


def test_a_meter_number_matches_when_no_account_is_read() -> None:
    facilities = [KC, _with(STL, meterNumbers=["Zähler E-55604"])]
    found = fi.match_by_identifier(None, "zähler e 55604", facilities)
    assert _id(found) == STL["facilityId"] and found.reason == fi.REASON and found.what == "Meter zähler e 55604"
    assert fi.match_by_identifier("", " ", facilities) == fi.IdentifierMatch()


def test_a_facility_listing_a_number_twice_does_not_count_as_two_facilities() -> None:
    facilities = [_with(KC, accountNumbers=[ACCT, "4417 2290 31"]), STL]
    assert _id(fi.match_by_identifier(ACCT, None, facilities)) == KC["facilityId"]
    assert fi.shared_numbers(facilities, fi.ACCOUNT) == {}


def test_old_or_malformed_facilities_read_as_having_no_numbers() -> None:
    facilities = [KC, {**STL, "accountNumbers": "4417-2290-31", "meterNumbers": [None, 5, "  "]}]
    assert fi.match_by_identifier(ACCT, "5", facilities) == fi.IdentifierMatch()


# --- an engagement saved before the field existed -----------------------------------------------
def _recalc(store: FakeStore, facilities: list[dict], company: str | None = None) -> dict:
    from backend.app.services.engagement_recalculation_service import EngagementRecalculationService

    engagement = {"id": "ENG-1", "reporting_period_start": "2025-01-01", "reporting_period_end": "2025-12-31",
                  "client_name": company, "settings": {"facilities": facilities, "recalculation": {}}}
    return EngagementRecalculationService(store, store, store).recalculate(engagement, _own, None)


def test_an_old_engagement_without_the_field_is_calculated_exactly_as_before() -> None:
    def build(with_account: bool) -> FakeStore:
        store = FakeStore()
        extra = {"account_number": "4417 2290 31", "meter_number": "Zähler 7"} if with_account else {}
        store.add_document("D1", "CT-S1-FUELQTY", [_gas(1000, **extra)])
        store.add_document("D2", "CT-S1-FUELQTY", [_gas(50, plant=UNKNOWN_PLANT, **extra)])
        store.add_document("D3", "CT-S1-FUELQTY", [{**_gas(60, **extra), "facility_name": (None, None)}])
        return store

    old_facilities = [KC, STL]  # saved before the field existed
    assert _recalc(build(True), old_facilities) == _recalc(build(False), old_facilities)
    with_empty = [{**KC, "accountNumbers": [], "meterNumbers": []}, STL]
    assert _recalc(build(True), with_empty) == _recalc(build(False), old_facilities)
    assert _lines_with_docs(_tree(build(True), facilities=old_facilities)) == {GAS_KC: ["D1"]}
