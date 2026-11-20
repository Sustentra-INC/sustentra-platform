"""A company's GHG inventory summary is a summary document (Block 1), and a supply contract is not a bill.

Synthetic text in the shape of the NPL set's inventory summary workbook and electric service agreement, with
non-ASCII names and units. The summary is typed so Methodology review can read it, and it is never read as fuel
evidence; the contract is stopped as not-evidence, whatever bill-like words ("monthly statements", "rate
schedule") it mentions; a real fuel bill that mentions an agreement in its terms is still a fuel bill."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from openpyxl import Workbook

from backend.app.repositories.extraction_result_repository import InMemoryExtractionResultRepository
from backend.app.repositories.pipeline_repository import InMemoryPipelineRunRepository
from backend.app.services.calculation_lines import SUMMARY_TYPES
from backend.app.services.classification_service import ClassificationService
from backend.app.services.document_shape import CONTRACT_MESSAGE, looks_like_a_contract
from backend.app.services.pipeline_orchestration_service import PipelineOrchestrationService

SUMMARY_TEXT = (
    "Müller Käserei AG – Zürich – 2025 GHG Inventory Summary (DRAFT, internal)\n"
    "Prepared by: Sustainability team · 02/10/2026 · Basis: EPA emission factors hub 2025\n"
    "Facility Scope 1 (tCO₂e) Scope 2 location-based (tCO₂e) Scope 2 market-based (tCO₂e) Total Scope 1+2 (tCO₂e)\n"
    "Fresno Plant 412.8 1046.3 978.5 1459.1\nTotal 967.9 1292.8 1132.1 2260.7\n"
    "Scope 2 location-based uses eGRID subregion factors. Refrigerants included in Scope 1 using AR5 GWPs.\n"
)


def classify(text: str, file_name: str) -> dict[str, Any]:
    return ClassificationService().classify({"file_name": file_name, "extracted_text": text})


# --- the inventory summary -----------------------------------------------------------------
@pytest.mark.parametrize("file_name", ["NPL_GHG_Inventory_Summary_2025.xlsx", "Zusammenfassung 2025.xlsx", "x.pdf"])
def test_an_inventory_summary_is_recognised_whatever_it_is_called(file_name: str) -> None:
    result = classify(SUMMARY_TEXT, file_name)
    assert result["primary_canonical_type_id"] == "CT-GHG-WORKBOOK" and result["status"] == "classified"
    assert "CT-GHG-WORKBOOK" in SUMMARY_TYPES  # the type Methodology prefill reads as the client's reports


@pytest.mark.parametrize("text", [
    SUMMARY_TEXT.replace("2025 GHG Inventory Summary", "Quarterly note"),  # no inventory title
    SUMMARY_TEXT.replace("Scope 2", "Scope two"),  # no Scope 2 totals
    SUMMARY_TEXT.replace("tCO₂e", "units"),  # no tonnes-CO2e unit
    SUMMARY_TEXT.replace("2025", "").replace("2026", ""),  # no year
])
def test_without_all_the_cues_it_is_not_taken_for_a_summary(text: str) -> None:
    assert classify(text, "report.xlsx")["primary_canonical_type_id"] != "CT-GHG-WORKBOOK" or \
        classify(text, "report.xlsx")["status"] != "classified"


def test_a_fuel_bill_is_never_taken_for_a_summary() -> None:
    bill = ("Cedarline Gas & Power\nAccount Number: 3305-778-1102\nService Period: 10/01/2025 - 10/31/2025\n"
            "Fuel: Natural gas\nUsage: 1,486 therms\nYour Scope 2 electricity is separate.\nAmount Due: $1,474.33\n")
    result = classify(bill, "Rechnung 2025.pdf")
    assert result["primary_canonical_type_id"] != "CT-GHG-WORKBOOK"


def _pipeline() -> PipelineOrchestrationService:
    return PipelineOrchestrationService(
        pipeline_repository=InMemoryPipelineRunRepository(),
        extraction_result_repository=InMemoryExtractionResultRepository(),
        clock=lambda: "2026-01-01T00:00:00+00:00")


def _run(path: Path) -> dict[str, Any]:
    out: dict[str, Any] = _pipeline().process_local_document(
        str(path), engagement_id="ENG-1", org_id="aaaaaaaa-0000-0000-0000-0000000000c3", persist_run=False)
    return out


def test_an_inventory_workbook_is_typed_as_a_summary_and_never_read_as_fuel(tmp_path: Path) -> None:
    book = Workbook()
    sheet = book.active
    for line in SUMMARY_TEXT.splitlines():
        sheet.append(line.split(" ", 0))
    path = tmp_path / "Zusammenfassung_GHG_Inventory_2025 電気.xlsx"
    book.save(path)
    run = _run(path)["pipeline_run"]
    assert run["canonical_type_id"] == "CT-GHG-WORKBOOK" and run["halt_reason"] is None
    result = _run(path)["extraction_result"]
    assert not [i for i in result["items"] if i["field_name"] in ("activity_quantity", "fuel_type")]  # #258: no fuel values


# --- the contract --------------------------------------------------------------------------
CONTRACT = """ELECTRIC SERVICE AGREEMENT
Agreement No. SBE-ESA-2024-3318
This Electric Service Agreement is entered into as of December 9, 2024 by and between Sierra Basin Energy Co.
(“Company”) and Müller Käserei AG – Zürich (“Customer”).
1. Term
This Agreement takes effect on January 1, 2025 (the “Effective Date”) and continues for thirty-six (36) months,
renewing automatically for successive twelve-month periods unless either party gives notice of non-renewal.
2. Service
The Company shall deliver electric service to the Premises. Service shall be billed under rate schedule E-TOU-C2.
Quantities shall be determined by Company meters and reported on monthly statements.
3. Limitation of Liability
Neither party shall be liable for consequential damages arising out of this Agreement.
4. Governing Law
This Agreement is governed by the laws of the State of California.
5. Entire Agreement
This Agreement and the Tariff constitute the entire agreement of the parties. Neither party may assign it.
"""


def output(text: str, **extra: Any) -> dict[str, Any]:
    return {"document_id": "D", "pages": [{"page_number": 1, "text": text}],
            "text_blocks": [{"block_id": "b", "page_number": 1, "text": text, "bounding_box": None}],
            "tables": [], "key_value_pairs": [], "source_references": [], **extra}


def test_a_supply_contract_is_a_contract() -> None:
    assert looks_like_a_contract(output(CONTRACT)) is True


def test_a_contract_with_a_table_or_a_sheet_is_left_to_the_other_rules() -> None:
    assert looks_like_a_contract(output(CONTRACT, tables=[{"rows": [["a"]]}])) is False
    assert looks_like_a_contract(output(CONTRACT, source_references=[{"sheet_name": "S1"}])) is False


def test_a_contract_that_quotes_a_usage_figure_is_not_stopped_as_one() -> None:
    assert looks_like_a_contract(output(CONTRACT + "Total usage for 2024 was 1,200,000 kWh.\n")) is False


BILL_WITH_TERMS = """Cedarline Gas & Power
Account Number: 3305-778-1102
Service Period: 10/01/2025 - 10/31/2025
Fuel: Natural gas
Usage: 1,486 therms
Amount Due: $1,474.33
Terms: Under your service agreement the supplier shall deliver gas at the metered rate. The term of the agreement renews
each year after the effective date, and neither party may assign it. Disputes are governed by the laws of Oregon.
"""


def test_a_fuel_bill_that_mentions_its_agreement_is_not_a_contract() -> None:
    assert looks_like_a_contract(output(BILL_WITH_TERMS)) is False
    assert looks_like_a_contract(output("SERVICE AGREEMENT\n" + BILL_WITH_TERMS)) is False  # labelled bill rows


def test_the_pipeline_stops_a_contract_as_not_evidence_but_reads_a_bill_with_terms(tmp_path: Path) -> None:
    contract = tmp_path / "Stromliefervertrag 電気.txt"
    contract.write_text(CONTRACT, encoding="utf-8")
    run = _run(contract)["pipeline_run"]
    assert run["canonical_type_id"] is None and run["canonical_type_source"] == "none"
    assert run["halt_reason"] == {"code": "unsupported_document", "message": CONTRACT_MESSAGE}

    bill = tmp_path / "Gasrechnung Oktober.txt"
    bill.write_text(BILL_WITH_TERMS, encoding="utf-8")
    result = _run(bill)
    assert result["pipeline_run"]["canonical_type_id"] == "CT-S1-FUELQTY"
    assert result["pipeline_run"]["halt_reason"] is None
    assert any(i["field_name"] == "activity_quantity" and i["normalized_value"] for i in result["extraction_result"]["items"])
