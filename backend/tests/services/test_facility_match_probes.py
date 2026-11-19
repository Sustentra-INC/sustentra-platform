"""The name and address step returns match, ambiguous or none: probes shared with the frontend
(backend/tests/fixtures/facility_match_probes.json, also read by facilityMatchProbes.test.ts), so the screen
and the backend always agree where a bill is not placed."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from backend.app.services.reviewed_evidence import match_facility, match_facility_state

SHARED = json.loads((Path(__file__).parent.parent / "fixtures" / "facility_match_probes.json").read_text("utf-8"))
PROBES: list[dict[str, Any]] = SHARED["probes"]


@pytest.mark.parametrize("probe", PROBES, ids=[f"{p['name']}|{p['address']}|{p['company']}" for p in PROBES])
def test_the_probe_is_a_match_ambiguous_or_none(probe: dict[str, Any]) -> None:
    facilities = probe.get("facilities") or SHARED["facilities"]
    found, ambiguous = match_facility_state(probe["name"], probe["address"], facilities, probe["company"])
    expect = probe["expect"]
    if expect == "ambiguous":
        assert found is None and ambiguous
    elif expect is None:
        assert found is None and not ambiguous
    else:
        assert found is not None and found["facilityId"] == expect and not ambiguous
    assert match_facility(probe["name"], probe["address"], facilities, probe["company"]) is found
