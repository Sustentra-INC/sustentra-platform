"""Meter numbers and statement dates read as evidence on every bill type (EXT-027).

Both are display only: they never feed a calculation. A statement date comes only from a labelled field (never the
service period, never a due date); a meter number follows the account number's guard (at least 3 characters, a digit,
not a phone number) and each meter of a bill of several meters keeps its own."""

from __future__ import annotations

from typing import Any

import pytest

from backend.app.reference.extraction_config_loader import load_default_extraction_configs
from backend.app.services.electricity_extractor import ElectricityExtractor
from backend.app.services.extraction_target_service import ExtractionTargetService
from backend.app.services.mobile_combustion_extractor import MobileCombustionExtractor
from backend.app.services.refrigerant_extractor import RefrigerantServiceExtractor
from backend.app.services.stationary_combustion_extractor import (
    StationaryCombustionExtractor,
    meter_value,
    statement_date_value,
)
from backend.app.services.thermal_extractor import ThermalExtractor
from backend.tests.services.test_calculation_lines import GAS_KC, KC, STL, _elec, _gas, _tree_service
from backend.tests.services.test_engagement_recalculation_service import FakeStore, _own
from backend.tests.services.test_facility_identifiers import _recalc


def _output(text: str) -> dict[str, Any]:
    return {"document_id": "DOC-1", "pages": [{"page_number": 1, "text": text}],
            "text_blocks": [{"block_id": "b1", "page_number": 1, "text": text, "confidence": None,
                             "bounding_box": None, "source_reference_id": None}],
            "tables": [], "key_value_pairs": [], "source_references": []}


def _targets(canonical: str) -> list[dict]:
    return ExtractionTargetService().get_targets_for_canonical_type(canonical)


def _read(extractor: Any, canonical: str, text: str) -> list[dict]:
    outcome = extractor.extract(_output(text), _targets(canonical), "EV-1")
    assert outcome.halt_reason is None, outcome.halt_reason
    return outcome.candidates


def _value(candidates: list[dict], field: str, record_index: int | None = None) -> Any:
    found = [c for c in candidates if c["field_name"] == field and c["record_index"] == record_index]
    assert found, f"no {field} candidate"
    return found[0]["normalized_value"]


ELEC = "CT-S2-ELEC"
GAS = "CT-S1-FUELQTY"


def _bill(*lines: str) -> str:
    return "\n".join(["Müller Strom AG – Zürich · Electricity Bill", "Customer Name\tMüller Käserei AG",
                      "Service Address\t12 Bahnhofstraße, 8001 Zürich", "Account Number\tMS-4417-2290",
                      "Service Period\tJan 1, 2025 to Jan 31, 2025", *lines, "Total kWh Used\t12,450 kWh"])


# --- the config: both fields are targets on every bill type --------------------------------------------------------
def test_meter_and_statement_date_are_rule_targets_on_every_bill_type() -> None:
    service = ExtractionTargetService()
    for canonical in (GAS, ELEC, "CT-S2-THERMAL"):
        assert {"meter_number", "statement_date"} <= {t["field_id"] for t in service.get_targets_for_canonical_type(canonical)}
    for canonical in ("CT-S1-MOBFUEL", "CT-S1-REFRSVC"):
        fields = {t["field_id"] for t in service.get_targets_for_canonical_type(canonical)}
        assert "statement_date" in fields and "meter_number" not in fields
    configs = {(c.canonical_type_id, c.field_id): c for c in load_default_extraction_configs()}
    for key in (("CT-S1-FUELQTY", "meter_number"), ("CT-S2-ELEC", "meter_number"), ("CT-S2-THERMAL", "meter_number")):
        assert not configs[key].ai_only and configs[key].required_status == "optional"  # Claude fills it when the rules miss it
    assert all(c.required_status == "optional" and c.value_type == "date" for k, c in configs.items()
               if k[1] == "statement_date")


# --- the statement date --------------------------------------------------------------------------------------------
@pytest.mark.parametrize("lines", [
    ("Statement Date\t05/01/2025", "Due Date\t05/21/2025"),
    ("Due Date\t05/21/2025", "Statement Date\t05/01/2025"),
    ("Statement Date: 05/01/2025   Due Date: 05/21/2025",),
    ("Due Date: 05/21/2025   Statement Date: 05/01/2025",),
    ("Bill Date\t05/01/2025", "Payment Due\t05/21/2025"),
    ("STMT DATE 05/01/2025", "DUE DATE 05/21/2025"),
    ("Invoice Date: May 1, 2025 · Due Date: May 21, 2025",),
])
def test_the_statement_date_is_the_labelled_date_never_the_due_date(lines: tuple[str, ...]) -> None:
    candidates = _read(ElectricityExtractor(), ELEC, _bill(*lines))
    assert _value(candidates, "statement_date") == "2025-05-01"


def test_a_due_date_alone_is_not_a_statement_date_and_the_service_period_is_never_one() -> None:
    candidates = _read(ElectricityExtractor(), ELEC, _bill("Due Date\t05/21/2025"))
    assert _value(candidates, "statement_date") is None
    assert _value(candidates, "service_period_start") == "2025-01-01"  # the period is read as the period, nothing else


@pytest.mark.parametrize("value", ["03/01/2025 - 03/31/2025", "03/01/2025 to 03/31/2025", "Jan 1, 2025 – Jan 31, 2025",
                                   "Due 05/21/2025", "see page 2"])
def test_a_range_or_words_before_a_date_are_not_a_statement_date(value: str) -> None:
    assert statement_date_value(value) is None
    candidates = _read(ElectricityExtractor(), ELEC, _bill(f"Billing Date\t{value}"))
    assert _value(candidates, "statement_date") is None


def test_a_revised_bill_gives_its_own_date_not_the_one_it_replaces() -> None:
    text = _bill("This statement replaces the statement dated 04/04/2025 for service 01/01/2025 – 01/31/2025.",
                 "Statement Date\t05/16/2025", "Due Date\t06/05/2025")
    assert _value(_read(ElectricityExtractor(), ELEC, text), "statement_date") == "2025-05-16"


def test_a_statement_date_is_read_on_a_gas_bill_and_a_fuel_invoice() -> None:
    gas = "National Fuel Gas Company\nAccount Number\tACC-100\nStatement Date\t02/04/2025\nService Period\tJan 1, 2025 to Jan 31, 2025\nTotal Usage\t32,400 MMBtu\n"
    assert _value(_read(StationaryCombustionExtractor(), GAS, gas), "statement_date") == "2025-02-04"
    propane = "Sierra Propane Co.\nInvoice Date\t12/05/2025\nDelivery Date\t12/03/2025\nFuel\tPropane\nQuantity\t350 gallons\n"
    assert _value(_read(StationaryCombustionExtractor(), GAS, propane), "statement_date") == "2025-12-05"


def test_a_statement_date_is_read_on_a_fleet_fuel_statement_and_a_refrigerant_invoice() -> None:
    fleet = ("Quartz Fleet Cards\nAccount QF-6620-1187 · Statement date 10/03/2025\nDate\tDescription\tFuel\tGallons\n"
             "07/01/2025\tTRK-01 Diesel #2\tDiesel\t42.5\n")
    assert _value(_read(MobileCombustionExtractor(), "CT-S1-MOBFUEL", fleet), "statement_date") == "2025-10-03"
    refrigerant = ("Köhlmann Cooling Service GmbH\nInvoice Date\t09/17/2025\nService Date\t09/15/2025\nEquipment\tRACK-A\n"
                   "Refrigerant\tR-404A\nRefrigerant added\t12.5 lb\n")
    assert _value(_read(RefrigerantServiceExtractor(), "CT-S1-REFRSVC", refrigerant), "statement_date") == "2025-09-17"


# --- the meter number ----------------------------------------------------------------------------------------------
@pytest.mark.parametrize("line, expected", [
    ("Meter Number\tM-55012", "M-55012"), ("Meter No.\tGM-0083315", "GM-0083315"), ("Meter #: 1009447183", "1009447183"),
    ("Meter:               RS-7781204", "RS-7781204"), ("METER GM-0127764 PREV 40,211 CURR 41,447 USED 1,236 CCF", "GM-0127764"),
    ("Service 01/01/2025 – 01/31/2025 · 31 days · Meter: 1009447183 · Multiplier 1", "1009447183"),
    ("Meter ID\tZähler-4417/B", "Zähler-4417/B"),
])
def test_a_meter_number_is_read_from_a_labelled_field(line: str, expected: str) -> None:
    assert _value(_read(ElectricityExtractor(), ELEC, _bill(line)), "meter_number") == expected


@pytest.mark.parametrize("line", [
    "Meter Reader Line\t(555) 123-4567",   # a phone number, whatever it is labelled
    "Meter: (555) 123-4567", "Meter No: 555-123-4567", "Meter: 555 123 4567",
    "Meter Reading\t04512", "Meter Charges\t$45.00", "Meter & Service Charge\t1 month\t$65.00",
    "Meter Totalizer\t10,442", "Meter: 12", "Meter: ABC", "Meter: 05/01/2025", "Your meter could not be read on 10/31/2025 (access).",
    "Meter 1 – Tacoma Distribution Center · Service Address: 2200 PORT OF TACOMA RD",
])
def test_a_meter_number_never_comes_from_a_phone_number_a_reading_or_prose(line: str) -> None:
    assert _value(_read(ElectricityExtractor(), ELEC, _bill(line)), "meter_number") is None


def test_the_meter_guard_is_the_account_guard() -> None:
    assert meter_value("GM-0083315 extra words after") == "GM-0083315"
    for bad in ("", "12", "ab", "ABCDE", "$45.00", "(555) 123-4567", "555-123-4567", "05/01/2025"):
        assert meter_value(bad) is None


def test_each_meter_of_a_bill_keeps_its_own_number_and_the_statement_date_is_shared() -> None:
    text = ("Valley Power and Light - Electric Service Statement\nFacility\tWest Warehouse\nAccount Number\tVPL-002-3391\n"
            "Statement Date\t04/05/2025\nBilling Period\t03/01/2025 - 03/31/2025\n"
            "Meter Number\tPrevious Read\tCurrent Read\tMultiplier\tkWh Used\tDemand (kW)\n"
            "M-55012\t104,220\t116,670\t1\t12,450\t85\nM-55013\t20,100\t24,300\t1\t4,200\t30\n")
    candidates = _read(ElectricityExtractor(), ELEC, text)
    assert [_value(candidates, "meter_number", i) for i in (1, 2)] == ["M-55012", "M-55013"]
    assert [_value(candidates, "statement_date", i) for i in (1, 2)] == ["2025-04-05", "2025-04-05"]


def test_two_labelled_meters_and_no_meter_column_give_no_single_meter() -> None:
    text = _bill("Meter No: A-1001", "Meter No: B-2002")
    assert _value(_read(ElectricityExtractor(), ELEC, text), "meter_number") is None  # which one would it be?
    one = _bill("Meter No: A-1001", "Meter No: A-1001")
    assert _value(_read(ElectricityExtractor(), ELEC, one), "meter_number") == "A-1001"


def test_a_steam_bill_reads_its_meter_from_a_steam_meter_column() -> None:
    text = ("Capitol Thermal Utilities · District Steam Statement\nCustomer Account\tCTU-STM-00417\nStatement Date\t02/06/2025\n"
            "Service Period: 01/01/2025 – 01/31/2025 (31 days)\nSteam Meter\tPrevious Read (Mlb)\tCurrent Read (Mlb)\tSteam Used (Mlb)\n"
            "STM-0417-A\t3,482.6\t3,701.1\t218.5\n")
    candidates = _read(ThermalExtractor(), "CT-S2-THERMAL", text)
    assert _value(candidates, "meter_number") == "STM-0417-A"
    assert _value(candidates, "statement_date") == "2025-02-06"


def test_an_hour_meter_column_is_not_a_meter_number() -> None:
    text = ("Generator log\nDate\tgenerator\tHour Meter\tGallons added\n01/07/2025\tG-1\t1234.5\t42\n")
    extractor = StationaryCombustionExtractor()
    rows = extractor._rows(_output(text))
    assert extractor._bill_meter(rows) is None


# --- display only: no calculation reads them -----------------------------------------------------------------------
def _store(with_fields: bool) -> FakeStore:
    extra = {"meter_number": "GM-0083315", "statement_date": "2025-02-04"} if with_fields else {}
    store = FakeStore()
    store.add_document("G1", "CT-S1-FUELQTY", [_gas(1000, **extra)])
    store.add_document("E1", "CT-S2-ELEC", [{**_elec(10), **{k: (v, None) for k, v in extra.items()}}])
    return store


def test_the_numbers_do_not_change_when_the_two_fields_are_added() -> None:
    facilities = [KC, STL]
    assert _recalc(_store(True), facilities) == _recalc(_store(False), facilities)


def test_the_workpaper_exports_list_the_two_fields_like_any_extracted_value() -> None:
    from backend.app.services.engagement_recalculation_service import EngagementRecalculationService

    store = _store(True)
    register = EngagementRecalculationService(store, store, store).evidence_register("ENG-1", _own)
    fields = {(v["file_name"], v["field"]) for v in register["values"]}
    assert ("G1.pdf", "meter_number") in fields and ("E1.pdf", "statement_date") in fields


def test_the_schedule_shows_the_meter_number_and_the_statement_date() -> None:
    store = FakeStore()
    store.add_document("G1", "CT-S1-FUELQTY", [_gas(1000, meter_number="GM-0083315", statement_date="2025-02-04")])
    store.add_document("G2", "CT-S1-FUELQTY", [_gas(500, start="2025-02-01", end="2025-02-28", meter_number="gm-0083315")])
    store.add_document("G3", "CT-S1-FUELQTY", [_gas(700, start="2025-03-01", end="2025-03-31")])
    engagement = {"id": "ENG-1", "reporting_period_start": "2025-01-01", "reporting_period_end": "2025-03-31",
                  "settings": {"facilities": [KC, STL]}}
    schedule = _tree_service(store).schedule(engagement, _own, GAS_KC)
    assert schedule is not None
    groups = {g["label"]: g for g in schedule["identifier_groups"]}
    meter = groups["Meter number"]
    assert meter["documents_total"] == 3 and meter["documents_with"] == 2  # a read fills it; one bill prints none
    assert [v["value"] for v in meter["values"]] == ["GM-0083315"]  # spelled alike once
    date = groups["Statement date"]
    assert date["documents_with"] == 1 and [v["value"] for v in date["values"]] == ["2025-02-04"]
