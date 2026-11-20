"""The trace evaluator and model: exact arithmetic, unit rules, and the schema."""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from backend.app.services.calc_trace import BUILDERS, PANELS, build_trace, ops
from backend.app.services.calc_trace.model import (
    Choice, ChoiceOption, LineTrace, Operand, Side, SourceRef, Term, TraceInput, TraceResult,
)

SCHEMA = json.loads((Path(__file__).parents[4] / "contracts" / "calculation_trace.schema.json").read_text())


def _t(value: float, unit: str | None, op: str | None = None, column: str = "x") -> Term:
    return Term(op, Operand(column, value, unit))


def test_propane_chain_is_exact() -> None:
    """Claire's propane panel: 2,350 gal x 5.72 kg/gal x 0.001 t/kg = 13.442 t, then x GWP 1 = 13.442 t CO2e."""

    mass = ops.make_operation([_t(2350, "gal"), _t(5.72, "kg/gal", "×"), _t(0.001, "t/kg", "×")], "mass", "t")
    assert mass.result.value == pytest.approx(13.442, abs=1e-12)
    co2e = ops.make_operation([_t(mass.result.value, "t"), _t(1, "t CO2e/t", "×")], "co2e", "t CO2e")  # type: ignore[arg-type]
    assert co2e.result.value == pytest.approx(13.442, abs=1e-12)
    assert co2e.result.unit == "t CO2e"


def test_difference_is_recomputed_minus_company() -> None:
    assert ops.difference(0.0236455, 0.02527, "t", "t") == pytest.approx(-0.0016245, abs=1e-12)
    assert ops.difference(None, 1.0, "t", "t") is None and ops.difference(1.0, None, "t", "t") is None


def test_mixed_units_raise() -> None:
    with pytest.raises(ops.TraceUnitError):
        ops.evaluate([_t(1, "gal"), _t(1, "MMBtu", "+")])
    with pytest.raises(ops.TraceUnitError):
        ops.difference(1.0, 2.0, "t", "kg")
    with pytest.raises(ops.TraceUnitError):  # computes to kg, declared t
        ops.make_operation([_t(1, "gal"), _t(2, "kg/gal", "×")], "mass", "t")


def test_division_by_zero_raises() -> None:
    with pytest.raises(ops.TraceDivisionError):
        ops.evaluate([_t(1, "t"), _t(0, "gal", "÷")])


def test_operators_and_units() -> None:
    value, unit = ops.evaluate([_t(10, "t"), _t(4, "t", "−"), _t(2, "t", "+")])
    assert (value, unit) == (8, "t")
    value, unit = ops.evaluate([_t(6, "kg"), _t(3, "gal", "÷")])
    assert (value, unit) == (2, "kg/gal")
    assert ops.parse_unit("t CO2e/t") == ops.parse_unit("t CO2e/t") and ops.same_unit(None, "")
    with pytest.raises(ops.TraceError):
        ops.evaluate([_t(1, "t", "×")])  # the first term has no operator
    with pytest.raises(ops.TraceError):
        ops.evaluate([Term(None, Operand("x", "text", None))])


def test_verify_checks_against_the_calculator() -> None:
    op = ops.make_operation([_t(2, "t"), _t(3, None, "×")], "m", "t")
    ops.verify(op, 6.0)
    with pytest.raises(ops.TraceError):
        ops.verify(op, 6.0001)


def test_differs_ignores_float_noise() -> None:
    assert ops.differs(1e-15, 100.0) is False and ops.differs(0.5, 100.0) is True and ops.differs(None, 1.0) is None


def test_a_trace_serialises_and_validates_against_the_schema() -> None:
    trace = LineTrace(
        line_key="s1:stationary:natural-gas:fac-kc01", panel="stationary", state="complete",
        result=TraceResult("t CO2e", None, 1.0, None),
        choices=[Choice("method", "Method", [ChoiceOption("a", "A")], chosen="a")],
        inputs={"x": TraceInput("x", "X", "reference", recomputed=Side(
            1.0, "t", "reference", SourceRef("reference", dataset="EPA Hub", table="Table 1", row=3, edition="2025",
                                              citation="EPA Hub, Table 1, row 3")))})
    plain = trace.to_dict()
    jsonschema.validate(plain, SCHEMA)
    assert plain["inputs"]["x"]["recomputed"]["source"]["table"] == "Table 1"
    assert "page" not in plain["inputs"]["x"]["recomputed"]["source"]  # unused SourceRef fields are left out
    json.dumps(plain)
    bad = {**plain, "panel": "nonsense"}
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(bad, SCHEMA)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({**plain, "extra": 1}, SCHEMA)


def test_registry_has_a_builder_for_every_panel_and_only_three_build_today() -> None:
    assert tuple(BUILDERS) == PANELS
    assert [p for p in PANELS if p not in ("stationary", "mobile", "electricity")] == [
        "fugitive", "purchased_gases", "steam", "heat", "cooling"]
    for panel in ("fugitive", "purchased_gases", "steam", "heat", "cooling", "no-such-panel"):
        assert build_trace(panel, {"key": "k"}) is None


def test_a_failing_builder_returns_none_and_never_raises() -> None:
    assert build_trace("stationary", {"key": "k"}) is None  # a line with no steps is not traceable
