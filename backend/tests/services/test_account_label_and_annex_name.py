"""MVP-189: an account number is read without its label, and a customer is never the facility of a meter that has its
own address.

The Textract-read Fresno bill gave the account as "SERVICE FOR: 8830-1174-562", so Q-003 called two bills with the
same account "different accounts". On the two-meter Tacoma bill the annex (2210, not in Setup) carried the customer's
name as its facility, so Q-001 listed "NORTHGATE PROVISIONS INC electricity"."""

from __future__ import annotations

from typing import Any

import pytest

from backend.app.services.electricity_extractor import CANONICAL_TYPE_ID, ElectricityExtractor
from backend.app.services.extraction_target_service import ExtractionTargetService
from backend.app.services.facility_identifiers import clean_account
from backend.tests.services.test_calculation_lines import GAS_KC, KC, _gas, _lines_with_docs, _tree
from backend.tests.services.test_data_quality_checks import YEAR, bill, run_checks, triggers
from backend.tests.services.test_engagement_recalculation_service import FakeStore, _own
from backend.tests.services.test_facility_placement_layouts import _meter_bill
from backend.tests.services.test_stationary_combustion_extractor import _measured_output, _text_output
from backend.tests.services.test_year_end_bills import ENGAGEMENT, _bill, _filed, _service


@pytest.fixture(scope="module")
def targets() -> list[dict]:
    return ExtractionTargetService().get_targets_for_canonical_type(CANONICAL_TYPE_ID)


# --- clean_account ----------------------------------------------------------------------------------------------
@pytest.mark.parametrize(("raw", "clean"), [
    ("SERVICE FOR: 8830-1174-562", "8830-1174-562"),
    ("service for:8830-1174-562", "8830-1174-562"),
    ("Account Number: 7730-115-2048", "7730-115-2048"),
    ("Acct #: 4417", "4417"),
    ("ACCOUNT NO.: Zürich-77/ä", "Zürich-77/ä"),
    ("Account: Service For: 8830-1174-562", "8830-1174-562"),
    ("8830-1174-562", "8830-1174-562"),            # nothing to take off
    ("ACCT-1", "ACCT-1"),                           # a value that starts like a label but has no colon
    ("Account Number:", "Account Number:"),         # nothing left after the label: kept as read
    ("ACCT#12", "ACCT#12"),                         # a real prefix: "#" with no space is not a label ending
    ("AC#12", "AC#12"),
    ("Account#5521", "Account#5521"),
    ("Customer#4417", "Customer#4417"),
    ("Meter#3", "Meter#3"),
    ("GAS-118204-3", "GAS-118204-3"),
    ("Account # 8830", "8830"),
    ("ACCT# 12", "12"),
    ("Account #: 8830", "8830"),
    ("SERVICE FOR：8830-1174-562", "8830-1174-562"),  # fullwidth colon
    ("SERVICE​ FOR:‍ 8830", "8830"),         # zero-width characters in the label
    ("Account：Ｚürich-77", "Zürich-77"),
    ("  ", ""),
    (None, ""),
])
def test_clean_account_takes_off_a_leading_label_and_nothing_else(raw: Any, clean: str) -> None:
    assert clean_account(raw) == clean


# --- the extractor: label and value in one Textract cell --------------------------------------------------------
def _fresno(cell: str) -> dict[str, Any]:
    return _measured_output([
        ("Fresno Electric Company", 0.1, 0.05, 0.3, 0.02),
        ("Account Number", 0.07, 0.12, 0.12, 0.012), ("Bill Date", 0.4, 0.12, 0.08, 0.012),
        (cell, 0.07, 0.14, 0.2, 0.012), ("01/21/2026", 0.4, 0.14, 0.08, 0.012),
        ("Service Period", 0.6, 0.12, 0.1, 0.012), ("12/16/2025 to 01/15/2026", 0.6, 0.14, 0.2, 0.012),
        ("Total kWh", 0.7, 0.5, 0.1, 0.012), ("52,840", 0.7, 0.52, 0.08, 0.012)])


@pytest.mark.parametrize("cell", ["SERVICE FOR: 8830-1174-562", "Account Number: 8830-1174-562",
                                  "8830-1174-562"])
def test_the_account_is_read_without_the_label_in_its_cell(targets: list[dict], cell: str) -> None:
    outcome = ElectricityExtractor().extract(_fresno(cell), targets, "EV-1")
    assert outcome.halt_reason is None
    account = [c for c in outcome.candidates if c["field_name"] == "account_number"]
    assert [c["normalized_value"] for c in account] == ["8830-1174-562"]


# --- Q-003: the same account written two ways is one account -----------------------------------------------------
def _pair(first: str, second: str, facility: str = "Fresno Plant") -> list:
    """Two files that share July but not their other month, so they are not taken for one document uploaded twice."""

    return [bill("A", "2025-07-01", "2025-07-31", account=first, facility=facility),
            bill("A", "2025-08-01", "2025-08-31", 90.0, account=first, facility=facility, record=2),
            bill("B", "2025-07-01", "2025-07-31", account=second, facility=facility),
            bill("B", "2025-09-01", "2025-09-30", 80.0, account=second, facility=facility, record=2)]


def test_the_same_account_in_two_spellings_is_a_duplicate_not_different_accounts() -> None:
    findings = [f for f in run_checks(_pair("8830-1174-562", "8830 1174 562"), YEAR)
                if f["check"] == "Q-003"]
    assert ("Q-003", "duplicate_counting_risk") in triggers(findings)
    assert "duplicate_period_amount_with_different_invoice_id" not in [f["trigger"] for f in findings]


def test_two_really_different_accounts_are_still_different_accounts() -> None:
    assert ("Q-003", "duplicate_period_amount_with_different_invoice_id") in triggers(
        run_checks(_pair("8830-1174-562", "8830-1174-563"), YEAR))


def test_non_ascii_accounts_compare_by_their_letters_and_digits() -> None:
    assert not any(t == "duplicate_period_amount_with_different_invoice_id" for _, t in triggers(run_checks(
        _pair("Müller-77", "MÜLLER 77", facility="Zürich"), YEAR)))


# --- the annex meter: the customer is not its facility ---------------------------------------------------------
def test_each_meter_with_its_own_address_gets_no_facility_name_from_the_customer(targets: list[dict]) -> None:
    outcome = ElectricityExtractor().extract(_meter_bill(), targets, "EV-1")
    assert outcome.halt_reason is None
    names = {c["record_index"]: c["normalized_value"] for c in outcome.candidates if c["field_name"] == "facility_name"}
    assert names == {1: None, 2: None}
    addresses = {c["record_index"]: c["normalized_value"] for c in outcome.candidates
                 if c["field_name"] == "service_address"}
    assert addresses == {1: "2200 PORT OF TACOMA RD", 2: "2210 PORT OF TACOMA RD"}


def test_a_single_meter_bill_with_no_address_still_takes_the_customer_as_a_last_resort(targets: list[dict]) -> None:
    text = "Valley Power\nCustomer: Käserei Müller AG\nAccount Number: V-1\nService Period: 2025-04-01 to 2025-04-30\nTotal kWh 900\n"
    outcome = ElectricityExtractor().extract(_text_output(text), targets, "EV-1")
    names = [c["normalized_value"] for c in outcome.candidates if c["field_name"] == "facility_name"]
    assert names == ["Käserei Müller AG"]


# --- Q-001: a record Setup does not list is grouped by its address, never by a customer or a blank ---------------
def _quality(records: list[dict[str, tuple]]) -> list[dict]:
    return _filed(records)[1]["quality_checks"]


def test_an_unplaced_record_is_grouped_by_its_own_address() -> None:
    findings = _quality([_bill("2025-09-01", "2025-09-30", 8.64, address="2210 Port of Tacoma Rd")])
    assert findings
    assert {f["facility"] for f in findings} == {"2210 Port of Tacoma Rd (not in Setup)"}


def test_a_non_ascii_unplaced_address_is_kept_whole() -> None:
    findings = _quality([_bill("2025-09-01", "2025-09-30", 8.64, address="12 Bahnhofstraße, 8001 Zürich")])
    assert {f["facility"] for f in findings} == {"12 Bahnhofstraße, 8001 Zürich (not in Setup)"}


def test_a_record_with_no_name_and_no_address_is_facility_not_known() -> None:
    findings = _quality([_bill("2025-09-01", "2025-09-30", 8.64, address=None)])
    assert {f["facility"] for f in findings} == {"Facility not known"}


def test_a_name_the_bill_gives_still_names_the_group() -> None:
    findings = _quality([_bill("2025-09-01", "2025-09-30", 8.64, name="Annex Cold Store", address=None)])
    assert {f["facility"] for f in findings} == {"Annex Cold Store"}


def test_a_label_left_in_the_account_does_not_make_two_bills_different_accounts() -> None:
    """Through the recalculation: the account reaches Q-003 without the label OCR left in front of it."""

    def record(month: str, last: str, account: str) -> dict[str, tuple]:
        return {**_bill(f"2025-{month}-01", f"2025-{month}-{last}", 31.0), "account_number": (account, None)}

    store = FakeStore()
    store.add_document("A", "CT-S2-ELEC", [record("07", "31", "8830-1174-562"), record("08", "31", "8830-1174-562")])
    store.add_document("B", "CT-S2-ELEC", [record("07", "31", "SERVICE FOR: 8830-1174-562"),
                                           record("09", "30", "SERVICE FOR: 8830-1174-562")])
    findings = _service(store).recalculate(ENGAGEMENT, _own)["quality_checks"]
    assert "duplicate_period_amount_with_different_invoice_id" not in [f["trigger"] for f in findings]
    assert "duplicate_counting_risk" in [f["trigger"] for f in findings]


@pytest.mark.parametrize(("first", "second"), [("12-345", "1234-5"), ("1-234", "12-34"), ("12-345", "123-45")])
def test_accounts_that_share_only_their_digits_are_still_different_accounts(first: str, second: str) -> None:
    findings = [f for f in run_checks(_pair(first, second), YEAR) if f["check"] == "Q-003"]
    assert [f["trigger"] for f in findings] == ["duplicate_period_amount_with_different_invoice_id"]
    assert first in findings[0]["message"] and second in findings[0]["message"]


def test_an_account_saved_with_its_label_before_this_change_still_places_the_bill_by_number() -> None:
    store = FakeStore()
    store.add_document("D1", "CT-S1-FUELQTY", [{**_gas(1000, account_number="SERVICE FOR: 4417-2290-31"),
                                                 "facility_name": (None, None)}])
    facilities = [{**KC, "accountNumbers": ["4417-2290-31"]}]
    assert _lines_with_docs(_tree(store, facilities=facilities)) == {GAS_KC: ["D1"]}
