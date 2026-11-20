"""The GWP set chosen on Methodology review drives the recalculation (Claire, C-M6)."""

from __future__ import annotations

from typing import Any

import pytest

from backend.app.reference.emission_factor_loader import default_emission_factor_reference
from backend.app.services.methodology_gwp import DEFAULT_LABEL, choice_from_record, default_choice
from backend.tests.services.test_recalculation_lines import GAS_KC, _by_key, _engagement, _gas_store, _service
from backend.tests.services.test_engagement_recalculation_service import _own


def _record(status: str | None, gwp_set: str = "AR5", horizon: str = "100-year") -> dict[str, Any]:
    decision = {"status": status, "value": {"set": gwp_set, "horizon": horizon}} if status else None
    return {"field_id": "gwp", "suggestion": {"value": {"set": "AR6", "horizon": "100-year"}},
            "decision": decision, "history": []}


def _run(choice: Any = None, **recalculation: Any) -> dict:
    engagement = _engagement(recalculation=recalculation)
    if choice is not None:
        engagement["methodology_gwp"] = choice
    return _service(_gas_store()).recalculate(engagement, _own)


def _kc_gas_co2e(result: dict) -> dict[str, float]:
    return _by_key(result)[GAS_KC]["results"]["gas_co2e_t"]


def test_ar5_versus_ar6_changes_the_ch4_and_n2o_contribution_on_a_natural_gas_line() -> None:
    # Kansas City Plant natural gas: 30,000 + 35,000 = 65,000 MMBtu (EPA Hub Table 1: 1 g CH4, 0.1 g N2O per MMBtu)
    #   CH4 = 65,000 x 1 g   = 65,000 g   = 0.065 t      N2O = 65,000 x 0.1 g = 6,500 g = 0.0065 t
    #   CO2 = 65,000 x 53.06 kg = 3,448,900 kg = 3,448.9 t (no GWP, 1)
    ar5 = _run(choice_from_record(_record("accepted", "AR5")))
    ar6 = _run(choice_from_record(_record("accepted", "AR6")))
    # AR5 (Hub Table 11):  CH4 0.065 x 28  = 1.82    N2O 0.0065 x 265 = 1.7225
    assert _kc_gas_co2e(ar5)["CH4"] == pytest.approx(1.82)
    assert _kc_gas_co2e(ar5)["N2O"] == pytest.approx(1.7225)
    # AR6 (emission_factor_library.json): CH4 0.065 x 27.0 = 1.755   N2O 0.0065 x 273 = 1.7745
    assert _kc_gas_co2e(ar6)["CH4"] == pytest.approx(1.755)
    assert _kc_gas_co2e(ar6)["N2O"] == pytest.approx(1.7745)
    assert _kc_gas_co2e(ar5)["CO2"] == pytest.approx(3448.9) == pytest.approx(_kc_gas_co2e(ar6)["CO2"])
    assert (ar5["gwp_set"], ar6["gwp_set"]) == ("AR5", "AR6")
    # The hub-level arithmetic for 28,100 MMBtu (the demo golden): CH4 0.0281 t, N2O 0.00281 t
    ref = default_emission_factor_reference()
    assert 0.0281 * ref.gwp("CH4", "AR5").value == pytest.approx(0.7868)
    assert 0.00281 * ref.gwp("N2O", "AR5").value == pytest.approx(0.74465)
    assert 0.0281 * ref.gwp("CH4", "AR6").value == pytest.approx(0.7587)
    assert 0.00281 * ref.gwp("N2O", "AR6").value == pytest.approx(0.76713)


def test_ar4_is_supported_too() -> None:
    result = _run(choice_from_record(_record("edited", "AR4")))
    assert _kc_gas_co2e(result)["CH4"] == pytest.approx(0.065 * 25)  # 1.625
    assert _kc_gas_co2e(result)["N2O"] == pytest.approx(0.0065 * 298)  # 1.937


@pytest.mark.parametrize("record", [None, _record(None), _record("pending"), _record("rejected")])
def test_no_confirmed_choice_keeps_ar5_and_says_so(record: dict | None) -> None:
    choice = choice_from_record(record)
    assert choice == default_choice()
    result = _run(choice)
    assert result["gwp_set"] == "AR5" and result["gwp_source"] == "default"
    assert result["gwp_label"] == DEFAULT_LABEL == "AR5 (default — not set in Methodology review)"
    assert result["gwp_blocked"] is None
    assert _kc_gas_co2e(result)["CH4"] == pytest.approx(1.82)


@pytest.mark.parametrize("horizon", ["500-year", "20-year"])
def test_an_unsupported_horizon_is_blocked_not_replaced(horizon: str) -> None:
    choice = choice_from_record(_record("accepted", "AR6", horizon))
    assert choice["supported"] is False
    result = _run(choice)
    assert result["gwp_label"] == f"AR6 {horizon} — not supported for calculation"
    assert f"The {horizon} horizon" in result["gwp_blocked"] and "not supported for calculation" in result["gwp_blocked"]
    assert result["calculation_lines"] == [] and all(v is None for v in result["categories"].values())


def test_an_unknown_set_is_blocked() -> None:
    choice = choice_from_record(_record("accepted", "AR3"))
    assert choice["supported"] is False and "not supported for calculation" in str(choice["message"])


# --- several GWP rows: one source of truth --------------------------------------------------
from backend.app.services.methodology_gwp import choice_from_records  # noqa: E402
from backend.tests.services.test_engagement_recalculation_service import FakeStore, _refrigerant  # noqa: E402
from backend.tests.services.test_engagement_recalculation_service import _engagement as _plain_engagement  # noqa: E402
from backend.tests.services.test_engagement_recalculation_service import _service as _plain_service  # noqa: E402


def test_a_rejected_ar6_and_an_accepted_ar5_row_say_ar5_confirmed_not_default() -> None:
    choice = choice_from_records({
        "gwp": _record("rejected", "AR6"),
        "gwp:ab12cd": {"decision": {"status": "accepted", "value": {"set": "AR5", "horizon": "100-year"}}},
    })
    assert choice["set"] == "AR5" and choice["source"] == "methodology" and choice["row"] == "gwp:ab12cd"
    assert "default" not in choice["label"]
    assert choice["label"] == "AR5 · 100-year (Methodology review, GWP set row 2)"
    result = _run(choice)
    assert result["gwp_set"] == "AR5" and result["gwp_source"] == "methodology" and result["gwp_row"] == "gwp:ab12cd"


def test_two_different_confirmed_sets_block_the_calculation() -> None:
    choice = choice_from_records({"gwp": _record("accepted", "AR5"), "gwp:ab12cd": _record("edited", "AR6")})
    assert choice["supported"] is False
    assert choice["message"] == "Two GWP sets confirmed in Methodology review — keep one"
    result = _run(choice)
    assert result["gwp_set"] is None and result["gwp_blocked"] == choice["message"]
    assert all(v is None for v in result["categories"].values())


def test_the_same_set_confirmed_twice_is_one_choice_and_a_removed_row_does_not_count() -> None:
    same = choice_from_records({"gwp": _record("accepted", "AR6"), "gwp:ab12cd": _record("accepted", "AR6")})
    assert same["supported"] and same["set"] == "AR6" and same["row"] == "gwp"
    removed = {**_record("accepted", "AR6"), "removed": True}
    assert choice_from_records({"gwp": _record("accepted", "AR5"), "gwp:ab12cd": removed})["set"] == "AR5"


def test_a_blocked_result_names_no_set() -> None:
    assert _run(choice_from_record(_record("accepted", "AR5", "500-year")))["gwp_set"] is None


def test_the_retired_settings_input_never_chooses_the_set() -> None:
    engagement = _engagement(recalculation={"gwp_set": "AR6"})  # an old save: ignored
    result = _service(_gas_store()).recalculate(engagement, _own)
    assert result["gwp_set"] == "AR5" and result["gwp_label"] == DEFAULT_LABEL


# --- refrigerants under AR4 / AR6 -----------------------------------------------------------
def _fridge_store() -> FakeStore:
    store = FakeStore()
    store.add_document("R410A", "CT-S1-REFRSVC", [_refrigerant("R-410A", "2025-03-01", added=10)])
    return store


def _fridge(choice: Any, **recalculation: Any) -> dict:
    engagement = _plain_engagement(**({"recalculation": recalculation} if recalculation else {}))
    engagement["methodology_gwp"] = choice
    return _plain_service(_fridge_store()).recalculate(engagement, _own)


def test_an_hfc_blend_has_no_ar6_gwp_in_the_reference_data_and_asks_for_one() -> None:
    result = _fridge(choice_from_record(_record("accepted", "AR6")))
    ask = next(n for n in result["needs_input"] if n["kind"] == "refrigerant_gwp")
    assert ask["message"].startswith("No AR6 GWP for R-410A in Sustentra's reference data")
    assert "Hub" not in ask["message"]
    assert result["categories"]["fugitive_refrigerants"] is None
    assert _fridge(choice_from_record(_record("accepted", "AR5")))["categories"]["fugitive_refrigerants"] is not None


def test_an_entered_gwp_applies_only_under_the_set_it_was_entered_under() -> None:
    ar6 = choice_from_record(_record("accepted", "AR6"))
    tagged = {"refrigerant_gwps": {"R-410A": {"value": 2256, "gwp_set": "AR6"}}}
    used = _fridge(ar6, **tagged)["categories"]["fugitive_refrigerants"]
    assert used["gwp"]["R-410A"]["value"] == 2256
    other = _fridge(choice_from_record(_record("accepted", "AR4")), **tagged)
    assert other["categories"]["fugitive_refrigerants"] is None
    ask = next(n for n in other["needs_input"] if n["kind"] == "refrigerant_gwp")
    assert "AR6 value" in ask["message"] and "chose AR4" in ask["message"]
    legacy = {"refrigerant_gwps": {"R-410A": 2088}}  # saved without a set: none is assumed, under any set
    for choice in (ar6, default_choice()):
        unsure = _fridge(choice, **legacy)
        assert unsure["categories"]["fugitive_refrigerants"] is None
        ask = next(n for n in unsure["needs_input"] if n["kind"] == "refrigerant_gwp")
        assert ask["message"].startswith("Confirm which GWP set this refrigerant value uses")


def test_a_blocked_gwp_choice_reaches_the_line_schedule_and_is_never_called_calculated() -> None:
    from backend.tests.services.test_calculation_lines import _engagement as lines_engagement
    from backend.tests.services.test_calculation_lines import _schedule_store, _tree_service

    engagement = lines_engagement()
    engagement["methodology_gwp"] = choice_from_record(_record("accepted", "AR6", "500-year"))
    schedule = _tree_service(_schedule_store()).schedule(engagement, _own, GAS_KC)
    assert schedule is not None
    assert schedule["calculated"] is False and "not supported for calculation" in schedule["calculation_blocked"]
    engagement["methodology_gwp"] = default_choice()
    schedule = _tree_service(_schedule_store()).schedule(engagement, _own, GAS_KC)
    assert schedule is not None and schedule["calculated"] is True and schedule["calculation_blocked"] is None


# --- use notes (applies_to) and "Not stated" ---------------------------------------------------
def _row(gwp_set: str, note: str = "", horizon: str = "100-year", status: str = "accepted") -> dict[str, Any]:
    value = {"set": gwp_set, "horizon": horizon, **({"applies_to": note} if note else {})}
    return {"field_id": "gwp", "suggestion": None, "decision": {"status": status, "value": value}, "history": []}


def test_a_not_stated_horizon_is_taken_as_100_year_and_labelled_assumed_never_blocked() -> None:
    choice = choice_from_record(_row("AR5", horizon="Not stated"))
    assert choice["supported"] and choice["set"] == "AR5" and choice["horizon"] == "100-year"
    assert choice["label"] == "AR5 · 100-year (assumed — horizon not stated)"
    assert _run(choice)["gwp_label"] == choice["label"]
    assert _kc_gas_co2e(_run(choice))["CH4"] == pytest.approx(1.82)
    assert choice_from_record(_row("AR5", horizon="20-year"))["supported"] is False


def test_the_general_set_drives_and_a_set_embedded_in_factors_is_information_only() -> None:
    choice = choice_from_records({
        "gwp": _row("AR6", "default"),
        "gwp:aa11bb": _row("AR5", "embedded in the supplier emission factors")})
    assert choice["set"] == "AR6" and choice["row"] == "gwp" and choice["supported"]
    assert choice["refrigerant_set"] == "AR6"
    assert len(choice["info"]) == 1 and choice["info"][0].startswith("AR5") and "information only" in choice["info"][0]
    result = _run(choice)
    assert result["gwp_set"] == "AR6" and result["gwp_info"] == choice["info"]
    assert _kc_gas_co2e(result)["CH4"] == pytest.approx(1.755)  # AR6 for the fuels


def test_a_set_limited_to_refrigerants_drives_only_the_refrigerant_gwps() -> None:
    choice = choice_from_records({"gwp": _row("AR5"), "gwp:aa11bb": _row("AR6", "for refrigerants")})
    assert (choice["set"], choice["refrigerant_set"], choice["refrigerant_row"]) == ("AR5", "AR6", "gwp:aa11bb")
    assert choice["label"] == ("AR5 · 100-year (Methodology review) for fuels and electricity; "
                               "AR6 · 100-year (Methodology review, GWP set row 2) for refrigerants")
    result = _run(choice)
    assert result["gwp_set"] == "AR5" and result["gwp_refrigerant_set"] == "AR6"
    assert result["gwp_refrigerant_row"] == "gwp:aa11bb"
    assert _kc_gas_co2e(result)["CH4"] == pytest.approx(1.82)  # AR5 for the fuels
    tagged = {"refrigerant_gwps": {"R-410A": {"value": 2256, "gwp_set": "AR6"}}}
    used = _fridge(choice, **tagged)["categories"]["fugitive_refrigerants"]
    assert used["gwp"]["R-410A"]["value"] == 2256  # AR6 for the HFCs
    assert _fridge(choice)["categories"]["fugitive_refrigerants"] is None  # no AR6 HFC value in the data


def test_two_general_sets_block_but_a_general_and_a_refrigerant_set_do_not() -> None:
    both = choice_from_records({"gwp": _row("AR5", "default"), "gwp:aa11bb": _row("AR6")})
    assert both["supported"] is False and both["message"] == "Two GWP sets confirmed in Methodology review — keep one"
    assert choice_from_records({"gwp": _row("AR5"), "gwp:aa11bb": _row("AR6", "HFCs only")})["supported"]


def test_an_embedded_set_with_an_unsupported_horizon_blocks_nothing() -> None:
    choice = choice_from_records({"gwp": _row("AR5"), "gwp:aa11bb": _row("AR6", "embedded in third-party factors", "500-year")})
    assert choice["supported"] and choice["set"] == "AR5"


@pytest.mark.parametrize("note", ["for fugitive methane", "for all gases except refrigerants",
                                  "default; supplier-specific factors where available",
                                  "for all gases other than HFCs", ""])
def test_these_use_notes_are_general_so_the_set_drives(note: str) -> None:
    from backend.app.services.methodology_gwp import GENERAL, use_of

    assert use_of(note) == GENERAL
    assert choice_from_records({"gwp": _row("AR6", note)})["set"] == "AR6"


@pytest.mark.parametrize("note,kind", [("for refrigerants", "refrigerants"), ("HFCs only", "refrigerants"),
                                       ("for R-410A and R-32", "refrigerants"), ("for HCFC blends", "refrigerants"),
                                       ("for cooling equipment", "refrigerants"),
                                       ("embedded in the third-party emission factors", "embedded"),
                                       ("included in supplier factors", "embedded"),
                                       ("built into purchased factors", "embedded")])
def test_these_use_notes_limit_the_set(note: str, kind: str) -> None:
    from backend.app.services.methodology_gwp import use_of

    assert use_of(note) == kind
