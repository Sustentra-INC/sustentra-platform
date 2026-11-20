"""A company's published GHG documents (a management assertion, a statement with a review report, an inventory
management plan) are summary documents (Block 1) even though their sentences say kWh, MWh and "invoices".
A real bill, a fuel log or a contract is never one. Synthetic text, non-ASCII on purpose."""

from __future__ import annotations

from typing import Any

import pytest

from backend.app.services import methodology_prefill as mp
from backend.app.services.calculation_lines import BLOCK_SUMMARY, SUMMARY_TYPES
from backend.app.services.classification_service import ClassificationService
from backend.app.services.document_shape import looks_like_a_contract, narrative_ghg_document_type
from backend.tests.services.test_summary_and_contract import CONTRACT, output

PROSE = (
    "Our operational emissions come from electricity use across the Zürich and Fresno offices, measured in kWh and "
    "reported in MWh, and from natural gas used for heating at our data centres across the year.\n"
    "Electricity use is taken from utility invoices and, where invoices are not available, from estimates that "
    "management reviewed and approved before the inventory was finalised for the reporting year.\n"
    "We used location-based and market-based factors, and the emission factors are listed in the appendix, "
    "which also records the global warming potentials applied to each gas in the inventory.\n"
    "Management is responsible for the statement, for the controls over it, and for the completeness of the "
    "underlying records, and our reviewers examined them on a test basis during the year.\n"
)


def doc(title_lines: list[str], pages: int = 3) -> dict[str, Any]:
    text = "\n".join(title_lines) + "\n" + PROSE * 2
    return {"document_id": "D", "tables": [], "key_value_pairs": [], "source_references": [],
            "pages": [{"page_number": n + 1, "text": text if n == 0 else PROSE} for n in range(pages)],
            "text_blocks": []}


JPM = ["2024 Operational GHG Emissions and Electric Power Use", "Management’s Assertion", "Chase Müller & Co. – 東京"]
YUM = ["Yum! Brands, Inc.", "2023 Statement of Greenhouse Gas Emissions",
       "Independent Accountants’ Review Report"]
FLUOR = ["Fluor Corporation", "2024 Greenhouse Gas Inventory Management Plan"]


def classify(parser_output: dict[str, Any], file_name: str = "report.pdf") -> dict[str, Any]:
    return ClassificationService().classify({"file_name": file_name, "parser_output": parser_output})


@pytest.mark.parametrize("title", [JPM, YUM, FLUOR])
@pytest.mark.parametrize("file_name", ["report.pdf", "Bericht 2024 電気.pdf"])
def test_a_company_narrative_ghg_document_is_a_summary(title: list[str], file_name: str) -> None:
    result = classify(doc(title), file_name)
    assert result["primary_canonical_type_id"] in SUMMARY_TYPES, result["notes"]
    assert result["status"] == "classified"


@pytest.mark.parametrize(("title", "expected"), [
    (["Basis of Reporting"], "CT-S1-METHODDOC"),
    (["Basis of Preparation"], "CT-S1-METHODDOC"),
    (["Climate Accounting Statement"], "CT-GHG-WORKBOOK"),
    (["Independent Accountants’ Review Report"], "CT-GHG-WORKBOOK"),
    (["INDEPENDENT ACCOUNTANTS' REVIEW REPORT"], "CT-GHG-WORKBOOK"),
    (["Limited Assurance Statement"], "CT-GHG-WORKBOOK"),
    (["GHG Inventory Report 2024"], "CT-GHG-WORKBOOK"),
])
def test_each_heading_cue_picks_the_closest_summary_type(title: list[str], expected: str) -> None:
    assert narrative_ghg_document_type(doc(title)) == expected


def test_plain_text_without_pages_also_counts() -> None:
    text = "\n".join(YUM) + "\n" + PROSE * 3
    result = ClassificationService().classify({"file_name": "x.pdf", "extracted_text": text})
    assert result["primary_canonical_type_id"] == "CT-GHG-WORKBOOK"


def test_a_utility_bill_with_ghg_in_the_footer_is_not_a_summary() -> None:
    bill = ("Cedarline Gas & Power\nAccount Number: 3305-778-1102\nBilling Period: 10/01/2025 - 10/31/2025\n"
            "Usage: 1,486 kWh\nAmount Due: $1,474.33\n" + PROSE * 2 +
            "Learn about our greenhouse gas emissions and our statement of GHG emissions on our website.\n")
    result = ClassificationService().classify({"file_name": "Rechnung.pdf", "extracted_text": bill})
    assert result["primary_canonical_type_id"] not in SUMMARY_TYPES or result["status"] != "classified"
    assert narrative_ghg_document_type(None, bill) is None


@pytest.mark.parametrize("top", [
    "Account Number: 3305\n", "Billing Period 10/01-10/31\n", "Amount Due: $44.10\n",
    "Fuel type | Gallons | Scope 1\n", "Date   Site   kWh   Charge\n", "Site,Date,kWh,Charge\n",
])
def test_bill_rows_or_a_quantity_table_near_the_top_veto_a_narrative_title(top: str) -> None:
    text = "2024 Statement of GHG Emissions\n" + top + PROSE * 3
    assert narrative_ghg_document_type(None, text) is None, top


def test_a_fuel_log_titled_emissions_report_is_not_a_summary() -> None:
    log = ("Emissions Report 2025\nScope 1 (tCO2e)   Scope 2 (tCO2e)\nDate Fuel type Gallons Operator\n"
           "2025-01-03 Diesel 120 gal Müller\n")
    assert narrative_ghg_document_type(None, log) is None
    assert narrative_ghg_document_type(None, "GHG Inventory Report\n" + log * 6) is None


def test_the_supply_contract_is_still_a_contract_and_never_a_summary() -> None:
    assert looks_like_a_contract(output(CONTRACT)) is True
    assert narrative_ghg_document_type(output(CONTRACT)) is None
    assert narrative_ghg_document_type(output("Methodology\n" + CONTRACT)) is None


def test_a_short_or_tabled_document_is_left_to_the_other_rules() -> None:
    assert narrative_ghg_document_type(doc(JPM, pages=1)) is None
    assert narrative_ghg_document_type({**doc(JPM), "tables": [{"rows": [["a"]]}]}) is None
    assert narrative_ghg_document_type(None, "Basis of Reporting\nShort.\n") is None


# --- Block 1 membership ----------------------------------------------------------------------
class Store:
    def __init__(self, types: dict[str, str]) -> None:
        self.types = types
        self.docs = [{"document_id": d, "org_id": "org"} for d in types]

    def list_documents(self, engagement_id: str) -> list[dict[str, Any]]:
        return self.docs

    def list_extraction_results_by_document(self, document_id: str) -> list[dict[str, Any]]:
        return [{"canonical_type_id": self.types[document_id]}]


def test_a_document_the_reviewer_moved_into_block_1_is_read_by_prefill() -> None:
    store = Store({"A": "CT-S1-FUELQTY", "B": "CT-S1-FUELQTY", "C": "CT-S1-FUELQTY", "D": "CT-GHG-ORGBOUND"})
    decisions = {
        "A": {"placements": [{"from": "block:unassigned", "to": BLOCK_SUMMARY}]},
        "B": {"placements": [{"from": "block:unassigned", "to": BLOCK_SUMMARY}, {"from": BLOCK_SUMMARY, "to": "L1"}]},
        "C": {"placements": "junk"},
    }
    found = mp.candidate_documents(store, store, "ENG", lambda record: True, decisions)
    assert [d["document_id"] for d in found] == ["A", "D"]


@pytest.mark.parametrize("title", [JPM, YUM, FLUOR])
def test_the_three_company_documents_reach_prefill(title: list[str]) -> None:
    typed = classify(doc(title))["primary_canonical_type_id"]
    store = Store({"X": typed, "Y": "CT-S1-FUELQTY"})
    found = mp.candidate_documents(store, store, "ENG", lambda record: True)
    assert [d["document_id"] for d in found] == ["X"]
