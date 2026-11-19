"""A file that holds several statements gives one record per statement (EXT-015, N28).

The STG utility bundle is 12 monthly electric statements of two pages each, behind a contents page and
ahead of the terms. It used to read as one record (the first statement's, with its on-peak and off-peak
lines as two more); each month now has its own record, with its own period, quantity and pages. A wrong cut
is worse than none, so the negative tests below are as important as the positive ones: single bills that
print a second period (a read period, an adjustment, a history table, several accounts) are never split, and a
file whose statements cannot be cut cleanly is read whole with a note. The bundles are synthetic and laid out
with geometry, like a text PDF.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from backend.app.services.document_chunk_service import merge_chunk_outputs
from backend.app.services.electricity_extractor import TOU_NOTE, ElectricityExtractor
from backend.app.services.engagement_recalculation_service import EngagementRecalculationService
from backend.app.services.extraction_target_service import ExtractionTargetService
from backend.app.services.statement_segments import SPLIT_NOTE, split_statements
from backend.app.services.thermal_extractor import AMBIGUOUS_ENERGY_NOTE, ThermalExtractor

# (start, end, total kWh, on-peak kWh) for twelve billing months, 16th to 15th
MONTHS = [
    ("12/16/2024", "01/15/2025", 143230, 58920), ("01/16/2025", "02/15/2025", 135630, 55410),
    ("02/16/2025", "03/15/2025", 148560, 61240), ("03/16/2025", "04/15/2025", 154030, 63880),
    ("04/16/2025", "05/15/2025", 160130, 66100), ("05/16/2025", "06/15/2025", 166830, 69400),
    ("06/16/2025", "07/15/2025", 162480, 68110), ("07/16/2025", "08/15/2025", 168520, 70200),
    ("08/16/2025", "09/15/2025", 157200, 65300), ("09/16/2025", "10/15/2025", 150700, 62500),
    ("10/16/2025", "11/15/2025", 145700, 60400), ("11/16/2025", "12/15/2025", 146590, 60480),
]
SUPPLIER = "Willowmere Electric Cooperative"
Line = list[tuple[str, float]]  # (text, left) cells of one visual row
HEADER: Line = [("Meter", 0.075), ("Register", 0.2), ("Previous Read", 0.35), ("Current Read", 0.5),
                ("Difference", 0.65), ("Usage", 0.8)]


@pytest.fixture(scope="module")
def targets() -> list[dict]:
    return ExtractionTargetService().get_targets_for_canonical_type("CT-S2-ELEC")


def _page(page: int, lines: list[Line], top: float = 0.05) -> list[dict[str, Any]]:
    blocks = []
    for n, cells in enumerate(lines):
        for m, (text, left) in enumerate(cells):
            blocks.append({"block_id": f"p{page}-{n}-{m}-{top}", "page_number": page, "text": text,
                           "confidence": None,
                           "bounding_box": {"left": left, "top": top + n * 0.03, "width": 0.1, "height": 0.012},
                           "source_reference_id": None})
    return blocks


def _summary(page: int, start: str, end: str, account: str = "4471-20983-6", address: str = "410 Mill Road, Springfield, OR 97477",
             supplier: str = SUPPLIER, extra: list[Line] | None = None) -> list[dict[str, Any]]:
    return _page(page, [
        [(supplier, 0.15)], [("Electric Service Statement", 0.15)],
        [("Account Number:", 0.07), (account, 0.3)], [("Service Address:", 0.07), (address, 0.3)],
        [("Billing Period:", 0.07), (f"{start} - {end} (31 days)", 0.3)], *(extra or []),
        [("Total Amount Due", 0.07), ("$16,387.72", 0.5)],
    ])


def _detail(page: int, start: str, end: str, total: int, on_peak: int, meter: str = "WEC-88213457",
            supplier: str = SUPPLIER, period_label: str = "Billing Period:") -> list[dict[str, Any]]:
    return _page(page, [
        [(supplier, 0.07)], [("Meter and Usage Detail", 0.07)], [(period_label, 0.07), (f"{start} - {end}", 0.3)],
        HEADER,
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
    supplier = summary.get("supplier", SUPPLIER)
    blocks = _page(1, [[(supplier, 0.15)], [("Annual Statement Package", 0.15)],
                       [("Contents", 0.07)], [("Section", 0.07), ("Billing Period", 0.3), ("Pages", 0.6)]]
                   + [[(f"Statement {n + 1}", 0.07), (f"{s} - {e}", 0.3), (f"{2 * n + 2}-{2 * n + 3}", 0.6)]
                      for n, (s, e, _, _) in enumerate(months)])
    for n, (start, end, total, on_peak) in enumerate(months):
        blocks += _summary(2 * n + 2, start, end, **summary) + _detail(2 * n + 3, start, end, total, on_peak,
                                                                       supplier=supplier)
    return blocks + _page(2 * len(months) + 2, [[("Terms and Conditions of Electric Service", 0.07)],
                                                 [("Charges are billed on 1,000 kWh blocks.", 0.07)]])


def _extract(blocks: list[dict[str, Any]], targets: list[dict]) -> Any:
    outcome = ElectricityExtractor().extract(_output(blocks), targets, "EV-1")
    assert outcome.halt_reason is None, outcome.halt_reason
    return outcome


def _records(outcome: Any) -> list[dict[str, Any]]:
    """One dict of field -> candidate per record, in record order."""

    records: dict[Any, dict[str, Any]] = {}
    for candidate in outcome.candidates:
        records.setdefault(candidate["record_index"], {})[candidate["field_name"]] = candidate
    return [records[key] for key in sorted(records, key=lambda k: (k is None, k))]


def _read(blocks: list[dict[str, Any]], targets: list[dict]) -> list[dict[str, Any]]:
    return _records(_extract(blocks, targets))


def _mwh(record: dict[str, Any]) -> float:
    return float(record["activity_quantity"]["normalized_value"])


def _split(blocks: list[dict[str, Any]]) -> Any:
    return split_statements(ElectricityExtractor()._rows(_output(blocks)))


# ---- the bundle ----------------------------------------------------------------------------------------
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
    assert {r["supplier_name"]["normalized_value"] for r in records} == {SUPPLIER}


def test_each_record_points_at_its_own_pages_and_has_its_own_key(targets: list[dict]) -> None:
    outcome = _extract(_bundle(), targets)
    assert outcome.records == 12
    pages: dict[int, int] = {}
    keys: dict[int, str] = {}
    for candidate in outcome.candidates:
        if candidate["field_name"] == "activity_quantity":
            pages[candidate["record_index"]] = candidate["source_reference"]["page_number"]
            keys[candidate["record_index"]] = candidate["source_reference"]["record_key"]
    assert pages == {n: 2 * n + 1 for n in range(1, 13)}  # the quantity is on each statement's detail page
    assert len(set(keys.values())) == 12  # r1..r12, each with its meter and period
    assert keys[3] == "r3:WEC-88213457:2025-02-16..2025-03-15"


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


def _stacked(top: float, start: str, end: str, total: int, title: Line | None = None) -> list[dict[str, Any]]:
    lines: list[Line] = [
        title or [("Electric Service Statement", 0.15)], [("Account Number:", 0.07), ("4471-20983-6", 0.3)],
        [("Service Address:", 0.07), ("410 Mill Road, Springfield, OR 97477", 0.3)],
        [("Billing Period:", 0.07), (f"{start} - {end}", 0.3)], HEADER,
        [("WEC-88213457", 0.075), ("Total kWh", 0.2), ("1", 0.35), ("2", 0.5), (f"{total:,}", 0.65),
         (f"{total:,} kWh", 0.8)]]
    return _page(1, lines, top=top)


def test_two_statements_on_one_page_are_two_records_when_the_second_repeats_the_title(targets: list[dict]) -> None:
    blocks = (_page(1, [[(SUPPLIER, 0.15)]], top=0.01) + _stacked(0.05, "01/16/2025", "02/15/2025", 135630)
              + _stacked(0.45, "02/16/2025", "03/15/2025", 148560))
    records = _read(blocks, targets)
    assert [_mwh(r) for r in records] == pytest.approx([135.63, 148.56])
    assert [r["service_period_start"]["normalized_value"] for r in records] == ["2025-01-16", "2025-02-16"]


def test_a_title_row_with_several_cells_still_marks_the_cut(targets: list[dict]) -> None:
    """The NPL layout: a logo, the utility's name and the title share one row."""

    title: Line = [("SB", 0.05), ("SIERRA BASIN ENERGY CO.", 0.15), ("Your Electric Service Statement", 0.5)]
    blocks = (_stacked(0.05, "01/01/2025", "01/31/2025", 338120, title)
              + _stacked(0.45, "02/01/2025", "02/28/2025", 315904, title))
    assert [_mwh(r) for r in _read(blocks, targets)] == pytest.approx([338.12, 315.904])


def test_two_statements_on_one_page_with_no_title_to_cut_at_are_read_whole_with_a_note(targets: list[dict]) -> None:
    blocks = (_stacked(0.05, "01/16/2025", "02/15/2025", 135630, [("Account statement", 0.15)])
              + _stacked(0.45, "02/16/2025", "03/15/2025", 148560, [("Meter reading", 0.15)]))
    outcome = _extract(blocks, targets)
    assert outcome.notes == [SPLIT_NOTE]
    assert [_mwh(r) for r in _records(outcome)][0] == pytest.approx(135.63)  # read whole, as before


def test_a_page_with_a_usage_summary_above_its_period_is_cut_at_the_page_top(targets: list[dict]) -> None:
    """Four one-page statements, each with a "Total kWh Used" box above its period line and no title row:
    the cut is at the top of each page, so no quantity is paired with another month's period."""

    blocks: list[dict[str, Any]] = []
    for n, (start, end, kwh) in enumerate([("01/01/2025", "01/31/2025", 1000), ("02/01/2025", "02/28/2025", 2000),
                                           ("03/01/2025", "03/31/2025", 3000), ("04/01/2025", "04/30/2025", 4000)]):
        blocks += _page(n + 1, [
            [(SUPPLIER, 0.15)], [("Total kWh Used:", 0.07), (f"{kwh:,} kWh", 0.3)],
            [("Account Number:", 0.07), ("4471-20983-6", 0.3)], [("Billing Period:", 0.07), (f"{start} - {end}", 0.3)],
            HEADER, [("M-1", 0.075), ("Total kWh", 0.2), ("1", 0.35), ("2", 0.5), (f"{kwh:,}", 0.65),
                     (f"{kwh:,} kWh", 0.8)]])
    records = _read(blocks, targets)
    assert [(r["service_period_start"]["normalized_value"], _mwh(r)) for r in records] == [
        ("2025-01-01", 1.0), ("2025-02-01", 2.0), ("2025-03-01", 3.0), ("2025-04-01", 4.0)]


# ---- single bills that print a second period are never split ------------------------------------------------
def _summary_with_usage() -> list[dict[str, Any]]:
    return _summary(1, "01/16/2025", "02/15/2025", extra=[[("Total kWh Used:", 0.07), ("135,630 kWh", 0.3)]])


@pytest.mark.parametrize("period_label", ["Read Period:", "Service Period:", "Usage Period:"])
def test_a_detail_page_with_its_period_a_day_off_is_the_same_statement(targets: list[dict], period_label: str) -> None:
    blocks = _summary_with_usage() + _detail(2, "01/15/2025", "02/14/2025", 135630, 55410, period_label=period_label)
    assert _split(blocks).parts is None
    assert _split(blocks).note is None  # one statement: nothing to say
    assert [_mwh(r) for r in _read(blocks, targets)] == pytest.approx([135.63])  # not 271.26


def test_a_summary_page_listing_each_accounts_period_and_usage_is_never_split(targets: list[dict]) -> None:
    summary = _page(1, [[(SUPPLIER, 0.15)], [("Summary of Accounts", 0.15)],
                        [("Account 1001", 0.07)], [("Billing Period:", 0.07), ("01/05/2025 - 02/04/2025", 0.3)],
                        [("Total kWh Used:", 0.07), ("12,000 kWh", 0.3)],
                        [("Account 1002", 0.07)], [("Billing Period:", 0.07), ("01/10/2025 - 02/09/2025", 0.3)],
                        [("Total kWh Used:", 0.07), ("8,000 kWh", 0.3)]])
    blocks = (summary + _detail(2, "01/05/2025", "02/04/2025", 12000, 5000, meter="M-1001")
              + _detail(3, "01/10/2025", "02/09/2025", 8000, 3000, meter="M-1002"))
    assert _split(blocks).parts is None
    assert sum(_mwh(r) for r in _read(blocks, targets)) == pytest.approx(20.0)  # not 40


def test_a_prior_period_restatement_page_is_never_a_statement(targets: list[dict]) -> None:
    adjustment = _page(3, [[(SUPPLIER, 0.07)], [("Prior Period Adjustment", 0.07)],
                           [("Service Period:", 0.07), ("12/16/2024 - 01/15/2025", 0.3)],
                           [("Meter", 0.075), ("Register", 0.2), ("Usage", 0.8)],
                           [("WEC-88213457", 0.075), ("Previously billed kWh", 0.2), ("143,230 kWh", 0.8)],
                           [("WEC-88213457", 0.075), ("Corrected kWh", 0.2), ("144,430 kWh", 0.8)]])
    blocks = (_summary(1, "01/16/2025", "02/15/2025") + _detail(2, "01/16/2025", "02/15/2025", 135630, 55410)
              + adjustment)
    assert _split(blocks).parts is None
    assert [_mwh(r) for r in _read(blocks, targets)][0] == pytest.approx(135.63)  # not 135.63 + 143.23 + ...


def test_a_usage_history_table_listing_other_periods_does_not_split_a_statement(targets: list[dict]) -> None:
    history = _page(3, [[("Usage History", 0.07)],
                        [("Billing Period: 12/16/2024 - 01/15/2025", 0.07), ("143,230 kWh", 0.5)],
                        [("Billing Period: 11/16/2024 - 12/15/2024", 0.07), ("139,100 kWh", 0.5)]])
    blocks = (_summary(1, "01/16/2025", "02/15/2025") + _detail(2, "01/16/2025", "02/15/2025", 135630, 55410)
              + history)
    assert _split(blocks).parts is None
    assert [_mwh(r) for r in _read(blocks, targets)] == pytest.approx([135.63])


def test_a_next_billing_period_line_does_not_split_a_statement(targets: list[dict]) -> None:
    blocks = (_summary(1, "01/16/2025", "02/15/2025", extra=[[("Next Billing Period:", 0.07),
                                                              ("02/16/2025 - 03/15/2025", 0.3)]])
              + _detail(2, "01/16/2025", "02/15/2025", 135630, 55410))
    assert [_mwh(r) for r in _read(blocks, targets)] == pytest.approx([135.63])


def test_a_bundle_whose_statements_cannot_be_cut_cleanly_is_read_whole_and_says_so(targets: list[dict]) -> None:
    """Two periods that do not overlap, but the second statement starts mid-page under no title: no cut."""

    blocks = (_summary(1, "01/16/2025", "02/15/2025")
              + _page(1, [[("Billing Period:", 0.07), ("02/16/2025 - 03/15/2025", 0.3)]], top=0.7))
    split = _split(blocks)
    assert split.parts is None and split.note == SPLIT_NOTE


# ---- time-of-use lines ----------------------------------------------------------------------------------------
def _tou_detail(first_cell_is_meter: bool) -> list[dict[str, Any]]:
    rows: list[Line]
    if first_cell_is_meter:  # the meter id repeats in the first cell; the peak label is in the register cell
        rows = [[("WEC-88213457", 0.075), ("Total kWh", 0.2), ("1", 0.35), ("2", 0.5), ("148,560", 0.65),
                 ("148,560 kWh", 0.8)],
                [("WEC-88213457", 0.075), ("On-Peak kWh", 0.2), ("61,240 kWh", 0.8)],
                [("WEC-88213457", 0.075), ("Off-Peak kWh", 0.2), ("87,320 kWh", 0.8)]]
    else:
        rows = [[("WEC-88213457", 0.075), ("Total kWh", 0.2), ("1", 0.35), ("2", 0.5), ("148,560", 0.65),
                 ("148,560 kWh", 0.8)],
                [("On-Peak kWh", 0.075), ("61,240 kWh", 0.8)], [("Off-Peak kWh", 0.075), ("87,320 kWh", 0.8)]]
    return _page(1, [[(SUPPLIER, 0.15)], [("Electric Service Statement", 0.15)],
                     [("Billing Period:", 0.07), ("02/16/2025 - 03/15/2025", 0.3)], HEADER, *rows])


@pytest.mark.parametrize("first_cell_is_meter", [False, True])
def test_a_time_of_use_bill_is_read_as_its_total_only(targets: list[dict], first_cell_is_meter: bool) -> None:
    """On-peak and off-peak lines are parts of the total (wherever their label sits in the row); counted as
    records they tripled the bill."""

    outcome = _extract(_tou_detail(first_cell_is_meter), targets)
    assert [_mwh(r) for r in _records(outcome)] == pytest.approx([148.56])
    assert outcome.notes == []


def test_a_total_row_under_the_time_of_use_lines_is_the_record(targets: list[dict]) -> None:
    """The NPL layout: Peak, Part-Peak, Off-Peak, then a Total row that the table reader stops at."""

    blocks = _page(1, [[(SUPPLIER, 0.15)], [("Electric Service Statement", 0.15)],
                       [("Billing Period:", 0.07), ("01/01/2025 - 01/31/2025", 0.3)],
                       [("TOU Period", 0.07), ("Hours", 0.4), ("Usage (kWh)", 0.8)],
                       [("Peak", 0.07), ("4 pm - 9 pm weekdays", 0.4), ("57,480", 0.8)],
                       [("Part-Peak", 0.07), ("2 pm - 4 pm", 0.4), ("91,292", 0.8)],
                       [("Off-Peak", 0.07), ("All other hours", 0.4), ("189,348", 0.8)],
                       [("Total", 0.07), ("338,120", 0.8)]])
    outcome = _extract(blocks, targets)
    assert [_mwh(r) for r in _records(outcome)] == pytest.approx([338.12])
    assert outcome.notes == []


def _npl_statement(page: int, start: str, end: str, total: int, parts: tuple[int, int, int]) -> list[dict[str, Any]]:
    title: Line = [("SB", 0.05), ("SIERRA BASIN ENERGY CO.", 0.15), ("Your Electric Service Statement", 0.5)]
    summary = _page(page, [title, [("Account Number", 0.07), ("8830-1174-562", 0.3)],
                           [("Service Period", 0.07), (f"{start} - {end} (31 days)", 0.3)],
                           [("Total Electricity Used", 0.07), (f"{total / 1000:,.3f} MWh", 0.3)]])
    peak, part, off = parts
    detail = _page(page + 1, [
        [("SB", 0.05), ("SIERRA BASIN ENERGY CO.", 0.15), ("Details of Electric Charges", 0.5)],
        [("Register", 0.07), ("Prior Read", 0.3), ("Current Read", 0.5), ("Usage (kWh)", 0.8)],
        [("Total kWh (cumulative)", 0.07), ("3,120,455", 0.3), ("3,458,575", 0.5), (f"{total:,}", 0.8)],
        [("Time-of-Use Breakdown", 0.07)],
        [("TOU Period", 0.07), ("Hours", 0.4), ("Usage (kWh)", 0.8)],
        [("Peak", 0.07), ("4 pm - 9 pm weekdays", 0.4), (f"{peak:,}", 0.8)],
        [("Part-Peak", 0.07), ("2 pm - 4 pm", 0.4), (f"{part:,}", 0.8)],
        [("Off-Peak", 0.07), ("All other hours", 0.4), (f"{off:,}", 0.8)],
        [("Total", 0.07), (f"{total:,}", 0.8)]])
    return summary + detail


def test_the_npl_bundle_layout_gives_twelve_monthly_totals_not_thirty_six_lines(targets: list[dict]) -> None:
    months = [("01/01/2025", "01/31/2025", 338120, (57480, 91292, 189348)),
              ("02/01/2025", "02/28/2025", 315904, (53704, 85294, 176906))] + [
        (f"{m:02d}/01/2025", f"{m:02d}/28/2025", 300000 + m * 1000, (100000, 100000, 100000 + m * 1000))
        for m in range(3, 13)]
    blocks: list[dict[str, Any]] = []
    for n, (start, end, total, parts) in enumerate(months):
        blocks += _npl_statement(2 * n + 1, start, end, total, parts)
    records = _read(blocks, targets)
    assert len(records) == 12
    assert [_mwh(r) for r in records][:2] == pytest.approx([338.12, 315.904])
    assert [r["service_period_start"]["normalized_value"] for r in records][:3] == [
        "2025-01-01", "2025-02-01", "2025-03-01"]


def test_a_meter_with_time_of_use_lines_and_no_total_keeps_every_line_and_says_so(targets: list[dict]) -> None:
    """Meter A has its own total; meter B is billed on peak and off-peak only. Dropping B's lines would lose
    50 MWh without a word: all three lines stay, with a note."""

    blocks = _page(1, [[(SUPPLIER, 0.15)], [("Electric Service Statement", 0.15)],
                       [("Billing Period:", 0.07), ("02/16/2025 - 03/15/2025", 0.3)], HEADER,
                       [("A-111", 0.075), ("Total kWh", 0.2), ("1", 0.35), ("2", 0.5), ("100,000", 0.65),
                        ("100,000 kWh", 0.8)],
                       [("B-222", 0.075), ("On-Peak kWh", 0.2), ("1", 0.35), ("2", 0.5), ("20,000", 0.65),
                        ("20,000 kWh", 0.8)],
                       [("Off-Peak kWh", 0.2), ("1", 0.35), ("2", 0.5), ("30,000", 0.65), ("30,000 kWh", 0.8)]])
    outcome = _extract(blocks, targets)
    assert sorted(_mwh(r) for r in _records(outcome)) == pytest.approx([20.0, 30.0, 100.0])
    assert outcome.notes == [TOU_NOTE]


def test_time_of_use_lines_that_do_not_add_up_to_their_total_are_all_kept(targets: list[dict]) -> None:
    blocks = _page(1, [[(SUPPLIER, 0.15)], [("Electric Service Statement", 0.15)],
                       [("Billing Period:", 0.07), ("02/16/2025 - 03/15/2025", 0.3)], HEADER,
                       [("WEC-88213457", 0.075), ("Total kWh", 0.2), ("1", 0.35), ("2", 0.5), ("200,000", 0.65),
                        ("200,000 kWh", 0.8)],
                       [("On-Peak kWh", 0.075), ("61,240 kWh", 0.8)], [("Off-Peak kWh", 0.075), ("87,320 kWh", 0.8)]])
    outcome = _extract(blocks, targets)
    assert sorted(_mwh(r) for r in _records(outcome)) == pytest.approx([61.24, 87.32, 200.0])
    assert outcome.notes == [TOU_NOTE]


def test_time_of_use_rows_that_each_carry_a_total_register_are_never_both_part_and_total(targets: list[dict]) -> None:
    blocks = _page(1, [[(SUPPLIER, 0.15)], [("Electric Service Statement", 0.15)],
                       [("Billing Period:", 0.07), ("02/16/2025 - 03/15/2025", 0.3)], HEADER,
                       [("On-Peak", 0.075), ("Total kWh", 0.2), ("1", 0.35), ("2", 0.5), ("61,240", 0.65),
                        ("61,240 kWh", 0.8)],
                       [("Off-Peak", 0.075), ("Total kWh", 0.2), ("1", 0.35), ("2", 0.5), ("87,320", 0.65),
                        ("87,320 kWh", 0.8)]])
    outcome = _extract(blocks, targets)  # the bill is not rejected, and nothing is dropped
    assert sorted(_mwh(r) for r in _records(outcome)) == pytest.approx([61.24, 87.32])
    assert outcome.notes == [TOU_NOTE]


def test_time_of_use_lines_without_a_total_are_kept(targets: list[dict]) -> None:
    blocks = _page(1, [[(SUPPLIER, 0.15)], [("Electric Service Statement", 0.15)],
                       [("Billing Period:", 0.07), ("02/16/2025 - 03/15/2025", 0.3)], HEADER,
                       [("On-Peak kWh", 0.075), ("61,240 kWh", 0.8)], [("Off-Peak kWh", 0.075), ("87,320 kWh", 0.8)]])
    assert [_mwh(r) for r in _read(blocks, targets)] == pytest.approx([61.24, 87.32])


def test_the_same_bill_printed_twice_in_a_file_keeps_each_print_as_one_record(targets: list[dict]) -> None:
    """A reprint is the same period, so it is one statement by its period: no split. Each print's time-of-use
    table is its own block, so its parts still collapse to its total."""

    blocks = (_summary(1, "01/16/2025", "02/15/2025") + _detail(2, "01/16/2025", "02/15/2025", 135630, 55410)
              + _summary(3, "01/16/2025", "02/15/2025") + _detail(4, "01/16/2025", "02/15/2025", 135630, 55410))
    assert _split(blocks).parts is None
    assert [_mwh(r) for r in _read(blocks, targets)] == pytest.approx([135.63, 135.63])


# ---- other shapes -----------------------------------------------------------------------------------------------
def test_a_non_ascii_bundle_is_split_and_read_whole(targets: list[dict]) -> None:
    blocks = _bundle(MONTHS[:3], supplier="Müller Elektrizität Zürich Utility Co.",
                     address="12 Bahnhofstraße, 8001 Zürich", account="ZH-00417")
    records = _read(blocks, targets)
    assert len(records) == 3
    assert {r["supplier_name"]["normalized_value"] for r in records} == {"Müller Elektrizität Zürich Utility Co."}
    assert {r["service_address"]["normalized_value"] for r in records} == {"12 Bahnhofstraße, 8001 Zürich"}


def test_a_two_page_statement_and_a_single_statement_are_one_record_each(targets: list[dict]) -> None:
    [only] = _read(_summary(1, "01/16/2025", "02/15/2025") + _detail(2, "01/16/2025", "02/15/2025", 135630, 55410),
                   targets)
    assert _mwh(only) == pytest.approx(135.63)


def test_a_bundle_where_only_one_statement_has_a_reading_is_read_whole_with_a_note(targets: list[dict]) -> None:
    blocks = (_summary(1, "01/16/2025", "02/15/2025") + _detail(2, "01/16/2025", "02/15/2025", 135630, 55410)
              + _summary(3, "02/16/2025", "03/15/2025"))
    outcome = _extract(blocks, targets)
    assert [_mwh(r) for r in _records(outcome)] == pytest.approx([135.63])
    assert outcome.notes == [SPLIT_NOTE]


def test_thermal_statements_in_one_file_are_split_too_and_each_part_carries_its_own_note() -> None:
    targets = ExtractionTargetService().get_targets_for_canonical_type("CT-S2-THERMAL")

    def bill(page: int, start: str, end: str, line: Line) -> list[dict[str, Any]]:
        return _page(page, [
            [("Harborline District Energy", 0.15)], [("Steam & chilled water service statement", 0.15)],
            [("Account:", 0.07), ("HDE-00417", 0.3)], [("Billing Period:", 0.07), (f"{start} - {end}", 0.3)], line])

    blocks = (bill(1, "01/01/2025", "01/31/2025", [("Steam Usage:", 0.07), ("410 MMBtu", 0.3)])
              + bill(2, "02/01/2025", "02/28/2025", [("Steam Usage:", 0.07), ("380 MMBtu", 0.3)])
              + bill(3, "03/01/2025", "03/31/2025", [("Total Usage:", 0.07), ("300 MMBtu", 0.3)]))
    outcome = ThermalExtractor().extract(_output(blocks), targets, "EV-1")
    assert outcome.records == 3 and outcome.halt_reason is None
    quantities = [c["normalized_value"] for c in outcome.candidates if c["field_name"] == "activity_quantity"]
    assert quantities == [410, 380, 300]
    energy = [c["normalized_value"] for c in outcome.candidates if c["field_name"] == "energy_type"]
    assert energy == ["steam", "steam", None]  # March names two types and says which one is billed nowhere
    assert outcome.notes == [AMBIGUOUS_ENERGY_NOTE]  # from March's own record only


def test_a_thermal_bundle_whose_parts_all_name_their_type_has_no_note() -> None:
    targets = ExtractionTargetService().get_targets_for_canonical_type("CT-S2-THERMAL")
    blocks = []
    for page, (start, end, quantity) in enumerate([("01/01/2025", "01/31/2025", 410), ("02/01/2025", "02/28/2025", 380)], 1):
        blocks += _page(page, [
            [("Harborline District Energy", 0.15)], [("Steam & chilled water service statement", 0.15)],
            [("Billing Period:", 0.07), (f"{start} - {end}", 0.3)], [("Steam Usage:", 0.07), (f"{quantity} MMBtu", 0.3)]])
    outcome = ThermalExtractor().extract(_output(blocks), targets, "EV-1")
    assert outcome.records == 2 and outcome.notes == []


# ---- the duplicate check -------------------------------------------------------------------------------------------
def _key(index: int, meters: list[str | None] | None, record: dict[str, tuple]) -> dict[str, str]:
    meter = meters[index - 1] if meters else None
    period = f"{record.get('service_period_start', (None,))[0]}..{record.get('service_period_end', (None,))[0]}"
    return {"record_key": f"r{index}:{meter}:{period}" if meter else f"r{index}:{period}"}


class _Store:
    """The three services the recalculation reads: a few documents, each with accepted records."""

    def __init__(self) -> None:
        self.documents: list[dict] = []
        self.results: dict[str, list[dict]] = {}
        self.reviews: dict[str, list[dict]] = {}

    def add(self, document_id: str, records: list[dict[str, tuple]], *, pages: list[int] | None = None,
            meters: list[str | None] | None = None) -> None:
        self.documents.append({"document_id": document_id, "engagement_id": "ENG-1", "org_id": "org-a",
                               "file_name": f"{document_id}.pdf"})
        items, reviews = [], []
        for index, record in enumerate(records, start=1):
            for name, (value, unit) in record.items():
                candidate_id = f"{document_id}:{index}:{name}"
                items.append({"candidate_id": candidate_id, "field_name": name, "normalized_value": value,
                              "unit": unit, "record_index": index if len(records) > 1 else None,
                              "source_reference": {"document_id": document_id,
                                                   "page_number": pages[index - 1] if pages else index,
                                                   **_key(index, meters, record)}})
                reviews.append({"candidate_id": candidate_id, "decision": "accepted", "org_id": "org-a",
                                "reviewed_value": value, "reviewed_unit": unit})
        self.results[document_id] = [{"document_id": document_id, "org_id": "org-a",
                                      "canonical_type_id": "CT-S2-ELEC", "items": items}]
        self.reviews[document_id] = reviews

    def list_documents(self, engagement_id: str) -> list[dict]:
        return [d for d in self.documents if d["engagement_id"] == engagement_id]

    def list_extraction_results_by_document(self, document_id: str) -> list[dict]:
        return self.results.get(document_id, [])

    def list_by_document(self, document_id: str) -> list[dict]:
        return self.reviews.get(document_id, [])


def _recalculate(store: _Store) -> dict:
    engagement = {"id": "ENG-1", "reporting_period_start": "2025-01-01", "reporting_period_end": "2025-12-31",
                  "settings": {"facilities": [{"facilityId": "fac-riv", "name": "Riverside Plant",
                                               "address": "410 Mill Road, Springfield, OR 97477"}]}}
    return EngagementRecalculationService(store, store, store).recalculate(
        engagement, lambda record: record.get("org_id") == "org-a")


def _electric(start: str, end: str, mwh: float) -> dict[str, tuple]:
    return {"activity_quantity": (mwh, "MWh"), "activity_unit": ("MWh", None), "energy_type": ("electricity", None),
            "service_period_start": (start, None), "service_period_end": (end, None),
            "service_address": ("410 Mill Road, Springfield, OR 97477", None), "account_number": ("4471-20983-6", None)}


def test_a_scan_of_a_bundled_statement_is_flagged_as_a_possible_duplicate_and_never_excluded() -> None:
    """The July bill, scanned on its own, repeats the bundle's July statement: same period, quantity and
    account. The data-quality check warns; both stay counted until the reviewer marks one a duplicate."""

    months = [(f"2025-{m:02d}-16", f"2025-{m + 1:02d}-15", 150.0 + m) for m in range(1, 12)]  # Jan 16 .. Dec 15
    store = _Store()
    store.add("BUNDLE", [_electric(*m) for m in months])
    store.add("JULY-SCAN", [_electric(*months[5])])  # 06-16 .. 07-15
    alone = _Store()
    alone.add("BUNDLE", [_electric(*m) for m in months])

    result = _recalculate(store)
    duplicates = [c for c in result["quality_checks"] if c["check"] == "Q-003"]
    assert len(duplicates) == 1 and duplicates[0]["trigger"] == "duplicate_counting_risk"
    assert duplicates[0]["severity"] == "warning"  # a warning, not a decision
    assert set(duplicates[0]["documents"]) == {"BUNDLE", "JULY-SCAN"}
    assert not result["excluded"]  # nothing was left out
    assert (result["categories"]["purchased_electricity_location_based"]["total_co2e"]
            > _recalculate(alone)["categories"]["purchased_electricity_location_based"]["total_co2e"])


def test_a_month_printed_twice_inside_one_bundle_is_flagged_as_a_possible_duplicate() -> None:
    """A, B, A again: the second A is a statement of its own by its position, so the file gives three
    records; the check names the repeat instead of letting it count twice unseen."""

    store = _Store()
    store.add("BUNDLE", [_electric("2025-01-16", "2025-02-15", 135.63), _electric("2025-02-16", "2025-03-15", 148.56),
                         _electric("2025-01-16", "2025-02-15", 135.63)])
    findings = [c for c in _recalculate(store)["quality_checks"] if c["check"] == "Q-003"]
    assert [f["trigger"] for f in findings] == ["duplicate_statement_in_same_file"]
    assert findings[0]["severity"] == "warning" and findings[0]["documents"] == ["BUNDLE"]
    assert "printed twice" in findings[0]["message"]


def test_two_meters_on_one_bill_with_the_same_reading_are_not_a_repeated_statement() -> None:
    """Meter A and meter B share the bill's account and period and both read 50 MWh: two meters, not a repeat.
    The overlap check still sees them, as it did before."""

    store = _Store()
    reading = _electric("2025-01-16", "2025-02-15", 50.0)
    store.add("ONE-BILL", [dict(reading), dict(reading)], pages=[3, 3], meters=["A-111", "B-222"])
    findings = _recalculate(store)["quality_checks"]
    assert not [c for c in findings if c["check"] == "Q-003"]
    assert [c["trigger"] for c in findings if c["check"] == "Q-004"] == ["overlapping_period"]


def test_two_meters_with_the_same_reading_and_no_account_are_not_flagged_as_a_repeat() -> None:
    store = _Store()
    plain = {k: v for k, v in _electric("2025-01-16", "2025-02-15", 50.0).items() if k != "account_number"}
    store.add("TWO-METERS", [plain, dict(plain)], pages=[3, 3])
    assert not [c for c in _recalculate(store)["quality_checks"] if c["check"] == "Q-003"]


def test_the_same_meter_read_twice_on_different_pages_of_one_file_is_a_repeat() -> None:
    store = _Store()
    reading = _electric("2025-01-16", "2025-02-15", 50.0)
    store.add("PRINTED-TWICE", [dict(reading), dict(reading)], pages=[3, 9], meters=["A-111", "A-111"])
    assert [c["trigger"] for c in _recalculate(store)["quality_checks"] if c["check"] == "Q-003"] == [
        "duplicate_statement_in_same_file"]


# ---- statements merged by a near period say so --------------------------------------------------------------------
def _two_pages(first: tuple[str, str], second: tuple[str, str]) -> list[dict[str, Any]]:
    return (_summary(1, *first) + _detail(2, *first, 135630, 55410)
            + _summary(3, *second) + _detail(4, *second, 148560, 61240))


def test_two_statements_whose_periods_overlap_by_two_days_are_read_as_one_with_a_note(targets: list[dict]) -> None:
    blocks = _two_pages(("01/16/2025", "02/15/2025"), ("02/14/2025", "03/15/2025"))  # share Feb 14 and 15
    split = _split(blocks)
    assert split.parts is None and split.note == SPLIT_NOTE
    assert SPLIT_NOTE in _extract(blocks, targets).notes


def test_a_short_move_in_bill_four_days_before_the_next_is_read_as_one_with_a_note(targets: list[dict]) -> None:
    blocks = _two_pages(("02/12/2025", "02/15/2025"), ("02/16/2025", "03/15/2025"))
    split = _split(blocks)
    assert split.parts is None and split.note == SPLIT_NOTE
    assert SPLIT_NOTE in _extract(blocks, targets).notes


def test_a_clean_bundle_and_a_reprinted_period_carry_no_note(targets: list[dict]) -> None:
    assert _extract(_bundle(), targets).notes == []
    blocks = _two_pages(("01/16/2025", "02/15/2025"), ("01/16/2025", "02/15/2025"))  # the same period twice
    assert _split(blocks).note is None
