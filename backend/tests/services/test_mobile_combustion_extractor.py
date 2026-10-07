from __future__ import annotations

from typing import Any

import pytest

from backend.app.services.extraction_target_service import ExtractionTargetService
from backend.app.services.mobile_combustion_extractor import (
    MobileCombustionExtractor,
    mask_card_numbers,
    normalize_mobile_fuel,
)
from backend.app.services.stationary_combustion_extractor import HALT_UNREADABLE, HALT_UNSUPPORTED


@pytest.fixture(scope="module")
def targets() -> list[dict]:
    return ExtractionTargetService().get_targets_for_canonical_type("CT-S1-MOBFUEL")


def _text_output(text: str, document_id: str = "DOC-1") -> dict[str, Any]:
    return {
        "document_id": document_id,
        "pages": [{"page_number": 1, "text": text}],
        "text_blocks": [{"block_id": "b1", "page_number": 1, "text": text, "confidence": None,
                         "bounding_box": None, "source_reference_id": None}],
        "tables": [], "key_value_pairs": [], "source_references": [],
    }


def _by_field(candidates: list[dict], record_index: int | None = None) -> dict[str, dict]:
    return {c["field_name"]: c for c in candidates if c["record_index"] == record_index}


# --- fuel type / blend normalization -------------------------------------------------------
@pytest.mark.parametrize(
    ("text", "fuel", "blend"),
    [
        ("Unleaded Regular", "gasoline", None),
        ("UNL REG 87", "gasoline", None),
        ("Premium Unleaded", "gasoline", None),
        ("Gasoline E10", "gasoline", 10),
        ("E85 Flex Fuel", "e85", 85),
        ("Petrol", "gasoline", None),
        ("Diesel #2", "diesel", None),
        ("ULSD", "diesel", None),
        ("Dyed Diesel (off-road)", "diesel", None),
        ("B20 Biodiesel blend", "diesel", 20),
        ("Diesel B5", "diesel", 5),
        ("B100", "biodiesel", 100),
        ("Biodiesel", "biodiesel", 100),
        ("Renewable Diesel R99", "renewable_diesel", None),
        ("CNG", "cng", None),
        ("Compressed Natural Gas", "cng", None),
        ("LNG", "lng", None),
        ("Propane (autogas)", "propane", None),
        ("Jet A", "jet_fuel", None),
    ],
)
def test_normalize_mobile_fuel(text: str, fuel: str, blend: int | None) -> None:
    hit = normalize_mobile_fuel(text)
    assert hit is not None
    assert (hit[0], hit[1]) == (fuel, blend)


@pytest.mark.parametrize(
    "text",
    ["Diesel Exhaust Fluid", "DEF 2.5 gal", "AdBlue", "Car Wash - Deluxe", "Motor Oil 5W-30", "Snacks",
     "Windshield washer fluid", "Electric vehicle charging"],
)
def test_non_fuel_items_are_not_fuel(text: str) -> None:
    assert normalize_mobile_fuel(text) is None


def test_mask_card_numbers() -> None:
    assert mask_card_numbers("Card 7083 0512 3456 7890") == "Card ****7890"
    assert mask_card_numbers("7083-0512-3456-7890") == "****7890"
    assert mask_card_numbers("Unit 1042, odometer 128455") == "Unit 1042, odometer 128455"
    assert mask_card_numbers(42) == 42


# --- extraction -------------------------------------------------------------------------------
STATEMENT = (
    "Northline Fleet Fuel Card - Monthly Statement\n"
    "Account Number: FL-20931\n"
    "Date\tCard\tUnit #\tMerchant\tCity\tProduct\tGallons\tPPG\tAmount\n"
    "03/02/2024\t7083051234567890\tT-101\tRiver Fuel Stop\tAkron, OH\tDiesel #2\t42.310\t3.899\t164.97\n"
    "03/02/2024\t7083051234567890\tT-101\tRiver Fuel Stop\tAkron, OH\tDEF\t2.500\t4.199\t10.50\n"
    "03/04/2024\t7083059999990001\tV-12\tCorner Gas\tKent, OH\tUnleaded Regular\t15.880\t3.259\t51.75\n"
    "03/05/2024\t7083059999990001\tV-12\tCorner Gas\tKent, OH\tCar Wash\t1\t9.00\t9.00\n"
)


def test_statement_one_record_per_fuel_transaction(targets: list[dict]) -> None:
    outcome = MobileCombustionExtractor().extract(_text_output(STATEMENT), targets, "EV-1")
    assert outcome.halt_reason is None
    assert outcome.records == 2  # DEF and car wash are not fuel
    first, second = _by_field(outcome.candidates, 1), _by_field(outcome.candidates, 2)
    assert first["fuel_type"]["normalized_value"] == "diesel"
    assert first["activity_quantity"]["normalized_value"] == pytest.approx(42.31)
    assert first["activity_unit"]["normalized_value"] == "gal"
    assert first["transaction_date"]["normalized_value"] == "2024-03-02"
    assert first["vehicle_or_equipment_id"]["normalized_value"] == "T-101"
    assert first["merchant_or_supplier"]["normalized_value"] == "River Fuel Stop"
    assert first["fueling_location"]["normalized_value"] == "Akron, OH"
    assert second["fuel_type"]["normalized_value"] == "gasoline"
    assert second["activity_quantity"]["normalized_value"] == pytest.approx(15.88)
    assert second["vehicle_or_equipment_id"]["normalized_value"] == "V-12"
    # the card column is the account for each transaction, and is never stored in full
    assert first["account_number"]["normalized_value"] == "****7890"
    assert "card_number_masked" in first["account_number"]["validation_flags"]
    for candidate in outcome.candidates:
        for text in (candidate["raw_value"], candidate["normalized_value"],
                     candidate["source_reference"]["text_snippet"]):
            assert "7083051234567890" not in str(text)
    assert first["activity_quantity"]["record_key"] == "r1:2024-03-02:T-101"
    assert "record 1 · 2024-03-02 · T-101" in first["activity_quantity"]["display_label"]


def test_odometer_and_price_columns_are_not_the_quantity(targets: list[dict]) -> None:
    text = (
        "Fleet Card Statement\nDate\tVehicle\tOdometer\tProduct\tPrice/Gal\tQty\n"
        "04/01/2024\tVAN-3\t128455\tUnleaded\t3.459\t18.2\n"
    )
    fields = _by_field(MobileCombustionExtractor().extract(_text_output(text), targets, "EV-1").candidates)
    assert fields["activity_quantity"]["normalized_value"] == pytest.approx(18.2)


def test_pump_receipt(targets: list[dict]) -> None:
    text = (
        "ROUTE 9 FUEL STOP\n"
        "1201 State Rte 9, Plattsburgh NY\n"
        "Date: 03/14/2024 07:42\n"
        "Pump 04   UNLEADED REG\n"
        "12.457 G @ $3.459/G\n"
        "Vehicle: TRK-22\n"
        "Receipt #: 004417\n"
        "TOTAL $43.09\n"
    )
    outcome = MobileCombustionExtractor().extract(_text_output(text), targets, "EV-1")
    fields = _by_field(outcome.candidates)
    assert outcome.records == 1
    assert fields["activity_quantity"]["normalized_value"] == pytest.approx(12.457)
    assert fields["activity_unit"]["normalized_value"] == "gal"
    assert fields["fuel_type"]["normalized_value"] == "gasoline"
    assert fields["transaction_date"]["normalized_value"] == "2024-03-14"
    assert fields["vehicle_or_equipment_id"]["normalized_value"] == "TRK-22"
    assert fields["transaction_id"]["normalized_value"] == "004417"
    assert fields["merchant_or_supplier"]["normalized_value"] == "ROUTE 9 FUEL STOP"


def test_blend_fields(targets: list[dict]) -> None:
    text = "Fleet Fuel Card\nProduct: B20 Biodiesel\nGallons: 100.0\nDate: 2024-05-01\nVehicle: T-9\n"
    fields = _by_field(MobileCombustionExtractor().extract(_text_output(text), targets, "EV-1").candidates)
    assert fields["fuel_type"]["normalized_value"] == "diesel"
    assert "biofuel_blend" in fields["fuel_type"]["validation_flags"]
    assert fields["biofuel_blend_pct"]["normalized_value"] == 20
    assert fields["biofuel_blend_pct"]["unit"] == "%"


def test_e85_is_flagged_outside_allowed_values(targets: list[dict]) -> None:
    text = "Fleet Card\nProduct: E85 Flex Fuel\nGallons: 10.0\nVehicle: F-1\n"
    fields = _by_field(MobileCombustionExtractor().extract(_text_output(text), targets, "EV-1").candidates)
    assert fields["fuel_type"]["normalized_value"] == "e85"
    assert "value_not_in_allowed_values" in fields["fuel_type"]["validation_flags"]


def test_ev_charging_halts_unsupported(targets: list[dict]) -> None:
    text = "ChargeWay Fleet Charging\nDate\tVehicle\tStation\tEnergy (kWh)\n04/02/2024\tEV-7\tLot B\t46.2\n"
    outcome = MobileCombustionExtractor().extract(_text_output(text), targets, "EV-1")
    assert outcome.candidates == []
    assert outcome.halt_reason is not None and outcome.halt_reason["code"] == HALT_UNSUPPORTED
    assert "electricity" in outcome.halt_reason["message"]


def test_no_fuel_halts_unsupported(targets: list[dict]) -> None:
    outcome = MobileCombustionExtractor().extract(_text_output("Car Wash Club\nDeluxe wash x 4\n"), targets, "EV-1")
    assert outcome.halt_reason is not None and outcome.halt_reason["code"] == HALT_UNSUPPORTED


def test_empty_document_halts_unreadable(targets: list[dict]) -> None:
    empty = _text_output("")
    empty["text_blocks"] = []
    outcome = MobileCombustionExtractor().extract(empty, targets, "EV-1")
    assert outcome.halt_reason is not None and outcome.halt_reason["code"] == HALT_UNREADABLE


def test_confirms_needs_a_vehicle_cue() -> None:
    extractor = MobileCombustionExtractor()
    assert extractor.confirms(_text_output("Fleet card\nVehicle: T-1\nDiesel\nGallons: 40.0\n"))
    # a generator diesel delivery (no vehicle/fleet cue) is not confirmed as mobile
    assert not extractor.confirms(_text_output("Diesel delivery to generator day tank\nGallons Delivered: 900\n"))


def test_handles_only_mobfuel(targets: list[dict]) -> None:
    extractor = MobileCombustionExtractor()
    assert extractor.handles(targets)
    assert not extractor.handles([{**targets[0], "canonical_type_id": "CT-S1-FUELQTY"}])


@pytest.mark.parametrize("text", ["Suite B12, 40 Main St", "Bay B5", "Gate E10"])
def test_blend_codes_need_fuel_context(text: str) -> None:
    assert normalize_mobile_fuel(text) is None


def test_bare_blend_code_is_diesel() -> None:
    assert normalize_mobile_fuel("B20") == ("diesel", 20, "b20")


# --- review findings (EXT-002 hardening) --------------------------------------------------
@pytest.mark.parametrize(
    ("text", "fuel", "blend"),
    [("Regular", "gasoline", None), ("Premium", "gasoline", None), ("Super", "gasoline", None),
     ("Plus 89", "gasoline", None), ("UNLD", "gasoline", None), ("Regular 87", "gasoline", None),
     ("Regular E10", "gasoline", 10), ("Mid Grade", "gasoline", None), ("93 Octane", "gasoline", None)],
)
def test_pump_grade_names(text: str, fuel: str, blend: int | None) -> None:
    hit = normalize_mobile_fuel(text)
    assert hit is not None and (hit[0], hit[1]) == (fuel, blend)


@pytest.mark.parametrize("text", ["Premium membership renewal", "Regular maintenance", "Federal Excise Tax Diesel",
                                  "State fuel tax - gasoline", "Diesel delivery fee"])
def test_grade_words_in_sentences_and_tax_lines_are_not_fuel(text: str) -> None:
    assert normalize_mobile_fuel(text) is None


def test_statement_with_grade_names_and_tax_lines(targets: list[dict]) -> None:
    text = (
        "Fleet Card Statement\nDate\tVehicle\tProduct\tGallons\n"
        "05/01/2024\tV-1\tRegular\t15.2\n"
        "05/01/2024\tV-2\tPremium\t12.0\n"
        "05/02/2024\tT-3\tDiesel\t40.0\n"
        "05/02/2024\tT-3\tFederal Excise Tax Diesel\t40.0\n"
    )
    outcome = MobileCombustionExtractor().extract(_text_output(text), targets, "EV-1")
    quantities = [c["normalized_value"] for c in outcome.candidates if c["field_name"] == "activity_quantity"]
    assert quantities == [pytest.approx(15.2), pytest.approx(12.0), pytest.approx(40.0)]


def test_receipt_with_several_lines_skips_def(targets: list[dict]) -> None:
    text = (
        "Truck Plaza 81\nDate: 04/22/2024\n"
        "DEF\n2.500 GAL @ $4.000/GAL\n"
        "DIESEL #2\n60.112 GAL @ $3.999/GAL\n"
        "Vehicle: TRK-9\n"
    )
    outcome = MobileCombustionExtractor().extract(_text_output(text), targets, "EV-1")
    assert outcome.records == 1
    fields = _by_field(outcome.candidates)
    assert fields["activity_quantity"]["normalized_value"] == pytest.approx(60.112)
    assert fields["fuel_type"]["normalized_value"] == "diesel"


def test_receipt_with_two_fuel_lines_gives_two_records(targets: list[dict]) -> None:
    text = "Truck Plaza 81\nDate: 04/22/2024\nDIESEL\n60.112 GAL @ $3.999/GAL\nUNLEADED\n5.000 GAL @ $3.299/GAL\n"
    outcome = MobileCombustionExtractor().extract(_text_output(text), targets, "EV-1")
    assert outcome.records == 2
    assert _by_field(outcome.candidates, 2)["fuel_type"]["normalized_value"] == "gasoline"


def test_masking_does_not_mangle_dates_or_ids() -> None:
    row = "03/02/2026 1012 4471 2209 Diesel 15"
    assert mask_card_numbers(row) == row
    assert mask_card_numbers("Card 7083 0512 3456 7890 Diesel") == "Card ****7890 Diesel"


def test_generic_qty_label_loses_to_a_unit_label(targets: list[dict]) -> None:
    text = "Fleet Fuel Co\nQty: 1 Coffee\nProduct: Diesel\nGallons: 120.5\n"
    fields = _by_field(MobileCombustionExtractor().extract(_text_output(text), targets, "EV-1").candidates)
    assert fields["activity_quantity"]["normalized_value"] == pytest.approx(120.5)
    assert fields["activity_unit"]["normalized_value"] == "gal"


def test_units_column_and_unit_column(targets: list[dict]) -> None:
    text = "Fleet Card Statement\nDate\tUnit\tProduct\tUnits\tUOM\n05/01/2024\tT-7\tDiesel\t44.0\tGAL\n"
    fields = _by_field(MobileCombustionExtractor().extract(_text_output(text), targets, "EV-1").candidates)
    assert fields["activity_quantity"]["normalized_value"] == pytest.approx(44.0)
    assert fields["vehicle_or_equipment_id"]["normalized_value"] == "T-7"
    assert fields["activity_unit"]["normalized_value"] == "gal"


def test_unit_column_holding_units_of_measure(targets: list[dict]) -> None:
    text = "Fleet Card Statement\nDate\tProduct\tQty\tUnit\n05/01/2024\tDiesel\t44.0\tGAL\n"
    fields = _by_field(MobileCombustionExtractor().extract(_text_output(text), targets, "EV-1").candidates)
    assert fields["activity_unit"]["normalized_value"] == "gal"
    assert fields["vehicle_or_equipment_id"]["normalized_value"] is None


def test_volume_l_header(targets: list[dict]) -> None:
    text = "Fleet Card Statement\nDate\tVehicle\tProduct\tVolume (L)\n14.03.2026\tKX19 ABC\tDiesel\t61.2\n"
    fields = _by_field(MobileCombustionExtractor().extract(_text_output(text), targets, "EV-1").candidates)
    assert fields["activity_unit"]["normalized_value"] == "L"
    assert fields["transaction_date"]["normalized_value"] == "2026-03-14"


def test_more_date_formats() -> None:
    from backend.app.services.stationary_combustion_extractor import parse_date

    assert parse_date("14.03.2026")[0] == "2026-03-14"  # type: ignore[index]
    assert parse_date("14-MAR-26")[0] == "2026-03-14"  # type: ignore[index]
    assert parse_date("Price 3.459") is None


def test_bare_blend_code_in_free_text_is_not_the_document_fuel(targets: list[dict]) -> None:
    text = "City Transit\nBus\nB12\nRoute 4 schedule\n"
    outcome = MobileCombustionExtractor().extract(_text_output(text), targets, "EV-1")
    assert outcome.halt_reason is not None and outcome.halt_reason["code"] == HALT_UNSUPPORTED


def test_cue_strength() -> None:
    from backend.app.services.mobile_combustion_extractor import fuel_use_cues

    address_only = _text_output("Propane delivery\nShip to: 45 Industrial Pkwy, Unit #4\nGallons Delivered: 120\n")
    assert fuel_use_cues(address_only) == ([], [])
    fleet = _text_output("Fleet card statement\nUnit #\nT-101\n")
    assert fuel_use_cues(fleet)[0] == ["fleet", "fleet card", "unit #"]
    one_weak = _text_output("Fleet Street Gas Company\nTotal Usage: 120 therms\n")
    assert fuel_use_cues(one_weak) == ([], ["therms"])
