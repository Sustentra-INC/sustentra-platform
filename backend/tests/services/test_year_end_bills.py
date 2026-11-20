"""A bill that crosses the year end (N30, CALC-019): it is filed on its facility's line and only its
in-year days count. The Harbor bill of the STG set was left in Unassigned because the extractor did not
read the site from its "SERVICE FOR" block, so no facility could be matched: placement and proration
were never the problem."""

from __future__ import annotations

from typing import Any

import pytest

from backend.app.services.electricity_extractor import CANONICAL_TYPE_ID, ElectricityExtractor
from backend.app.services.evidence_tree_service import EvidenceTreeService
from backend.app.services.extraction_target_service import ExtractionTargetService
from backend.tests.services.test_calculation_lines import _lines_with_docs
from backend.tests.services.test_engagement_recalculation_service import FakeStore, _own, _service

HARBOR = {"facilityId": "fac-harb", "name": "Harbor Warehouse", "address": "22 Dock Street, Tacoma, WA 98421"}
LINE = "s2:purchased_energy:electricity:fac-harb"
ENGAGEMENT = {"id": "ENG-1", "reporting_period_start": "2025-01-01", "reporting_period_end": "2025-12-31",
              "settings": {"facilities": [HARBOR]}}


def _bill(start: str, end: str, mwh: float = 31.0, name: str | None = None,
          address: str | None = "22 Dock Street, Tacoma, WA 98421") -> dict[str, tuple]:
    record: dict[str, tuple] = {
        "activity_quantity": (mwh, "MWh"), "activity_unit": ("MWh", None), "energy_type": ("electricity", None),
        "service_period_start": (start, None), "service_period_end": (end, None)}
    if name:
        record["facility_name"] = (name, None)
    if address:
        record["service_address"] = (address, None)
    return record


def _filed(records: list[dict[str, tuple]]) -> tuple[dict[str, list[str]], dict]:
    store = FakeStore()
    store.add_document("DEC", "CT-S2-ELEC", records)
    tree = EvidenceTreeService(store, store, store).tree(ENGAGEMENT, _own, None)
    return _lines_with_docs(tree), _service(store).recalculate(ENGAGEMENT, _own)


def _tonnes(result: dict) -> float:
    return result["categories"]["purchased_electricity_location_based"]["total_co2e"]


def test_a_year_end_bill_with_its_address_is_filed_on_its_line_and_counts_its_in_year_days() -> None:
    filed, result = _filed([_bill("2025-12-16", "2026-01-15")])  # 31 days, 16 of them in 2025
    assert filed == {LINE: ["DEC"]}
    _, full = _filed([_bill("2025-12-01", "2025-12-31")])  # the same 31 MWh, all in the year
    assert _tonnes(result) == pytest.approx(_tonnes(full) * 16 / 31)


def test_the_same_bill_with_no_facility_read_is_unplaced_and_not_counted() -> None:
    """The cause of N30: placement needs the facility (name or address); the period is not involved."""

    filed, result = _filed([_bill("2025-12-16", "2026-01-15", address=None)])
    assert filed == {}  # not on any line: it sits in Unassigned supporting evidence
    assert "purchased_electricity_location_based" not in {k for k, v in result["categories"].items() if v}
    # Changed by Claire's ruling (Evidence Screen tab I8): a bill on no line feeds nothing, so it no longer
    # asks for a grid region (before: needs_input == ["grid_region"]); Results lists it instead.
    assert result["needs_input"] == []
    assert [d["document_id"] for d in result["uncounted_values"]["documents"]] == ["DEC"]


def test_a_bill_entirely_in_the_next_year_is_left_out_with_its_reason() -> None:
    filed, result = _filed([_bill("2026-01-02", "2026-01-31")])
    assert filed == {LINE: ["DEC"]}  # still filed on its line
    assert not result["categories"].get("purchased_electricity_location_based")
    assert [e["reason"] for e in result["excluded"]] == ["outside_reporting_period"]


def test_a_bill_that_starts_before_the_year_counts_only_its_2025_days() -> None:
    _, result = _filed([_bill("2024-12-16", "2025-01-15")])  # 31 days, 15 of them in 2025
    _, full = _filed([_bill("2025-12-01", "2025-12-31")])
    assert _tonnes(result) == pytest.approx(_tonnes(full) * 15 / 31)


def test_a_two_meter_year_end_bill_counts_each_meter_by_the_same_in_year_share() -> None:
    filed, result = _filed([_bill("2025-12-16", "2026-01-15", 20.0), _bill("2025-12-16", "2026-01-15", 11.0)])
    _, full = _filed([_bill("2025-12-01", "2025-12-31", 31.0)])
    assert filed == {LINE: ["DEC"]}
    assert _tonnes(result) == pytest.approx(_tonnes(full) * 16 / 31)


def test_a_non_ascii_facility_matched_by_name_is_filed_the_same_way() -> None:
    store = FakeStore()
    store.add_document("DEC", "CT-S2-ELEC", [_bill("2025-12-16", "2026-01-15", name="Müller Käserei – Zürich",
                                                    address=None)])
    engagement = {**ENGAGEMENT, "settings": {"facilities": [
        {"facilityId": "fac-zh", "name": "Müller Käserei – Zürich", "address": "12 Bahnhofstraße, 8001 Zürich"}]}}
    tree = EvidenceTreeService(store, store, store).tree(engagement, _own, None)
    assert _lines_with_docs(tree) == {"s2:purchased_energy:electricity:fac-zh": ["DEC"]}


# --- the bill's "SERVICE FOR" block: the extractor reads the site, never the mailing address ----
def _layout(left_lines: list[str], right_lines: list[str], heading: str = "SERVICE FOR") -> dict[str, Any]:
    blocks: list[tuple[str, float, float]] = [
        ("Saltline Electric Company", 0.157, 0.05), ("YOUR ELECTRIC BILL", 0.065, 0.09), ("Account Number", 0.075, 0.12), ("Bill Date", 0.23, 0.12),
        ("Service Period", 0.345, 0.12), ("7730-115-2048", 0.075, 0.14), ("01/21/2026", 0.23, 0.14),
        ("12/16/2025 to 01/15/2026", 0.345, 0.14), (heading, 0.065, 0.2), ("MAILING ADDRESS", 0.523, 0.2)]
    for i, text in enumerate(left_lines):
        blocks.append((text, 0.065, 0.22 + i * 0.02))
    for i, text in enumerate(right_lines):
        blocks.append((text, 0.523, 0.22 + i * 0.02))
    blocks += [("ELECTRIC USAGE", 0.065, 0.22 + max(len(left_lines), len(right_lines)) * 0.02),
               ("Meter No.", 0.075, 0.5), ("Read Dates", 0.193, 0.5), ("kWh Used", 0.729, 0.5),
               ("Peak kW", 0.857, 0.5), ("SEC-4412907", 0.075, 0.52), ("12/16/2025 - 01/15/2026", 0.193, 0.52),
               ("52,840", 0.759, 0.52), ("163", 0.898, 0.52)]
    return {"document_id": "DOC-1", "pages": [], "tables": [], "key_value_pairs": [], "source_references": [],
            "text_blocks": [{"block_id": f"b{i}", "page_number": 1, "text": text, "confidence": None,
                             "bounding_box": {"left": left, "top": top, "width": 0.2, "height": 0.012},
                             "source_reference_id": None} for i, (text, left, top) in enumerate(blocks)]}


MAILING = ["Staging-Test Foods Inc.", "Attn: Accounts Payable", "PO Box 7718", "Springfield, OR 97477"]


@pytest.fixture(scope="module")
def targets() -> list[dict]:
    return ExtractionTargetService().get_targets_for_canonical_type(CANONICAL_TYPE_ID)


def _read(parser_output: dict, targets: list[dict]) -> dict[str, Any]:
    outcome = ElectricityExtractor().extract(parser_output, targets, "EV-1")
    assert outcome.halt_reason is None, outcome.halt_reason
    return {c["field_name"]: c["normalized_value"] for c in outcome.candidates if c["record_index"] is None}


def test_the_service_for_block_gives_the_site_and_address_and_never_the_mailing_address(targets: list[dict]) -> None:
    read = _read(_layout(["Staging-Test Foods Inc.", "Harbor Warehouse", "22 Dock Street", "Tacoma, WA 98421"],
                         MAILING), targets)
    assert read["facility_name"] == "Harbor Warehouse"
    assert read["service_address"] == "22 Dock Street, Tacoma, WA 98421"


def test_a_service_for_block_with_no_site_name_gives_the_address_only(targets: list[dict]) -> None:
    read = _read(_layout(["Staging-Test Foods Inc.", "22 Dock Street", "Tacoma, WA 98421"], MAILING), targets)
    assert read["facility_name"] is None  # the customer is not a facility
    assert read["service_address"] == "22 Dock Street, Tacoma, WA 98421"


def test_a_non_ascii_service_for_block_is_read_whole(targets: list[dict]) -> None:
    read = _read(_layout(["Müller Käserei AG", "Käserei Zürich Nord", "12 Bahnhofstraße", "8001 Zürich"],
                         ["Müller Käserei AG", "Postfach 77", "3000 Bern"]), targets)
    assert read["facility_name"] == "Käserei Zürich Nord"
    assert read["service_address"] == "12 Bahnhofstraße, 8001 Zürich"


def test_a_block_with_no_street_is_not_guessed_and_a_mailing_block_alone_is_never_the_site(targets: list[dict]) -> None:
    read = _read(_layout(["Staging-Test Foods Inc.", "Harbor Warehouse"], MAILING), targets)
    assert read["service_address"] is None and read["facility_name"] is None
    only_mailing = _read(_layout(["Staging-Test Foods Inc.", "PO Box 7718", "Springfield, OR 97477"], MAILING,
                                 heading="BILL TO"), targets)
    assert only_mailing["service_address"] is None
