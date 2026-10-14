from __future__ import annotations

from typing import Any

import pytest

from backend.app.adapters.parsers.textract_parser import TextractParser
from backend.app.services.extraction_service import ExtractionService
from backend.app.services.extraction_target_service import ExtractionTargetService
from backend.app.services.stationary_combustion_extractor import (
    HALT_UNREADABLE,
    HALT_UNSUPPORTED,
    StationaryCombustionExtractor,
    detect_fuel,
    parse_date,
    parse_dates,
    parse_number,
)


@pytest.fixture(scope="module")
def targets() -> list[dict]:
    return ExtractionTargetService().get_targets_for_canonical_type("CT-S1-FUELQTY")


def _text_output(text: str, document_id: str = "DOC-1") -> dict[str, Any]:
    """parser_output for a plain-text document (no geometry)."""
    return {
        "document_id": document_id,
        "pages": [{"page_number": 1, "text": text}],
        "text_blocks": [{"block_id": "b1", "page_number": 1, "text": text, "confidence": None,
                         "bounding_box": None, "source_reference_id": None}],
        "tables": [],
        "key_value_pairs": [],
        "source_references": [],
    }


def _by_field(candidates: list[dict], record_index: int | None = None) -> dict[str, dict]:
    return {c["field_name"]: c for c in candidates if c["record_index"] == record_index}


# --- value parsing ---------------------------------------------------------------------
@pytest.mark.parametrize(
    ("text", "iso"),
    [
        ("01/03/2024", "2024-01-03"),
        ("1/3/24", "2024-01-03"),
        ("2024-06-30", "2024-06-30"),
        ("Jan 1, 2023", "2023-01-01"),
        ("January 31, 2023", "2023-01-31"),
        ("Sept. 4, 2024", "2024-09-04"),
        ("4 Mar 2024", "2024-03-04"),
        ("04-Mar-2024", "2024-03-04"),
        ("Feb 30, 2024", None),
        ("no date here", None),
    ],
)
def test_parse_date(text: str, iso: str | None) -> None:
    hit = parse_date(text)
    assert (hit[0] if hit else None) == iso


def test_parse_date_ranges() -> None:
    assert parse_dates("Service Period: 01/03/2024 - 02/01/2024") == ["2024-01-03", "2024-02-01"]
    assert parse_dates("Feb 1, 2024 to Feb 29, 2024") == ["2024-02-01", "2024-02-29"]
    assert parse_dates("2024-05-01 – 2024-05-31") == ["2024-05-01", "2024-05-31"]


@pytest.mark.parametrize(
    ("text", "number"),
    [("1,284", 1284.0), ("18,442.7 MCF", 18442.7), ("742.6", 742.6), ("-12", -12.0), ("no number", None)],
)
def test_parse_number(text: str, number: float | None) -> None:
    hit = parse_number(text)
    assert (hit[0] if hit else None) == number


@pytest.mark.parametrize(
    ("text", "fuel"),
    [
        ("Natural Gas - Industrial Interruptible", "natural_gas"),
        ("#2 Heating Oil", "fuel_oil"),
        ("Propane (HD-5) bulk delivery", "propane"),
        ("Ultra Low Sulfur Diesel", "diesel"),
        ("Biodiesel B20", "biodiesel"),
        ("Renewable Natural Gas", "biogas"),
        ("Bituminous coal", "coal"),
        ("Wood pellets", "biomass"),
        ("Water and sewer service", None),
        ("Electric service", None),
    ],
)
def test_detect_fuel(text: str, fuel: str | None) -> None:
    hit = detect_fuel(text)
    assert (hit[0] if hit else None) == fuel


# --- extraction --------------------------------------------------------------------------
def test_handles_only_fuelqty_targets(targets: list[dict]) -> None:
    extractor = StationaryCombustionExtractor()
    assert extractor.handles(targets)
    assert not extractor.handles([])
    assert not extractor.handles([{**targets[0], "canonical_type_id": "CT-S1-MOBFUEL"}])


def test_plain_text_tab_separated_bill(targets: list[dict]) -> None:
    text = (
        "Riverside Gas Utilities Inc. - Monthly Statement\n"
        "Facility Name\tEastside Bakery\tAccount Number\tRG-7731\n"
        "Service Address\t9 Oven Lane, Dayton, OH 45402\n"
        "Service Period\t03/01/2024 to 03/31/2024\n"
        "Meter ID\tPrevious Read\tCurrent Read\tUsage\tUnit\n"
        "M-1\t100\t412\t312\tTherms\n"
    )
    outcome = StationaryCombustionExtractor().extract(_text_output(text), targets, "EV-1")
    fields = _by_field(outcome.candidates)
    assert outcome.halt_reason is None
    assert fields["facility_name"]["normalized_value"] == "Eastside Bakery"
    assert fields["account_number"]["normalized_value"] == "RG-7731"
    assert fields["supplier_name"]["normalized_value"] == "Riverside Gas Utilities Inc."
    assert fields["activity_quantity"]["normalized_value"] == pytest.approx(31.2)
    assert fields["activity_quantity"]["raw_value"] == "312"
    assert fields["activity_unit"]["normalized_value"] == "MMBtu"
    assert fields["service_period_start"]["normalized_value"] == "2024-03-01"
    assert fields["service_period_end"]["normalized_value"] == "2024-03-31"
    assert fields["fuel_type"]["normalized_value"] == "natural_gas"


def _textract_line(block_id: str, text: str, left: float, top: float, width: float, confidence: float = 99.0) -> dict:
    return {
        "Id": block_id, "BlockType": "LINE", "Page": 1, "Text": text, "Confidence": confidence,
        "Geometry": {"BoundingBox": {"Left": left, "Top": top, "Width": width, "Height": 0.012}},
    }


def test_textract_lines_multi_meter(targets: list[dict]) -> None:
    payload = {"Blocks": [
        _textract_line("l1", "Summit Natural Gas Co.", 0.08, 0.05, 0.4),
        _textract_line("l2", "Customer:", 0.08, 0.12, 0.1),
        _textract_line("l3", "Hilltop Brewery", 0.25, 0.12, 0.2),
        _textract_line("l4", "Account No: SNG-1-22", 0.6, 0.12, 0.25),
        _textract_line("l5", "Meter", 0.08, 0.30, 0.08),
        _textract_line("l6", "From", 0.25, 0.30, 0.06),
        _textract_line("l7", "To", 0.40, 0.30, 0.04),
        _textract_line("l8", "Usage (CCF)", 0.62, 0.30, 0.12),
        _textract_line("l9", "A-100", 0.08, 0.33, 0.08),
        _textract_line("l10", "02/01/2024", 0.25, 0.33, 0.1),
        _textract_line("l11", "02/29/2024", 0.40, 0.33, 0.1),
        _textract_line("l12", "1,050", 0.68, 0.33, 0.06, confidence=71.0),
        _textract_line("l13", "A-200", 0.08, 0.36, 0.08),
        _textract_line("l14", "02/03/2024", 0.25, 0.36, 0.1),
        _textract_line("l15", "03/01/2024", 0.40, 0.36, 0.1),
        _textract_line("l16", "88", 0.70, 0.36, 0.04),
        _textract_line("l17", "Total", 0.08, 0.39, 0.08),
        _textract_line("l18", "1,138", 0.68, 0.39, 0.06),
    ]}
    parser_output = TextractParser().parse(payload, document_id="TX-1", processing_run_id="RUN")
    outcome = StationaryCombustionExtractor().extract(parser_output, targets, "EV-TX")

    assert outcome.records == 2
    first, second = _by_field(outcome.candidates, 1), _by_field(outcome.candidates, 2)
    assert first["activity_quantity"]["normalized_value"] == 1050
    assert first["activity_unit"]["normalized_value"] == "ccf"
    assert first["service_period_start"]["normalized_value"] == "2024-02-01"
    assert second["activity_quantity"]["normalized_value"] == 88
    assert second["service_period_end"]["normalized_value"] == "2024-03-01"
    assert first["facility_name"]["normalized_value"] == "Hilltop Brewery"
    assert first["account_number"]["normalized_value"] == "SNG-1-22"
    assert first["activity_quantity"]["record_key"] == "r1:A-100:2024-02-01..2024-02-29"
    assert first["activity_quantity"]["candidate_id"].endswith("::activity_quantity::r1")
    assert first["activity_quantity"]["display_label"] == "Activity quantity (record 1 \u00b7 A-100 \u00b7 2024-02-01 to 2024-02-29)"
    # source traceability: Textract geometry carried through as x/y/width/height
    ref = first["activity_quantity"]["source_reference"]
    assert ref["bounding_box"] == {"x": 0.68, "y": 0.33, "width": 0.06, "height": 0.012}
    assert ref["parser_block_ids"] == ["l12"]
    assert "1,050" in ref["text_snippet"]
    # OCR confidence caps the candidate confidence
    assert first["activity_quantity"]["confidence"] == pytest.approx(0.71)


def test_single_record_ids_are_unchanged(targets: list[dict]) -> None:
    text = "Gas Company Inc.\nFuel Type: Natural Gas\nTotal Usage: 120 therms\nPeriod: 01/01/2024 - 01/31/2024\n"
    outcome = StationaryCombustionExtractor().extract(_text_output(text), targets, "EV-1")
    quantity = _by_field(outcome.candidates)["activity_quantity"]
    assert quantity["candidate_id"] == "candidate::EV-1::DOC-1::activity_quantity"
    assert quantity["record_key"] is None and quantity["record_index"] is None
    assert quantity["display_label"] == "Activity quantity"
    assert quantity["normalized_value"] == 12 and quantity["unit"] == "MMBtu"
    assert "unit_converted" in quantity["validation_flags"]


def test_daily_average_is_not_the_quantity(targets: list[dict]) -> None:
    text = "Fuel: Natural Gas\nAverage daily usage: 40 MCF\nTotal Usage: 1,240 MCF\n"
    outcome = StationaryCombustionExtractor().extract(_text_output(text), targets, "EV-1")
    assert _by_field(outcome.candidates)["activity_quantity"]["normalized_value"] == 1240


def test_header_with_values_is_not_a_table_header(targets: list[dict]) -> None:
    text = (
        "Fuel Type\tNatural Gas\tQuantity / Unit\t12,000 Mcf\n"
        "\n"
        "Date Posted\tFuel Type\tQuantity\tUnit\n"
        "Jan 28, 2023\tNatural Gas\t12,000\tMcf\n"
    )
    outcome = StationaryCombustionExtractor().extract(_text_output(text), targets, "EV-1")
    fields = _by_field(outcome.candidates)
    assert fields["activity_quantity"]["normalized_value"] == 12000
    assert fields["activity_unit"]["normalized_value"] == "Mcf"
    assert fields["service_period_start"]["normalized_value"] == "2023-01-28"


def test_non_fuel_line_items_are_skipped(targets: list[dict]) -> None:
    text = (
        "Fuel Supplier Co.\n"
        "Product\tQty\tUOM\n"
        "Tank rental\t1\tEA\n"
        "Propane\t500\tgal\n"
    )
    outcome = StationaryCombustionExtractor().extract(_text_output(text), targets, "EV-1")
    assert outcome.records == 1
    fields = _by_field(outcome.candidates)
    assert fields["activity_quantity"]["normalized_value"] == 500
    assert fields["fuel_type"]["normalized_value"] == "propane"


def test_unit_missing_is_flagged(targets: list[dict]) -> None:
    text = "Fuel: Heating oil\nQuantity: 300\n"
    fields = _by_field(StationaryCombustionExtractor().extract(_text_output(text), targets, "EV-1").candidates)
    assert fields["activity_quantity"]["normalized_value"] == 300
    assert fields["activity_quantity"]["unit"] is None
    assert "unit_missing" in fields["activity_quantity"]["validation_flags"]
    assert fields["activity_unit"]["validation_flags"] == ["field_not_found"]


def test_fuel_outside_allowed_values_is_flagged(targets: list[dict]) -> None:
    text = "Fuel Type: Biogas (digester)\nVolume Consumed (scf)\tOperator\n83,000\tJ.C.\n"
    fields = _by_field(StationaryCombustionExtractor().extract(_text_output(text), targets, "EV-1").candidates)
    assert fields["fuel_type"]["normalized_value"] == "biogas"
    assert "value_not_in_allowed_values" in fields["fuel_type"]["validation_flags"]


def test_halts_unreadable_without_text(targets: list[dict]) -> None:
    empty = _text_output("")
    empty["text_blocks"] = []
    outcome = StationaryCombustionExtractor().extract(empty, targets, "EV-1")
    assert outcome.candidates == []
    assert outcome.halt_reason is not None and outcome.halt_reason["code"] == HALT_UNREADABLE


def test_halts_unsupported_without_fuel(targets: list[dict]) -> None:
    text = "City Water Dept\nAccount Number: W-1\nMeter\tUsage\tUnit\nW-9\t118\tCCF\n"
    outcome = StationaryCombustionExtractor().extract(_text_output(text), targets, "EV-1")
    assert outcome.candidates == []
    assert outcome.halt_reason is not None and outcome.halt_reason["code"] == HALT_UNSUPPORTED
    assert "water" in outcome.halt_reason["message"]


def test_requires_document_id(targets: list[dict]) -> None:
    with pytest.raises(ValueError):
        StationaryCombustionExtractor().extract({"document_id": ""}, targets, "EV-1")


def test_confirms_needs_fuel_and_fuel_unit() -> None:
    extractor = StationaryCombustionExtractor()
    assert extractor.confirms(_text_output("Natural gas\nTotal Usage: 120 therms\n"))
    assert not extractor.confirms(_text_output("Natural gas\nTotal Usage: 120\n"))
    assert not extractor.confirms(_text_output("Water\nTotal Usage: 120 CCF\n"))


def test_extraction_service_routes_fuelqty_and_reports_halts(targets: list[dict]) -> None:
    service = ExtractionService()
    ok = service.extract({"parser_output": _text_output("Fuel: Propane\nGallons Delivered: 90\n"),
                          "extraction_targets": targets, "evidence_id": "EV-1"})
    assert ok["record_count"] == 1 and "halt_reason" not in ok
    assert ok["candidate_count"] == len(targets)
    halted = service.extract({"parser_output": _text_output("Water bill\nUsage: 3 CCF\n"),
                              "extraction_targets": targets, "evidence_id": "EV-1"})
    assert halted["halt_reason"]["code"] == HALT_UNSUPPORTED and halted["items"] == []


def test_unknown_target_field_is_reported_not_guessed(targets: list[dict]) -> None:
    extra = {**targets[0], "field_id": "hhv_value", "field_label": "HHV"}
    outcome = StationaryCombustionExtractor().extract(
        _text_output("Fuel: Propane\nGallons Delivered: 90\n"), [*targets, extra], "EV-1")
    assert _by_field(outcome.candidates)["hhv_value"]["validation_flags"] == ["unsupported_extraction_method"]


# --- review findings (EXT-001 hardening) --------------------------------------------------
@pytest.mark.parametrize(
    ("text", "number"),
    [
        ("1.234,5 m3", 1234.5),
        ("12,5", 12.5),
        ("1.234.567", 1234567.0),
        ("(1,234)", -1234.0),
        ("1,234-", -1234.0),
        ("1,234 CR", -1234.0),
        ("Usage 2,131 CCF", 2131.0),
    ],
)
def test_parse_number_conventions_and_credits(text: str, number: float) -> None:
    hit = parse_number(text)
    assert hit is not None and hit[0] == number


def test_day_first_dates() -> None:
    assert parse_date("13/01/2024")[0] == "2024-01-13"  # type: ignore[index]
    assert parse_date("05/01/2024", day_first=True)[0] == "2024-01-05"  # type: ignore[index]
    assert parse_dates("13/01/2024 - 12/02/2024", day_first=True) == ["2024-01-13", "2024-02-12"]


def test_day_first_document_is_read_day_first(targets: list[dict]) -> None:
    text = "Gas Co Ltd\nFuel: Natural Gas\nPeriod: 05/01/2024 - 04/02/2024\nIssued 15/02/2024\nTotal Usage: 120 therms\n"
    fields = _by_field(StationaryCombustionExtractor().extract(_text_output(text), targets, "EV-1").candidates)
    assert fields["service_period_start"]["normalized_value"] == "2024-01-05"
    assert fields["service_period_end"]["normalized_value"] == "2024-02-04"
    assert fields["service_period_start"]["validation_flags"] == []


def test_period_start_after_end_is_flagged(targets: list[dict]) -> None:
    text = "Fuel: Natural Gas\nService Period: 03/31/2024 - 03/01/2024\nTotal Usage: 120 therms\n"
    fields = _by_field(StationaryCombustionExtractor().extract(_text_output(text), targets, "EV-1").candidates)
    assert "period_start_after_end" in fields["service_period_start"]["validation_flags"]
    assert "period_start_after_end" in fields["service_period_end"]["validation_flags"]


def test_negative_quantity_is_flagged(targets: list[dict]) -> None:
    text = "Fuel: Heating oil\nGallons Delivered: (120.0) gal\n"
    quantity = _by_field(StationaryCombustionExtractor().extract(_text_output(text), targets, "EV-1").candidates)[
        "activity_quantity"]
    assert quantity["normalized_value"] == -120
    assert "negative_quantity" in quantity["validation_flags"]


def test_fuel_keywords_are_whole_words_and_ignore_fuel_mix() -> None:
    assert detect_fuel("Smart thermostat rebate") is None
    assert detect_fuel("Thermo Fuel Inc") is None
    assert detect_fuel("Generation mix: Coal 20%, Natural Gas 40%, Wind 40%") is None
    assert detect_fuel("1,284 therms") == ("natural_gas", "therms")


ELECTRIC_BILL = (
    "Metro Power & Light\n"
    "Account Number: 99-1234\n"
    "Service Address: 5 Elm St, Springfield\n"
    "Billing Period: 01/01/2024 - 01/31/2024\n"
    "Electric service - Meter Number E-77\n"
    "Total Usage: 850 kWh\n"
    "Your power mix: Coal 20%, Natural Gas 40%, Nuclear 40%\n"
)


def test_electricity_bill_is_not_stationary_combustion(targets: list[dict]) -> None:
    extractor = StationaryCombustionExtractor()
    outcome = extractor.extract(_text_output(ELECTRIC_BILL), targets, "EV-1")
    assert outcome.candidates == []
    assert outcome.halt_reason is not None and outcome.halt_reason["code"] == HALT_UNSUPPORTED
    assert not extractor.confirms(_text_output(ELECTRIC_BILL))
    # even if the bill names a real fuel, kWh is not a fuel unit for the content check
    assert not extractor.confirms(_text_output(ELECTRIC_BILL.replace("Your power mix", "Natural gas backup")))


def test_layout_variants(targets: list[dict]) -> None:
    text = (
        "Fuel: Natural Gas\n"
        "Account Number 1234-5678\n"
        "Account Summary 2024\n"
        "Total Usage (Therms): 1,234\n"
    )
    fields = _by_field(StationaryCombustionExtractor().extract(_text_output(text), targets, "EV-1").candidates)
    assert fields["account_number"]["normalized_value"] == "1234-5678"
    assert fields["activity_quantity"]["normalized_value"] == pytest.approx(123.4)
    assert fields["activity_unit"]["normalized_value"] == "MMBtu"


def test_metered_usage_header(targets: list[dict]) -> None:
    text = "Fuel: Natural Gas\nMeter #\tPrevious Read\tCurrent Read\tMetered Usage (Therms)\nG-1\t10\t50\t40\n"
    fields = _by_field(StationaryCombustionExtractor().extract(_text_output(text), targets, "EV-1").candidates)
    assert fields["activity_quantity"]["raw_value"] == "40"


def _boxed_output(lines: list[tuple[int, str, float, float]]) -> dict[str, Any]:
    """parser_output with geometry: (page, text, left, top)."""
    blocks = []
    for i, (page, text, left, top) in enumerate(lines):
        blocks.append({"block_id": f"b{i}", "page_number": page, "text": text, "confidence": None,
                       "bounding_box": {"left": left, "top": top, "width": 0.08, "height": 0.012},
                       "source_reference_id": None})
    return {"document_id": "DOC-MP", "pages": [], "text_blocks": blocks, "tables": [],
            "key_value_pairs": [], "source_references": []}


def test_usage_table_continues_on_next_page(targets: list[dict]) -> None:
    header = [("Meter", 0.08), ("Date", 0.3), ("Usage", 0.6), ("Unit", 0.75)]
    lines: list[tuple[int, str, float, float]] = [(1, "Fuel Type: Natural Gas", 0.08, 0.10)]
    lines += [(1, text, left, 0.30) for text, left in header]
    for n, top in enumerate((0.33, 0.36, 0.39)):
        lines += [(1, f"M-{n}", 0.08, top), (1, f"0{n + 1}/15/2024", 0.3, top), (1, str(100 + n), 0.6, top),
                  (1, "therms", 0.75, top)]
    lines += [(1, "Page 1 of 2", 0.45, 0.95), (2, "Gas Co - continued", 0.08, 0.05)]
    lines += [(2, text, left, 0.10) for text, left in header]
    for n, top in enumerate((0.13, 0.16), start=3):
        lines += [(2, f"M-{n}", 0.08, top), (2, f"0{n + 1}/15/2024", 0.3, top), (2, str(100 + n), 0.6, top),
                  (2, "therms", 0.75, top)]
    outcome = StationaryCombustionExtractor().extract(_boxed_output(lines), targets, "EV-MP")
    assert outcome.records == 5
    assert _by_field(outcome.candidates, 5)["activity_quantity"]["normalized_value"] == pytest.approx(10.4)


def test_concurrent_extractions_do_not_share_state(targets: list[dict]) -> None:
    from concurrent.futures import ThreadPoolExecutor

    def doc(meter: str, dates: tuple[str, str]) -> dict[str, Any]:
        return _text_output(
            f"Fuel: Natural Gas\nMeter\tFrom\tTo\tUsage\tUnit\n{meter}-1\t{dates[0]}\t{dates[1]}\t10\ttherms\n"
            f"{meter}-2\t{dates[0]}\t{dates[1]}\t20\ttherms\n", document_id=meter)

    us = doc("AAA", ("01/02/2024", "02/01/2024"))      # month-first
    eu = doc("ZZZ", ("13/01/2024", "12/02/2024"))      # day-first
    extractor = StationaryCombustionExtractor()
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda d: (d["document_id"], extractor.extract(d, targets, "EV")), [us, eu] * 20))
    for document_id, outcome in results:
        for candidate in outcome.candidates:
            assert f"{document_id}-" in candidate["display_label"]
        start = _by_field(outcome.candidates, 1)["service_period_start"]["normalized_value"]
        assert start == ("2024-01-02" if document_id == "AAA" else "2024-01-13")


def test_multi_record_candidates_carry_record_key_in_source_reference(targets: list[dict]) -> None:
    text = "Fuel: Natural Gas\nMeter\tUsage\tUnit\nA\t10\ttherms\nB\t20\ttherms\n"
    outcome = StationaryCombustionExtractor().extract(_text_output(text), targets, "EV-1")
    for candidate in outcome.candidates:
        assert candidate["source_reference"]["record_key"] == candidate["record_key"]
    assert {c["record_key"] for c in outcome.candidates} == {"r1:A", "r2:B"}


def test_annual_summary_row_is_not_a_record(targets: list[dict]) -> None:
    # Richmond Refinery bill: twelve monthly meter rows, then "Annual quantity" (their sum).
    text = (
        "Pacific Gas Supply Company\nFuel Type: Natural gas\n"
        "Month\tCycle start\tCycle end\tMMBtu\n"
        "Jan\t2025-01-01\t2025-01-31\t41,820\n"
        "Feb\t2025-02-01\t2025-02-28\t34,360\n"
        "Annual quantity\t76,180\n"
    )
    outcome = StationaryCombustionExtractor().extract(_text_output(text), targets, "EV-1")
    assert outcome.records == 2
    quantities = [c["normalized_value"] for c in outcome.candidates if c["field_name"] == "activity_quantity"]
    assert quantities == [41820, 34360]
    # Each month keeps its own cycle dates rather than the statement's service year.
    assert _by_field(outcome.candidates, 2)["service_period_start"]["normalized_value"] == "2025-02-01"
    assert _by_field(outcome.candidates, 2)["service_period_end"]["normalized_value"] == "2025-02-28"


def test_a_fuel_log_site_column_is_each_lines_facility(targets: list[dict]) -> None:
    text = ("Date    Site    Equipment    Product    Gallons\n"
            "02/10/2025    Richmond Refinery    Standby generator    Diesel    450\n"
            "08/22/2025    Albany Plant    Boiler 2    Diesel    380\n")
    outcome = StationaryCombustionExtractor().extract(_text_output(text), targets, "EV-1")
    first, second = _by_field(outcome.candidates, 1), _by_field(outcome.candidates, 2)
    assert (first["facility_name"]["normalized_value"], first["activity_quantity"]["normalized_value"]) == (
        "Richmond Refinery", 450)
    assert (second["facility_name"]["normalized_value"], second["activity_quantity"]["normalized_value"]) == (
        "Albany Plant", 380)


# --- values that wrap inside a table cell ----------------------------------------------------
def _measured_output(lines: list[tuple[str, float, float, float, float]]) -> dict[str, Any]:
    """parser_output with measured geometry: (text, left, top, width, height)."""
    blocks = [{"block_id": f"w{i}", "page_number": 1, "text": text, "confidence": None,
               "bounding_box": {"left": left, "top": top, "width": width, "height": height},
               "source_reference_id": None} for i, (text, left, top, width, height) in enumerate(lines)]
    return {"document_id": "DOC-WRAP", "pages": [], "text_blocks": blocks, "tables": [], "key_value_pairs": [],
            "source_references": []}


# The text-PDF reader's layout of a two-column label/value table (National Fuel Gas sample,
# EV-NG-2023-001): the first line of a wrapped value shares the label's row, the second does not.
PDF_WRAPPED = [
    ("Natural Gas Statement", 0.147, 0.135, 0.38, 0.014),
    ("Customer", 0.077, 0.196, 0.061, 0.013), ("Anheuser-Busch Baldwinsville", 0.293, 0.190, 0.181, 0.013),
    ("Service Address", 0.509, 0.196, 0.099, 0.013), ("4797 River Road, Baldwinsville,", 0.725, 0.190, 0.186, 0.013),
    ("Brewery", 0.293, 0.203, 0.050, 0.013), ("NY 13027", 0.725, 0.203, 0.054, 0.013),
    ("Account Number", 0.077, 0.219, 0.106, 0.013), ("ACC-2023-BWV-001", 0.293, 0.219, 0.112, 0.013),
    ("Bill Number", 0.509, 0.219, 0.076, 0.013), ("NFG-23-BWV-0001", 0.725, 0.219, 0.107, 0.013),
    ("Service Period", 0.077, 0.237, 0.090, 0.013), ("Jan 1, 2023 to Jan 31, 2023", 0.293, 0.237, 0.150, 0.013),
    ("Usage", 0.077, 0.30, 0.05, 0.013), ("32,400 MMBtu", 0.293, 0.30, 0.09, 0.013),
]


def test_a_wrapped_value_is_read_whole_and_the_next_field_keeps_its_own(targets: list[dict]) -> None:
    fields = _by_field(StationaryCombustionExtractor().extract(_measured_output(PDF_WRAPPED), targets, "EV-1").candidates)
    assert fields["facility_name"]["normalized_value"] == "Anheuser-Busch Baldwinsville Brewery"
    assert fields["service_address"]["normalized_value"] == "4797 River Road, Baldwinsville, NY 13027"
    # "Brewery" is nearer "Customer" than "Account Number", so it is not the account's
    assert fields["account_number"]["normalized_value"] == "ACC-2023-BWV-001"
    # the highlight covers both lines of the name
    box = fields["facility_name"]["source_reference"]["bounding_box"]
    assert box["y"] == pytest.approx(0.190) and box["height"] == pytest.approx(0.026)


def test_a_scanned_bills_wrapped_values_are_read_from_textract() -> None:
    from pathlib import Path

    from backend.app.services.parser_service import ParserService
    from backend.app.services.pipeline_orchestration_service import PipelineOrchestrationService

    # Live AnalyzeDocument (FORMS, TABLES) response for the scanned National Fuel Gas bill
    # (s1-test-suite/raw_documents/ocr_png/EV-NG-2023-001/page-1.png). On the scan each
    # wrapped value sits centered on its label: neither line shares the label's row.
    saved = Path(__file__).parent / "data" / "textract_scanned_gas_bill.json"
    parser_output = ParserService().parse_textract_json(saved, "DOC-SCAN", "RUN-1")
    assert PipelineOrchestrationService._fuel_content_confirmed(
        {"status": "low_confidence", "candidate_matches": [{"canonical_type_id": "CT-S1-FUELQTY", "confidence": 0.9}]},
        parser_output) == "CT-S1-FUELQTY"
    result = ExtractionService().extract({"parser_output": parser_output, "evidence_id": "EV-SCAN",
                                          "extraction_targets": ExtractionTargetService()
                                          .get_targets_for_canonical_type("CT-S1-FUELQTY")})
    values = {i["field_name"]: i["normalized_value"] for i in result["items"]}
    assert values["facility_name"] == "Anheuser-Busch Baldwinsville Brewery"
    assert values["service_address"] == "4797 River Road, Baldwinsville, NY 13027"
    assert values["account_number"] == "ACC-2023-BWV-001"
    assert (values["activity_quantity"], values["activity_unit"]) == (32400, "MMBtu")
    assert (values["service_period_start"], values["service_period_end"]) == ("2023-01-01", "2023-01-31")
    boxed = [i for i in result["items"] if i["normalized_value"] is not None]
    assert all(i["source_reference"]["bounding_box"] for i in boxed)  # every value can be highlighted on the scan
