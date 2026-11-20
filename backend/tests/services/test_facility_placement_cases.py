"""Where a bill is placed, over the cases shared with the frontend
(backend/tests/fixtures/facility_placement_cases.json, also read by facilityPlacementCases.test.ts).

Each case is checked every way the backend places a bill, and the ways must agree: the Evidence tree (its
lines, and the document row's note), the calculation lines and the recalculation (and the reason it gives for
a record it cannot place)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from backend.app.services import calculation_lines as cl
from backend.tests.services.test_calculation_lines import _engagement, _lines_with_docs, _tree_service
from backend.tests.services.test_engagement_recalculation_service import ORG, FakeStore, _own
from backend.tests.services.test_facility_identifiers import _recalc

SHARED = json.loads((Path(__file__).parent.parent / "fixtures" / "facility_placement_cases.json").read_text("utf-8"))
DEFAULT_COMPANY: str = SHARED["company"]
FACILITIES: list[dict[str, Any]] = SHARED["facilities"]
CASES: list[dict[str, Any]] = SHARED["cases"]
FIXED = {
    "gas": ("CT-S1-FUELQTY", {"fuel_type": ("natural_gas", None), "activity_quantity": (1000, "MMBtu"),
                              "activity_unit": ("MMBtu", None), "service_period_start": ("2025-01-01", None),
                              "service_period_end": ("2025-01-31", None)}, "s1:stationary:natural-gas:"),
    "electricity": ("CT-S2-ELEC", {"energy_type": ("electricity", None), "activity_quantity": (1, "MWh"),
                                   "activity_unit": ("MWh", None), "service_period_start": ("2025-01-01", None),
                                   "service_period_end": ("2025-01-31", None)}, "s2:purchased_energy:electricity:"),
}


def _readings(value: Any) -> list[tuple[str, str]]:
    """A field is [value, status] or a list of those (several readings, in the order read)."""

    return [tuple(r) for r in value] if isinstance(value[0], list) else [tuple(value)]  # type: ignore[misc]


def _store(case: dict[str, Any]) -> FakeStore:
    """One document with the case's records. The quantity is accepted, so the recalculation counts every
    record; only the fields under test have the case's statuses."""

    canonical, fixed, _ = FIXED[case.get("type", "gas")]
    store = FakeStore()
    items: list[dict[str, Any]] = []
    reviews: list[dict[str, Any]] = []
    multi = len(case["records"]) > 1
    indexes = case.get("record_indexes") or list(range(1, len(case["records"]) + 1))

    def add(name: str, value: Any, unit: Any, index: int, status: str, reading: int = 0) -> None:
        candidate_id = f"D1:{index}:{name}:{reading}"
        flags = ["ai_suggested"] if status in ("ai_only", "accepted") else []
        items.append({"candidate_id": candidate_id, "field_name": name, "normalized_value": value, "unit": unit,
                      "record_index": index if multi else None, "validation_flags": flags,
                      "source_reference": {"document_id": "D1", "page_number": 1}})
        decision = {"accepted": "accepted", "fixed": "accepted", "rejected": "rejected",
                    "needs_more_evidence": "needs_more_evidence"}.get(status)
        if decision:
            snapshot = {k: v for k, v in items[-1].items() if k not in ("record_index", "validation_flags")}
            reviews.append({"candidate_id": candidate_id, "decision": decision, "org_id": ORG,
                            "document_id": "D1", "field_name": name, "candidate_snapshot": snapshot,
                            "reviewed_value": value if decision == "accepted" else None,
                            "reviewed_unit": unit if decision == "accepted" else None})

    for index, record in zip(indexes, case["records"], strict=True):
        for name, (value, unit) in fixed.items():
            add(name, value, unit, index, "fixed")
        for name, raw in record.items():
            for reading, (value, status) in enumerate(_readings(raw)):
                add(name, value, None, index, status, reading)
    store.documents.append({"document_id": "D1", "engagement_id": "ENG-1", "org_id": ORG, "file_name": "D1.pdf"})
    store.results["D1"] = [{"document_id": "D1", "org_id": ORG, "canonical_type_id": canonical, "items": items,
                            **({"facility_suggestion": case["suggestion"]} if case.get("suggestion") else {})}]
    store.reviews["D1"] = reviews
    return store


def _rows(tree: dict) -> list[dict]:
    rows: list[dict] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            if node.get("document_id") == "D1" and "facility_id" in node:
                rows.append(node)
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(tree)
    return rows


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_the_tree_the_lines_and_the_recalculation_agree_on_where_a_bill_is_placed(case: dict[str, Any]) -> None:
    company = case["company"] if "company" in case else DEFAULT_COMPANY
    decisions = {"D1": case["decision"]} if case.get("decision") else {}
    store = _store(case)
    engagement = {**_engagement(facilities=FACILITIES), "client_name": company}
    loaded = _tree_service(store).load(engagement, _own, decisions)
    indexes = case.get("record_indexes") or list(range(1, len(case["records"]) + 1))
    expected = {i if len(indexes) > 1 else None: (f, n) for i, f, n in
                zip(indexes, case["expect"]["facility"], case["expect"]["note"], strict=True)}
    placed: list[str | None] = []
    for record in loaded.docs[0].records:  # looked up by record_index, never by position
        want_facility, want_note = expected[record.record_index]
        found = cl.facility_match(loaded.facilities, decisions, "D1", record, company)
        placed.append(found[0]["facilityId"] if found else None)
        assert placed[-1] == want_facility
        note = cl.unplaced_note(loaded.facilities, decisions, "D1", record, company)
        if want_note is None:
            assert note is None
        else:
            assert note is not None and want_note in note
    prefix = FIXED[case.get("type", "gas")][2]
    keys = {f"{prefix}{facility}" for facility in placed if facility}
    tree = _tree_service(store).tree(engagement, _own, decisions)
    assert set(_lines_with_docs(tree)) == keys
    # the document row in the Evidence tree carries the same note (a bill with one record)
    if len(case["records"]) == 1:
        want_note = case["expect"]["note"][0]
        rows = _rows(tree)
        assert rows
        for row in rows:
            if placed[0] is not None or want_note is None:
                assert row.get("facility_note") is None
            else:
                assert want_note in (row.get("facility_note") or "")
        # Claude's suggestion: shown on the row only while the bill awaits a decision (a suggestion, not a placement)
        suggested = [(row.get("facility_suggestion") or {}).get("facility_id") for row in rows]
        assert suggested and set(suggested) == {case["expect"].get("suggestion")}
        for row in rows:
            if case["expect"].get("suggestion"):
                assert row["facility_suggestion"]["quote"] == case["suggestion"]["quote"]
                assert row["facility_suggestion"]["label"] == "Suggested by Sustentra's AI"
                assert row["facility_id"] is None  # still unplaced until the reviewer decides
    result = _recalc(store, FACILITIES, company, decisions)
    assert {line["key"] for line in result["calculation_lines"]} == keys
    # Changed by Claire's ruling (Evidence Screen tab I8): a record placed on no facility is not counted and
    # is not reported under ``calculation_unplaced`` any more (before, a gas bill was, with a reason such as
    # ``expect.reason``); Results lists its document among the values left out. The tree row's note says why.
    assert result["calculation_unplaced"] == []
    left_out = [d["document_id"] for d in result["uncounted_values"]["documents"]]
    assert left_out == (["D1"] if None in placed else [])
