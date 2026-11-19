"""Where a bill is placed, over the cases shared with the frontend
(backend/tests/fixtures/facility_placement_cases.json, also read by facilityPlacementCases.test.tsx).

Each case is checked three ways, which must agree: the Evidence tree, the calculation lines and the
recalculation, and the reason a record was not placed."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from backend.app.services import calculation_lines as cl
from backend.tests.services.test_calculation_lines import _lines_with_docs, _tree, _tree_service
from backend.tests.services.test_engagement_recalculation_service import ORG, FakeStore, _own
from backend.tests.services.test_facility_identifiers import _recalc

SHARED = json.loads((Path(__file__).parent.parent / "fixtures" / "facility_placement_cases.json").read_text("utf-8"))
FACILITIES: list[dict[str, Any]] = SHARED["facilities"]
CASES: list[dict[str, Any]] = SHARED["cases"]
FIXED = {"fuel_type": ("natural_gas", None), "activity_quantity": (1000, "MMBtu"), "activity_unit": ("MMBtu", None),
         "service_period_start": ("2025-01-01", None), "service_period_end": ("2025-01-31", None)}


def _store(case: dict[str, Any]) -> FakeStore:
    """One document with the case's records. The quantity is accepted, so the recalculation counts every
    record; only the field under test has the case's status."""

    store = FakeStore()
    items: list[dict[str, Any]] = []
    reviews: list[dict[str, Any]] = []
    multi = len(case["records"]) > 1

    def add(name: str, value: Any, unit: Any, index: int, status: str) -> None:
        candidate_id = f"D1:{index}:{name}"
        flags = ["ai_suggested"] if status in ("ai_only", "accepted") else []
        items.append({"candidate_id": candidate_id, "field_name": name, "normalized_value": value, "unit": unit,
                      "record_index": index if multi else None, "validation_flags": flags,
                      "source_reference": {"document_id": "D1", "page_number": 1}})
        decision = {"accepted": "accepted", "fixed": "accepted", "rejected": "rejected",
                    "needs_more_evidence": "needs_more_evidence"}.get(status)
        if decision:
            reviews.append({"candidate_id": candidate_id, "decision": decision, "org_id": ORG,
                            "reviewed_value": value if decision == "accepted" else None,
                            "reviewed_unit": unit if decision == "accepted" else None})

    for index, record in enumerate(case["records"], start=1):
        for name, (value, unit) in FIXED.items():
            add(name, value, unit, index, "fixed")
        for name, (value, status) in record.items():
            add(name, value, None, index, status)
    store.documents.append({"document_id": "D1", "engagement_id": "ENG-1", "org_id": ORG, "file_name": "D1.pdf"})
    store.results["D1"] = [{"document_id": "D1", "org_id": ORG, "canonical_type_id": "CT-S1-FUELQTY", "items": items}]
    store.reviews["D1"] = reviews
    return store


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_the_tree_the_lines_and_the_recalculation_agree_on_where_a_bill_is_placed(case: dict[str, Any]) -> None:
    store = _store(case)
    loaded = _tree_service(store).load({"id": "ENG-1", "settings": {"facilities": FACILITIES}}, _own)
    records = sorted(loaded.docs[0].records, key=lambda r: r.record_index or 0)
    placed = []
    for record, want_facility, want_note in zip(records, case["expect"]["facility"], case["expect"]["note"],
                                                strict=True):
        found = cl.facility_match(loaded.facilities, {}, "D1", record)
        placed.append(found[0]["facilityId"] if found else None)
        assert placed[-1] == want_facility
        note = cl.unplaced_note(loaded.facilities, {}, "D1", record)
        if want_note is None:
            assert note is None
        else:
            assert note is not None and want_note in note
    keys = {f"s1:stationary:natural-gas:{facility}" for facility in placed if facility}
    tree = _tree(store, facilities=FACILITIES)
    assert set(_lines_with_docs(tree)) == keys
    result = _recalc(store, FACILITIES)
    assert {line["key"] for line in result["calculation_lines"]} == keys
    assert bool(result["calculation_unplaced"]) == (None in placed)
