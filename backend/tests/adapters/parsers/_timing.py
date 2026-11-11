"""Wall-clock budgets for the parser tests that guard against a hang.

Coverage's tracer slows Python roughly 3-6x, so a bound that holds locally fails on the CI runner
(``pytest --cov``). ``budget(seconds)`` returns the bound scaled by ``TIME_SCALE``: 6 while coverage
is measuring this run, 1 otherwise. ``TEST_TIME_SCALE`` (a positive number) overrides it, for
example ``TEST_TIME_SCALE=10`` on a slow machine.
"""

from __future__ import annotations

import math
import os
import sys

COVERAGE_TIME_SCALE = 6.0


def _coverage_is_measuring() -> bool:
    # pytest-cov imports coverage whenever it is installed, and since 7.x it no longer sets
    # COV_CORE_SOURCE, so neither tells a plain run from a --cov run: ask for the active measurement.
    coverage = sys.modules.get("coverage")
    return coverage is not None and coverage.Coverage.current() is not None


def _time_scale() -> float:
    override = os.environ.get("TEST_TIME_SCALE", "").strip()
    if override:
        try:
            scale = float(override)
        except ValueError:
            scale = 0.0
        if not (scale > 0 and math.isfinite(scale)):
            raise ValueError(f"TEST_TIME_SCALE must be a positive number, got {override!r}")
        return scale
    return COVERAGE_TIME_SCALE if _coverage_is_measuring() else 1.0


TIME_SCALE = _time_scale()


def budget(seconds: float) -> float:
    # Bounds guard hangs that ran many times over them; a regression slows by the same factor, so it is still caught.
    return seconds * TIME_SCALE
