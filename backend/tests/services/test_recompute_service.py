from backend.app.services.recompute_service import RecomputeService


def test_stationary_fuel_recompute_matched() -> None:
    result = RecomputeService().recompute_stationary_fuel_emissions(
        fuel_quantity=_value("mv-qty", 100, "MMBtu"),
        emission_factor=_value("mv-ef", 0.05, "tCO2e/MMBtu"),
        reported_emissions=_value("mv-reported", 5, "tCO2e"),
    )

    assert result["status"] == "matched"
    assert result["computed_value"] == 5
    assert result["delta"] == 0
    assert result["input_methodology_value_ids"] == ["mv-qty", "mv-ef", "mv-reported"]


def test_stationary_fuel_recompute_mismatch_reports_delta() -> None:
    result = RecomputeService().recompute_stationary_fuel_emissions(
        fuel_quantity=_value("mv-qty", "100", "MMBtu"),
        emission_factor=_value("mv-ef", "0.05", "tCO2e/MMBtu"),
        reported_emissions=_value("mv-reported", 6, "tCO2e"),
    )

    assert result["status"] == "mismatch"
    assert result["computed_value"] == 5
    assert result["reported_value"] == 6
    assert result["delta"] == 1


def test_stationary_fuel_recompute_missing_input() -> None:
    result = RecomputeService().recompute_stationary_fuel_emissions(
        fuel_quantity=None,
        emission_factor=_value("mv-ef", 0.05, "tCO2e/MMBtu"),
        reported_emissions=_value("mv-reported", 5, "tCO2e"),
    )

    assert result["status"] == "missing_input"
    assert "fuel_quantity" in (result["reason"] or "")


def test_stationary_fuel_recompute_nonnumeric_input_is_unsupported() -> None:
    result = RecomputeService().recompute_stationary_fuel_emissions(
        fuel_quantity=_value("mv-qty", "many", "MMBtu"),
        emission_factor=_value("mv-ef", 0.05, "tCO2e/MMBtu"),
        reported_emissions=_value("mv-reported", 5, "tCO2e"),
    )

    assert result["status"] == "unsupported"


def _value(methodology_value_id: str, value: object, unit: str) -> dict:
    return {
        "methodology_value_id": methodology_value_id,
        "methodology_field_id": "S1-STC-010",
        "data_schema_field": "quantity_combusted",
        "approved_value": value,
        "approved_unit": unit,
    }
