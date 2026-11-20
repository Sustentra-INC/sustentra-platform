"""A statement's usage carries that statement's own printed period: a page with no usage never supplies it.

Monthly interim notices (a period and no usage) before or after a real quarterly "Statement of Account" bill
used to give the bill's total the first notice's period.
"""

from __future__ import annotations

from typing import Any

import pytest

from backend.app.services.extraction_target_service import ExtractionTargetService
from backend.tests.services.recalc_store import RecalcStore, recalculate
from backend.tests.services.test_gas_statement_bundles import (
    ACCOUNT, ADDRESS, FACILITIES, MONTHS, SUPPLIER, Line, _output, _page, _read, _therms)


@pytest.fixture(scope="module")
def targets() -> list[dict]:
    return ExtractionTargetService().get_targets_for_canonical_type("CT-S1-FUELQTY")


def _notice(page: int, start: str, end: str) -> list[dict[str, Any]]:
    """A monthly interim notice: its period and an estimate of charges, no usage at all."""

    return _page(page, [[(SUPPLIER, 0.15)], [("Interim Notice", 0.15)], [("Account Number:", 0.07), (ACCOUNT, 0.3)],
                        [("Billing Period:", 0.07), (f"{start} - {end}", 0.3)],
                        [("Estimated charges to date", 0.07), ("$2,100.00", 0.5)]])


def _bill(page: int, start: str, end: str, therms: float) -> list[dict[str, Any]]:
    """A quarterly Statement of Account: one period line over the quarter, then its usage table."""

    lines: list[Line] = [[(SUPPLIER, 0.15)], [("Statement of Account", 0.15)], [("Account Number:", 0.07), (ACCOUNT, 0.3)],
                         [("Billing Period:", 0.07), (f"{start} - {end}", 0.3)],
                         [("Meter", 0.075), ("Start Read", 0.3), ("End Read", 0.5), ("Usage (therms)", 0.75)],
                         [("GM-0091742", 0.075), ("215,480", 0.3), ("218,860", 0.5), (f"{therms:,.1f}", 0.75)]]
    return _page(page, lines)


QUARTER = (MONTHS[1][0], MONTHS[3][1], 7654.1)  # 01/13/2025 - 04/11/2025
YEAR_END = (MONTHS[0][0], MONTHS[2][1], 9038.7)  # 12/12/2024 - 03/12/2025


def _notices(months: list[tuple[str, str, float]], first_page: int) -> list[dict[str, Any]]:
    return sum([_notice(first_page + n, m[0], m[1]) for n, m in enumerate(months)], [])


def _period(record: dict[str, Any]) -> tuple[str, str]:
    return record["service_period_start"]["normalized_value"], record["service_period_end"]["normalized_value"]


def test_notices_before_the_bill_do_not_supply_its_period(targets: list[dict]) -> None:
    blocks = _notices(MONTHS[1:4], 1) + _bill(10, *QUARTER)
    records = _read(blocks, targets)
    assert [_therms(r) for r in records] == pytest.approx([7654.1])
    assert _period(records[0]) == ("2025-01-13", "2025-04-11")  # the quarter, not the first notice's month


def test_notices_after_the_bill_do_not_supply_its_period(targets: list[dict]) -> None:
    blocks = _bill(1, *QUARTER) + _notices(MONTHS[1:4], 2)
    records = _read(blocks, targets)
    assert [_therms(r) for r in records] == pytest.approx([7654.1])
    assert _period(records[0]) == ("2025-01-13", "2025-04-11")


def test_a_bill_whose_period_is_on_its_cover_page_still_takes_it_from_there(targets: list[dict]) -> None:
    """The nearest earlier page that prints a period is the statement's own cover: that is not a notice."""

    cover = _page(2, [[(SUPPLIER, 0.15)], [("Statement of Account", 0.15)], [("Account Number:", 0.07), (ACCOUNT, 0.3)],
                      [("Billing Period:", 0.07), (f"{QUARTER[0]} - {QUARTER[1]}", 0.3)]])
    usage = _page(3, [[(SUPPLIER, 0.07)], [("Meter Read and Usage", 0.07)],
                      [("Meter", 0.075), ("Start Read", 0.3), ("End Read", 0.5), ("Usage (therms)", 0.75)],
                      [("GM-0091742", 0.075), ("215,480", 0.3), ("218,860", 0.5), ("7,654.1", 0.75)]])
    records = _read(_notices(MONTHS[1:2], 1) + cover + usage, targets)
    assert [_therms(r) for r in records] == pytest.approx([7654.1])
    assert _period(records[0]) == ("2025-01-13", "2025-04-11")


def test_a_quarter_across_the_year_end_is_prorated_on_its_own_period(targets: list[dict]) -> None:
    """12/12/2024 - 03/12/2025 is 91 days, 71 of them in 2025 (Jan 1 to Mar 12); the first notice's month
    (12/12/2024 - 01/12/2025: 12 of 32 days) would prorate it wrongly."""

    blocks = _notices(MONTHS[0:3], 1) + _bill(10, *YEAR_END)
    record = _read(blocks, targets)[0]
    assert _period(record) == ("2024-12-12", "2025-03-12")
    store = RecalcStore()
    store.add("BILL", [{
        "fuel_type": ("natural_gas", None), "activity_quantity": (record["activity_quantity"]["normalized_value"], "MMBtu"),
        "activity_unit": ("MMBtu", None), "service_period_start": (_period(record)[0], None),
        "service_period_end": (_period(record)[1], None), "service_address": (ADDRESS, None)}],
        canonical_type_id="CT-S1-FUELQTY")
    line = recalculate(store, FACILITIES)["categories"]["stationary_combustion"]["lines"][0]
    assert "prorated_to_reporting_period" in line["flags"]
    assert line["mass_t"]["CO2"] == pytest.approx(903.87 * 71 / 91 * 53.06 / 1000)


# ---- a period that is only mentioned on the usage page never beats the statement's labelled one ----------------
def _cover(page: int, start: str, end: str, title: str = "Natural Gas Statement") -> list[dict[str, Any]]:
    return _page(page, [[(SUPPLIER, 0.15)], [(title, 0.15)], [("Account Number:", 0.07), (ACCOUNT, 0.3)],
                        [("Billing Period:", 0.07), (f"{start} - {end}", 0.3)], [("Fuel:", 0.07), ("Natural Gas", 0.3)]])


def _usage_page(page: int, extra: list[Line], therms: float = 2999.5) -> list[dict[str, Any]]:
    return _page(page, [[(SUPPLIER, 0.07)], [("Meter Read and Usage", 0.07)], *extra,
                        [("Meter", 0.075), ("Start Read", 0.3), ("End Read", 0.5), ("Usage (therms)", 0.75)],
                        [("GM-0091742", 0.075), ("215,480", 0.3), ("218,860", 0.5), (f"{therms:,.1f}", 0.75)]])


@pytest.mark.parametrize("extra", [
    [[("Compared with your previous billing period: 12/12/2024 - 01/12/2025", 0.07)]],
    [[("Same month last year", 0.07)], [("01/13/2024 - 02/11/2024", 0.07)]],
    [[("Same month last year", 0.07)], [("Billing Period:", 0.07), ("01/13/2024 - 02/11/2024", 0.3)]],
    [[("Rates effective 01/01/2025 through 12/31/2025", 0.07)]],
], ids=["compared", "same_month_last_year", "labelled_under_last_year", "rates_effective"])
def test_a_gas_usage_page_that_only_mentions_another_period_keeps_the_statements_labelled_one(
        targets: list[dict], extra: list[Line]) -> None:
    blocks = _cover(1, MONTHS[1][0], MONTHS[1][1]) + _usage_page(2, extra)
    records = _read(blocks, targets)
    assert [_therms(r) for r in records] == pytest.approx([2999.5])
    assert _period(records[0]) == ("2025-01-13", "2025-02-11")


@pytest.mark.parametrize("extra", [
    [[("Compared with last period: 12/16/2024 - 01/15/2025", 0.07)]],
    [[("Rates effective 01/01/2025 through 12/31/2025", 0.07)]],
], ids=["compared", "rates_effective"])
def test_an_electricity_meter_page_that_only_mentions_another_period_keeps_the_bills_labelled_one(
        extra: list[Line]) -> None:
    from backend.app.services.electricity_extractor import ElectricityExtractor

    targets = ExtractionTargetService().get_targets_for_canonical_type("CT-S2-ELEC")
    cover = _page(1, [[(SUPPLIER, 0.15)], [("Electric Service Statement", 0.15)], [("Account Number:", 0.07), (ACCOUNT, 0.3)],
                      [("Billing Period:", 0.07), ("01/16/2025 - 02/15/2025", 0.3)]])
    meter = _page(2, [[(SUPPLIER, 0.07)], [("Meter Read and Usage", 0.07)], *extra,
                      [("Meter", 0.075), ("Start Read", 0.3), ("End Read", 0.5), ("Total kWh", 0.75)],
                      [("M-1", 0.075), ("1", 0.3), ("2", 0.5), ("135,630 kWh", 0.75)]])
    outcome = ElectricityExtractor().extract(_output(cover + meter), targets, "EV-1")
    got = {c["field_name"]: c["normalized_value"] for c in outcome.candidates}
    assert (got["service_period_start"], got["service_period_end"]) == ("2025-01-16", "2025-02-15")


def test_a_notice_between_the_cover_and_the_usage_is_passed_over(targets: list[dict]) -> None:
    blocks = _cover(1, MONTHS[1][0], MONTHS[1][1]) + _notice(2, *MONTHS[2][:2]) + _usage_page(3, [])
    records = _read(blocks, targets)
    assert _period(records[0]) == ("2025-01-13", "2025-02-11")
