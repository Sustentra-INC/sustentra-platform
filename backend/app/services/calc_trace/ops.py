"""The deterministic evaluator behind a trace: ``Operation.terms`` -> a value and a unit.

A unit is a product of symbols over a product of symbols: ``"kg/MMBtu"``, ``"t CO2e/t"``, ``"gal"``.
Multiplying and dividing combines them and cancels like symbols (``gal x kg/gal x t/kg`` is ``t``); adding or
subtracting needs the same unit. No operand is ever converted silently: a mismatch raises ``TraceUnitError``.
"""

from __future__ import annotations

import math
from collections import Counter

from backend.app.services.calc_trace.model import Operand, Operation, Term


class TraceError(ValueError):
    """The trace's own arithmetic cannot be done as written."""


class TraceUnitError(TraceError):
    """Two units that do not match were added, subtracted, compared or declared as a result."""


class TraceDivisionError(TraceError):
    """A division by zero."""


REL_TOL = 1e-9


def parse_unit(unit: str | None) -> Counter[str]:
    """``"kg/MMBtu"`` -> {kg: 1, MMBtu: -1}. ``None`` or ``""`` is dimensionless. ``a·b`` multiplies symbols."""

    dims: Counter[str] = Counter()
    if not unit or not unit.strip():
        return dims
    top, *bottom = unit.split("/")
    for part, sign in [(top, 1), *[(b, -1) for b in bottom]]:
        for symbol in part.split("·"):
            if symbol.strip():
                dims[symbol.strip()] += sign
    return Counter({k: v for k, v in dims.items() if v != 0})


def format_unit(dims: Counter[str]) -> str | None:
    top = [s if n == 1 else "·".join([s] * n) for s, n in sorted(dims.items()) if n > 0]
    bottom = [s if n == -1 else "·".join([s] * -n) for s, n in sorted(dims.items()) if n < 0]
    if not top and not bottom:
        return None
    text = "·".join(top) if top else "1"
    for b in bottom:
        text += f"/{b}"
    return text


def same_unit(a: str | None, b: str | None) -> bool:
    return parse_unit(a) == parse_unit(b)


def _number(operand: Operand) -> float:
    value = operand.value
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TraceError(f"operand {operand.column!r} is not a number: {value!r}")
    return float(value)


def evaluate(terms: list[Term]) -> tuple[float, str | None]:
    """Left to right. The first term has no operator; every later one has ×, ÷, + or −."""

    if not terms or terms[0].op is not None or any(t.op is None for t in terms[1:]):
        raise TraceError("the first term has no operator and every other term has one")
    total = _number(terms[0].operand)
    dims = parse_unit(terms[0].operand.unit)
    for term in terms[1:]:
        value, unit = _number(term.operand), parse_unit(term.operand.unit)
        if term.op == "×":
            total *= value
            dims = _combine(dims, unit, 1)
        elif term.op == "÷":
            if value == 0:
                raise TraceDivisionError(f"division by zero at {term.operand.column!r}")
            total /= value
            dims = _combine(dims, unit, -1)
        elif term.op in ("+", "−"):
            if dims != unit:
                raise TraceUnitError(
                    f"cannot {'add' if term.op == '+' else 'subtract'} {format_unit(unit)!r} "
                    f"{'to' if term.op == '+' else 'from'} {format_unit(dims)!r}")
            total = total + value if term.op == "+" else total - value
        else:
            raise TraceError(f"unknown operator {term.op!r}")
    return total, format_unit(dims)


def _combine(a: Counter[str], b: Counter[str], sign: int) -> Counter[str]:
    out: Counter[str] = Counter(a)
    for symbol, n in b.items():
        out[symbol] += sign * n
    return Counter({k: v for k, v in out.items() if v != 0})


def make_operation(terms: list[Term], column: str, unit: str | None, *, input_id: str | None = None) -> Operation:
    """An Operation whose result is *computed* from ``terms``. ``unit`` is the unit the result is declared in:
    the computed unit must equal it, or this raises."""

    value, computed = evaluate(terms)
    if not same_unit(computed, unit):
        raise TraceUnitError(f"{column!r} computes to {computed!r}, not {unit!r}")
    return Operation(terms, Operand(column=column, value=value, unit=unit, input_id=input_id))


def verify(operation: Operation, expected: float, *, rel_tol: float = REL_TOL) -> None:
    """Re-evaluate ``operation`` and check it against ``expected`` (what the calculator produced) to ``rel_tol``."""

    value, unit = evaluate(operation.terms)
    if not same_unit(unit, operation.result.unit):
        raise TraceUnitError(f"{operation.result.column!r} computes to {unit!r}, not {operation.result.unit!r}")
    if not math.isclose(value, expected, rel_tol=rel_tol, abs_tol=1e-12):
        raise TraceError(f"{operation.result.column!r}: trace {value!r} differs from the calculator's {expected!r}")


def difference(recomputed: float | None, company: float | None, recomputed_unit: str | None,
               company_unit: str | None) -> float | None:
    """``recomputed − company``. ``None`` when either side is missing. Raises when the units differ: a
    caller that may hold different units (therms against MMBtu) must convert first or not ask."""

    if recomputed is None or company is None:
        return None
    if not same_unit(recomputed_unit, company_unit):
        raise TraceUnitError(f"cannot compare {recomputed_unit!r} with {company_unit!r}")
    return recomputed - company


def differs(diff: float | None, recomputed: float | None) -> bool | None:
    """True when a numeric difference is beyond float noise (1e-9 relative to the recomputed value)."""

    if diff is None:
        return None
    return not math.isclose(diff, 0.0, rel_tol=0.0, abs_tol=REL_TOL * max(abs(recomputed or 0.0), 1e-3))
