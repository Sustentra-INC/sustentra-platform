"""Key-label parsing and the field-family mapping table: synthetic labels only."""

from datetime import date

import pytest

from backend.tools.accuracy.keys import parse_label, record_ordinal
from backend.tools.accuracy.mapping import META, REPORTING, UNMAPPED, family_of


def fam(label: str) -> str:
    p = parse_label(label)
    return family_of(p.base, p.qualifier)


@pytest.mark.parametrize("label, family", [
    ("supplier", "supplier"), ("account number", "account"), ("account_number", "account"),
    ("meter number", "meter"), ("statement date", "statement_date"), ("statement_date", "statement_date"),
    ("service period start", "period_start"), ("service_period_end", "period_end"),
    ("activity quantity (total electricity)", "activity_quantity"), ("activity_quantity", "activity_quantity"),
    ("activity quantity (statement total)", "activity_total"), ("activity quantity (diesel)", "activity_total"),
    ("activity_quantity_gasoline", "activity_total"), ("activity quantity (converted)", "converted_quantity"),
    ("[row 2 03/05/2031] fuel added", "activity_quantity"), ("[VEH-9 Jan-31] distance", "distance"),
    ("run 03/05/2031 run_hours", "run_hours"), ("run 03/05/2031 gallons_added", "activity_quantity"),
    ("on_peak_kwh [MTR-70]", "period_usage"), ("meter start read", "meter_read_start"),
    ("meter_reading_current", "meter_read_end"), ("total amount due", "total_amount"),
    ("[Apr 2031] billed demand", "billed_demand"), ("fuel type", "fuel_type"), ("[VEH-9] model year", "model_year"),
    ("[entry 3 03/14/2031 EQ-03] technician", "technician"), ("emission_factor", REPORTING),
    ("CO2_location", REPORTING), ("note: period crosses year end; days in 2031 = 16 of 31", META),
    ("platform_action", META), ("page_count", META), ("some new field", UNMAPPED), ("full charge", "equipment_capacity"),
    ("[EQ-01] full charge", "equipment_capacity"), ("service_address", "service_address"),
    ("2031-06 fuel", "activity_quantity"), ("2031-06 distance converted", "converted_quantity"),
])
def test_family_mapping(label: str, family: str) -> None:
    assert fam(label) == family


def test_selector_parts() -> None:
    p = parse_label("[row 2 03/05/2031] fuel added")
    assert p.selector.dates == (date(2031, 3, 5),) and p.base == "fuel added"
    p = parse_label("[VEH-9 Jan-31] distance")
    assert p.selector.ids == ("veh9",) and p.selector.month == 1 and p.selector.year == 2031
    p = parse_label("[Apr 2031] service period start")
    assert p.selector.month == 4 and p.selector.year == 2031 and p.base == "service period start"
    p = parse_label("January service_period_end")
    assert p.selector.month == 1 and p.base == "service period end"
    p = parse_label("on_peak_kwh [MTR-70]")
    assert p.selector.ids == ("mtr70",) and p.base == "on peak kwh"
    p = parse_label("row 12 gallons (VEH-9 03/04/2031)")
    assert p.selector.ids == ("veh9",) and p.selector.dates == (date(2031, 3, 4),) and p.base == "gallons"
    p = parse_label("activity quantity (total electricity)")
    assert p.selector.empty and p.qualifier == "total electricity"
    assert parse_label("supplier").selector.empty
    assert parse_label("2031-06 fuel").selector.month == 6


def test_record_ordinal() -> None:
    assert record_ordinal("row 2", "log.csv") == 1  # the header is row 1
    assert record_ordinal("row 2", "log.xlsx") == 1
    assert record_ordinal("p1 row 2", "bill.pdf") == 2
    assert record_ordinal("rows 2-4 (derived sum)", "log.xlsx") is None
    assert record_ordinal("p1", "bill.pdf") is None
