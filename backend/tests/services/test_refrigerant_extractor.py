"""CT-S1-REFRSVC: refrigerant service work orders and logs -> material-balance inputs."""

from __future__ import annotations

from typing import Any

import pytest

from backend.app.domain.refrigerants import find_refrigerant, parse_mass
from backend.app.services.extraction_service import ExtractionService
from backend.app.services.extraction_target_service import ExtractionTargetService
from backend.app.services.refrigerant_extractor import (
    HALT_UNSUPPORTED,
    RefrigerantServiceExtractor,
    classify_service,
)


@pytest.fixture(scope="module")
def targets() -> list[dict]:
    return ExtractionTargetService().get_targets_for_canonical_type("CT-S1-REFRSVC")


def _text_output(text: str, document_id: str = "DOC-1") -> dict[str, Any]:
    return {
        "document_id": document_id,
        "pages": [{"page_number": 1, "text": text}],
        "text_blocks": [{"block_id": "b1", "page_number": 1, "text": text, "confidence": None,
                         "bounding_box": None, "source_reference_id": None}],
        "tables": [], "key_value_pairs": [], "source_references": [],
    }


def _sheet_output(rows: list[list[Any]], document_id: str = "DOC-X") -> dict[str, Any]:
    """parser_output as the spreadsheet parser writes it: one text block per non-empty cell."""

    blocks, references = [], []
    for r, row in enumerate(rows, start=1):
        for c, value in enumerate(row):
            if value in (None, ""):
                continue
            ref = f"A{len(references) + 1}"
            cell = f"{chr(65 + c)}{r}"
            blocks.append({"block_id": f"openpyxl-Log-{cell}", "page_number": None, "text": str(value),
                           "confidence": None, "bounding_box": None, "source_reference_id": ref})
            references.append({"source_reference_id": ref, "document_id": document_id, "page_number": None,
                               "sheet_name": "Log", "cell_or_range": cell, "text_snippet": str(value),
                               "bounding_box": None, "parser_block_ids": [f"openpyxl-Log-{cell}"],
                               "source_kind": "excel_cell"})
    return {"document_id": document_id, "pages": [], "text_blocks": blocks, "tables": [], "key_value_pairs": [],
            "source_references": references}


def _by_field(candidates: list[dict], record_index: int | None = None) -> dict[str, dict]:
    return {c["field_name"]: c for c in candidates if c["record_index"] == record_index}


# --- names and amounts -----------------------------------------------------------------
@pytest.mark.parametrize(
    ("text", "name", "family"),
    [
        ("R410A", "R-410A", "blend"),
        ("Refrigerant: r-404a", "R-404A", "blend"),
        ("Puron", "R-410A", "blend"),
        ("R-134A", "HFC-134a", "hfc"),
        ("HFC134a", "HFC-134a", "hfc"),
        ("FM-200 clean agent", "HFC-227ea", "hfc"),
        ("R-32", "HFC-32", "hfc"),
        ("SF6 breaker", "SF6", "sf6"),
        ("R-744", "CO2", "co2"),
        ("Freon 22", "HCFC-22", "hcfc"),
        ("R-22", "HCFC-22", "hcfc"),
        ("CFC-12", "CFC-12", "cfc"),
        ("Halon 1301", "Halon 1301", "halon"),
        ("R-454B", "R-454B", "blend"),
        ("R-1234yf", "R-1234yf", "other"),
    ],
)
def test_find_refrigerant(text: str, name: str, family: str) -> None:
    found = find_refrigerant(text)
    assert found is not None and (found.name, found.family) == (name, family)
    assert found.montreal == (family in ("cfc", "hcfc", "halon"))


@pytest.mark.parametrize("text", ["Route 22", "Suite 410", "CO2e total", "Unit 45 lb", "no gas here"])
def test_find_refrigerant_ignores_lookalikes(text: str) -> None:
    assert find_refrigerant(text) is None


@pytest.mark.parametrize(
    ("text", "default", "value", "unit"),
    [
        ("4.5 lbs", None, 4.5, "lb"),
        ("4 lb 8 oz", None, 4.5, "lb"),
        ("12 lbs. 4 oz.", None, 12.25, "lb"),
        ("72 oz", None, 4.5, "lb"),
        ("2.1 kg", None, 2.1, "kg"),
        ("500 g", None, 0.5, "kg"),
        ("1,250 lb", None, 1250, "lb"),
        ("6.5", "Added (lb)", 6.5, "lb"),
        ("6.5", None, None, None),
    ],
)
def test_parse_mass(text: str, default: str | None, value: float | None, unit: str | None) -> None:
    mass = parse_mass(text, default)
    assert (mass.value if mass else None, mass.unit if mass else None) == (value, unit)


def test_service_type_wording() -> None:
    assert classify_service("Leak repair, recharged") == "service"
    assert classify_service("New unit installed") == "installation"
    assert classify_service("Unit decommissioned") == "disposal"
    # In free notes an equipment's install date is its age, not a new installation.
    assert classify_service("Install date: 2015-03-01. Leak found on coil.", notes=True) == "service"


# --- a work order --------------------------------------------------------------------------
WORK_ORDER = """Arctic Air Mechanical, Inc.
SERVICE WORK ORDER
Work Order #: WO-24817
Service Date: 03/14/2025
Customer: Richmond Refinery
Service Address: 4100 Deepwater Terminal Rd, Richmond, VA 23234
Equipment ID: RTU-3
Refrigerant Type: R-410A
Full Charge: 18 lb
Refrigerant Added: 6 lb 8 oz
Refrigerant Recovered: 0 lb
Reason for Service: Leak repair
"""


def test_work_order_is_one_record(targets: list[dict]) -> None:
    outcome = RefrigerantServiceExtractor().extract(_text_output(WORK_ORDER), targets, "EV-1")
    fields = _by_field(outcome.candidates)
    assert outcome.halt_reason is None and outcome.records == 1
    assert fields["refrigerant_type"]["normalized_value"] == "R-410A"
    assert (fields["refrigerant_added"]["normalized_value"], fields["refrigerant_added"]["unit"]) == (6.5, "lb")
    assert "unit_converted" in fields["refrigerant_added"]["validation_flags"]
    assert (fields["equipment_capacity"]["normalized_value"], fields["equipment_capacity"]["unit"]) == (18, "lb")
    assert fields["refrigerant_recovered"]["normalized_value"] == 0
    assert fields["service_date"]["normalized_value"] == "2025-03-14"
    assert fields["equipment_id"]["normalized_value"] == "RTU-3"
    assert fields["service_type"]["normalized_value"] == "service"
    assert fields["facility_name"]["normalized_value"] == "Richmond Refinery"
    assert fields["refrigerant_added"]["source_reference"]["text_snippet"] == "Refrigerant Added: 6 lb 8 oz"


def test_hcfc_is_flagged(targets: list[dict]) -> None:
    text = WORK_ORDER.replace("R-410A", "R-22")
    fields = _by_field(RefrigerantServiceExtractor().extract(_text_output(text), targets, "EV-1").candidates)
    assert fields["refrigerant_type"]["normalized_value"] == "HCFC-22"
    assert "montreal_protocol_gas" in fields["refrigerant_type"]["validation_flags"]


def test_bare_amount_is_kept_and_flagged_without_a_unit(targets: list[dict]) -> None:
    text = WORK_ORDER.replace("Refrigerant Added: 6 lb 8 oz", "Refrigerant Added: 6.5")
    fields = _by_field(RefrigerantServiceExtractor().extract(_text_output(text), targets, "EV-1").candidates)
    assert fields["refrigerant_added"]["normalized_value"] == 6.5
    assert fields["refrigerant_added"]["unit"] is None and "unit_missing" in fields["refrigerant_added"]["validation_flags"]


def test_a_document_without_a_refrigerant_halts(targets: list[dict]) -> None:
    text = "Valley HVAC\nService Date: 03/14/2025\nReplaced belt and filters on RTU-3.\n"
    outcome = RefrigerantServiceExtractor().extract(_text_output(text), targets, "EV-1")
    assert outcome.candidates == [] and outcome.halt_reason["code"] == HALT_UNSUPPORTED


# --- a log ---------------------------------------------------------------------------------
LOG_ROWS = [
    ["Date", "Equipment", "Refrigerant", "Service Type", "Added (lb)", "Recovered (lb)", "Full Charge (lb)"],
    ["01/22/2025", "Chiller CH-1", "R-134a", "Leak repair", "45", "0", "650"],
    ["08/18/2025", "RTU-12", "R-410A", "New unit installed", "21", "0", "20"],
    ["12/05/2025", "Chiller CH-2", "R-134a", "Decommissioned", "0", "580", "600"],
    ["Total", "", "", "", "66", "580", ""],
]


def test_log_in_plain_text_is_one_record_per_line(targets: list[dict]) -> None:
    text = "Refrigerant Management Log 2025\n" + "\n".join("    ".join(r) for r in LOG_ROWS[:-1]) + "\nTotal    66\n"
    outcome = RefrigerantServiceExtractor().extract(_text_output(text), targets, "EV-1")
    assert outcome.records == 3
    first, second, third = (_by_field(outcome.candidates, i) for i in (1, 2, 3))
    assert (first["refrigerant_type"]["normalized_value"], first["refrigerant_added"]["normalized_value"]) == (
        "HFC-134a", 45)
    assert first["refrigerant_added"]["unit"] == "lb"  # from the "Added (lb)" header
    assert second["service_type"]["normalized_value"] == "installation"
    assert third["service_type"]["normalized_value"] == "disposal"
    assert (third["refrigerant_recovered"]["normalized_value"], third["equipment_capacity"]["normalized_value"]) == (
        580, 600)
    assert third["service_date"]["normalized_value"] == "2025-12-05"
    assert "record 3" in third["refrigerant_type"]["display_label"]


def test_log_in_a_spreadsheet_matches_columns_by_letter(targets: list[dict]) -> None:
    rows = [list(r) for r in LOG_ROWS]
    rows[1][5] = ""  # an empty Recovered cell must not shift the Full Charge value left
    outcome = RefrigerantServiceExtractor().extract(_sheet_output(rows), targets, "EV-1")
    assert outcome.records == 3  # the Total row is not a record
    first = _by_field(outcome.candidates, 1)
    assert first["refrigerant_recovered"]["normalized_value"] is None
    assert first["equipment_capacity"]["normalized_value"] == 650
    reference = first["refrigerant_added"]["source_reference"]
    assert (reference["sheet_name"], reference["cell_or_range"]) == ("Log", "E2")


def test_extraction_service_routes_refrigerant_targets(targets: list[dict]) -> None:
    result = ExtractionService().extract({"parser_output": _text_output(WORK_ORDER), "extraction_targets": targets,
                                          "evidence_id": "EV-1"})
    assert result["record_count"] == 1
    assert {item["field_name"] for item in result["items"]} >= {"refrigerant_type", "refrigerant_added"}


def test_confirms_needs_a_refrigerant_and_an_amount() -> None:
    extractor = RefrigerantServiceExtractor()
    assert extractor.confirms(_text_output(WORK_ORDER))
    assert not extractor.confirms(_text_output("Chiller CH-1 uses R-134a. Annual inspection passed.\n"))


# --- review findings: misreads that would change the material balance --------------------
@pytest.mark.parametrize(
    ("text", "kind"),
    [
        ("Replaced failed compressor, installed new filter drier, evacuated and recharged", "service"),
        ("Replaced TXV; old valve disposed", "service"),
        ("Seasonal start-up", None),  # read as a service downstream
        ("Commissioning check", None),
        ("Installed new rooftop unit RTU-12", "installation"),
        ("New RTU-12 installed", "installation"),
        ("Chiller CH-2 retired and scrapped", "disposal"),
        ("Removed from service", "disposal"),
        ("Disposal", "disposal"),
        ("Installation", "installation"),
    ],
)
def test_only_the_equipment_itself_makes_an_installation_or_disposal(text: str, kind: str | None) -> None:
    assert classify_service(text) == kind


def test_a_repair_work_order_stays_a_service(targets: list[dict]) -> None:
    text = ("Refrigerant Type: R-410A\nRefrigerant Added: 8 lbs\nSystem Charge: 10 lbs\n"
            "Work Performed: Replaced failed compressor, installed new filter drier, evacuated and recharged\n")
    fields = _by_field(RefrigerantServiceExtractor().extract(_text_output(text), targets, "EV-1").candidates)
    assert fields["service_type"]["normalized_value"] == "service"


def test_an_invoice_unit_column_is_the_unit_not_the_equipment(targets: list[dict]) -> None:
    text = ("Item    Description    Qty    Unit    Price\n"
            "1    R-410A refrigerant    6    LB    210.00\n"
            "2    R-404A refrigerant    12    OZ    95.00\n")
    outcome = RefrigerantServiceExtractor().extract(_text_output(text), targets, "EV-1")
    first, second = _by_field(outcome.candidates, 1), _by_field(outcome.candidates, 2)
    assert (first["refrigerant_added"]["normalized_value"], first["refrigerant_added"]["unit"]) == (6, "lb")
    assert (second["refrigerant_added"]["normalized_value"], second["refrigerant_added"]["unit"]) == (0.75, "lb")
    assert first["equipment_id"]["normalized_value"] is None


def test_a_cylinder_size_multiplies_the_quantity(targets: list[dict]) -> None:
    text = "Description    Qty    Price\nR-410A refrigerant 25 lb cylinder    2    300.00\n"
    fields = _by_field(RefrigerantServiceExtractor().extract(_text_output(text), targets, "EV-1").candidates)
    added = fields["refrigerant_added"]
    assert (added["normalized_value"], added["unit"]) == (50, "lb")
    assert "quantity_times_package_size" in added["validation_flags"]


def test_cooling_tonnage_is_not_a_refrigerant_charge(targets: list[dict]) -> None:
    text = "Refrigerant Type: R-410A\nCapacity: 5 tons\nRefrigerant Added: 3 lb\n"
    fields = _by_field(RefrigerantServiceExtractor().extract(_text_output(text), targets, "EV-1").candidates)
    assert fields["equipment_capacity"]["normalized_value"] is None
    assert fields["refrigerant_added"]["normalized_value"] == 3
