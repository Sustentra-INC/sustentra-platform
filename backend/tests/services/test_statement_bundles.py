"""A file that holds several statements gives one record per statement (EXT-015, N28).

The STG utility bundle is 12 monthly electric statements of two pages each, behind a contents page and
ahead of the terms. It used to read as one record (the first statement's, with its on-peak and off-peak
lines as two more); each month now has its own record, with its own period, quantity and pages. The
bundles here are synthetic and laid out with geometry, like a text PDF.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from backend.app.services.document_chunk_service import merge_chunk_outputs
from backend.app.services.electricity_extractor import ElectricityExtractor
from backend.app.services.extraction_target_service import ExtractionTargetService
from backend.app.services.statement_segments import split_statements
from backend.app.services.thermal_extractor import ThermalExtractor

PERIODS = [(f"{m:02d}/16/2024" if m == 12 else f"{m:02d}/16/2025", "") for m in range(1, 13)]
# (start, end, total kWh, on-peak kWh) for twelve billing months, 16th to 15th
MONTHS = [
    ("12/16/2024", "01/15/2025", 143230, 58920), ("01/16/2025", "02/15/2025", 135630, 55410),
    ("02/16/2025", "03/15/2025", 148560, 61240), ("03/16/2025", "04/15/2025", 154030, 63880),
    ("04/16/2025", "05/15/2025", 160130, 66100), ("05/16/2025", "06/15/2025", 166830, 69400),
    ("06/16/2025", "07/15/2025", 162480, 68110), ("07/16/2025", "08/15/2025", 168520, 70200),
    ("08/16/2025", "09/15/2025", 157200, 65300), ("09/16/2025", "10/15/2025", 150700, 62500),
    ("10/16/2025", "11/15/2025", 145700, 60400), ("11/16/2025", "12/15/2025", 146590, 60480),
]


@pytest.fixture(scope="module")
def targets() -> list[dict]:
    return ExtractionTargetService().get_targets_for_canonical_type("CT-S2-ELEC")


Line = list[tuple[str, float]]  # (text, left) cells of one visual row


def _page(page: int, lines: list[Line], top: float = 0.05) -> list[dict[str, Any]]:
    blocks = []
    for n, cells in enumerate(lines):
        for m, (text, left) in enumerate(cells):
            blocks.append({"block_id": f"p{page}-{n}-{m}", "page_number": page, "text": text, "confidence": None,
                           "bounding_box": {"left": left, "top": top + n * 0.03, "width": 0.1, "height": 0.012},
                           "source_reference_id": None})
    return blocks


def _summary(page: int, start: str, end: str, account: str = "4471-20983-6", address: str = "410 Mill Road, Springfield, OR 97477",
             supplier: str = "Willowmere Electric Cooperative") -> list[dict[str, Any]]:
    return _page(page, [
        [(supplier, 0.15)], [("Electric Service Statement", 0.15)],
        [("Account Number:", 0.07), (account, 0.3)], [("Service Address:", 0.07), (address, 0.3)],
        [("Billing Period:", 0.07), (f"{start} - {end} (31 days)", 0.3)],
        [("Total Amount Due", 0.07), ("$16,387.72", 0.5)],
    ])


def _detail(page: int, start: str, end: str, total: int, on_peak: int, meter: str = "WEC-88213457",
            supplier: str = "Willowmere Electric Cooperative") -> list[dict[str, Any]]:
    return _page(page, [
        [(supplier, 0.07)], [("Meter and Usage Detail", 0.07)],
        [("Billing Period:", 0.07), (f"{start} - {end}", 0.3)],
        [("Meter", 0.075), ("Register", 0.2), ("Previous Read", 0.35), ("Current Read", 0.5), ("Difference", 0.65),
         ("Usage", 0.8)],
        [(meter, 0.075), ("Total kWh", 0.2), ("1,005,700", 0.35), ("1,148,930", 0.5), (f"{total:,}", 0.65),
         (f"{total:,} kWh", 0.8)],
        [("On-Peak kWh", 0.075), (f"{on_peak:,} kWh", 0.8)],
        [("Off-Peak kWh", 0.075), (f"{total - on_peak:,} kWh", 0.8)],
        [("Max Demand (kW)", 0.075), ("398 kW", 0.8)],
    ])


def _output(blocks: list[dict[str, Any]]) -> dict[str, Any]:
    return {"document_id": "DOC-1", "pages": [], "text_blocks": blocks, "tables": [], "key_value_pairs": [],
            "source_references": []}


def _bundle(months: list[tuple[str, str, int, int]] = MONTHS, **summary: str) -> list[dict[str, Any]]:
    supplier = summary.get("supplier", "Willowmere Electric Cooperative")
    blocks = _page(1, [[(supplier, 0.15)], [("Annual Statement Package", 0.15)],
                       [("Contents", 0.07)], [("Section", 0.07), ("Billing Period", 0.3), ("Pages", 0.6)]]
                   + [[(f"Statement {n + 1}", 0.07), (f"{s} - {e}", 0.3), (f"{2 * n + 2}-{2 * n + 3}", 0.6)]
                      for n, (s, e, _, _) in enumerate(months)])
    for n, (start, end, total, on_peak) in enumerate(months):
        blocks += _summary(2 * n + 2, start, end, **summary) + _detail(2 * n + 3, start, end, total, on_peak, supplier=supplier)
    last = 2 * len(months) + 2
    return blocks + _page(last, [[("Terms and Conditions of Electric Service", 0.07)],
                                 [("Charges are billed on 1,000 kWh blocks.", 0.07)]])


def _read(blocks: list[dict[str, Any]], targets: list[dict]) -> list[dict[str, Any]]:
    """One dict of field -> candidate per record, in record order."""

    outcome = ElectricityExtractor().extract(_output(blocks), targets, "EV-1")
    assert outcome.halt_reason is None, outcome.halt_reason
    records: dict[Any, dict[str, Any]] = {}
    for candidate in outcome.candidates:
        records.setdefault(candidate["record_index"], {})[candidate["field_name"]] = candidate
    return [records[key] for key in sorted(records, key=lambda k: (k is None, k))]


def _mwh(record: dict[str, Any]) -> float:
    return float(record["activity_quantity"]["normalized_value"])


def test_a_twelve_statement_bundle_gives_one_record_per_month(targets: list[dict]) -> None:
    records = _read(_bundle(), targets)
    assert len(records) == 12
    assert [(r["service_period_start"]["normalized_value"], r["service_period_end"]["normalized_value"])
            for r in records] == [
        ("2024-12-16", "2025-01-15"), ("2025-01-16", "2025-02-15"), ("2025-02-16", "2025-03-15"),
        ("2025-03-16", "2025-04-15"), ("2025-04-16", "2025-05-15"), ("2025-05-16", "2025-06-15"),
        ("2025-06-16", "2025-07-15"), ("2025-07-16", "2025-08-15"), ("2025-08-16", "2025-09-15"),
        ("2025-09-16", "2025-10-15"), ("2025-10-16", "2025-11-15"), ("2025-11-16", "2025-12-15")]
    # each month's own total, in MWh; the on-peak and off-peak lines are parts of it, not records
    assert [_mwh(r) for r in records] == pytest.approx([m[2] / 1000 for m in MONTHS])
    assert {r["account_number"]["normalized_value"] for r in records} == {"4471-20983-6"}
    assert {r["supplier_name"]["normalized_value"] for r in records} == {"Willowmere Electric Cooperative"}


def test_each_record_points_at_its_own_pages_and_has_its_own_key(targets: list[dict]) -> None:
    outcome = ElectricityExtractor().extract(_output(_bundle()), targets, "EV-1")
    assert outcome.records == 12
    by_record: dict[int, set] = {}
    keys: dict[int, str] = {}
    for candidate in outcome.candidates:
        if candidate["field_name"] == "activity_quantity":
            by_record[candidate["record_index"]] = candidate["source_reference"]["page_number"]
            keys[candidate["record_index"]] = candidate["source_reference"]["record_key"]
    assert by_record == {n: 2 * n + 1 for n in range(1, 13)}  # the quantity is on each statement's detail page
    assert len(set(keys.values())) == 12  # r1..r12, each with its period
    assert keys[3].startswith("r3:") and "2025-02-16..2025-03-15" in keys[3]


def test_a_statement_that_crosses_a_chunk_boundary_is_one_record(targets: list[dict]) -> None:
    """Large PDFs are read in page chunks and merged before extraction: statements 5 (pages 10-11) and 6
    straddle the boundaries of ten-page chunks."""

    blocks = _bundle()
    chunks = []
    for index, (first, last) in enumerate(((1, 10), (11, 20), (21, 26))):
        part = [b for b in blocks if first <= b["page_number"] <= last]
        chunks.append(SimpleNamespace(page_from=first, page_to=last, chunk_index=index, status="completed",
                                      parser_output={**_output(part), "status": "parsed"}))
    merged, unread = merge_chunk_outputs(chunks, "DOC-1", "RUN-1")  # type: ignore[arg-type]
    assert unread == []
    records = _read(merged["text_blocks"], targets)
    assert len(records) == 12
    assert _mwh(records[4]) == pytest.approx(160.13)  # May: its summary on page 10, its detail on page 11


def test_two_statements_on_one_page_are_two_records(targets: list[dict]) -> None:
    """Two short statements stacked on one page: the second starts at its own title line."""

    def statement(top: float, start: str, end: str, total: int) -> list[dict[str, Any]]:
        lines: list[Line] = [
            [("Electric Service Statement", 0.15)], [("Account Number:", 0.07), ("4471-20983-6", 0.3)],
            [("Service Address:", 0.07), ("410 Mill Road, Springfield, OR 97477", 0.3)],
            [("Billing Period:", 0.07), (f"{start} - {end}", 0.3)],
            [("Meter", 0.075), ("Register", 0.2), ("Previous Read", 0.35), ("Current Read", 0.5), ("Difference", 0.65),
             ("Usage", 0.8)],
            [("WEC-88213457", 0.075), ("Total kWh", 0.2), ("1", 0.35), ("2", 0.5), (f"{total:,}", 0.65),
             (f"{total:,} kWh", 0.8)]]
        return _page(1, lines, top=top)

    blocks = (_page(1, [[("Willowmere Electric Cooperative", 0.15)]], top=0.01)
              + statement(0.05, "01/16/2025", "02/15/2025", 135630)
              + statement(0.45, "02/16/2025", "03/15/2025", 148560))
    records = _read(blocks, targets)
    assert [_mwh(r) for r in records] == pytest.approx([135.63, 148.56])
    assert [r["service_period_start"]["normalized_value"] for r in records] == ["2025-01-16", "2025-02-16"]


def test_a_two_page_statement_and_a_single_statement_are_one_record_each(targets: list[dict]) -> None:
    [only] = _read(_summary(1, "01/16/2025", "02/15/2025") + _detail(2, "01/16/2025", "02/15/2025", 135630, 55410),
                   targets)
    assert _mwh(only) == pytest.approx(135.63)


def test_a_single_time_of_use_bill_is_read_as_its_total_only(targets: list[dict]) -> None:
    """On-peak and off-peak lines are parts of the total; counted as records they tripled the bill."""

    records = _read(_summary(1, "02/16/2025", "03/15/2025") + _detail(2, "02/16/2025", "03/15/2025", 148560, 61240),
                    targets)
    assert [_mwh(r) for r in records] == pytest.approx([148.56])


def test_time_of_use_lines_without_a_total_are_kept(targets: list[dict]) -> None:
    blocks = _page(1, [
        [("Willowmere Electric Cooperative", 0.15)], [("Electric Service Statement", 0.15)],
        [("Billing Period:", 0.07), ("02/16/2025 - 03/15/2025", 0.3)],
        [("Meter", 0.075), ("Register", 0.2), ("Previous Read", 0.35), ("Current Read", 0.5), ("Difference", 0.65),
         ("Usage", 0.8)],
        [("On-Peak kWh", 0.075), ("61,240 kWh", 0.8)], [("Off-Peak kWh", 0.075), ("87,320 kWh", 0.8)]])
    assert [_mwh(r) for r in _read(blocks, targets)] == pytest.approx([61.24, 87.32])


def test_a_non_ascii_bundle_is_split_and_read_whole(targets: list[dict]) -> None:
    months = MONTHS[:3]
    blocks = _bundle(months, supplier="Müller Elektrizität Zürich Utility Co.",
                     address="12 Bahnhofstraße, 8001 Zürich", account="ZH-00417")
    records = _read(blocks, targets)
    assert len(records) == 3
    assert {r["supplier_name"]["normalized_value"] for r in records} == {"Müller Elektrizität Zürich Utility Co."}
    assert {r["service_address"]["normalized_value"] for r in records} == {"12 Bahnhofstraße, 8001 Zürich"}


def test_a_bill_with_one_period_is_never_split(targets: list[dict]) -> None:
    rows = ElectricityExtractor()._rows(_output(_summary(1, "01/16/2025", "02/15/2025")
                                                + _detail(2, "01/16/2025", "02/15/2025", 135630, 55410)))
    assert split_statements(rows) is None


def test_a_contents_table_listing_periods_does_not_split_a_single_statement(targets: list[dict]) -> None:
    """A usage-history table lists other periods in its rows; only a labelled period line starts a statement."""

    history = _page(2, [[("Usage history", 0.07)], [("Billing Period", 0.07), ("kWh", 0.5)],
                        [("12/16/2024 - 01/15/2025", 0.07), ("143,230", 0.5)],
                        [("11/16/2024 - 12/15/2024", 0.07), ("139,100", 0.5)]])
    blocks = _summary(1, "01/16/2025", "02/15/2025") + history + _detail(3, "01/16/2025", "02/15/2025", 135630, 55410)
    assert [_mwh(r) for r in _read(blocks, targets)] == pytest.approx([135.63])


def test_a_bundle_where_only_one_statement_has_a_reading_is_read_whole(targets: list[dict]) -> None:
    """Two periods but a reading in only one: nothing is split, so nothing is lost."""

    blocks = (_summary(1, "01/16/2025", "02/15/2025") + _detail(2, "01/16/2025", "02/15/2025", 135630, 55410)
              + _summary(3, "02/16/2025", "03/15/2025"))
    assert [_mwh(r) for r in _read(blocks, targets)] == pytest.approx([135.63])


def test_thermal_statements_in_one_file_are_split_too() -> None:
    targets = ExtractionTargetService().get_targets_for_canonical_type("CT-S2-THERMAL")

    def bill(page: int, start: str, end: str, mmbtu: int) -> list[dict[str, Any]]:
        return _page(page, [
            [("Harborline District Energy", 0.15)], [("Steam Service Statement", 0.15)],
            [("Account:", 0.07), ("HDE-00417", 0.3)], [("Billing Period:", 0.07), (f"{start} - {end}", 0.3)],
            [("Steam Usage:", 0.07), (f"{mmbtu:,} MMBtu", 0.3)]])

    blocks = bill(1, "01/01/2025", "01/31/2025", 410) + bill(2, "02/01/2025", "02/28/2025", 380)
    outcome = ThermalExtractor().extract(_output(blocks), targets, "EV-1")
    assert outcome.records == 2 and outcome.halt_reason is None
    quantities = [c["normalized_value"] for c in outcome.candidates if c["field_name"] == "activity_quantity"]
    assert quantities == [410, 380]
    assert {c["normalized_value"] for c in outcome.candidates if c["field_name"] == "energy_type"} == {"steam"}


def test_a_scan_of_a_bundled_statement_is_flagged_as_a_possible_duplicate_and_never_excluded() -> None:
    """The July bill, scanned on its own, repeats the bundle's July statement: same period, quantity and
    account. The data-quality check warns; both stay counted until the reviewer marks one a duplicate."""

    from backend.tests.services.test_engagement_recalculation_service import FakeStore, _own, _service

    def record(start: str, end: str, mwh: float) -> dict[str, tuple]:
        return {"activity_quantity": (mwh, "MWh"), "activity_unit": ("MWh", None), "energy_type": ("electricity", None),
                "service_period_start": (start, None), "service_period_end": (end, None),
                "service_address": ("410 Mill Road, Springfield, OR 97477", None),
                "account_number": ("4471-20983-6", None)}

    months = [(f"2025-{m:02d}-16", f"2025-{m + 1:02d}-15", 150.0 + m) for m in range(1, 12)]  # Jan 16 .. Dec 15
    july = months[5]  # 06-16 .. 07-15
    store = FakeStore()
    store.add_document("BUNDLE", "CT-S2-ELEC", [record(*m) for m in months])
    store.add_document("JULY-SCAN", "CT-S2-ELEC", [record(*july)])
    engagement = {"id": "ENG-1", "reporting_period_start": "2025-01-01", "reporting_period_end": "2025-12-31",
                  "settings": {"facilities": [{"facilityId": "fac-riv", "name": "Riverside Plant",
                                               "address": "410 Mill Road, Springfield, OR 97477"}]}}
    alone = FakeStore()
    alone.add_document("BUNDLE", "CT-S2-ELEC", [record(*m) for m in months])
    only_bundle = _service(alone).recalculate(engagement, _own)["categories"]["purchased_electricity_location_based"]

    result = _service(store).recalculate(engagement, _own)
    duplicates = [c for c in result["quality_checks"] if c["check"] == "Q-003"]
    assert len(duplicates) == 1 and duplicates[0]["trigger"] == "duplicate_counting_risk"
    assert duplicates[0]["severity"] == "warning"  # a warning, not a decision
    assert set(duplicates[0]["documents"]) == {"BUNDLE", "JULY-SCAN"}
    assert not result["excluded"]  # nothing was left out
    counted = result["categories"]["purchased_electricity_location_based"]["total_co2e"]
    assert counted > only_bundle["total_co2e"]  # the scan still counts until the reviewer marks it a duplicate
