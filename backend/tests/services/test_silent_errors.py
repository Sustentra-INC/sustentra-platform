"""Regression tests for the "silent" errors the accuracy harness found: a wrong value that carried no flag.

Every fixture is synthetic text written for the test; none is a real document.
"""

from __future__ import annotations

from typing import Any

import pytest

from backend.app.services import bill_notes
from backend.app.services.extraction_target_service import ExtractionTargetService
from backend.app.services.mobile_combustion_extractor import MobileCombustionExtractor
from backend.app.services.stationary_combustion_extractor import StationaryCombustionExtractor


def _text_output(text: str) -> dict[str, Any]:
    return {
        "document_id": "DOC-1",
        "pages": [{"page_number": 1, "text": text}],
        "text_blocks": [{"block_id": "b1", "page_number": 1, "text": text, "confidence": None,
                         "bounding_box": None, "source_reference_id": None}],
        "tables": [], "key_value_pairs": [], "source_references": [],
    }


def _by_field(candidates: list[dict], record_index: int | None = None) -> dict[str, dict]:
    return {c["field_name"]: c for c in candidates if c["record_index"] == record_index}


@pytest.fixture(scope="module")
def fuel_targets() -> list[dict]:
    return ExtractionTargetService().get_targets_for_canonical_type("CT-S1-FUELQTY")


@pytest.fixture(scope="module")
def mobile_targets() -> list[dict]:
    return ExtractionTargetService().get_targets_for_canonical_type("CT-S1-MOBFUEL")


# --- a card statement's account is the account, not a transaction's card -------------------------------
CARD_STATEMENT = (
    "Quillfeather Fleet Card Services\n"
    "Company:    Example Foods Ltd - Dock fleet\n"
    "Account:    QFC-1234-0007\n"
    "Statement Period:    07/01/2025 - 07/31/2025\n"
    "Date\tCard\tVehicle\tType\tFuel\tGallons\tAmount\n"
    "07/04/2025\t****7301\tTR-01\tBox truck\tDiesel\t31.5\t$140.00\n"
    "07/05/2025\t****7302\tTR-02\tTractor\tDiesel\t88.8\t$400.00\n"
)


def test_card_statement_account_is_the_header_account_when_label_and_value_are_separate_cells(
        mobile_targets: list[dict]) -> None:
    outcome = MobileCombustionExtractor().extract(_text_output(CARD_STATEMENT), mobile_targets, "EV-1")
    for index in (1, 2):
        assert _by_field(outcome.candidates, index)["account_number"]["normalized_value"] == "QFC-1234-0007"


def test_a_masked_card_read_as_the_account_is_flagged(mobile_targets: list[dict]) -> None:
    text = CARD_STATEMENT.replace("Account:    QFC-1234-0007\n", "")  # no account printed: only the cards remain
    outcome = MobileCombustionExtractor().extract(_text_output(text), mobile_targets, "EV-1")
    account = _by_field(outcome.candidates, 1)["account_number"]
    assert account["normalized_value"] == "****7301"
    assert "card_number_masked" in account["validation_flags"]


# --- a line a party label opens is not the letterhead ---------------------------------------------------
def test_report_title_names_the_issuer_not_the_customer_line(mobile_targets: list[dict]) -> None:
    text = (
        "Acme Equipment Hire – Customer Fuel Report (METRIC UNITS)\n"
        "Customer: Zed Provisions Inc. · Rental site: 1 Main Street · Contract AB-1\n"
        "Unit\tFuel Type\tMonth\tFuel Dispensed (L)\n"
        "R-1\tDiesel\t2025-01\t321.0\n"
    )
    outcome = MobileCombustionExtractor().extract(_text_output(text), mobile_targets, "EV-1")
    supplier = _by_field(outcome.candidates)["merchant_or_supplier"]
    assert supplier["normalized_value"] == "Acme Equipment Hire"


# --- an email's From display name carries the mailbox, not the company ---------------------------------
EMAIL = (
    "From: Acme Power Billing <ebill@acme-power.example>\n"
    "To: Accounts Payable <ap@example-foods.example>\n"
    "Subject: Your bill is ready - Account 1234-567-8901\n"
    "\n"
    "Hello Example Foods Inc.,\n"
    "\n"
    "Account number:   1234-567-8901\n"
    "Billing period:   03/16/2025 - 04/15/2025\n"
    "Energy used:      9,000 kWh\n"
    "\n"
    "Thank you,\n"
    "Acme Power Company - Business Billing\n"
    "1 Main Street, Springfield\n"
)


def _sender(text: str) -> str | None:
    rows = StationaryCombustionExtractor()._rows(_text_output(text))
    found = StationaryCombustionExtractor._from_header(rows)
    return found.raw if found is not None else None


def test_email_sender_company_drops_the_mailbox_word_and_takes_the_sign_off() -> None:
    assert _sender(EMAIL) == "Acme Power Company"


def test_email_sender_without_a_sign_off_drops_the_mailbox_word() -> None:
    assert _sender(EMAIL.split("Thank you")[0]) == "Acme Power"


def test_email_sender_without_a_mailbox_word_is_unchanged() -> None:
    assert _sender(EMAIL.replace("Acme Power Billing", "Acme Power Company")) == "Acme Power Company"


# --- one usage printed in two units is flagged ---------------------------------------------------------
GAS_BILL_TWO_UNITS = (
    "Springfield Gas Co.\n"
    "Natural Gas Invoice\n"
    "Account: SG-100-200\n"
    "Service from January 1, 2025 through January 31, 2025\n"
    "Meter    Read on January 1    Read on January 31    Usage (CCF)\n"
    "G-1    1,000    1,500    500\n"
    "Heat content: 1.05 therms per CCF\n"
    "Therms billed = 500 CCF x 1.05 = 525.0 therms\n"
)


def test_quantity_is_flagged_when_the_bill_prints_a_conversion(fuel_targets: list[dict]) -> None:
    outcome = StationaryCombustionExtractor().extract(_text_output(GAS_BILL_TWO_UNITS), fuel_targets, "EV-1")
    fields = _by_field(outcome.candidates)
    assert fields["activity_quantity"]["normalized_value"] is not None
    for name in ("activity_quantity", "activity_unit"):
        assert bill_notes.UNIT_AMBIGUOUS_FLAG in fields[name]["validation_flags"]


def test_quantity_is_not_flagged_when_the_bill_prints_one_unit(fuel_targets: list[dict]) -> None:
    text = GAS_BILL_TWO_UNITS.replace("Heat content: 1.05 therms per CCF\n", "").replace(
        "Therms billed = 500 CCF x 1.05 = 525.0 therms\n", "")
    fields = _by_field(StationaryCombustionExtractor().extract(_text_output(text), fuel_targets, "EV-1").candidates)
    assert fields["activity_quantity"]["normalized_value"] is not None
    assert bill_notes.UNIT_AMBIGUOUS_FLAG not in fields["activity_quantity"]["validation_flags"]


class _Cell:
    def __init__(self, text: str) -> None:
        self.text = text


class _Row:
    def __init__(self, text: str) -> None:
        self.cells = [_Cell(text)]


@pytest.mark.parametrize("line", [
    "Heat content: 1.05 therms per CCF",
    "Conversion 1.2 MMBtu / Mlb",
    "(500 x 1.05 = 525.0)",
    "1,000 CCF x 1.05 = 1,050 therms",
])
def test_prints_conversion_finds_a_factor_or_a_derivation(line: str) -> None:
    assert bill_notes.prints_conversion([_Row(line)])


@pytest.mark.parametrize("line", [
    "Energy charge: $1,000.00 (10,000 kWh x $0.10)",
    "Consumption charge 300.0 Mlb x $20.00",
    "Demand 100 kW x $9.00",
    "Price 3.999 $/gal",
])
def test_prints_conversion_ignores_rates(line: str) -> None:
    assert not bill_notes.prints_conversion([_Row(line)])
