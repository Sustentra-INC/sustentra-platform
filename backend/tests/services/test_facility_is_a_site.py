"""MVP-234 (EXT-032): the facility of a bill is the site, never the customer or a meter.

Two fictional bills gave the wrong facility. The 12-statement electric bundle printed its site under "Premise:" (singular), a
label the reader did not know, so every record took the customer company. The steam bill printed "Service Location" with its
value to the right of the label, so the reader took the line under the label ("Steam Meter") for the site. A wrong facility
puts emissions on the wrong calculation line; an empty one is asked of the reviewer."""

from __future__ import annotations

import time
from typing import Any

import pytest

from backend.app.services.electricity_extractor import ElectricityExtractor
from backend.app.services.extraction_target_service import ExtractionTargetService
from backend.app.services.stationary_combustion_extractor import _is_a_site_name
from backend.app.services.thermal_extractor import ThermalExtractor
from backend.tests.services.test_statement_bundles import (
    MONTHS, SUPPLIER, Line, _detail, _output, _page, _summary,
)

CUSTOMER = "Staging-Test Foods Inc."
ADDRESS = "410 Mill Road, Springfield, OR 97477"


@pytest.fixture(scope="module")
def elec_targets() -> list[dict]:
    return ExtractionTargetService().get_targets_for_canonical_type("CT-S2-ELEC")


@pytest.fixture(scope="module")
def thermal_targets() -> list[dict]:
    return ExtractionTargetService().get_targets_for_canonical_type("CT-S2-THERMAL")


def _values(outcome: Any, field: str) -> list[Any]:
    return [c["normalized_value"] for c in sorted(outcome.candidates, key=lambda c: c["record_index"] or 0)
            if c["field_name"] == field]


def _statement(page: int, start: str, end: str, site_line: Line | None, customer: str | None = CUSTOMER) -> list[dict[str, Any]]:
    extra: list[Line] = []
    if customer:
        extra.append([("Customer:", 0.07), (customer, 0.3)])
    if site_line:
        extra.append(site_line)
    return _summary(page, start, end, address=ADDRESS, extra=extra)


def _bundle_with(site_for: dict[int, Line | None], customer: str | None = CUSTOMER) -> list[dict[str, Any]]:
    blocks = _page(1, [[(SUPPLIER, 0.15)], [("Annual Statement Package", 0.15)], [("Contents", 0.07)],
                       [("Section", 0.07), ("Billing Period", 0.3), ("Pages", 0.6)]]
                   + [[(f"Statement {n + 1}", 0.07), (f"{s} - {e}", 0.3), (f"{2 * n + 2}-{2 * n + 3}", 0.6)]
                      for n, (s, e, _, _) in enumerate(MONTHS)])
    for n, (start, end, total, on_peak) in enumerate(MONTHS):
        blocks += _statement(2 * n + 2, start, end, site_for.get(n), customer) + _detail(2 * n + 3, start, end, total, on_peak)
    return blocks + _page(2 * len(MONTHS) + 2, [[("Terms and Conditions of Electric Service", 0.07)]])


# ---- the electric bundle: "Premise:" names the site -------------------------------------------------------------
def test_a_premise_label_names_the_site_of_every_statement_in_a_bundle(elec_targets: list[dict]) -> None:
    site: Line = [("Premise:", 0.07), ("Riverside Plant", 0.3)]
    outcome = ElectricityExtractor().extract(_output(_bundle_with({n: site for n in range(12)})), elec_targets, "EV-1")
    assert outcome.records == 12
    assert _values(outcome, "facility_name") == ["Riverside Plant"] * 12
    assert _values(outcome, "service_address") == [ADDRESS] * 12


def test_each_statement_keeps_its_own_site_and_none_leaks_into_another(elec_targets: list[dict]) -> None:
    sites = {0: "North Mill", 1: "South Mill", 2: None, 3: "North Mill"}  # statement 3 prints no site; no customer is printed
    lines: dict[int, Line | None] = {n: [("Premise:", 0.07), (name, 0.3)] if name else None for n, name in sites.items()}
    outcome = ElectricityExtractor().extract(_output(_bundle_with(lines, customer=None)), elec_targets, "EV-1")
    names = _values(outcome, "facility_name")
    assert names[:2] == ["North Mill", "South Mill"] and names[3] == "North Mill"
    assert CUSTOMER not in names
    assert names[2] != "South Mill"  # a statement with no site of its own never takes the one before it


# ---- the steam bill: the value of "Service Location" is on the label's row ------------------------------------------
def _steam(site_value: str, meter_label: str = "Steam Meter", customer: str | None = CUSTOMER) -> dict[str, Any]:
    lines: list[Line] = [
        [("Millrace District Energy", 0.09)], [("Steam & chilled water utility", 0.09)], [("Billing Details", 0.08)],
        *([[("Customer", 0.08), (customer, 0.29)]] if customer else []), [("Account", 0.08), ("MDE-00417", 0.29)],
        [("Service Location", 0.08), (site_value, 0.29)], [(meter_label, 0.08), ("STM-0417-B", 0.29)],
        [("From", 0.08), ("01/01/2025", 0.29)], [("To", 0.08), ("01/31/2025", 0.29)],
        [("Steam Usage:", 0.08), ("970.01 MMBtu", 0.29)],
    ]
    return _output(_page(1, lines))


def test_a_service_location_value_beside_its_label_is_the_site_not_the_meter_line_below(thermal_targets: list[dict]) -> None:
    outcome = ThermalExtractor().extract(_steam(f"Riverside Plant, {ADDRESS}"), thermal_targets, "EV-1")
    assert _values(outcome, "facility_name") == ["Riverside Plant"]
    assert _values(outcome, "service_address") == [f"Riverside Plant, {ADDRESS}"]  # the address as the bill's label prints it


@pytest.mark.parametrize("meter_label", ["Steam Meter", "Electric Meter 2", "Meter No.", "Meter"])
def test_a_service_location_that_is_only_an_address_leaves_the_facility_empty_not_a_meter(thermal_targets: list[dict], meter_label: str) -> None:
    outcome = ThermalExtractor().extract(_steam(ADDRESS, meter_label, customer=None), thermal_targets, "EV-1")
    assert _values(outcome, "facility_name") == [None]
    assert _values(outcome, "service_address") == [ADDRESS]


def _single(*extra: Line) -> dict[str, Any]:
    return _output(_summary(1, "01/01/2025", "01/31/2025", extra=[*extra, [("Total kWh Used:", 0.07), ("12,000 kWh", 0.3)]]))


# ---- what is never a site -------------------------------------------------------------------------------------------
@pytest.mark.parametrize("value", ["Steam Meter", "Electric Meter 2", "Meter No.", "Gas Meter #4", "Meter", "Rate Schedule LGS-3",
                                   "Electric Service", "Natural Gas", "Account Summary", "Billing Details"])
def test_meter_rate_commodity_and_heading_wording_is_never_a_facility(elec_targets: list[dict], value: str) -> None:
    outcome = ElectricityExtractor().extract(_single([("Facility:", 0.07), (value, 0.3)]), elec_targets, "EV-1")
    assert _values(outcome, "facility_name") != [value]
    assert _values(outcome, "service_address") == [ADDRESS]


@pytest.mark.parametrize("name", ["Meter Street Plant", "Rate Street Warehouse", "Electric Avenue Depot",
                                  "Northgate Provisions Inc. – Sacramento Warehouse"])
def test_a_site_whose_name_contains_meter_or_a_company_is_kept(elec_targets: list[dict], name: str) -> None:
    outcome = ElectricityExtractor().extract(
        _single([("Customer:", 0.07), ("Northgate Provisions Inc.", 0.3)], [("Facility:", 0.07), (name, 0.3)]), elec_targets, "EV-1")
    assert _values(outcome, "facility_name") == [name]


def test_a_delivered_to_heading_beside_another_label_keeps_its_block_below(elec_targets: list[dict]) -> None:
    """Propane layout: "Sold To: | Delivered To: | Invoice #: BK-1" are headings; the site is the block under its own."""

    def tight(lines: list[Line]) -> list[dict[str, Any]]:  # rows close enough that a block's lines read as one block
        return [{"block_id": f"t{n}-{m}", "page_number": 1, "text": text, "confidence": None, "source_reference_id": None,
                 "bounding_box": {"left": left, "top": 0.05 + n * 0.016, "width": 0.1, "height": 0.012}}
                for n, cells in enumerate(lines) for m, (text, left) in enumerate(cells)]

    blocks = tight([
        [("Blue Kettle Propane Supply", 0.18)], [("INVOICE", 0.83)],
        [("Sold To:", 0.07), ("Delivered To:", 0.36), ("Invoice #:", 0.64), ("BK-2025-118844", 0.76)],
        [(CUSTOMER, 0.07), (CUSTOMER, 0.36), ("Invoice Date:", 0.64), ("11/21/2025", 0.76)],
        [("Attn: Accounts Payable", 0.07), ("Riverside Plant", 0.36), ("Customer #:", 0.64), ("C-008831", 0.76)],
        [("PO Box 7718", 0.07), ("410 Mill Road", 0.36)], [("Springfield, OR 97477", 0.07), ("Springfield, OR 97477", 0.36)],
        [("Billing Period:", 0.07), ("01/01/2025 - 01/31/2025", 0.3)], [("Total kWh Used:", 0.07), ("12,000 kWh", 0.3)]])
    outcome = ElectricityExtractor().extract(_output(blocks), elec_targets, "EV-1")
    assert _values(outcome, "facility_name") == ["Riverside Plant"]


@pytest.mark.parametrize("value", ["Meter " + "1 " * 2000 + "!x", "steam " * 2000 + "x", "Meter " + "# 1 " * 2000 + "!",
                                   "Meter " + "a-1-1 " * 2000 + "!", "Rate schedule " + " " * 5000 + "\n"])
def test_a_long_hostile_value_is_judged_quickly(value: str) -> None:
    started = time.perf_counter()
    _is_a_site_name(value)
    assert time.perf_counter() - started < 1
