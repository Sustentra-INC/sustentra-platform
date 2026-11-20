"""A gas bill bundle gives one record per statement, like the electricity one (EXT-015, NPL gas bundle).

The NPL Sacramento bundle is 37 scanned pages: twelve monthly gas statements, the first running across the
year end (12 of its 32 days in 2025), one of them also filed as its own document. The text of a scan is laid
out with geometry by the reader; these synthetic bundles are laid out the same way (cells with positions,
page by page), with non-ASCII names throughout.
"""

from __future__ import annotations

from typing import Any

import pytest

from backend.app.services.extraction_target_service import ExtractionTargetService
from backend.app.services.stationary_combustion_extractor import ACCOUNT_SUMMARY_NOTE, StationaryCombustionExtractor
from backend.tests.services.recalc_store import RecalcStore, recalculate
from backend.app.services.statement_segments import SPLIT_NOTE, account_summary_pages, split_statements

SUPPLIER = "Südbaden Erdgas Müller & Söhne Gas Co."
ACCOUNT = "4417-6631-08"
SITE = "Käserei Zürich Nord"
ADDRESS = "Bahnhofstraße 12, 8001 Zürich"
# (start, end, therms) for twelve billing months; the first crosses the year end (12 of 32 days in 2025)
MONTHS = [
    ("12/12/2024", "01/12/2025", 3484.8), ("01/13/2025", "02/11/2025", 2999.5), ("02/12/2025", "03/12/2025", 2554.4),
    ("03/13/2025", "04/11/2025", 2100.2), ("04/12/2025", "05/12/2025", 1600.7), ("05/13/2025", "06/11/2025", 900.3),
    ("06/12/2025", "07/11/2025", 700.9), ("07/12/2025", "08/11/2025", 650.4), ("08/12/2025", "09/10/2025", 880.6),
    ("09/11/2025", "10/10/2025", 1500.1), ("10/11/2025", "11/10/2025", 2300.8), ("11/11/2025", "12/10/2025", 3100.5),
]
FACILITIES = [{"facilityId": "fac-zh", "name": SITE, "address": ADDRESS}]
Line = list[tuple[str, float]]  # (text, left) cells of one visual row


@pytest.fixture(scope="module")
def targets() -> list[dict]:
    return ExtractionTargetService().get_targets_for_canonical_type("CT-S1-FUELQTY")


def _page(page: int, lines: list[Line], top: float = 0.05) -> list[dict[str, Any]]:
    blocks = []
    for n, cells in enumerate(lines):
        for m, (text, left) in enumerate(cells):
            blocks.append({"block_id": f"p{page}-{n}-{m}", "page_number": page, "text": text, "confidence": 0.93,
                           "bounding_box": {"left": left, "top": top + n * 0.03, "width": 0.1, "height": 0.012},
                           "source_reference_id": None})
    return blocks


def _summary(page: int, start: str, end: str, label: str = "Billing Period:", next_read: str = "") -> list[dict[str, Any]]:
    lines: list[Line] = [
        [(SUPPLIER, 0.15)], [("Natural Gas Statement", 0.15)],
        [("Account Number:", 0.07), (ACCOUNT, 0.3)],
        [("Service Address:", 0.07), (ADDRESS, 0.3)],
        [("Fuel:", 0.07), ("Natural Gas", 0.3)],
        [(label, 0.07), (f"{start} - {end}", 0.3)],
        [("Total Amount Due", 0.07), ("$6,639.24", 0.5)]]
    if next_read:
        lines.append([("Next read date:", 0.07), (next_read, 0.3)])
    return _page(page, lines)


def _usage(page: int, start: str, end: str, therms: float, label: str = "Billing Period:") -> list[dict[str, Any]]:
    return _page(page, [
        [(SUPPLIER, 0.07)], [("Meter Read and Usage", 0.07)], [(label, 0.07), (f"{start} - {end}", 0.3)],
        [("Meter", 0.075), ("Start Read", 0.3), ("End Read", 0.5), ("Usage (therms)", 0.75)],
        [("GM-0091742", 0.075), ("215,480", 0.3), ("218,860", 0.5), (f"{therms:,.1f}", 0.75)]])


def _charges(page: int, start: str, end: str) -> list[dict[str, Any]]:
    """A third page of a statement: its charge detail, repeating the statement's period."""

    return _page(page, [[(SUPPLIER, 0.07)], [("Charge Detail", 0.07)], [("Billing Period:", 0.07), (f"{start} - {end}", 0.3)],
                        [("Commodity charge", 0.07), ("$5,900.00", 0.5)], [("Taxes", 0.07), ("$739.24", 0.5)]])


def _bundle(months: list[tuple[str, str, float]] = MONTHS, three_page: int = 5, label: str = "Billing Period:",
            cover: bool = True) -> list[dict[str, Any]]:
    """A cover, then a summary page and a usage page for each statement; statement ``three_page`` (1-based)
    runs across a third page of charge detail."""

    blocks = _page(1, [[(SUPPLIER, 0.15)], [("Annual Statement Package", 0.15)], [("Contents", 0.07)]]) if cover else []
    page = 2
    for n, (start, end, therms) in enumerate(months, start=1):
        blocks += _summary(page, start, end, label) + _usage(page + 1, start, end, therms, label)
        page += 2
        if n == three_page:
            blocks += _charges(page, start, end)
            page += 1
    return blocks


def _output(blocks: list[dict[str, Any]]) -> dict[str, Any]:
    return {"document_id": "DOC-1", "pages": [], "text_blocks": blocks, "tables": [], "key_value_pairs": [],
            "source_references": []}


def _read(blocks: list[dict[str, Any]], targets: list[dict]) -> list[dict[str, Any]]:
    outcome = StationaryCombustionExtractor().extract(_output(blocks), targets, "EV-1")
    assert outcome.halt_reason is None, outcome.halt_reason
    records: dict[Any, dict[str, Any]] = {}
    for candidate in outcome.candidates:
        records.setdefault(candidate["record_index"], {})[candidate["field_name"]] = candidate
    return [records[key] for key in sorted(records, key=lambda k: (k is None, k))]


def _therms(record: dict[str, Any]) -> float:
    quantity = record["activity_quantity"]["normalized_value"]
    assert record["activity_quantity"]["unit"] == "MMBtu"
    return round(float(quantity) * 10, 3)


def test_a_twelve_statement_gas_bundle_gives_one_record_per_statement(targets: list[dict]) -> None:
    records = _read(_bundle(), targets)  # statement 5 runs over three pages
    assert len(records) == 12
    assert [(r["service_period_start"]["normalized_value"], r["service_period_end"]["normalized_value"])
            for r in records][:3] == [("2024-12-12", "2025-01-12"), ("2025-01-13", "2025-02-11"),
                                      ("2025-02-12", "2025-03-12")]
    assert [_therms(r) for r in records] == pytest.approx([m[2] for m in MONTHS])
    assert {r["fuel_type"]["normalized_value"] for r in records} == {"natural_gas"}
    assert {r["account_number"]["normalized_value"] for r in records} == {ACCOUNT}
    assert {r["supplier_name"]["normalized_value"] for r in records} == {SUPPLIER}
    assert {r["service_address"]["normalized_value"] for r in records} == {ADDRESS}


def test_each_gas_record_keeps_its_own_pages_and_key(targets: list[dict]) -> None:
    outcome = StationaryCombustionExtractor().extract(_output(_bundle()), targets, "EV-1")
    assert outcome.records == 12
    pages: dict[int, int] = {}
    keys: dict[int, str] = {}
    for candidate in outcome.candidates:
        if candidate["field_name"] == "activity_quantity":
            pages[candidate["record_index"]] = candidate["source_reference"]["page_number"]
            keys[candidate["record_index"]] = candidate["source_reference"]["record_key"]
    # statements 1-5 have two pages (usage on pages 3, 5, 7, 9, 11); the 3-page fifth pushes the rest on by one
    assert pages == {1: 3, 2: 5, 3: 7, 4: 9, 5: 11, 6: 14, 7: 16, 8: 18, 9: 20, 10: 22, 11: 24, 12: 26}
    assert len(set(keys.values())) == 12 and "2024-12-12..2025-01-12" in keys[1]


def test_the_first_statement_crossing_the_year_end_is_counted_for_its_days_in_the_year(targets: list[dict]) -> None:
    """12 of its 32 days (12/12/2024 to 01/12/2025) fall in 2025: 3,484.8 therms -> 1,306.8 therms."""

    first = _read(_bundle(), targets)[0]
    start, end = first["service_period_start"]["normalized_value"], first["service_period_end"]["normalized_value"]
    store = RecalcStore()
    store.add("BUNDLE", [{
        "fuel_type": ("natural_gas", None), "activity_quantity": (first["activity_quantity"]["normalized_value"], "MMBtu"),
        "activity_unit": ("MMBtu", None), "service_period_start": (start, None), "service_period_end": (end, None),
        "service_address": (ADDRESS, None)}], canonical_type_id="CT-S1-FUELQTY")
    line = recalculate(store, FACILITIES)["categories"]["stationary_combustion"]["lines"][0]
    assert "prorated_to_reporting_period" in line["flags"]
    assert line["mass_t"]["CO2"] == pytest.approx(348.48 * 12 / 32 * 53.06 / 1000)


def test_a_statement_repeated_from_another_document_is_flagged_and_nothing_is_excluded(targets: list[dict]) -> None:
    """February's statement is also filed as its own document: the existing duplicate check warns."""

    bundle = _read(_bundle(), targets)

    def record(source: dict[str, Any]) -> dict[str, tuple]:
        return {"fuel_type": ("natural_gas", None),
                "activity_quantity": (source["activity_quantity"]["normalized_value"], "MMBtu"),
                "activity_unit": ("MMBtu", None),
                "service_period_start": (source["service_period_start"]["normalized_value"], None),
                "service_period_end": (source["service_period_end"]["normalized_value"], None),
                "account_number": (source["account_number"]["normalized_value"], None),
                "service_address": (source["service_address"]["normalized_value"], None)}

    store = RecalcStore()
    store.add("BUNDLE", [record(r) for r in bundle], canonical_type_id="CT-S1-FUELQTY")
    february = _read(_summary(1, *MONTHS[1][:2]) + _usage(2, *MONTHS[1]), targets)  # the same month, on its own
    assert len(february) == 1
    store.add("FEB-2025", [record(february[0])], canonical_type_id="CT-S1-FUELQTY")
    result = recalculate(store, FACILITIES)
    duplicates = [c for c in result["quality_checks"] if c["check"] == "Q-003"]
    assert len(duplicates) == 1 and duplicates[0]["severity"] == "warning"
    assert set(duplicates[0]["documents"]) == {"BUNDLE", "FEB-2025"}
    assert not result["excluded"]


def test_a_single_gas_bill_with_a_next_read_date_or_an_adjustment_is_never_split(targets: list[dict]) -> None:
    blocks = _summary(1, "01/13/2025", "02/11/2025", next_read="03/12/2025") + _page(2, [
        [(SUPPLIER, 0.07)], [("Meter Read and Usage", 0.07)],
        [("Billing Period:", 0.07), ("01/13/2025 - 02/11/2025", 0.3)],
        [("Billing period adjustment:", 0.07), ("12/12/2024 - 01/12/2025 (rebilled)", 0.3)],
        [("Prior period adjustment:", 0.07), ("12/01/2024 - 12/31/2024", 0.3)],
        [("Meter", 0.075), ("Start Read", 0.3), ("End Read", 0.5), ("Usage (therms)", 0.75)],
        [("GM-0091742", 0.075), ("218,860", 0.3), ("221,775", 0.5), ("2,999.5", 0.75)]])
    records = _read(blocks, targets)
    assert [_therms(r) for r in records] == pytest.approx([2999.5])
    assert records[0]["service_period_start"]["normalized_value"] == "2025-01-13"


def test_a_statement_that_prints_a_meter_read_period_beside_its_billing_period_is_not_split(targets: list[dict]) -> None:
    """The read dates run a few days off the billing dates; only the name most lines carry is the period."""

    blocks = _summary(1, "01/13/2025", "02/11/2025") + _page(2, [
        [(SUPPLIER, 0.07)], [("Meter Read and Usage", 0.07)],
        [("Billing Period:", 0.07), ("01/13/2025 - 02/11/2025", 0.3)],
        [("Read period:", 0.07), ("01/10/2025 - 02/08/2025", 0.3)],
        [("Meter", 0.075), ("Start Read", 0.3), ("End Read", 0.5), ("Usage (therms)", 0.75)],
        [("GM-0091742", 0.075), ("218,860", 0.3), ("221,775", 0.5), ("2,999.5", 0.75)]])
    assert [_therms(r) for r in _read(blocks, targets)] == pytest.approx([2999.5])


def test_a_bundle_whose_statements_carry_no_labelled_period_is_read_whole(targets: list[dict]) -> None:
    """The periods are printed bare ("12/12/2024 - 01/12/2025"): nothing says where a statement starts."""

    blocks: list[dict[str, Any]] = []
    for n, (start, end, therms) in enumerate(MONTHS[:3]):
        blocks += _page(n + 1, [
            [(SUPPLIER, 0.15)], [("Natural Gas Statement", 0.15)], [("Account Number:", 0.07), (ACCOUNT, 0.3)],
            [("Fuel:", 0.07), ("Natural Gas", 0.3)], [(f"{start} - {end}", 0.07)],
            [("Meter", 0.075), ("Start Read", 0.3), ("End Read", 0.5), ("Usage (therms)", 0.75)],
            [("GM-0091742", 0.075), ("215,480", 0.3), ("218,860", 0.5), (f"{therms:,.1f}", 0.75)]])
    records = _read(blocks, targets)
    # exactly what the reader gave before statements were split: the usage tables, all under the first period
    assert [_therms(r) for r in records] == pytest.approx([m[2] for m in MONTHS[:3]])
    assert {r["service_period_start"]["normalized_value"] for r in records} == {None}


def test_a_gas_file_with_two_periods_but_one_reading_is_read_whole(targets: list[dict]) -> None:
    blocks = (_summary(1, *MONTHS[0][:2]) + _usage(2, *MONTHS[0]) + _summary(3, *MONTHS[1][:2]))
    assert [_therms(r) for r in _read(blocks, targets)] == pytest.approx([MONTHS[0][2]])


def test_a_gas_adjustment_block_with_its_own_period_is_never_a_statement(targets: list[dict]) -> None:
    adjustment = _page(3, [[(SUPPLIER, 0.07)], [("Prior Period Adjustment", 0.07)],
                           [("Billing Period:", 0.07), ("12/12/2024 - 01/12/2025", 0.3)],
                           [("Meter", 0.075), ("Start Read", 0.3), ("End Read", 0.5), ("Usage (therms)", 0.75)],
                           [("GM-0091742", 0.075), ("215,480", 0.3), ("218,860", 0.5), ("120.0", 0.75)]])
    blocks = _summary(1, "01/13/2025", "02/11/2025") + _usage(2, "01/13/2025", "02/11/2025", 2999.5) + adjustment
    assert split_statements(StationaryCombustionExtractor()._rows(_output(blocks))).parts is None
    assert [_therms(r) for r in _read(blocks, targets)][0] == pytest.approx(2999.5)


def test_one_page_gas_statements_with_a_usage_box_above_the_period_are_cut_at_the_page_top(targets: list[dict]) -> None:
    blocks: list[dict[str, Any]] = []
    for n, (start, end, therms) in enumerate(MONTHS[:4]):
        blocks += _page(n + 1, [
            [(SUPPLIER, 0.15)], [("Total usage:", 0.07), (f"{therms:,.1f} therms", 0.3)],
            [("Account Number:", 0.07), (ACCOUNT, 0.3)], [("Fuel:", 0.07), ("Natural Gas", 0.3)],
            [("Billing Period:", 0.07), (f"{start} - {end}", 0.3)],
            [("Meter", 0.075), ("Start Read", 0.3), ("End Read", 0.5), ("Usage (therms)", 0.75)],
            [("GM-0091742", 0.075), ("215,480", 0.3), ("218,860", 0.5), (f"{therms:,.1f}", 0.75)]])
    records = _read(blocks, targets)
    assert [(r["service_period_start"]["normalized_value"], _therms(r)) for r in records] == [
        (f"{m[0][6:]}-{m[0][:2]}-{m[0][3:5]}", m[2]) for m in MONTHS[:4]]


def _stacked(top: float, start: str, end: str, therms: float, title: str) -> list[dict[str, Any]]:
    return _page(1, [[(title, 0.15)], [("Account Number:", 0.07), (ACCOUNT, 0.3)], [("Fuel:", 0.07), ("Natural Gas", 0.3)],
                     [("Billing Period:", 0.07), (f"{start} - {end}", 0.3)],
                     [("Meter", 0.075), ("Start Read", 0.3), ("End Read", 0.5), ("Usage (therms)", 0.75)],
                     [("GM-0091742", 0.075), ("215,480", 0.3), ("218,860", 0.5), (f"{therms:,.1f}", 0.75)]], top=top)


def test_two_gas_statements_on_one_page_are_cut_at_the_repeated_title(targets: list[dict]) -> None:
    blocks = (_page(1, [[(SUPPLIER, 0.15)]], top=0.01)
              + _stacked(0.05, *MONTHS[1][:2], MONTHS[1][2], "Natural Gas Statement")
              + _stacked(0.45, *MONTHS[2][:2], MONTHS[2][2], "Natural Gas Statement"))
    assert [_therms(r) for r in _read(blocks, targets)] == pytest.approx([MONTHS[1][2], MONTHS[2][2]])


def test_two_gas_statements_on_one_page_with_no_title_to_cut_at_are_read_whole_with_a_note(targets: list[dict]) -> None:
    blocks = (_page(1, [[(SUPPLIER, 0.15)]], top=0.01)
              + _stacked(0.05, *MONTHS[1][:2], MONTHS[1][2], "Account overview")
              + _stacked(0.45, *MONTHS[2][:2], MONTHS[2][2], "Meter reading"))
    outcome = StationaryCombustionExtractor().extract(_output(blocks), targets, "EV-1")
    assert outcome.notes == [SPLIT_NOTE]  # read whole, as before, and the reviewer is told
    assert outcome.records >= 1


def test_a_gas_bundle_without_its_cover_still_splits(targets: list[dict]) -> None:
    records = _read(_bundle(MONTHS[:4], three_page=0, cover=False), targets)
    assert [_therms(r) for r in records] == pytest.approx([m[2] for m in MONTHS[:4]])


# ---- review findings (19 Nov): previous-bill pages, statement of account, inherited placement, two accounts ----
def _own_page(page: int, heading: str, start: str, end: str, therms: float = 1234.5) -> list[dict[str, Any]]:
    return _page(page, [[(SUPPLIER, 0.07)], [(heading, 0.07)], [("Billing Period:", 0.07), (f"{start} - {end}", 0.3)],
                        [("Total usage:", 0.07), (f"{therms:,.1f} therms", 0.3)]])


@pytest.mark.parametrize("heading", ["Your Previous Bill", "Usage Comparison", "Budget Plan Detail", "Billing History",
                                     "Account Activity"])
def test_a_previous_bill_comparison_or_budget_page_is_never_a_second_gas_statement(
        targets: list[dict], heading: str) -> None:
    """A February bill, then a page of its own that shows another period and a total: one record, February's."""

    blocks = _summary(1, *MONTHS[1][:2]) + _usage(2, *MONTHS[1]) + _own_page(3, heading, *MONTHS[0][:2])
    assert split_statements(StationaryCombustionExtractor()._rows(_output(blocks))).parts is None
    assert [_therms(r) for r in _read(blocks, targets)] == pytest.approx([MONTHS[1][2]])


def _account_statement(page: int, periods: list[tuple[str, str, float]], account: str = ACCOUNT,
                       heading: str = "Statement of Account", total: float | None = None) -> list[dict[str, Any]]:
    """A statement of account: its heading, the account, a line per invoice it lists (number, period) and its total."""

    lines: list[Line] = [[(SUPPLIER, 0.15)], [(heading, 0.15)], [("Account Number:", 0.07), (account, 0.3)]]
    for n, (start, end, _) in enumerate(periods, start=1):
        lines.append([(f"Invoice INV-{page}{n:02d}", 0.07), (f"{start} - {end}", 0.4)])
    lines.append([("Total usage:", 0.07), (f"{(sum(p[2] for p in periods) if total is None else total):,.1f} therms", 0.4)])
    return _page(page, lines)


def _invoice(page: int, month: tuple[str, str, float]) -> list[dict[str, Any]]:
    return _summary(page, *month[:2]) + _usage(page + 1, *month)


F, S_ = MONTHS[1], MONTHS[2]
PERIODS = [(m[0], m[1], m[2]) for m in (F, S_)]
BOTH = [(F[0], F[1], F[2]), (S_[0], S_[1], S_[2])]


def _facts(blocks: list[dict[str, Any]], targets: list[dict]) -> list[tuple[float, str, str]]:
    return [(_therms(r), r["service_period_start"]["normalized_value"], r["service_period_end"]["normalized_value"])
            for r in _read(blocks, targets)]


EXPECTED = [(F[2], "2025-01-13", "2025-02-11"), (S_[2], "2025-02-12", "2025-03-12")]


@pytest.mark.parametrize("where", ["first", "middle", "last"])
def test_a_statement_of_account_that_adds_up_is_left_out_first_middle_or_last(
        targets: list[dict], where: str) -> None:
    """Counted once, from the invoices, each with its own period, wherever the summary sits."""

    one, two = _invoice(10, MONTHS[1]), _invoice(20, MONTHS[2])
    summary = _account_statement(40, BOTH)
    blocks = {"first": summary + one + two, "middle": one + summary + two, "last": one + two + summary}[where]
    outcome = StationaryCombustionExtractor().extract(_output(blocks), targets, "EV-1")
    assert _facts(blocks, targets) == [(pytest.approx(v), a, b) for v, a, b in EXPECTED]
    assert ACCOUNT_SUMMARY_NOTE in outcome.notes and not any("differs" in n for n in outcome.notes)


def test_a_statement_of_account_over_a_single_invoice_page_set_is_left_out(targets: list[dict]) -> None:
    summary = _account_statement(40, [(F[0], F[1], F[2]), (F[0], F[1], 0.0)], total=F[2])
    blocks = summary + _invoice(10, MONTHS[1])
    assert [t[0] for t in _facts(blocks, targets)] == pytest.approx([F[2]])


def test_a_statement_of_account_that_does_not_add_up_keeps_every_record_and_flags_it(targets: list[dict]) -> None:
    blocks = _invoice(10, MONTHS[1]) + _invoice(20, MONTHS[2]) + _account_statement(40, BOTH, total=6200.0)
    outcome = StationaryCombustionExtractor().extract(_output(blocks), targets, "EV-1")
    assert len(_facts(blocks, targets)) == 3  # nothing dropped
    flag = next(n for n in outcome.notes if "differs" in n)
    assert "6,200.0 therm" in flag and "5,553.9 therm" in flag and "check for double counting" in flag
    assert ACCOUNT_SUMMARY_NOTE not in outcome.notes
    flagged = [c for c in outcome.candidates if c["field_name"] == "statement_total_check"]
    assert flagged and all(c["raw_value"] == flag for c in flagged)


def test_a_statement_of_account_with_only_some_of_its_invoices_is_kept_and_flagged(targets: list[dict]) -> None:
    blocks = _invoice(10, MONTHS[1]) + _account_statement(40, [(F[0], F[1], F[2]), (S_[0], S_[1], S_[2])])
    outcome = StationaryCombustionExtractor().extract(_output(blocks), targets, "EV-1")
    assert len(_facts(blocks, targets)) == 2
    assert any("differs" in n and "only part" in n for n in outcome.notes)


def test_a_statement_of_account_with_no_invoice_in_the_file_is_a_reading_of_its_own(targets: list[dict]) -> None:
    other = _account_statement(40, BOTH, account="9999-0000-11")
    blocks = _invoice(10, MONTHS[1]) + other
    outcome = StationaryCombustionExtractor().extract(_output(blocks), targets, "EV-1")
    assert len(_facts(blocks, targets)) == 2 and not any("differs" in n for n in outcome.notes)


def _flag_record(period: bool) -> dict[str, tuple]:
    record: dict[str, tuple] = {
        "fuel_type": ("natural_gas", None), "activity_quantity": (299.95, "MMBtu"), "activity_unit": ("MMBtu", None),
        "account_number": (ACCOUNT, None), "service_address": (ADDRESS, None),
        "statement_total_check": ("Statement of account total 620.0 therms differs from its invoices 555.4 therms; "
                                  "check for double counting.", None)}
    if period:
        record |= {"service_period_start": ("2025-01-13", None), "service_period_end": ("2025-02-11", None)}
    return record


def test_a_flagged_statement_of_account_is_an_open_item_and_the_category_is_incomplete() -> None:
    store = RecalcStore()
    month = {k: v for k, v in _flag_record(True).items() if k != "statement_total_check"}
    store.add("PKG", [month, _flag_record(True)], canonical_type_id="CT-S1-FUELQTY", pages=[2, 5], keys=["r1:A", "r2:B"])
    result = recalculate(store, FACILITIES)
    items = [n for n in result["needs_input"] if n["kind"] == "statement_total_differs"]
    assert len(items) == 1 and "check for double counting" in items[0]["message"]
    # with its own period the flagged record is counted (both, until a reviewer decides) and Q-004 can see it
    assert result["categories"]["stationary_combustion"]["lines"][0]["mass_t"]["CO2"] == pytest.approx(
        2 * 299.95 * 53.06 / 1000)


def test_a_flagged_statement_of_account_with_no_period_counts_nothing_until_a_reviewer_decides() -> None:
    store = RecalcStore()
    month = {k: v for k, v in _flag_record(True).items() if k != "statement_total_check"}
    store.add("PKG", [month, _flag_record(False)], canonical_type_id="CT-S1-FUELQTY", pages=[2, 5], keys=["r1:A", "r2:B"])
    result = recalculate(store, FACILITIES)
    assert [n for n in result["needs_input"] if n["kind"] == "statement_total_differs"]  # still flagged
    line = result["categories"]["stationary_combustion"]["lines"][0]
    assert line["mass_t"]["CO2"] == pytest.approx(299.95 * 53.06 / 1000)  # the one month; not a whole extra year
    assert "prorated_to_reporting_period" not in line["flags"]


def _quarter_summary(page: int, total: float | None = None) -> list[dict[str, Any]]:
    """A statement of account with ONE billing period line over the quarter and a usage table: no invoice listed."""

    quarter = MONTHS[1:4]
    return _page(page, [
        [(SUPPLIER, 0.15)], [("Statement of Account", 0.15)], [("Account Number:", 0.07), (ACCOUNT, 0.3)],
        [("Billing Period:", 0.07), (f"{quarter[0][0]} - {quarter[-1][1]}", 0.3)],
        [("Meter", 0.075), ("Start Read", 0.3), ("End Read", 0.5), ("Usage (therms)", 0.75)],
        [("GM-0091742", 0.075), ("215,480", 0.3), ("218,860", 0.5),
         (f"{(sum(m[2] for m in quarter) if total is None else total):,.1f}", 0.75)]])


QUARTER = [(m[2], m[0][6:] + "-" + m[0][:2] + "-" + m[0][3:5], m[1][6:] + "-" + m[1][:2] + "-" + m[1][3:5])
           for m in MONTHS[1:4]]


@pytest.mark.parametrize("where", ["first", "middle", "last"])
def test_a_single_period_statement_of_account_over_the_quarter_is_found_wherever_it_sits(
        targets: list[dict], where: str) -> None:
    invoices = [_invoice(10 + 10 * n, m) for n, m in enumerate(MONTHS[1:4])]
    summary = _quarter_summary(60)
    blocks = {"first": summary + sum(invoices, []), "middle": invoices[0] + summary + invoices[1] + invoices[2],
              "last": sum(invoices, []) + summary}[where]
    outcome = StationaryCombustionExtractor().extract(_output(blocks), targets, "EV-1")
    assert _facts(blocks, targets) == [(pytest.approx(v), a, b) for v, a, b in QUARTER]
    assert ACCOUNT_SUMMARY_NOTE in outcome.notes


def test_a_single_period_statement_of_account_that_does_not_add_up_is_kept_with_its_period(
        targets: list[dict]) -> None:
    blocks = sum([_invoice(10 + 10 * n, m) for n, m in enumerate(MONTHS[1:4])], []) + _quarter_summary(60, total=8000.0)
    outcome = StationaryCombustionExtractor().extract(_output(blocks), targets, "EV-1")
    facts = _facts(blocks, targets)
    assert len(facts) == 4 and facts[3] == (pytest.approx(8000.0), "2025-01-13", "2025-04-11")
    assert any("differs" in n for n in outcome.notes)


def test_a_statement_of_account_that_prints_no_period_is_flagged_and_has_none(targets: list[dict]) -> None:
    summary = _page(60, [[(SUPPLIER, 0.15)], [("Statement of Account", 0.15)], [("Account Number:", 0.07), (ACCOUNT, 0.3)],
                         [("Invoice INV-001", 0.07)], [("Invoice INV-002", 0.07)],
                         [("Meter", 0.075), ("Start Read", 0.3), ("End Read", 0.5), ("Usage (therms)", 0.75)],
                         [("GM-0091742", 0.075), ("215,480", 0.3), ("218,860", 0.5), ("5,553.9", 0.75)]])
    blocks = _invoice(10, MONTHS[1]) + _invoice(20, MONTHS[2]) + summary
    outcome = StationaryCombustionExtractor().extract(_output(blocks), targets, "EV-1")
    facts = _facts(blocks, targets)
    assert len(facts) == 3 and facts[2][1] is None  # kept, with no period
    assert any("prints no period" in n for n in outcome.notes)


def test_a_two_page_bill_headed_account_statement_keeps_both_meters(targets: list[dict]) -> None:
    """"Your Account Statement" is a bill's title, not a statement of account: meter A on page 1 (1,000 therms)
    and meter B on page 2 (500) are both kept, 1,500 in all."""

    head: list[Line] = [[(SUPPLIER, 0.15)], [("Your Account Statement", 0.15)], [("Account Number:", 0.07), (ACCOUNT, 0.3)],
                        [("Billing Period:", 0.07), (f"{F[0]} - {F[1]}", 0.3)], [("Fuel:", 0.07), ("Natural Gas", 0.3)]]
    table = [("Meter", 0.075), ("Start Read", 0.3), ("End Read", 0.5), ("Usage (therms)", 0.75)]
    blocks = (_page(1, [*head, table, [("GM-A", 0.075), ("1", 0.3), ("2", 0.5), ("1,000.0", 0.75)]])
              + _page(2, [[(SUPPLIER, 0.15)], [("Account Number:", 0.07), (ACCOUNT, 0.3)],
                          [("Billing Period:", 0.07), (f"{F[0]} - {F[1]}", 0.3)], table,
                          [("GM-B", 0.075), ("1", 0.3), ("2", 0.5), ("500.0", 0.75)]]))
    outcome = StationaryCombustionExtractor().extract(_output(blocks), targets, "EV-1")
    assert sorted(t[0] for t in _facts(blocks, targets)) == pytest.approx([500.0, 1000.0])
    assert ACCOUNT_SUMMARY_NOTE not in outcome.notes
    # an account summary heading with only one period listed is not a statement of account either
    alone = _account_statement(1, [(F[0], F[1], F[2])], heading="Account Summary")
    assert account_summary_pages(StationaryCombustionExtractor()._rows(_output(alone))) == set()


def test_a_real_duplicate_still_raises_the_duplicate_warning() -> None:
    """The same month printed twice in a file (one with its meter, one without): Q-003 is shown."""

    store = RecalcStore()
    month = {"fuel_type": ("natural_gas", None), "activity_quantity": (299.95, "MMBtu"), "activity_unit": ("MMBtu", None),
             "service_period_start": ("2025-01-13", None), "service_period_end": ("2025-02-11", None),
             "account_number": (ACCOUNT, None), "service_address": (ADDRESS, None)}
    store.add("PKG", [dict(month), dict(month)], canonical_type_id="CT-S1-FUELQTY", pages=[1, 3],
              keys=["r1", "r2:GM-0091742"])
    found = [c for c in recalculate(store)["quality_checks"] if c["check"] == "Q-003"]
    assert [c["trigger"] for c in found] == ["duplicate_statement_in_same_file"]


def test_later_statements_of_a_bundle_take_the_bundles_facility_account_and_meter(targets: list[dict]) -> None:
    """Only the first statement names the site and the meter, and only the first and the third name the
    account; the others are the same account at the same site."""

    blocks = (_page(1, [[(SUPPLIER, 0.15)], [("Natural Gas Statement", 0.15)], [("Account Number:", 0.07), (ACCOUNT, 0.3)],
                        [("Billing Period:", 0.07), (f"{MONTHS[1][0]} - {MONTHS[1][1]}", 0.3)],
                        [("Facility:", 0.07), (SITE, 0.3)], [("Meter Number:", 0.07), ("GM-0091742", 0.3)]])
              + _usage(2, *MONTHS[1]))
    for n, month in enumerate(MONTHS[2:4]):
        blocks += _page(3 + 2 * n, [[(SUPPLIER, 0.15)], [("Natural Gas Statement", 0.15)],
                                    [("Billing Period:", 0.07), (f"{month[0]} - {month[1]}", 0.3)]])
        blocks += _usage(4 + 2 * n, *month)
    records = _read(blocks, targets)
    assert len(records) == 3
    for field in ("facility_name", "account_number"):
        assert {r[field]["normalized_value"] for r in records} == {SITE if field == "facility_name" else ACCOUNT}
    assert all(r["meter_number"]["normalized_value"] for r in records)


def test_a_statement_with_its_own_account_or_facility_keeps_it(targets: list[dict]) -> None:
    other = "7710-0042-19"
    blocks = (_summary(1, *MONTHS[1][:2]) + _usage(2, *MONTHS[1])
              + _page(3, [[(SUPPLIER, 0.15)], [("Natural Gas Statement", 0.15)], [("Account Number:", 0.07), (other, 0.3)],
                          [("Billing Period:", 0.07), (f"{MONTHS[2][0]} - {MONTHS[2][1]}", 0.3)]])
              + _usage(4, *MONTHS[2])
              + _page(5, [[(SUPPLIER, 0.15)], [("Natural Gas Statement", 0.15)],
                          [("Billing Period:", 0.07), (f"{MONTHS[3][0]} - {MONTHS[3][1]}", 0.3)]])
              + _usage(6, *MONTHS[3]))
    accounts = [r["account_number"]["normalized_value"] for r in _read(blocks, targets)]
    # two accounts are in the file: the third statement names none, and is not given either of them
    assert accounts[:2] == [ACCOUNT, other] and accounts[2] in (None, "")


def test_two_accounts_with_the_same_period_stay_two_statements(targets: list[dict]) -> None:
    other = "7710-0042-19"
    period = MONTHS[1][:2]
    blocks = (_page(1, [[(SUPPLIER, 0.15)], [("Natural Gas Statement", 0.15)], [("Account Number:", 0.07), (ACCOUNT, 0.3)],
                        [("Billing Period:", 0.07), (f"{period[0]} - {period[1]}", 0.3)]]) + _usage(2, *MONTHS[1])
              + _page(3, [[(SUPPLIER, 0.15)], [("Natural Gas Statement", 0.15)], [("Account Number:", 0.07), (other, 0.3)],
                          [("Billing Period:", 0.07), (f"{period[0]} - {period[1]}", 0.3)]]) + _usage(4, *MONTHS[1]))
    records = _read(blocks, targets)
    assert [r["account_number"]["normalized_value"] for r in records] == [ACCOUNT, other]
    assert [_therms(r) for r in records] == pytest.approx([MONTHS[1][2], MONTHS[1][2]])
    # and the recalculation keeps both: different accounts are not the same statement printed twice
    store = RecalcStore()
    rows = [{"fuel_type": ("natural_gas", None), "activity_quantity": (299.95, "MMBtu"), "activity_unit": ("MMBtu", None),
             "service_period_start": ("2025-01-13", None), "service_period_end": ("2025-02-11", None),
             "account_number": (account, None), "service_address": (ADDRESS, None)} for account in (ACCOUNT, other)]
    store.add("TWO", rows, canonical_type_id="CT-S1-FUELQTY", pages=[2, 4], keys=["r1:GM-0091742", "r2:GM-0091742"])
    result = recalculate(store, FACILITIES)
    assert not [c for c in result["quality_checks"] if c["check"] == "Q-003"] and not result["excluded"]
    lines = result["categories"]["stationary_combustion"]["lines"]
    assert sum(line["mass_t"]["CO2"] for line in lines) == pytest.approx(2 * 299.95 * 53.06 / 1000)


def test_a_statement_that_names_its_own_address_inherits_nothing_from_the_bundle(targets: list[dict]) -> None:
    """Zürich names a facility and an address; Basel (same account) names only its own address; a third part names
    nothing. Basel is not given Zürich's facility, and the nameless part is given neither."""

    zurich = _page(1, [[(SUPPLIER, 0.15)], [("Natural Gas Statement", 0.15)], [("Account Number:", 0.07), (ACCOUNT, 0.3)],
                       [("Billing Period:", 0.07), (f"{MONTHS[1][0]} - {MONTHS[1][1]}", 0.3)],
                       [("Facility:", 0.07), (SITE, 0.3)], [("Service Address:", 0.07), (ADDRESS, 0.3)]])
    basel = _page(3, [[(SUPPLIER, 0.15)], [("Natural Gas Statement", 0.15)], [("Account Number:", 0.07), (ACCOUNT, 0.3)],
                      [("Billing Period:", 0.07), (f"{MONTHS[2][0]} - {MONTHS[2][1]}", 0.3)],
                      [("Service Address:", 0.07), ("77 Hafenweg, 4057 Basel", 0.3)]])
    nameless = _page(5, [[(SUPPLIER, 0.15)], [("Natural Gas Statement", 0.15)],
                         [("Billing Period:", 0.07), (f"{MONTHS[3][0]} - {MONTHS[3][1]}", 0.3)]])
    blocks = zurich + _usage(2, *MONTHS[1]) + basel + _usage(4, *MONTHS[2]) + nameless + _usage(6, *MONTHS[3])
    records = _read(blocks, targets)
    facilities = [(r["facility_name"]["normalized_value"], r["service_address"]["normalized_value"]) for r in records]
    assert facilities[0] == (SITE, ADDRESS)
    assert facilities[1] == (None, "77 Hafenweg, 4057 Basel")
    assert facilities[2] == (None, None)
