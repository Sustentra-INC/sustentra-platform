"""Wall-clock budgets for the parser tests that guard against a hang.

These tests exist to catch a blow-up (quadratic or worse work on hostile input: the cases they
guard took 50 s or more), not a slow machine. Each bound is written as the time the run takes
unloaded, plus headroom, and ``budget(seconds)`` scales it by ``TIME_SCALE``: 10 normally (a loaded
laptop or CI runner running other suites in parallel is routinely 3-5x slower), 20 while coverage
is measuring this run (its tracer slows Python 3-6x on top). A real regression is still caught,
because it overshoots the scaled bound by a wide margin. ``TEST_TIME_SCALE`` (a positive number)
overrides it, for example ``TEST_TIME_SCALE=40`` on a very slow machine.
"""

from __future__ import annotations

import math
import os
import sys

BASE_TIME_SCALE = 10.0
COVERAGE_TIME_SCALE = 20.0


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
    return COVERAGE_TIME_SCALE if _coverage_is_measuring() else BASE_TIME_SCALE


TIME_SCALE = _time_scale()


def budget(seconds: float) -> float:
        return seconds * TIME_SCALE
