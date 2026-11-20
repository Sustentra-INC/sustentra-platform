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


CUE = "cue: GHG inventory summary"


def credited(text: str, file_name: str = "report.xlsx") -> bool:
    """Whether the classifier credited the summary type for this text (the cue fired)."""

    result = classify(text, file_name)
    return any(CUE in " ".join(c["matched_signals"]["key_phrases"]) for c in result.get("candidate_matches") or [])


def test_the_cue_fires_for_the_full_summary() -> None:
    assert credited(SUMMARY_TEXT)


@pytest.mark.parametrize(("what", "text"), [
    ("title", SUMMARY_TEXT.replace("2025 GHG Inventory Summary", "Quarterly note")),
    ("scope 1", SUMMARY_TEXT.replace("Scope 1", "Scope one")),
    ("scope 2", SUMMARY_TEXT.replace("Scope 2", "Scope two")),
    ("unit", SUMMARY_TEXT.replace("tCO₂e", "units")),
    ("year", SUMMARY_TEXT.replace("2025", "").replace("2026", "")),
])
def test_each_missing_cue_stops_the_summary_cue(what: str, text: str) -> None:
    assert not credited(text), what


@pytest.mark.parametrize("unit", ["tCO2e", "t CO2e", "tCO₂e", "metric tons CO2e", "metric tonnes CO2e", "tonnes CO2-eq",
                                  "t CO2-eq", "MT CO2e", "tons CO₂e"])
def test_the_unit_variants_are_accepted(unit: str) -> None:
    assert credited(SUMMARY_TEXT.replace("tCO₂e", unit)), unit


def test_a_fuel_log_with_emissions_columns_is_not_outranked_by_the_summary_cue() -> None:
    log = ("Emissions Report 2025\nScope 1 (tCO2e)   Scope 2 (tCO2e)\nCedarline Gas & Power\n"
           "Account Number: 3305-778-1102\nBilling Period: 10/01/2025 - 10/31/2025\nFuel: Natural gas\n"
           "Usage: 1,486 therms\nAmount Due: $1,474.33\n")
    assert not credited(log, "Emissions Report 2025.pdf")
    result = classify(log, "Emissions Report 2025.pdf")
    assert result["primary_canonical_type_id"] != "CT-GHG-WORKBOOK" or result["status"] != "classified"
    delivery = ("Emissions Report 2025\nScope 1 (tCO2e)   Scope 2 (tCO2e)\nDate Fuel type Gallons Operator\n"
                "2025-01-03 Diesel 120 gal Müller\n")
    assert not credited(delivery, "log.csv")


SPLIT_HEADER_LOG = ("Emissions Report 2025\nFuel type,Gallons,Scope 1 tCO2e,Scope 2 tCO2e\n"
                    "Diesel,120,1.2,0\nDiesel,95,0.9,0\n")


@pytest.mark.parametrize("header", [
    "Fuel type | Gallons | Scope 1 tCO2e | Scope 2 tCO2e", "Date | Litres | Scope 1 tCO2e | Scope 2 tCO2e",
    "Site | Therms | Scope 1 tCO2e | Scope 2 tCO2e", "Site | kWh | Scope 1 tCO2e | Scope 2 tCO2e",
    "Vehicle | Odometer | Scope 1 tCO2e | Scope 2 tCO2e", "Unit | Run hours | Scope 1 tCO2e | Scope 2 tCO2e",
    "Meter reading | Scope 1 tCO2e | Scope 2 tCO2e", "Site | MMBtu | Scope 1 tCO2e | Scope 2 tCO2e",
    "Site | CCF | Scope 1 tCO2e | Scope 2 tCO2e", "Site | MWh | Scope 1 tCO2e | Scope 2 tCO2e",
    "Site | Dth | Scope 1 tCO2e | Scope 2 tCO2e", "Site | MCF | Scope 1 tCO2e | Scope 2 tCO2e",
])
def test_an_activity_column_header_keeps_the_summary_cue_off(header: str) -> None:
    assert not credited(f"Emissions Report 2025\n{header}\nMüller 120 1.2 0\n", "log.xlsx"), header


def test_a_log_with_split_value_and_unit_keeps_its_fuel_type_and_quantities(tmp_path: Path) -> None:
    assert not credited(SPLIT_HEADER_LOG, "emissions log 2025.csv")
    path = tmp_path / "Emissionen Log 2025 電気.csv"
    path.write_text(SPLIT_HEADER_LOG, encoding="utf-8")
    read = _run(path)
    assert read["pipeline_run"]["canonical_type_id"] in ("CT-S1-MOBFUEL", "CT-S1-FUELQTY")
    assert read["pipeline_run"]["canonical_type_id"] != "CT-GHG-WORKBOOK"
    items = read["extraction_result"]["items"]
    assert [i["normalized_value"] for i in items if i["field_name"] == "activity_quantity"] == [120, 95]
    assert {i["normalized_value"] for i in items if i["field_name"] == "fuel_type"} == {"diesel"}


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
    read = _run(path)
    run, result = read["pipeline_run"], read["extraction_result"]
    assert run["canonical_type_id"] == "CT-GHG-WORKBOOK" and run["halt_reason"] is None
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


# --- a real bill is never stopped as a contract (round 1) ----------------------------------
BACK_PAGE = """By and between the parties, the supplier shall deliver and the customer shall pay. Neither party may
assign this Agreement. The Effective Date is the date of the first delivery. The term renews each year. Notices
shall be in writing. This Agreement is governed by the laws of Oregon. Limitation of liability applies. The
entire agreement of the parties is stated here. Force majeure excuses delay."""


@pytest.mark.parametrize("heading", ["Fuel Supply Agreement", "Contract Account", "Contract Number", "Contract #4471",
                                     "Contract Date: 10/01/2025"])
def test_a_table_less_delivery_ticket_with_contract_terms_is_not_halted(heading: str) -> None:
    ticket = (f"{heading}\nHarbor Fuel Oil Co.\nDelivery Ticket\nQty\n500 gal\nProduct\nHeating oil\n"
              f"Delivery Date\n11/05/2025\nTotal\n$1,250.00\n{BACK_PAGE}\n")
    assert looks_like_a_contract(output(ticket, tables=[], key_value_pairs=[])) is False


def test_a_ticket_with_only_a_quantity_label_or_a_unit_is_not_halted() -> None:
    base = f"Fuel Supply Agreement\nHarbor Fuel Oil Co.\nDelivery\n{BACK_PAGE}\n"
    assert looks_like_a_contract(output(base + "Qty 500\n")) is False
    assert looks_like_a_contract(output(base + "Delivered 1,200 L of diesel\n")) is False
    assert looks_like_a_contract(output(base + "Total 38.5 Dth\n")) is False


def test_a_utility_bill_with_space_gapped_labels_and_empty_tables_is_not_halted() -> None:
    bill = ("Rainier Sound Power & Light\nSERVICE AGREEMENT\nAccount Number   3305-778-1102\n"
            "Billing Period 10/01-10/31\nCustomer   Müller Käserei – Zürich\n" + BACK_PAGE + "\n")
    assert looks_like_a_contract(output(bill, tables=[], key_value_pairs=[])) is False
    assert looks_like_a_contract(output("SERVICE AGREEMENT\nAmount Due $44.10\n" + BACK_PAGE)) is False
    assert looks_like_a_contract(output("SERVICE AGREEMENT\nInvoice 4471\n" + BACK_PAGE)) is False
    assert looks_like_a_contract(output("SERVICE AGREEMENT\nStatement Date: 10/31/2025\n" + BACK_PAGE)) is False


@pytest.mark.parametrize("label", ["Account No. 3305", "Account #3305", "Meter No. 12", "Meter # 12", "Invoice No. 889",
                                   "Account Number   3305", "Billing Period 10/01-10/31"])
def test_abbreviated_and_space_gapped_bill_labels_block_the_contract(label: str) -> None:
    assert looks_like_a_contract(output(CONTRACT + label + "\n", tables=[], key_value_pairs=[])) is False, label


@pytest.mark.parametrize("quantity", ["12 mcf", "300 lb", "300 lbs", "250 kg", "500 gal", "38.5 Dth", "1,200 L"])
def test_a_quantity_with_a_unit_blocks_the_contract(quantity: str) -> None:
    assert looks_like_a_contract(output(CONTRACT + f"Delivered {quantity}\n")) is False, quantity


@pytest.mark.parametrize("sentence", ["Meter notices shall be sent in writing.", "Account notes are kept by the Company.",
                                      "Meter noting is done monthly.", "Account numbers are assigned by the Company."])
def test_a_sentence_that_only_starts_like_a_label_is_not_a_bill_row(sentence: str) -> None:
    assert looks_like_a_contract(output(CONTRACT + sentence + "\n", tables=[], key_value_pairs=[])) is True, sentence


def test_a_wrapped_sentence_that_starts_with_statement_date_is_not_a_bill_row() -> None:
    # The NPL contract wraps "...within twenty-one (21) days of the / statement date. Late payments accrue."
    wrapped = CONTRACT.replace("5. Entire", "4b. Payment\nPayment is due within twenty-one (21) days of the\n"
                               "statement date. Late payments accrue charges.\n5. Entire")
    assert looks_like_a_contract(output(wrapped, tables=[], key_value_pairs=[])) is True


def test_the_contract_still_halts_with_empty_tables() -> None:
    assert looks_like_a_contract(output(CONTRACT, tables=[], key_value_pairs=[])) is True
