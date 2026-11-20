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


def test_a_caller_with_no_methodology_choice_keeps_the_settings_value() -> None:
    assert _run(gwp_set="AR4")["gwp_set"] == "AR4"
    assert _run()["gwp_label"] == DEFAULT_LABEL


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
