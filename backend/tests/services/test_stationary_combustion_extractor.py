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


def test_labels_after_other_text_in_a_cell_are_read(targets: list[dict]) -> None:
    # OCR joins a row into one line; the labels are not at the start of the cell
    line = ("Fuel Type: Natural Gas   Total Usage: 1,200 therms   Account Number: NG-4471   "
            "Billing Period: 03/01/2025 to 03/31/2025")
    blocks = [("Riverside Gas Company", 0.05, 0.03), (line, 0.2, 0.012)]
    output = {"document_id": "DOC-OCR", "pages": [], "tables": [], "key_value_pairs": [], "source_references": [],
              "text_blocks": [{"block_id": f"b{i}", "page_number": 1, "text": t, "confidence": 98.0,
                               "bounding_box": {"left": 0.1, "top": top, "width": 0.7, "height": h},
                               "source_reference_id": None} for i, (t, top, h) in enumerate(blocks)]}
    fields = _by_field(StationaryCombustionExtractor().extract(output, targets, "EV-1").candidates)
    assert fields["account_number"]["normalized_value"] == "NG-4471"
    assert fields["service_period_start"]["normalized_value"] == "2025-03-01"
    assert fields["service_period_end"]["normalized_value"] == "2025-03-31"
    assert fields["supplier_name"]["normalized_value"] == "Riverside Gas Company"


# --- the facility is the site, never the company that is billed ----------------------------------
def _facility_of(text: str, targets: list[dict]) -> str | None:
    outcome = StationaryCombustionExtractor().extract(_text_output(text), targets, "EV-1")
    assert outcome.halt_reason is None
    value = _by_field(outcome.candidates).get("facility_name", {}).get("normalized_value")
    return value or None


PROPANE_SHAPE = (
    "Blue Kettle Propane Supply\nPROPANE DELIVERY INVOICE\nInvoice No: BK-2025-118844\n"
    "{parties}"
    "Account Number: C-008831\nFuel Type: Propane (LPG)\n"
    "Delivery Date\tGallons\n02/11/2025\t612.4\n11/18/2025\t588.7\n"
)


@pytest.fixture
def strict(monkeypatch: pytest.MonkeyPatch) -> None:
    """A document that names no site has no facility (the bill-to is not used as a last resort)."""

    monkeypatch.setattr("backend.app.services.stationary_combustion_extractor.BILL_TO_NAME_IS_LAST_RESORT_FACILITY", False)


@pytest.mark.parametrize(
    ("parties", "site"),
    [
        ("Bill To: Staging-Test Foods Inc.\nShip To: Riverside Plant\n", "Riverside Plant"),
        ("Bill To: Staging-Test Foods Inc.\nService Location: Riverside Plant\n", "Riverside Plant"),
        ("Sold To: Staging-Test Foods Inc.\nDeliver To: Riverside Plant, 12 Mill Road, Dayton, OH 45402\n", "Riverside Plant"),
        ("Bill To: Staging-Test Foods Inc.\nFacility: Riverside Plant\n", "Riverside Plant"),
        # non-ASCII and CJK site names
        ("Bill To: Staging-Test Foods Inc.\nShip To: Müller Käserei – Zürich\n", "Müller Käserei – Zürich"),
        ("Bill To: Staging-Test Foods Inc.\nShip To: 東京工場\n", "東京工場"),
        # a site name that contains the company name is a site, not the company
        ("Bill To: Staging-Test Foods Inc.\nShip To: Staging-Test Foods Inc. – Riverside Plant\n",
         "Staging-Test Foods Inc. – Riverside Plant"),
    ],
)
def test_the_site_is_the_facility_when_a_bill_to_is_also_present(targets: list[dict], parties: str, site: str) -> None:
    assert _facility_of(PROPANE_SHAPE.format(parties=parties), targets) == site


@pytest.mark.parametrize("label", ["Bill To", "Sold To", "Customer", "Customer Name", "Account Name", "Account Holder",
                                   "Billed To", "Invoice To"])
def test_a_bill_to_name_alone_is_not_a_facility_in_strict_mode(targets: list[dict], strict: None, label: str) -> None:
    assert _facility_of(PROPANE_SHAPE.format(parties=f"{label}: Staging-Test Foods Inc.\n"), targets) is None


@pytest.mark.parametrize("label", ["Bill To", "Sold To", "Customer"])
def test_a_document_with_no_site_keeps_the_company_on_the_bill_as_its_facility(targets: list[dict], label: str) -> None:
    # the golden set's SC-03 and SC-05 rely on this (a bill to a single plant)
    assert _facility_of(PROPANE_SHAPE.format(parties=f"{label}: Harborview Cold Storage LLC\n"), targets) == (
        "Harborview Cold Storage LLC")


def test_a_facility_label_that_repeats_the_bill_to_name_is_not_a_facility(targets: list[dict], strict: None) -> None:
    parties = "Bill To: Staging-Test Foods Inc.\nSite: staging-test foods inc\n"
    assert _facility_of(PROPANE_SHAPE.format(parties=parties), targets) is None


def test_a_ship_to_that_is_only_a_street_address_is_not_a_facility_name(targets: list[dict], strict: None) -> None:
    parties = "Bill To: Staging-Test Foods Inc.\nShip To: 12 Mill Road, Dayton, OH 45402\n"
    outcome = StationaryCombustionExtractor().extract(_text_output(PROPANE_SHAPE.format(parties=parties)), targets, "EV-1")
    fields = _by_field(outcome.candidates)
    assert not fields.get("facility_name", {}).get("normalized_value")
    assert fields["service_address"]["normalized_value"].startswith("12 Mill Road")  # the address is still read


def test_bill_to_and_ship_to_blocks_in_columns_give_the_ship_to_name(targets: list[dict]) -> None:
    layout = [
        ("Blue Kettle Propane Supply", 0.08, 0.05, 0.4, 0.02),
        ("Bill To", 0.08, 0.12, 0.07, 0.013), ("Ship To", 0.55, 0.12, 0.07, 0.013),
        ("Staging-Test Foods Inc.", 0.08, 0.14, 0.2, 0.013), ("Riverside Plant", 0.55, 0.14, 0.15, 0.013),
        ("500 Corporate Way", 0.08, 0.16, 0.18, 0.013), ("12 Mill Road", 0.55, 0.16, 0.12, 0.013),
        ("Fuel Type", 0.08, 0.25, 0.1, 0.013), ("Propane (LPG)", 0.3, 0.25, 0.12, 0.013),
        ("Delivery Date", 0.08, 0.30, 0.12, 0.013), ("Gallons", 0.4, 0.30, 0.07, 0.013),
        ("02/11/2025", 0.08, 0.33, 0.1, 0.013), ("612.4", 0.4, 0.33, 0.06, 0.013),
    ]
    outcome = StationaryCombustionExtractor().extract(_measured_output(layout), targets, "EV-1")
    fields = _by_field(outcome.candidates)
    assert fields["facility_name"]["normalized_value"] == "Riverside Plant"


def test_bill_to_block_alone_in_columns_gives_no_facility(targets: list[dict], strict: None) -> None:
    layout = [
        ("Blue Kettle Propane Supply", 0.08, 0.05, 0.4, 0.02),
        ("Bill To", 0.08, 0.12, 0.07, 0.013), ("Staging-Test Foods Inc.", 0.08, 0.14, 0.2, 0.013),
        ("Fuel Type", 0.08, 0.25, 0.1, 0.013), ("Propane (LPG)", 0.3, 0.25, 0.12, 0.013),
        ("Delivery Date", 0.08, 0.30, 0.12, 0.013), ("Gallons", 0.4, 0.30, 0.07, 0.013),
        ("02/11/2025", 0.08, 0.33, 0.1, 0.013), ("612.4", 0.4, 0.33, 0.06, 0.013),
    ]
    outcome = StationaryCombustionExtractor().extract(_measured_output(layout), targets, "EV-1")
    assert not _by_field(outcome.candidates).get("facility_name", {}).get("normalized_value")


# --- the layouts of the two staging invoices: the ship-to block repeats the bill-to company ----------
# (synthetic text in the shape of a propane delivery invoice and a refrigerant supply invoice)
def _blocks(left_label: str, right_label: str, bill: list[str], ship: list[str], x_ship: float, top: float = 0.17):
    rows = [(left_label, 0.065, top, 0.08, 0.012), (right_label, x_ship, top, 0.1, 0.012)]
    for i, text in enumerate(bill):
        rows.append((text, 0.065, top + 0.016 * (i + 1), 0.2, 0.012))
    for i, text in enumerate(ship):
        rows.append((text, x_ship, top + 0.016 * (i + 1), 0.2, 0.012))
    return rows


def test_propane_invoice_shape_gives_the_site_line_of_the_delivered_to_block(targets: list[dict]) -> None:
    layout = [
        ("Blue Kettle Propane Supply", 0.18, 0.06, 0.4, 0.02),
        *_blocks("Sold To:", "Delivered To:",
                 ["Staging-Test Foods Inc.", "Attn: Accounts Payable", "PO Box 7718", "Springfield, OR 97477"],
                 ["Staging-Test Foods Inc.", "Riverside Plant", "410 Mill Road", "Springfield, OR 97477"], 0.36),
        ("Customer #:", 0.64, 0.205, 0.08, 0.012), ("C-008831", 0.76, 0.205, 0.08, 0.012),
        ("Fuel: Propane (LPG), HD-5 grade.", 0.065, 0.45, 0.3, 0.012),
        ("Delivery Date", 0.065, 0.30, 0.1, 0.012), ("Gallons", 0.5, 0.30, 0.05, 0.012),
        ("02/11/2025", 0.065, 0.33, 0.1, 0.012), ("612.4", 0.5, 0.33, 0.05, 0.012),
    ]
    fields = _by_field(StationaryCombustionExtractor().extract(_measured_output(layout), targets, "EV-1").candidates)
    assert fields["facility_name"]["normalized_value"] == "Riverside Plant"
    assert fields["service_address"]["normalized_value"] == "410 Mill Road, Springfield, OR 97477"


def test_refrigerant_invoice_shape_gives_the_site_line_of_the_ship_to_block(targets: list[dict]) -> None:
    from backend.app.services.refrigerant_extractor import RefrigerantServiceExtractor

    layout = [
        ("POLAR RIDGE", 0.065, 0.06, 0.3, 0.025),
        *_blocks("BILL TO", "SHIP TO",
                 ["Staging-Test Foods Inc.", "Attn: Accounts Payable", "PO Box 7718", "Springfield, OR 97477"],
                 ["Staging-Test Foods Inc.", "Riverside Plant - Maintenance", "410 Mill Road", "Springfield, OR 97477"],
                 0.49, top=0.2),
        ("Total refrigerant shipped: 120 lb (4 cylinders x 30 lb).", 0.065, 0.48, 0.4, 0.012),
        ("Refrigerant R-134a (HFC-134a), 30 lb returnable cylinder", 0.15, 0.42, 0.35, 0.012),
    ]
    from backend.tests.services.test_refrigerant_extractor import _by_field as refrigerant_fields

    outcome = RefrigerantServiceExtractor().extract(_measured_output(layout), targets, "EV-1")
    fields = refrigerant_fields(outcome.candidates)
    assert fields["facility_name"]["normalized_value"] == "Riverside Plant - Maintenance"
    assert fields["service_address"]["normalized_value"] == "410 Mill Road, Springfield, OR 97477"


def test_a_ship_to_block_with_only_the_company_and_an_address_gives_no_facility(targets: list[dict], strict: None) -> None:
    layout = [
        ("Blue Kettle Propane Supply", 0.18, 0.06, 0.4, 0.02),
        *_blocks("Sold To:", "Delivered To:", ["Staging-Test Foods Inc.", "PO Box 7718", "Springfield, OR 97477"],
                 ["Staging-Test Foods Inc.", "410 Mill Road", "Springfield, OR 97477"], 0.36),
        ("Fuel: Propane (LPG), HD-5 grade.", 0.065, 0.45, 0.3, 0.012),
        ("Delivery Date", 0.065, 0.30, 0.1, 0.012), ("Gallons", 0.5, 0.30, 0.05, 0.012),
        ("02/11/2025", 0.065, 0.33, 0.1, 0.012), ("612.4", 0.5, 0.33, 0.05, 0.012),
    ]
    fields = _by_field(StationaryCombustionExtractor().extract(_measured_output(layout), targets, "EV-1").candidates)
    assert not fields.get("facility_name", {}).get("normalized_value")


def test_plain_text_blocks_skip_the_company_and_attention_lines(targets: list[dict]) -> None:
    parties = ("Sold To:\nStaging-Test Foods Inc.\nAttn: Accounts Payable\nPO Box 7718\nSpringfield, OR 97477\n"
               "Delivered To:\nStaging-Test Foods Inc.\nMüller Käserei – Zürich\n410 Mill Road\nSpringfield, OR 97477\n")
    assert _facility_of(PROPANE_SHAPE.format(parties=parties), targets) == "Müller Käserei – Zürich"


def test_a_site_beats_a_customer(targets: list[dict]) -> None:
    parties = "Customer: Staging-Test Foods Inc.\nService Location: Riverside Plant\n"
    assert _facility_of(PROPANE_SHAPE.format(parties=parties), targets) == "Riverside Plant"


# --- an untitled bill: the quantity in large type with its unit below, and a period with no label ------
@pytest.mark.parametrize(
    ("text", "dates"),
    [
        ("October 1 - 31, 2025", ["2025-10-01", "2025-10-31"]),
        ("Oct 1 – 31, 2025", ["2025-10-01", "2025-10-31"]),
        ("Oct. 1 — 31, 2025", ["2025-10-01", "2025-10-31"]),
        ("September 28 - October 27, 2025", ["2025-09-28", "2025-10-27"]),
        ("December 16, 2025 - January 15, 2026", ["2025-12-16", "2026-01-15"]),
        ("Dec 16 - Jan 15, 2026", ["2025-12-16", "2026-01-15"]),  # across a year end, the first year left out
        ("Feb 1 - 29, 2024", ["2024-02-01", "2024-02-29"]),
        ("Billing period October 1 - 31, 2025 (31 days)", ["2025-10-01", "2025-10-31"]),
        # not a date range: nothing is invented
        ("Feb 1 - 29, 2025", []),                       # no 29 February in 2025
        ("October 31 - 1, 2025", []),                   # backwards
        ("Oktober 1 - 31, 2025", []),                   # another language's month name does not match
        ("10月1日 - 31日", []),
        ("Mai 1 - 31, 2025", []),
    ],
)
def test_a_range_written_with_one_year_is_read_and_anything_else_is_not(text: str, dates: list[str]) -> None:
    assert parse_dates(text) == dates


def _read(layout: list[tuple[str, float, float, float, float]], targets: list[dict], extractor: Any = None) -> dict[str, dict]:
    outcome = (extractor or StationaryCombustionExtractor()).extract(_measured_output(layout), targets, "EV-1")
    return _by_field(outcome.candidates)


def _nothing_read(fields: dict[str, dict], *names: str) -> None:
    for name in names:
        assert not fields.get(name, {}).get("normalized_value"), (name, fields.get(name))


# (text, left, top, width, height): the staging bill's layout, with the quantity in large type
MYSTERY = [
    ("Hello, Staging-Test Foods Inc.", 0.065, 0.054, 0.3, 0.013),
    ("Gas meter", 0.039, 0.489, 0.1, 0.01), ("CG-6620193", 0.039, 0.502, 0.1, 0.01),
    ("1,486", 0.036, 0.171, 0.2, 0.058), ("therms used", 0.039, 0.228, 0.15, 0.015),
    ("October 1 - 31, 2025", 0.039, 0.269, 0.2, 0.011),
    ("That's 9% less than", 0.039, 0.302, 0.2, 0.011), ("October last year.", 0.039, 0.318, 0.2, 0.011),
    ("Pay by 11/25/2025:", 0.039, 0.351, 0.2, 0.011), ("$1,474.33", 0.039, 0.385, 0.2, 0.025),
    ("Customer number", 0.039, 0.447, 0.12, 0.01), ("3305-778-1102", 0.039, 0.461, 0.12, 0.01),
    ("Natural gas bill from Cedarline Gas & Power", 0.351, 0.141, 0.4, 0.014),
    ("1,980", 0.358, 0.47, 0.04, 0.009), ("May", 0.358, 0.58, 0.04, 0.009),
    ("1,486", 0.808, 0.498, 0.04, 0.009), ("Oct", 0.808, 0.58, 0.04, 0.009),
]

# Body-size text, with non-ASCII names so a layout that reads the wrong thing is also not helped by ASCII.
BODY = 0.011
HEAD = [("Natural gas service, Müller Käserei – Zürich 東京工場", 0.35, 0.05, 0.4, 0.014),
        ("Hello, Staging-Test Foods Inc.", 0.065, 0.02, 0.3, 0.013)]


def test_a_headline_quantity_with_its_unit_below_and_a_lone_period_are_read(targets: list[dict]) -> None:
    fields = _read(MYSTERY, targets)
    assert fields["activity_quantity"]["raw_value"] == "1,486"
    assert fields["activity_quantity"]["normalized_value"] == pytest.approx(148.6)  # therms to MMBtu
    assert fields["activity_quantity"]["confidence"] == 0.7  # a guess from layout, not a labelled value
    assert fields["activity_unit"]["normalized_value"] == "MMBtu"
    assert fields["service_period_start"]["normalized_value"] == "2025-10-01"
    assert fields["service_period_end"]["normalized_value"] == "2025-10-31"
    assert fields["fuel_type"]["normalized_value"] == "natural_gas"


def test_the_headline_quantity_is_never_part_of_the_classification_check(targets: list[dict]) -> None:
    # confirms() decides the document's type: a number above a unit word must not flip it.
    assert not StationaryCombustionExtractor().confirms(_measured_output(
        [("Natural gas & propane supply", 0.05, 0.05, 0.4, BODY), ("1,486", 0.036, 0.171, 0.2, 0.058),
         ("therms used", 0.039, 0.228, 0.15, 0.015)]))


# Each layout is a stray number over a word that looks like a unit. Every one was an empty field before the
# headline read, and has to stay empty. Non-ASCII text sits in every layout.
NEGATIVE_LAYOUTS: dict[str, list[tuple[str, float, float, float, float]]] = {
    "a tank size": HEAD + [("Your tank", 0.05, 0.30, 0.1, BODY), ("500", 0.05, 0.315, 0.05, BODY),
                           ("gallons capacity", 0.05, 0.33, 0.15, BODY), ("Total therms 1,486", 0.5, 0.4, 0.2, BODY)],
    "a meter reading in body type": HEAD + [("Current reading", 0.05, 0.30, 0.15, BODY),
                                            ("46696", 0.05, 0.315, 0.06, BODY), ("CCF", 0.05, 0.33, 0.05, BODY)],
    "a meter reading in large type": HEAD + [("Current reading", 0.05, 0.1, 0.15, BODY),
                                             ("46696", 0.05, 0.115, 0.1, 0.05), ("CCF used", 0.05, 0.168, 0.05, 0.012)],
    "a daily average": HEAD + [("Average daily use", 0.05, 0.30, 0.15, BODY), ("48", 0.05, 0.315, 0.05, 0.03),
                               ("therms per day", 0.05, 0.35, 0.15, BODY), ("Total therms: 1,486", 0.5, 0.4, 0.2, BODY)],
    "a year over Therms": HEAD + [("2025", 0.6, 0.30, 0.05, BODY), ("Therms", 0.6, 0.315, 0.08, BODY),
                                  ("Total therms 1,486", 0.05, 0.4, 0.2, BODY)],
    "a rate": HEAD + [("0.0912", 0.05, 0.30, 0.15, 0.03), ("therm rate", 0.05, 0.335, 0.1, BODY)],
    "a rate per therm": HEAD + [("0.0912", 0.05, 0.30, 0.15, 0.03), ("per therm", 0.05, 0.335, 0.1, BODY)],
    "a chart axis": HEAD + [("500", 0.05, 0.50, 0.03, 0.008), ("0", 0.05, 0.52, 0.03, 0.008),
                            ("Therms", 0.05, 0.535, 0.06, 0.008)],
    "a number in large type over a word that is not a unit": HEAD + [
        ("1,474.33", 0.05, 0.30, 0.2, 0.058), ("Total due", 0.05, 0.36, 0.15, 0.015)],
    "a postal code over an ambiguous short unit": HEAD + [
        ("Remit to", 0.05, 0.80, 0.1, BODY), ("63150", 0.05, 0.815, 0.1, 0.05),
        ("St. Louis, MO 63150", 0.05, 0.868, 0.2, 0.012)],
    "a postal code over a unit with a digit": HEAD + [
        ("63150", 0.05, 0.815, 0.1, 0.05), ("T 63150", 0.05, 0.868, 0.2, 0.012)],
    "a number in a table column (not under, not large)": HEAD + [
        ("Therms", 0.5, 0.5, 0.1, BODY), ("1,486", 0.5, 0.52, 0.1, BODY)],
}


@pytest.mark.parametrize("name", list(NEGATIVE_LAYOUTS))
def test_a_stray_number_over_a_word_like_a_unit_is_not_a_quantity(targets: list[dict], name: str) -> None:
    fields = _read(NEGATIVE_LAYOUTS[name], targets)

    _nothing_read(fields, "activity_quantity", "activity_unit")


def test_the_number_must_be_among_the_largest_type_on_its_page(targets: list[dict]) -> None:
    # Twice as tall as its unit line, but three bigger sizes of text on the page: not a headline.
    layout = HEAD + [("Pay now", 0.5, 0.05, 0.2, 0.09), ("Big", 0.5, 0.2, 0.2, 0.08), ("Bigger", 0.5, 0.3, 0.2, 0.07),
                     ("1,486", 0.05, 0.5, 0.1, 0.04), ("therms used", 0.05, 0.545, 0.15, 0.015)]

    _nothing_read(_read(layout, targets), "activity_quantity")


def test_a_number_that_is_not_twice_as_tall_as_the_unit_line_is_not_a_headline(targets: list[dict]) -> None:
    layout = HEAD + [("1,486", 0.05, 0.5, 0.1, 0.029), ("therms used", 0.05, 0.53, 0.15, 0.015)]

    _nothing_read(_read(layout, targets), "activity_quantity")


@pytest.mark.parametrize("unit_line", ["therms billed", "Therms consumed", "therms delivered", "therms usage", "therms"])
def test_a_unit_line_may_end_in_a_usage_word(targets: list[dict], unit_line: str) -> None:
    layout = [row for row in MYSTERY if row[0] not in ("1,486", "therms used")] + [
        ("1,486", 0.036, 0.171, 0.2, 0.058), (unit_line, 0.039, 0.228, 0.15, 0.015)]

    assert _read(layout, targets)["activity_quantity"]["raw_value"] == "1,486"


@pytest.mark.parametrize("unit_line", ["therms per day", "therms used last year", "therms 2025", "St", "T", "L", "CF",
                                       "Ton", "gallons capacity"])
def test_any_other_unit_line_is_not_read(targets: list[dict], unit_line: str) -> None:
    layout = [row for row in MYSTERY if row[0] not in ("1,486", "therms used")] + [
        ("1,486", 0.036, 0.171, 0.2, 0.058), (unit_line, 0.039, 0.228, 0.15, 0.015)]

    _nothing_read(_read(layout, targets), "activity_quantity")


def test_plain_text_has_no_sign_of_size_so_it_is_not_a_headline(targets: list[dict]) -> None:
    lone = "Hello, Staging-Test Foods Inc.\n1,486\ntherms used\nOctober 1 - 31, 2025\nNatural gas from Cedarline\n"
    fields = _by_field(StationaryCombustionExtractor().extract(_text_output(lone), targets, "EV-1").candidates)
    _nothing_read(fields, "activity_quantity")
    # a labelled quantity is still read, and a day count or a meter reading above it is not taken for it
    for text in ("Cedarline Gas & Power\nNatural gas service, Z\u00fcrich\nDays in period    31\nTherms billed 1,486\n",
                 "Cedarline Gas & Power\nNatural gas service\nCurrent reading\n46696\nTherms used 1,486\n"):
        fields = _by_field(StationaryCombustionExtractor().extract(_text_output(text), targets, "EV-1").candidates)
        assert fields["activity_quantity"]["raw_value"] not in ("31", "46696"), text


def test_only_the_natural_gas_reader_reads_a_headline(targets: list[dict]) -> None:
    from backend.app.services.electricity_extractor import ElectricityExtractor
    from backend.app.services.mobile_combustion_extractor import MobileCombustionExtractor
    from backend.app.services.refrigerant_extractor import RefrigerantServiceExtractor
    from backend.app.services.thermal_extractor import ThermalExtractor

    assert StationaryCombustionExtractor.HEADLINE_QUANTITY is True
    for extractor in (ElectricityExtractor, MobileCombustionExtractor, RefrigerantServiceExtractor, ThermalExtractor):
        assert extractor.HEADLINE_QUANTITY is False, extractor.__name__


def test_a_meter_reading_over_kwh_on_an_electricity_bill_is_not_read_and_the_bill_still_halts() -> None:
    from backend.app.services.electricity_extractor import ElectricityExtractor
    from backend.app.services.extraction_target_service import ExtractionTargetService

    layout = [("Metro Electric Company – Zürich 東京", 0.35, 0.05, 0.4, 0.02),
              ("Electric service statement", 0.05, 0.1, 0.3, BODY),
              ("Meter 99812", 0.05, 0.30, 0.15, BODY), ("Present read", 0.05, 0.32, 0.15, BODY),
              ("045210", 0.05, 0.335, 0.08, 0.05), ("kWh actual", 0.05, 0.388, 0.1, BODY),
              ("Energy charge 1,210 kWh x $0.12", 0.4, 0.5, 0.4, BODY)]
    electricity = ExtractionTargetService().get_targets_for_canonical_type("CT-S2-ELEC")

    outcome = ElectricityExtractor().extract(_measured_output(layout), electricity, "EV-1")

    assert outcome.halt_reason is not None and outcome.halt_reason["code"] == "unsupported_document"
    assert not outcome.candidates
    assert not StationaryCombustionExtractor().confirms(_measured_output(layout))
    assert not ElectricityExtractor().confirms(_measured_output(layout))
    # and a gas reader that is handed it reads no quantity either
    _nothing_read(_read(layout, ExtractionTargetService().get_targets_for_canonical_type("CT-S1-FUELQTY")),
                  "activity_quantity")


def test_the_headline_never_runs_ahead_of_a_fuel_card_receipt(targets: list[dict]) -> None:
    from backend.app.services.extraction_target_service import ExtractionTargetService
    from backend.app.services.mobile_combustion_extractor import MobileCombustionExtractor

    mobile = ExtractionTargetService().get_targets_for_canonical_type("CT-S1-MOBFUEL")
    receipt = [("Fleet fuel receipt – Zürich", 0.1, 0.05, 0.4, 0.02), ("Diesel", 0.05, 0.2, 0.1, BODY),
               ("48", 0.05, 0.3, 0.05, 0.05), ("gallons", 0.05, 0.353, 0.1, 0.012)]

    outcome = MobileCombustionExtractor().extract(_measured_output(receipt), mobile, "EV-1")

    assert not [c for c in outcome.candidates if c["field_name"] == "activity_quantity" and c["normalized_value"] == 48]


def test_an_amount_due_in_the_same_large_type_beside_the_therms_is_never_the_quantity(targets: list[dict]) -> None:
    layout = [row for row in MYSTERY if row[0] != "$1,474.33"] + [
        ("1,474.33", 0.45, 0.171, 0.2, 0.058), ("Total due", 0.45, 0.228, 0.15, 0.015)]

    fields = _read(layout, targets)

    assert fields["activity_quantity"]["raw_value"] == "1,486"
    assert fields["activity_quantity"]["normalized_value"] == pytest.approx(148.6)


def test_two_numbers_that_each_have_a_unit_below_are_not_guessed_between(targets: list[dict]) -> None:
    layout = [row for row in MYSTERY if row[0] not in ("1,486", "therms used")] + [
        ("1,486", 0.036, 0.171, 0.2, 0.058), ("therms used", 0.039, 0.228, 0.15, 0.015),
        ("1,433", 0.3, 0.171, 0.2, 0.058), ("CCF", 0.3, 0.228, 0.1, 0.015)]

    _nothing_read(_read(layout, targets), "activity_quantity")


def test_a_number_far_above_the_unit_line_is_not_its_quantity(targets: list[dict]) -> None:
    layout = [row for row in MYSTERY if row[0] != "1,486"] + [("1,486", 0.036, 0.05, 0.1, 0.05)]

    _nothing_read(_read(layout, targets), "activity_quantity")


# --- a period with no label ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "period",
    [
        "11/03/2025 11/25/2025",                       # a statement date and a due date side by side
        "11/03/2025 Pay by 11/25/2025",
        "10/01/2025 - 10/31/2025 (31 days)",
        "11/03/2025 - 11/10/2025",                     # seven days: not a billing period
        "01/01/2025 - 12/31/2025",                     # a whole year
        "10/01/2025 – Müller 10/31/2025",
    ],
)
def test_a_cell_that_is_not_exactly_two_dates_a_dash_apart_and_a_month_long_is_not_a_period(
        targets: list[dict], period: str) -> None:
    layout = [row for row in MYSTERY if row[0] != "October 1 - 31, 2025"] + [(period, 0.5, 0.315, 0.3, BODY)]

    _nothing_read(_read(layout, targets), "service_period_start", "service_period_end")


@pytest.mark.parametrize("label", ["Next scheduled meter read", "Due date", "Pay by", "Statement date",
                                   "Bill date", "Nächste Ablesung / next read", "Date issued"])
def test_a_range_labelled_as_a_next_read_due_or_statement_date_is_not_the_service_period(
        targets: list[dict], label: str) -> None:
    layout = [row for row in MYSTERY if row[0] != "October 1 - 31, 2025"] + [
        (label, 0.5, 0.30, 0.3, BODY), ("Nov 26 - Dec 21, 2025", 0.5, 0.315, 0.3, BODY)]

    _nothing_read(_read(layout, targets), "service_period_start", "service_period_end")


@pytest.mark.parametrize(
    ("period", "start", "end"),
    [
        ("10/01/2025 - 10/31/2025", "2025-10-01", "2025-10-31"),
        ("10/01/2025 – 10/31/2025", "2025-10-01", "2025-10-31"),
        ("10/01/2025 to 10/31/2025", "2025-10-01", "2025-10-31"),
        ("December 16, 2025 - January 15, 2026", "2025-12-16", "2026-01-15"),
        ("Dec 16 - Jan 15, 2026", "2025-12-16", "2026-01-15"),
        ("Sep 28 — Oct 27, 2025", "2025-09-28", "2025-10-27"),
    ],
)
def test_a_cell_that_is_exactly_two_dates_a_dash_apart_is_the_period(
        targets: list[dict], period: str, start: str, end: str) -> None:
    layout = [row for row in MYSTERY if row[0] != "October 1 - 31, 2025"] + [(period, 0.039, 0.269, 0.3, BODY)]

    fields = _read(layout, targets)

    assert (fields["service_period_start"]["normalized_value"], fields["service_period_end"]["normalized_value"]) == (
        start, end)


def test_a_period_printed_twice_or_as_a_year_is_not_taken_as_the_service_period(targets: list[dict]) -> None:
    twice = MYSTERY + [("October 1 - 31, 2024", 0.5, 0.269, 0.2, BODY)]  # last year's, too

    _nothing_read(_read(twice, targets), "service_period_start")
    year = [row for row in MYSTERY if row[0] != "October 1 - 31, 2025"] + [
        ("January 1 - December 31, 2025", 0.039, 0.269, 0.3, BODY)]
    _nothing_read(_read(year, targets), "service_period_start")


def test_a_labelled_period_still_wins_over_a_lone_range(targets: list[dict]) -> None:
    layout = MYSTERY + [("Service Period: 09/01/2025 - 09/30/2025", 0.351, 0.62, 0.4, BODY)]

    fields = _read(layout, targets)

    assert (fields["service_period_start"]["normalized_value"], fields["service_period_end"]["normalized_value"]) == (
        "2025-09-01", "2025-09-30")


def test_a_non_english_month_name_is_not_read_silently_as_a_period(targets: list[dict]) -> None:
    layout = [("Oktober 1 - 31, 2025" if row[0] == "October 1 - 31, 2025" else row[0], *row[1:]) for row in MYSTERY]

    fields = _read(layout, targets)

    assert fields["activity_quantity"]["raw_value"] == "1,486"  # the quantity does not depend on the month name
    _nothing_read(fields, "service_period_start")


def test_a_heading_with_a_digit_is_not_an_account_number(targets: list[dict]) -> None:
    layout = [("Customer number", 0.039, 0.447, 0.12, 0.01), ("Your last 6 months", 0.351, 0.444, 0.14, 0.014),
              ("Natural gas therms", 0.039, 0.3, 0.2, 0.01), ("1,486", 0.036, 0.171, 0.2, 0.058),
              ("therms used", 0.039, 0.228, 0.15, 0.015)]

    _nothing_read(_read(layout, targets), "account_number")


# --- a dense statement: the usage inside a line, and who is paid on a Remit To line ------------------------
def _lines_output(lines: list[str], *, boxed: bool = True) -> dict[str, Any]:
    """A statement as a PDF reader gives it: one cell per line, all the same height (so no line is a letterhead
    by size), or as plain text."""

    if not boxed:
        return _text_output("\n".join(lines))
    return _measured_output([(text, 0.088, 0.08 + 0.0155 * i, 0.5, 0.011) for i, text in enumerate(lines)])


def _fields(lines: list[str], targets: list[dict], *, boxed: bool = True) -> dict[str, dict]:
    outcome = StationaryCombustionExtractor().extract(_lines_output(lines, boxed=boxed), targets, "EV-1")
    return _by_field(outcome.candidates)


def _value(fields: dict[str, dict], name: str) -> Any:
    return fields.get(name, {}).get("normalized_value")


# The layout of a dense gas statement (synthetic, with non-ASCII in the customer and supplier names).
DENSE = [
    "NORTHGATE PROVISIONS ÅNGSTRÖM INC",
    "555 CAPITOL MALL STE 900",
    "SACRAMENTO CA 95814",
    "ACCOUNT NO 4417-9083-52",
    "STMT DATE 09/05/2025",
    "DUE DATE 09/26/2025",
    "FROM 08/01/2025 TO 08/31/2025 31 DAYS",
    "METER GM-0127764 PREV 40,211 CURR 41,447 USE 1,236 CCF",
    "THERM FACTOR 1.030 TOTAL 1,273.1 THERMS",
    "CUSTOMER CHARGE 31 DAYS @ 1.48000 45.88",
    "GAS TRANSPORTATION 1,273.1 THM @ 0.68420 871.04",
    "SUBTOTAL 1,785.85",
    "TOTAL DUE 1,910.86",
    "REMIT TO: SIERRA BASIN ÉNERGIE CO, PO BOX 618 東京",
]


@pytest.mark.parametrize("boxed", [True, False])
def test_a_dense_statement_gives_its_inline_total_and_who_is_paid(targets: list[dict], boxed: bool) -> None:
    fields = _fields(DENSE, targets, boxed=boxed)

    assert fields["activity_quantity"]["raw_value"] == "1,273.1"
    assert _value(fields, "activity_quantity") == pytest.approx(127.31)  # therms to MMBtu
    assert _value(fields, "activity_unit") == "MMBtu"
    assert _value(fields, "supplier_name") == "SIERRA BASIN ÉNERGIE CO"  # not the addressee on the first line
    assert (_value(fields, "service_period_start"), _value(fields, "service_period_end")) == ("2025-08-01", "2025-08-31")
    assert _value(fields, "account_number") == "4417-9083-52"


def test_only_the_therms_count_when_a_total_amount_due_sits_beside_them(targets: list[dict]) -> None:
    lines = [row for row in DENSE if not row.startswith(("THERM FACTOR", "TOTAL DUE"))]
    lines[7:7] = ["TOTAL AMOUNT DUE $1,474.33", "THERM FACTOR 1.030 TOTAL 1,273.1 THERMS", "TOTAL 1,474.33 USD"]

    fields = _fields(lines, targets)

    assert fields["activity_quantity"]["raw_value"] == "1,273.1"


@pytest.mark.parametrize("line", ["TOTAL CHARGES 1,474.33", "TOTAL AMOUNT DUE $1,474.33", "TOTAL $1,474.33 THERMS",
                                  "TOTAL DUE 1,910.86 EUR – Zürich", "TOTAL 45.88 USD", "TOTAL 7 ST"])
def test_a_total_that_is_money_or_has_no_real_unit_is_not_the_quantity(targets: list[dict], line: str) -> None:
    lines = ["Natural gas statement – Zürich 東京", "ACCOUNT NO 4417-9083-52", "FROM 08/01/2025 TO 08/31/2025", line]

    assert _value(_fields(lines, targets), "activity_quantity") is None


def test_a_meter_read_line_is_not_the_quantity(targets: list[dict]) -> None:
    lines = ["Natural gas statement – Zürich", "METER GM-0127764 PREV 40,211 CURR 41,447 USE 1,236 CCF",
             "FROM 08/01/2025 TO 08/31/2025"]

    fields = _fields(lines, targets)

    assert _value(fields, "activity_quantity") not in (40211, 41447)  # the reads are never taken as usage
    assert fields["activity_quantity"].get("raw_value") not in ("40,211", "41,447")


def test_two_different_totals_in_units_are_not_guessed_between(targets: list[dict]) -> None:
    lines = ["Natural gas statement – Zürich", "TOTAL 1,273.1 THERMS", "TOTAL 1,236 CCF", "FROM 08/01/2025 TO 08/31/2025"]

    assert _value(_fields(lines, targets), "activity_quantity") is None


def test_the_labelled_usage_reads_win_over_an_inline_total(targets: list[dict]) -> None:
    lines = ["Natural gas statement – Zürich", "Total Usage: 900 therms", "THERM FACTOR 1.030 TOTAL 1,273.1 THERMS"]

    assert _fields(lines, targets)["activity_quantity"]["raw_value"] == "900"


def test_no_other_reader_reads_an_inline_total() -> None:
    from backend.app.services.electricity_extractor import ElectricityExtractor
    from backend.app.services.mobile_combustion_extractor import MobileCombustionExtractor
    from backend.app.services.refrigerant_extractor import RefrigerantServiceExtractor
    from backend.app.services.thermal_extractor import ThermalExtractor

    assert StationaryCombustionExtractor.INLINE_TOTAL_QUANTITY is True
    for extractor in (ElectricityExtractor, MobileCombustionExtractor, RefrigerantServiceExtractor, ThermalExtractor):
        assert extractor.INLINE_TOTAL_QUANTITY is False, extractor.__name__


def test_the_inline_total_is_not_part_of_the_classification_check() -> None:
    # confirms() is decided by the labelled reads alone: the inline form does not confirm a document's type
    assert not StationaryCombustionExtractor().confirms(_lines_output(["Natural gas statement", "TOTAL 1,273.1 THERMS"]))


# --- the supplier ------------------------------------------------------------------------------------
@pytest.mark.parametrize("remit", ["REMIT TO: PO BOX 618, LOCKBOX 1234", "REMIT TO: LOCKBOX 1234 PO BOX 618",
                                   "Remit to: First National Bank, Lockbox 1234", "PAYABLE TO: Remittance Center – Zürich",
                                   "REMIT TO: 618 Main Street", "REMIT TO: P.O. Box 618"])
def test_a_remit_to_that_is_a_lockbox_or_a_bank_names_no_supplier(targets: list[dict], remit: str) -> None:
    lines = ["Natural gas statement – Zürich 東京", "ACCOUNT NO 4417-9083-52", "Total Usage: 900 therms", remit]

    assert _value(_fields(lines, targets), "supplier_name") is None


@pytest.mark.parametrize("remit", ["REMIT TO: SIERRA BASIN ENERGY CO, PO BOX 618", "Make checks payable to: Sierra Basin Energy Co.",
                                   "PAYABLE TO SIERRA BASIN ENERGY CO – PO BOX 618"])
def test_a_remit_to_organisation_is_the_supplier_when_nothing_else_names_one(targets: list[dict], remit: str) -> None:
    lines = ["Natural gas statement – Zürich", "Bill To: Müller Käserei GmbH", "Total Usage: 900 therms", remit]

    assert str(_value(_fields(lines, targets), "supplier_name")).lower().startswith("sierra basin energy co")


def test_a_bill_that_names_only_the_customer_and_a_remit_to_gets_the_remit_to(targets: list[dict]) -> None:
    lines = ["Natural gas statement – Zürich", "CUSTOMER: ÅNGSTRÖM FOODS INC", "Total Usage: 900 therms",
             "REMIT TO: SIERRA BASIN ENERGY CO"]

    assert _value(_fields(lines, targets), "supplier_name") == "SIERRA BASIN ENERGY CO"


@pytest.mark.parametrize("label", ["BILL TO", "SOLD TO", "SERVICE FOR", "CUSTOMER", "ACCOUNT HOLDER"])
def test_the_customer_is_never_the_supplier(targets: list[dict], label: str) -> None:
    # the customer named on the first line (a letterhead guess) and again under a customer label
    lines = ["ÅNGSTRÖM FOODS INC", f"{label}: ÅNGSTRÖM FOODS INC", "Total Usage: 900 therms"]

    assert _value(_fields(lines, targets), "supplier_name") is None


def test_a_letterhead_that_names_the_utility_is_not_overridden_by_a_remit_to(targets: list[dict]) -> None:
    # sized letterhead: the largest text near the top
    layout = [("Acme Gas Company – Zürich", 0.2, 0.05, 0.5, 0.03), ("100 Main Street", 0.2, 0.09, 0.3, 0.011),
              ("Dayton OH 45402", 0.2, 0.105, 0.3, 0.011), ("ACCOUNT NO 4417-9083-52", 0.2, 0.12, 0.3, 0.011),
              ("Total Usage: 900 therms", 0.2, 0.3, 0.3, 0.011),
              ("REMIT TO: ACME BILLING SERVICES INC, PO BOX 618", 0.2, 0.5, 0.5, 0.011)]
    fields = _by_field(StationaryCombustionExtractor().extract(_measured_output(layout), targets, "EV-1").candidates)

    assert _value(fields, "supplier_name") == "Acme Gas Company – Zürich"


def test_a_first_line_that_is_not_an_address_block_is_still_the_letterhead(targets: list[dict]) -> None:
    lines = ["Acme Gas Company", "Natural gas bill", "ACCOUNT NO 4417-9083-52", "Total Usage: 900 therms",
             "REMIT TO: ACME BILLING SERVICES INC, PO BOX 618"]

    assert _value(_fields(lines, targets), "supplier_name") == "Acme Gas Company"


def test_a_labelled_supplier_is_not_overridden_by_a_remit_to(targets: list[dict]) -> None:
    lines = ["Natural gas statement – Zürich", "Supplier: Cedarline Gas & Power", "Total Usage: 900 therms",
             "REMIT TO: SIERRA BASIN ENERGY CO"]

    assert _value(_fields(lines, targets), "supplier_name") == "Cedarline Gas & Power"


# --- fix round 2: the line under the unit line, whole-word labels, height bands ---------------------------
UNDER_UNIT_LAYOUTS: dict[str, list[tuple[str, float, float, float, float]]] = {
    "a daily average": HEAD + [("Average daily use", 0.05, 0.25, 0.15, BODY), ("48", 0.05, 0.27, 0.06, 0.05),
                               ("therms", 0.05, 0.322, 0.08, 0.015), ("per day", 0.05, 0.34, 0.08, 0.015),
                               ("Total therms: 1,486", 0.5, 0.6, 0.2, BODY)],
    "a tank size": HEAD + [("500", 0.05, 0.27, 0.06, 0.05), ("gallons", 0.05, 0.322, 0.08, 0.015),
                           ("tank capacity", 0.05, 0.34, 0.1, 0.015), ("Total therms: 1,486", 0.5, 0.6, 0.2, BODY)],
    "a meter reading": HEAD + [("46696", 0.05, 0.27, 0.1, 0.05), ("CCF", 0.05, 0.322, 0.08, 0.015),
                               ("current meter reading", 0.05, 0.34, 0.15, 0.015),
                               ("Total therms: 1,486", 0.5, 0.6, 0.2, BODY)],
    "last year's figure": HEAD + [("Same month last yr", 0.05, 0.25, 0.15, BODY), ("1,640", 0.05, 0.27, 0.1, 0.05),
                                  ("therms", 0.05, 0.322, 0.08, 0.015), ("October 2024", 0.05, 0.34, 0.1, 0.015),
                                  ("Total therms: 1,486", 0.5, 0.6, 0.2, BODY)],
    "last year's figure, year only": HEAD + [("1,640", 0.05, 0.27, 0.1, 0.05), ("therms", 0.05, 0.322, 0.08, 0.015),
                                             ("in 2024", 0.05, 0.34, 0.1, 0.015)],
    "a date under the unit": HEAD + [("1,640", 0.05, 0.27, 0.1, 0.05), ("therms", 0.05, 0.322, 0.08, 0.015),
                                     ("as of 10/31/2025", 0.05, 0.34, 0.1, 0.015)],
    "a previous period (non-ASCII)": HEAD + [("1,640", 0.05, 0.27, 0.1, 0.05), ("therms", 0.05, 0.322, 0.08, 0.015),
                                             ("Vorjahr: previous Zürich", 0.05, 0.34, 0.2, 0.015)],
}


@pytest.mark.parametrize("name", list(UNDER_UNIT_LAYOUTS))
def test_a_qualifier_or_a_date_under_the_unit_line_means_it_is_not_the_bills_quantity(
        targets: list[dict], name: str) -> None:
    fields = _read(UNDER_UNIT_LAYOUTS[name], targets)

    assert fields["activity_quantity"].get("raw_value") in (None, "1,486"), name  # only a labelled total, never the tile
    assert _value_of(fields, "activity_quantity") in (None, pytest.approx(148.6))


def _value_of(fields: dict[str, dict], name: str) -> Any:
    return fields.get(name, {}).get("normalized_value")


def test_the_bills_own_period_under_the_unit_line_is_fine(targets: list[dict]) -> None:
    layout = [row for row in MYSTERY if row[0] not in ("October 1 - 31, 2025",)] + [
        ("October 1 - 31, 2025", 0.039, 0.245, 0.2, 0.012)]  # right under "therms used"

    fields = _read(layout, targets)

    assert fields["activity_quantity"]["raw_value"] == "1,486"


@pytest.mark.parametrize("heading", ["Corporate account usage", "Your usage (31 days)", "Ihre Nutzung (31 Tage) – Zürich"])
def test_a_heading_that_only_contains_a_label_word_does_not_exclude_the_number(targets: list[dict], heading: str) -> None:
    # "rate" is inside "Corporate" and "days" is in a parenthesis about the period: whole words only
    layout = MYSTERY + [(heading, 0.036, 0.15, 0.2, 0.012)]

    assert _read(layout, targets)["activity_quantity"]["raw_value"] == "1,486"


@pytest.mark.parametrize("heading", ["Days in period", "Billing rate", "Average usage", "Last year"])
def test_a_heading_that_is_one_of_the_label_words_still_excludes_the_number(targets: list[dict], heading: str) -> None:
    layout = MYSTERY + [(heading, 0.036, 0.15, 0.2, 0.012)]

    _nothing_read(_read(layout, targets), "activity_quantity")


@pytest.mark.parametrize("label", ["Meter read dates", "Reading period", "Service period (meter read dates)",
                                   "Zählerablesung – meter read dates"])
def test_a_meter_read_label_over_the_range_is_the_service_period(targets: list[dict], label: str) -> None:
    layout = [row for row in MYSTERY if row[0] != "October 1 - 31, 2025"] + [
        (label, 0.5, 0.30, 0.3, BODY), ("Oct 1 - 31, 2025", 0.5, 0.315, 0.3, BODY)]

    fields = _read(layout, targets)

    assert (_value_of(fields, "service_period_start"), _value_of(fields, "service_period_end")) == (
        "2025-10-01", "2025-10-31")


def test_sizes_within_ten_percent_are_one_size_so_ocr_jitter_does_not_push_the_number_out(targets: list[dict]) -> None:
    # a logo, a heading and an amount in nearly the same large type: exact heights make four sizes, bands make one
    layout = MYSTERY + [("CEDARLINE", 0.7, 0.02, 0.2, 0.0601), ("Gas", 0.7, 0.1, 0.1, 0.0599),
                        ("Power – Zürich", 0.85, 0.1, 0.1, 0.0602), ("LOGO", 0.5, 0.02, 0.1, 0.07),
                        ("Your bill", 0.7, 0.2, 0.2, 0.065)]

    assert _read(layout, targets)["activity_quantity"]["raw_value"] == "1,486"


def test_three_clearly_larger_sizes_still_keep_the_number_out(targets: list[dict]) -> None:
    layout = MYSTERY + [("A", 0.7, 0.02, 0.2, 0.2), ("B", 0.7, 0.3, 0.2, 0.15), ("C", 0.7, 0.5, 0.2, 0.1)]

    _nothing_read(_read(layout, targets), "activity_quantity")


def test_the_ambiguous_unit_check_is_a_public_helper() -> None:
    from backend.app.domain import fuel_units

    for word in ("St", "st.", "T", "L", "CF", "Ton", "tons", "MT"):
        assert fuel_units.is_ambiguous_in_text(word), word
    for word in ("therms", "gallons", "CCF", "kWh"):
        assert not fuel_units.is_ambiguous_in_text(word), word


# --- fix round 3: a parenthesis that holds only words still says what the figure is; "may" is a month only beside a number
PAREN_LABELS = ["Same month (last year)", "Usage (previous reading)", "Tank (capacity)", "(per day)",
                "Durchschnitt (daily) – Zürich"]


@pytest.mark.parametrize("label", PAREN_LABELS)
def test_a_label_in_parentheses_above_the_number_still_excludes_it(targets: list[dict], label: str) -> None:
    layout = HEAD + [("Total therms: 1,486", 0.5, 0.6, 0.2, BODY), (label, 0.05, 0.25, 0.15, BODY),
                     ("1,640", 0.05, 0.265, 0.1, 0.05), ("therms", 0.05, 0.317, 0.08, 0.015)]

    fields = _read(layout, targets)

    assert fields["activity_quantity"].get("raw_value") != "1,640", label


def test_a_parenthesis_that_holds_a_number_is_still_ignored(targets: list[dict]) -> None:
    layout = MYSTERY + [("Your usage (31 days)", 0.036, 0.15, 0.2, 0.012)]

    assert _read(layout, targets)["activity_quantity"]["raw_value"] == "1,486"


def test_a_payment_due_date_label_in_parentheses_is_not_the_service_period(targets: list[dict]) -> None:
    layout = [row for row in MYSTERY if row[0] != "October 1 - 31, 2025"] + [
        ("Zahlung (due date) – Zürich", 0.5, 0.30, 0.3, BODY), ("Nov 1 - Nov 25, 2025", 0.5, 0.315, 0.3, BODY)]

    _nothing_read(_read(layout, targets), "service_period_start", "service_period_end")


@pytest.mark.parametrize(("under", "month"), [("May 5", True), ("5 May", True), ("May, 2025", True),
                                               ("you may pay online", False), ("Thank you, you may pay online – Zürich", False)])
def test_may_is_a_month_only_beside_a_day_or_a_year(targets: list[dict], under: str, month: bool) -> None:
    layout = [row for row in MYSTERY if row[0] != "October 1 - 31, 2025"] + [(under, 0.039, 0.245, 0.3, 0.012)]

    fields = _read(layout, targets)

    assert (fields["activity_quantity"].get("raw_value") != "1,486") is month


# --- fix round 1 of the dense statement: periods, order, payees, customers ----------------------------------
TOTAL_HEAD = ["Natural gas statement – Zürich 東京", "ACCOUNT NO 4417-9083-52", "FROM 08/01/2025 TO 08/31/2025"]


@pytest.mark.parametrize("line", [
    "TOTAL 2025 THERMS 14,200", "TOTAL 2025 THERMS", "TOTAL LAST YEAR 1,190 THERMS", "12-MONTH TOTAL 14,200 THERMS",
    "YEAR TO DATE TOTAL 14,200 THERMS", "YTD TOTAL 14,200 THERMS", "SAME MONTH LAST YEAR TOTAL 1,190 THERMS",
    "ANNUAL TOTAL 14,200 THERMS", "AVG DAILY TOTAL 41 THERMS", "AUG 2024 TOTAL 1,190 THERMS",
    "BUDGET PLAN TOTAL 14,200 THERMS", "ESTIMATED TOTAL 1,300 THERMS", "EST TOTAL 1,300 THERMS", "TOTAL 12 MCF-DAY",
    "PRIOR PERIOD TOTAL 1,190 THERMS", "USAGE HISTORY TOTAL 1,190 THERMS", "SEP TOTAL 1,190 THERMS",
    "TOTAL 1,273.1 THERMS-DAY", "TOTAL 1,273.1 THERMS/DAY", "TOTAL 500 KWH", "TOTAL 2,100 THERMS – Zürich 2024",
])
def test_an_inline_total_about_another_period_or_a_year_is_not_the_bills_usage(targets: list[dict], line: str) -> None:
    assert _value(_fields([*TOTAL_HEAD, line], targets), "activity_quantity") is None


def test_the_current_total_is_read_when_a_year_to_date_line_sits_beside_it(targets: list[dict]) -> None:
    fields = _fields([*TOTAL_HEAD, "THERM FACTOR 1.030 TOTAL 1,273.1 THERMS", "YEAR TO DATE TOTAL 14,200 THERMS"], targets)

    assert fields["activity_quantity"]["raw_value"] == "1,273.1"


def test_a_year_with_a_thousands_separator_is_a_quantity_and_without_one_is_not(targets: list[dict]) -> None:
    assert _fields([*TOTAL_HEAD, "TOTAL 1,999 THERMS"], targets)["activity_quantity"]["raw_value"] == "1,999"
    assert _value(_fields([*TOTAL_HEAD, "TOTAL 1999 THERMS"], targets), "activity_quantity") is None


def test_the_headline_read_runs_before_the_inline_total(targets: list[dict]) -> None:
    layout = MYSTERY + [("Year to date total 14,200 therms", 0.36, 0.62, 0.3, 0.009),
                        ("THERM FACTOR 1.030 TOTAL 9,999.9 THERMS", 0.36, 0.66, 0.3, 0.009)]

    assert _read(layout, targets)["activity_quantity"]["raw_value"] == "1,486"


def test_the_inline_total_runs_only_when_the_labelled_reads_and_the_usage_table_find_nothing(targets: list[dict]) -> None:
    lines = [*TOTAL_HEAD, "Total Usage: 900 therms", "THERM FACTOR 1.030 TOTAL 1,273.1 THERMS"]

    assert _fields(lines, targets)["activity_quantity"]["raw_value"] == "900"


@pytest.mark.parametrize("second", ["TOTAL 1,273.1 THM", "TOTAL 1273.1 therms", "TOTAL 1,273.1 Therm"])
def test_two_spellings_of_one_unit_are_one_total(targets: list[dict], second: str) -> None:
    fields = _fields([*TOTAL_HEAD, "TOTAL 1,273.1 THERMS", second], targets)

    assert _value(fields, "activity_quantity") == pytest.approx(127.31)


def test_a_total_in_two_different_units_is_not_guessed_between(targets: list[dict]) -> None:
    assert _value(_fields([*TOTAL_HEAD, "TOTAL 1,236 CCF", "TOTAL 1,273.1 THERMS"], targets), "activity_quantity") is None


# --- who is paid -------------------------------------------------------------------------------------
BASE_BILL = ["Natural gas statement – Zürich", "Bill To: Northgate Provisions Inc", "Total Usage: 900 therms"]


@pytest.mark.parametrize("remit", [
    "REMIT TO: UTILITY BILLING SERVICES LLC, PO BOX 618", "REMIT TO: ACH PAYMENTS DEPT, Sierra Basin Energy Co",
    "REMIT TO: WELLS FARGO NA, LOCKBOX 1234", "REMIT TO: Payment Processing Center, PO Box 618",
    "REMIT TO: c/o JPMorgan Chase, Sierra Basin Energy", "Please pay to: Sierra Basin Energy Co",
    "Pay to avoid late fee of 1.5% by 09/26", "Amount payable to date $1,474.33",
    "REMIT TO: Maria Müller", "REMIT TO: Sierra Basin Treasury", "REMIT TO: First National Bank N.A.",
    "REMIT TO: Attn Accounts Receivable Dept Co", "REMIT TO: NORTHGATE HOLDINGS INC, PO BOX 618",
])
def test_a_payee_that_is_an_agent_a_bank_a_person_a_sentence_or_the_customers_parent_is_no_supplier(
        targets: list[dict], remit: str) -> None:
    assert _value(_fields([*BASE_BILL, remit], targets), "supplier_name") is None


@pytest.mark.parametrize("remit", [
    "Remit to: Utility Billing Services LLC on behalf of Sierra Basin Energy Co",
    "REMIT PAYMENT TO: SIERRA BASIN ENERGY CO, PO BOX 618", "Make checks payable to Sierra Basin Energy Co.",
])
def test_a_payee_that_is_a_company_or_on_whose_behalf_an_agent_collects_is_the_supplier(targets: list[dict], remit: str) -> None:
    assert str(_value(_fields([*BASE_BILL, remit], targets), "supplier_name")).lower().startswith("sierra basin energy co")


def test_a_remit_to_ranks_below_the_letterhead_and_the_labelled_supplier(targets: list[dict]) -> None:
    assert _value(_fields(["Acme Gas Company", "Natural gas bill", "Total Usage: 900 therms",
                           "REMIT TO: SIERRA BASIN ENERGY CO"], targets), "supplier_name") == "Acme Gas Company"


# --- the customer ------------------------------------------------------------------------------------
@pytest.mark.parametrize("label", [
    "Bill To: Northgate Provisions Inc - Plant 4", "Bill To: Northgate Provisions Inc.",
    "Sold To: Northgate Provisions, Inc.", "Customer: NORTHGATE PROVISIONS INC (ACCT 4417)",
    "Account Holder: northgate provisions inc – Zürich", "Bill To: Northgate Provisions LLC [Plant 4]",
])
def test_the_customer_is_not_the_supplier_however_the_name_is_written(targets: list[dict], label: str) -> None:
    lines = ["NORTHGATE PROVISIONS INC", "Natural gas bill", label, "Total Usage: 900 therms"]

    assert _value(_fields(lines, targets), "supplier_name") is None


def test_a_customer_with_a_remit_to_parent_is_not_paid_to_either(targets: list[dict]) -> None:
    lines = ["Natural gas bill", "Customer: Northgate Provisions Inc", "Total Usage: 900 therms",
             "REMIT TO: NORTHGATE PROVISIONS HOLDINGS INC"]

    assert _value(_fields(lines, targets), "supplier_name") is None


def test_a_utility_that_shares_a_first_word_with_the_customer_can_still_be_the_supplier(targets: list[dict]) -> None:
    lines = ["Natural gas bill", "Customer: Sierra Foods Inc", "Total Usage: 900 therms",
             "REMIT TO: SIERRA BASIN ENERGY CO"]

    assert _value(_fields(lines, targets), "supplier_name") == "SIERRA BASIN ENERGY CO"


# --- a real letterhead over a PO box -------------------------------------------------------------------
UTILITY_BLOCK = ["SIERRA BASIN ENERGY CO", "PO BOX 618", "SACRAMENTO CA 95814", "ACCOUNT NO 4417-9083-52",
                 "Total Usage: 900 therms"]


@pytest.mark.parametrize("remit", ["REMIT TO: UTILITY BILLING SERVICES LLC, PO BOX 99", "Make checks payable to: SBE Gas",
                                   "Make checks payable to: Sierra Basin Energy", "REMIT TO: WELLS FARGO NA, LOCKBOX 1234"])
def test_a_utility_letterhead_over_a_po_box_is_kept_whatever_the_remit_to_says(targets: list[dict], remit: str) -> None:
    assert _value(_fields([*UTILITY_BLOCK, remit], targets), "supplier_name") == "SIERRA BASIN ENERGY CO"


def test_a_customer_block_with_no_remit_to_names_no_supplier(targets: list[dict]) -> None:
    lines = ["NORTHGATE PROVISIONS INC", "555 CAPITOL MALL STE 900", "SACRAMENTO CA 95814", "ACCOUNT NO 4417-9083-52",
             "Total Usage: 900 therms"]

    assert _value(_fields(lines, targets), "supplier_name") is None


# --- fix round 2 of the dense statement: split cells, labelled suppliers, gallons ---------------------------
def _split_row(label: str, total: str) -> list[tuple[str, float, float, float, float]]:
    return [("NATURAL GAS STATEMENT – Zürich 東京", 0.05, 0.05, 0.4, 0.011), ("FROM 08/01/2025 TO 08/31/2025", 0.05, 0.07, 0.4, 0.011),
            (label, 0.05, 0.3, 0.15, 0.011), (total, 0.4, 0.3, 0.25, 0.011)]


@pytest.mark.parametrize(("label", "total"), [("Year to date", "TOTAL 14,200 THERMS"), ("Aug 2024", "TOTAL 1,190 THERMS"),
                                              ("Same month last year", "TOTAL 1,190 THERMS"), ("Annual", "TOTAL 14,200 THERMS"),
                                              ("Jahr bis heute YTD", "TOTAL 14,200 THERMS")])
def test_a_period_word_in_another_cell_of_the_same_row_means_the_total_is_not_the_bills_usage(
        targets: list[dict], label: str, total: str) -> None:
    _nothing_read(_read(_split_row(label, total), targets), "activity_quantity")


@pytest.mark.parametrize("header", ["Year to date", "Aug 2024", "Prior year", "Budget plan"])
def test_a_period_header_on_the_row_above_means_the_total_is_not_the_bills_usage(targets: list[dict], header: str) -> None:
    layout = [("NATURAL GAS STATEMENT", 0.05, 0.05, 0.4, 0.011), (header, 0.4, 0.28, 0.2, 0.011),
              ("TOTAL 14,200 THERMS", 0.4, 0.3, 0.25, 0.011)]

    _nothing_read(_read(layout, targets), "activity_quantity")


def test_the_bills_own_period_on_the_row_above_does_not_stop_its_total(targets: list[dict]) -> None:
    layout = [("NATURAL GAS STATEMENT", 0.05, 0.05, 0.4, 0.011), ("FROM 08/01/2025 TO 08/31/2025", 0.05, 0.28, 0.4, 0.011),
              ("TOTAL 1,273.1 THERMS", 0.05, 0.3, 0.25, 0.011)]

    assert _read(layout, targets)["activity_quantity"]["raw_value"] == "1,273.1"


@pytest.mark.parametrize(("supplier", "customer"), [
    ("Southern California Gas Company", "Southern California Foods Inc"), ("City of Lodi Utilities", "City of Lodi"),
    ("Sierra Basin Co", "Sierra Basin Foods Inc"), ("Northgate Holdings Inc", "Northgate Provisions Inc"),
    ("Müller Gas AG", "Müller Käserei AG"),
])
def test_a_labelled_supplier_is_never_dropped_for_sharing_words_with_the_customer(
        targets: list[dict], supplier: str, customer: str) -> None:
    lines = ["Natural gas bill", f"Supplier: {supplier}", f"Bill To: {customer}", "Total Usage: 900 therms"]

    assert _value(_fields(lines, targets), "supplier_name") == supplier


def test_a_labelled_supplier_that_is_the_customer_itself_is_still_dropped(targets: list[dict]) -> None:
    lines = ["Natural gas bill", "Supplier: Northgate Provisions Inc - Plant 4", "Bill To: NORTHGATE PROVISIONS INC",
             "Total Usage: 900 therms"]

    assert _value(_fields(lines, targets), "supplier_name") is None


def test_a_utility_that_shares_two_words_with_the_customer_is_a_supplier_on_the_letterhead_too(targets: list[dict]) -> None:
    lines = ["Southern California Gas Company", "Natural gas bill", "Bill To: Southern California Foods Inc",
             "Total Usage: 900 therms"]

    assert _value(_fields(lines, targets), "supplier_name") == "Southern California Gas Company"


def test_gallons_count_for_a_total_only_where_gallons_are_an_activity_unit(targets: list[dict]) -> None:
    gas = _fields(["NATURAL GAS STATEMENT – Zürich", "TOTAL 500 GALLONS"], targets)
    propane = _fields(["PROPANE DELIVERY STATEMENT – Zürich", "TOTAL 500 GALLONS"], targets)

    assert _value(gas, "activity_quantity") is None
    assert propane["activity_quantity"]["raw_value"] == "500" and _value(propane, "activity_unit") == "gal"
