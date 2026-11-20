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
    text = "\n".join(YUM) + "\n" + PROSE * 8
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
    text = "2024 Statement of GHG Emissions\n" + top + PROSE * 8
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


def test_a_footer_that_names_a_report_is_not_a_title() -> None:
    ticket = ("Harbor Fuel Oil Co.\nDelivery details\n" + PROSE * 8 +
              "See our Greenhouse Gas Inventory Report at example.com/esg\n")
    assert narrative_ghg_document_type(None, ticket) is None
    for title in ["See our Greenhouse Gas Inventory Report at example.com/esg", "Visit our GHG Inventory Report",
                  "The GHG Inventory Report is published each year."]:
        assert narrative_ghg_document_type(None, title + "\n" + PROSE * 8) is None, title
    # not within the first six lines, and bare cues are not titles
    assert narrative_ghg_document_type(None, "a\nb\nc\nd\ne\nf\nGHG Inventory Report\n" + PROSE * 8) is None
    assert narrative_ghg_document_type(None, "Methodology\n" + PROSE * 8) is None
    assert narrative_ghg_document_type(None, "Limited Assurance\n" + PROSE * 8) is None
    assert narrative_ghg_document_type(None, "Operational GHG Emissions\n" + PROSE * 8) is None
    assert narrative_ghg_document_type(None, "Emissions Calculation Methodology\n" + PROSE * 8) == "CT-S1-METHODDOC"
    assert narrative_ghg_document_type(None, "GHG Methodology\n" + PROSE * 8) == "CT-S1-METHODDOC"


def test_a_single_spaced_log_of_data_rows_titled_inventory_report_is_not_a_summary() -> None:
    rows = "".join(f"2025-01-{d % 28 + 1:02d} Diesel fuel delivered {100 + d} gal to Fresno depot truck {d}\n"
                    for d in range(40))
    log = "GHG Inventory Report\n" + PROSE + rows
    assert narrative_ghg_document_type(None, log) is None
    few = "GHG Inventory Report\n" + PROSE * 12 + "".join(rows.splitlines(True)[:5])
    assert narrative_ghg_document_type(None, few) is None  # five data rows
    pages = doc(["GHG Inventory Report"], pages=3)
    pages["pages"][1]["text"] += rows
    assert narrative_ghg_document_type(pages) is None


@pytest.mark.parametrize("label", ["Delivery Ticket", "Ticket # 4471", "Invoice 889", "Invoice No. 12", "Gallons delivered",
                                   "Bill Date 10/31", "Service Address", "Due Date: 11/15"])
def test_bill_and_ticket_labels_veto(label: str) -> None:
    pages = doc(["GHG Inventory Report"])
    pages["pages"][2]["text"] += label + "\n"
    assert narrative_ghg_document_type(pages) is None, label
    assert narrative_ghg_document_type(doc(["GHG Inventory Report"])) is not None  # the invoices wording alone is fine


def test_unknown_page_count_needs_800_words_of_prose() -> None:
    assert narrative_ghg_document_type(None, "GHG Inventory Report\n" + PROSE * 2) is None
    assert narrative_ghg_document_type(None, "GHG Inventory Report\n" + PROSE * 8) is not None


def test_key_value_pairs_with_bill_fields_bail_out() -> None:
    parsed = doc(YUM)
    assert narrative_ghg_document_type(parsed) is not None
    parsed["key_value_pairs"] = [{"key": "Account Number", "value": "3305"}]
    assert narrative_ghg_document_type(parsed) is None
    parsed["key_value_pairs"] = [{"key": "Amount Due", "value": "$44"}, {"key": "Prepared by", "value": "x"}]
    assert narrative_ghg_document_type(parsed) is None


def _candidate(type_id: str, confidence: float) -> dict[str, Any]:
    return {"canonical_type_id": type_id, "variant_id": "V", "confidence": confidence, "threshold": 0.55,
            "matched_signals": {"filename_patterns": [], "layout_features": [], "header_terms": [], "key_phrases": []},
            "reason": "r", "review_required": False}


def test_an_evidence_type_that_meets_its_threshold_is_never_demoted() -> None:
    from backend.app.services.classification_service import MAY_BE_REPORT

    service = ClassificationService()
    library = service._get_vocabulary_library()
    bill, summary = _candidate("CT-S1-FUELQTY", 0.9), _candidate("CT-GHG-WORKBOOK", 0.2)
    out = service._credit_narrative(library, "CT-GHG-WORKBOOK", [bill, summary])
    assert bill["confidence"] == 0.9 and bill["review_required"] is True and MAY_BE_REPORT in bill["reason"]
    assert summary["confidence"] == 0.2  # the narrative type is not credited
    assert [c["canonical_type_id"] for c in out] == ["CT-S1-FUELQTY", "CT-GHG-WORKBOOK"]


def test_with_no_qualifying_evidence_type_the_narrative_type_is_credited_and_review_is_not_forced() -> None:
    service = ClassificationService()
    weak, summary = _candidate("CT-S1-FUELQTY", 0.3), _candidate("CT-GHG-WORKBOOK", 0.2)
    service._credit_narrative(service._get_vocabulary_library(), "CT-GHG-WORKBOOK", [weak, summary])
    assert summary["confidence"] >= 0.55 and summary["review_required"] is False
    assert weak["confidence"] == 0.3


# --- Block 1 membership ----------------------------------------------------------------------
class Store:
    def __init__(self, types: dict[str, str]) -> None:
        self.types = types
        self.docs = [{"document_id": d, "org_id": "org"} for d in types]

    def list_documents(self, engagement_id: str) -> list[dict[str, Any]]:
        return self.docs

    def list_extraction_results_by_document(self, document_id: str) -> list[dict[str, Any]]:
        return [{"canonical_type_id": self.types[document_id]}]


def test_block_1_membership_follows_the_evidence_tree() -> None:
    store = Store({"A": "CT-S1-FUELQTY", "B": "CT-S1-FUELQTY", "C": "CT-S1-FUELQTY", "D": "CT-GHG-ORGBOUND",
                   "E": "CT-GHG-ORGBOUND", "F": "CT-S1-FUELQTY", "G": "CT-GHG-ORGBOUND", "H": ""})
    decisions = {
        "A": {"placements": [{"from": "supporting:unassigned", "to": BLOCK_SUMMARY}]},  # moved in: read
        "B": {"placements": [{"from": "supporting:unassigned", "to": BLOCK_SUMMARY}, {"from": BLOCK_SUMMARY, "to": "L1"}]},
        "C": {"placements": "junk"},
        "E": {"placements": [{"from": BLOCK_SUMMARY, "to": "block:unassigned"}]},  # a summary moved out: not read
        "F": {"placements": [{"from": "block:unassigned", "to": BLOCK_SUMMARY}]},  # stale from: ignored
        "G": {"placements": [{"from": "block:unassigned", "to": BLOCK_SUMMARY}]},  # stale, still a summary
        "H": {"placements": [{"from": "block:unassigned", "to": BLOCK_SUMMARY}]},  # untyped, Block 2: moved in
    }
    found = mp.candidate_documents(store, store, "ENG", lambda record: True, decisions)
    assert [d["document_id"] for d in found] == ["A", "D", "G", "H"]


@pytest.mark.parametrize("title", [JPM, YUM, FLUOR])
def test_the_three_company_documents_reach_prefill(title: list[str]) -> None:
    typed = classify(doc(title))["primary_canonical_type_id"]
    store = Store({"X": typed, "Y": "CT-S1-FUELQTY"})
    found = mp.candidate_documents(store, store, "ENG", lambda record: True)
    assert [d["document_id"] for d in found] == ["X"]
