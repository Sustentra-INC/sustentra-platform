"""EXT-025: account labels, estimated reads and revised bills, read from the bill's own words.

Estimated reads add the ``estimated_read`` flag to the quantity and never change its value. A revised bill keeps
the reference to the bill it replaces; the data quality check then suggests marking the earlier bill as
superseded (a suggestion only), and only when the reference matches. Non-ASCII text throughout; the cases marked
"probe" are the ones the review found."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import pytest
from openpyxl import Workbook

from backend.app.services.bill_notes import (
    ESTIMATED_FLAG,
    REVISED_WITHOUT_REFERENCE,
    REVISES_FIELD,
    estimated_reads,
    revision,
)
from backend.app.services.data_quality_checks import EvidenceRecord, run_checks
from backend.app.services.electricity_extractor import ElectricityExtractor
from backend.app.services.extraction_target_service import ExtractionTargetService
from backend.app.services.parser_service import ParserService
from backend.app.services.stationary_combustion_extractor import Cell, Row, StationaryCombustionExtractor


@pytest.fixture(scope="module")
def elec_targets() -> list[dict]:
    return ExtractionTargetService().get_targets_for_canonical_type("CT-S2-ELEC")


@pytest.fixture(scope="module")
def fuel_targets() -> list[dict]:
    return ExtractionTargetService().get_targets_for_canonical_type("CT-S1-FUELQTY")


def _text_output(text: str) -> dict[str, Any]:
    return {
        "document_id": "DOC-1", "pages": [{"page_number": 1, "text": text}],
        "text_blocks": [{"block_id": "b1", "page_number": 1, "text": text, "confidence": None,
                         "bounding_box": None, "source_reference_id": None}],
        "tables": [], "key_value_pairs": [], "source_references": [],
    }


def _electric(text: str, targets: list[dict]) -> list[dict]:
    outcome = ElectricityExtractor().extract(_text_output(text), targets, "EV-1")
    assert outcome.halt_reason is None, outcome.halt_reason
    return outcome.candidates


def _fuel(text: str, targets: list[dict]) -> list[dict]:
    outcome = StationaryCombustionExtractor().extract(_text_output(text), targets, "EV-1")
    assert outcome.halt_reason is None, outcome.halt_reason
    return outcome.candidates


def _field(candidates: list[dict], name: str, record_index: int | None = None) -> dict | None:
    return next((c for c in candidates if c["field_name"] == name and c["record_index"] == record_index), None)


def _account(candidates: list[dict]) -> str | None:
    found = _field(candidates, "account_number") or _field(candidates, "account_number", 1)
    return (found or {}).get("normalized_value") or None


def _estimated(candidates: list[dict], record_index: int | None = None) -> bool:
    quantity = _field(candidates, "activity_quantity", record_index)
    assert quantity is not None
    return ESTIMATED_FLAG in quantity["validation_flags"]


HEAD = (
    "Müller Käserei Stromversorgung – Zürich\nElectric Service Statement\n"
    "Account Number: 3348-221905\nBilling Period: 10/01/2025 - 10/31/2025\n"
)
USAGE = "Total kWh Used: 103,200 kWh\n"
LEGEND = "E = Estimated read. A = Actual read.\n"


# --- account labels ------------------------------------------------------------------------
PROPANE = ("Delta Ridge Propane Co.\nPROPANE DELIVERY INVOICE\n{account}Fuel Type: Propane (LPG)\n"
           "Delivery Date\tGallons\n12/05/2025\t612.4\n")


@pytest.mark.parametrize(("line", "expected"), [
    ("Customer No.: DRP-30418\n", "DRP-30418"),
    ("Customer No: DRP-30418\n", "DRP-30418"),
    ("Cust. No.: 暖房-30418\n", "暖房-30418"),
    ("Customer: Northgate Provisions Inc. Acct: NFS-08812\n", "NFS-08812"),
    ("Acct: 12-345\n", "12-345"),
    ("Acct. No. 98-7654\n", "98-7654"),
    ("Customer: Müller Käserei – Zürich Acct: MK-0042\n", "MK-0042"),
])
def test_common_account_labels_are_read(fuel_targets: list[dict], line: str, expected: str) -> None:
    assert _account(_fuel(PROPANE.format(account=line), fuel_targets)) == expected


@pytest.mark.parametrize("line", [
    "Subject: Re: your Acct: 3348-221905\n",  # an email's subject line
    "Please quote your account 3348-221905 when you call us.\n",  # prose
    "Your account balance is on page 2 of 3.\n",
    "Acct: pending\n",  # no digit: not an identifier
    "Client ID: KR-FR-2025-044\n",  # probe: a CRM reference, not a utility account
    "Customer ID: 998877\n",  # probe: the same
    "Account: 555-123-4567\n",  # probe: a phone number
    "Account: (555) 123-4567\n",
    "Account: +1 555 123 4567\n",
    "Acct: call 253-555-0127 for help\n",
    "Account: please quote this number 12345 on every payment you make\n",  # probe: a sentence
    "Account: Zahlung bis 15. Dezember 2025 an Müller Käserei\n",
])
def test_an_account_is_not_read_from_a_subject_prose_a_phone_or_a_crm_id(fuel_targets: list[dict], line: str) -> None:
    assert _account(_fuel(PROPANE.format(account=line), fuel_targets)) is None


# --- estimated reads: the forms of a bill that does say so ---------------------------------
@pytest.mark.parametrize("extra", [
    "Your meter could not be read (Zugang). This bill is based on an ESTIMATED read.\n",
    "Your usage was estimated this month.\n",
    "ESTIMATED READ\n",
    "Read Type: Estimated\n",
    "Read Type: Estimate\n",
    "Read Type: EST\n",
    "Read Type: E\n" + LEGEND,  # probe
    "Meter\tRead Type\tkWh Used\nM-55012\tEstimated\t103,200\n",
    "Meter\tPresent Read\tkWh Used\nM-55012\t853,925 (E)\t103,200\n" + LEGEND,  # probe
    "Meter\tReading\tkWh Used\nM-55012\tE\t103,200\n" + LEGEND,  # probe
    "Meter\tRead\tkWh Used\nM-55012\t853,925 E\t103,200\n" + LEGEND,
])
def test_a_bill_that_says_a_read_was_estimated_flags_its_quantity_and_keeps_the_value(
        elec_targets: list[dict], extra: str) -> None:
    plain = _field(_electric(HEAD + USAGE, elec_targets), "activity_quantity")
    candidates = _electric(HEAD + USAGE + extra, elec_targets)
    quantity = _field(candidates, "activity_quantity")
    assert plain is not None and quantity is not None
    assert ESTIMATED_FLAG in quantity["validation_flags"], extra
    assert (quantity["normalized_value"], quantity["raw_value"], quantity["unit"]) == (
        plain["normalized_value"], plain["raw_value"], plain["unit"])  # the value is never changed


# --- estimated reads: words that are not a statement about this bill -----------------------
@pytest.mark.parametrize("extra", [
    "This is not an estimated read.\n",
    LEGEND,  # a legend alone says nothing about this bill
    "Estimated annual usage: 1,200,000 kWh.\n",
    "Estimated Read: not applicable\n",  # probe
    "Estimated Read Fee: $5.00 applies when we estimate your read.\n",  # probe
    "If we estimate your read, the bill is marked as estimated.\n",  # probe
    "Estimated reading date: 11/05\n",  # probe
    "Ihre Rechnung kann bei Schätzung als geschätzt gekennzeichnet werden (Müller 電気).\n",
    "Meter\tRead Type\tkWh Used\nM-55012\tActual\t103,200\n",
    "Meter\tRead Type\tkWh Used\nRS-7781204 (E)\tActual\t103,200\n" + LEGEND,  # a meter named "(E)", not a read
    "Time\tZone\n10:00\tEST\n",  # a time zone
])
def test_words_that_are_not_an_estimated_read_do_not_flag(elec_targets: list[dict], extra: str) -> None:
    assert not _estimated(_electric(HEAD + USAGE + extra, elec_targets)), extra


def _row(*texts: str) -> Row:
    return Row(cells=[Cell(text=t, page=1, box=None, block_id=None, source_reference_id=None, confidence=None,
                           order=i) for i, t in enumerate(texts)], page=1)


def test_an_e_marker_always_needs_its_legend() -> None:
    marked = [_row("Meter", "Present Read", "Read Type"), _row("M-1", "853,925 E", "1")]
    assert not estimated_reads(marked).any()  # no legend: an "E" is only a letter
    assert estimated_reads([*marked, _row("E = Estimated read")]).any()
    assert not estimated_reads([_row("Meter", "Read Type"), _row("M-1", "E")]).any()
    assert estimated_reads([_row("Meter", "Read Type"), _row("M-1", "EST")]).marked_rows  # a word needs no legend


def test_the_estimated_meter_is_the_one_flagged_in_a_multi_meter_bill(elec_targets: list[dict]) -> None:
    table = "Meter\tRead Type\tkWh Used\nM-1\tActual\t12,450\nM-2\tEstimated\t4,200\n"
    candidates = _electric(HEAD + table, elec_targets)
    flagged = {c["record_index"]: ESTIMATED_FLAG in c["validation_flags"]
               for c in candidates if c["field_name"] == "activity_quantity"}
    assert flagged == {1: False, 2: True}
    by_record = {c["record_index"]: c["raw_value"] for c in candidates if c["field_name"] == "activity_quantity"}
    assert by_record == {1: "12,450", 2: "4,200"}  # the second meter is the 4,200 one


def test_a_spreadsheet_bill_flags_the_estimated_meter(tmp_path: Path, elec_targets: list[dict]) -> None:
    book = Workbook()
    sheet = book.active
    sheet.append(["Müller Käserei Stromversorgung – Zürich"])
    sheet.append(["Account Number", "3348-221905"])
    sheet.append(["Billing Period", "10/01/2025 - 10/31/2025"])
    sheet.append(["Meter", "Read Type", "kWh Used"])
    sheet.append(["M-1", "Actual", 12450])
    sheet.append(["M-2", "Estimated", 4200])
    sheet.append(["E = Estimated read"])
    path = tmp_path / "Stromrechnung 電気.xlsx"
    book.save(path)
    parsed = ParserService().parse_document(file_path=path, document_id="DOC-X", processing_run_id="RUN-X")
    outcome = ElectricityExtractor().extract(parsed, elec_targets, "EV-X")
    assert outcome.halt_reason is None
    flagged = {c["record_index"]: (c["raw_value"], ESTIMATED_FLAG in c["validation_flags"])
               for c in outcome.candidates if c["field_name"] == "activity_quantity"}
    assert flagged == {1: ("12450", False), 2: ("4200", True)}


# --- revised bills -------------------------------------------------------------------------
@pytest.mark.parametrize(("sentence", "reference", "key"), [
    ("REVISED STATEMENT\nThis statement replaces the statement dated 04/17/2025 for service 10/01/2025 - 10/31/2025.",
     "04/17/2025", "2025-04-17"),
    ("Corrected bill. This bill supersedes bill no. INV-2025-889 (Reason: Zählerfehler 電気).", "INV-2025-889",
     "INV-2025-889"),
    ("This invoice corrects the invoice of March 4, 2025.", "March 4, 2025", "2025-03-04"),
    ("CORRECTED BILL", REVISED_WITHOUT_REFERENCE, None),
])
def test_a_revised_bill_keeps_the_reference_to_the_one_it_replaces(
        elec_targets: list[dict], sentence: str, reference: str, key: str | None) -> None:
    candidates = _electric(HEAD + USAGE + sentence + "\n", elec_targets)
    found = _field(candidates, REVISES_FIELD)
    assert found is not None and found["normalized_value"] == reference
    assert found["source_reference"].get("reference_key") == key
    assert found["source_reference"]["text_snippet"]  # the reviewer can see where it was read
    quantity = _field(candidates, "activity_quantity")
    assert quantity is not None and quantity["normalized_value"] == 103.2  # nothing else changes


@pytest.mark.parametrize("sentence", [
    "A corrected bill will be issued if an error is found.",  # probe: boilerplate
    "Please pay this revised statement by the due date.",  # probe
    "Billing errors are corrected on the next statement.",
    "Revised bill: the previous bill for this period is replaced.",  # not a heading, not "This bill replaces"
    "The utility replaces meters every ten years.",
    "We replaced the meter on 03/01/2025.",
    "Statement of account for Müller Käserei 電気.",
])
def test_ordinary_words_do_not_make_a_bill_a_revision(elec_targets: list[dict], sentence: str) -> None:
    assert _field(_electric(HEAD + USAGE + sentence + "\n", elec_targets), REVISES_FIELD) is None
    assert revision([_row(sentence)]) is None


def test_a_bill_keeps_its_own_statement_date_and_number(elec_targets: list[dict]) -> None:
    with_ids = _electric(HEAD + USAGE + "Statement Date: 04/17/2025\nInvoice No.: SB-2025-0042\n", elec_targets)
    assert _field(with_ids, "activity_quantity")["source_reference"]["bill_ids"] == ["2025-04-17", "SB-2025-0042"]
    without = _electric(HEAD + USAGE, elec_targets)
    assert "bill_ids" not in _field(without, "activity_quantity")["source_reference"]


# --- the data quality suggestion -----------------------------------------------------------
def record(document: str, *, revises: str | None = None, key: str | None = None, ids: tuple[str, ...] = (),
           account: str | None = "3348-221905", facility: str = "Tacoma DC", start: str = "2025-03-01",
           end: str = "2025-03-31", quantity: float = 107.88) -> EvidenceRecord:
    return EvidenceRecord(
        category="purchased_electricity", document_id=document, file_name=f"{document}.pdf", label=f"{document}.pdf",
        facility=facility, item=None, account=account, start=date.fromisoformat(start), end=date.fromisoformat(end),
        amounts=(quantity,), unit="MWh", periodic=True, revises=revises, revises_key=key, bill_ids=ids)


YEAR = (date(2025, 1, 1), date(2025, 12, 31))
ORIGINAL = {"ids": ("2025-04-04", "SB-2025-0042")}


def suggestions(records: list[EvidenceRecord]) -> list[dict]:
    return [f for f in run_checks(records, YEAR) if f["trigger"] == "revised_bill_replaces_earlier"]


def test_a_revised_bill_suggests_marking_the_bill_it_names_as_superseded() -> None:
    found = suggestions([record("ORIGINAL", **ORIGINAL),
                         record("REVISED", revises="04/04/2025", key="2025-04-04", quantity=105.12)])
    assert len(found) == 1
    finding = found[0]
    assert finding["detail"]["suggestion"] == "mark_superseded"
    assert finding["detail"]["original_document_id"] == "ORIGINAL"
    assert finding["documents"] == ["REVISED", "ORIGINAL"]
    assert "the earlier statement dated 04/04/2025" in finding["message"]
    assert "mark it as superseded" in finding["message"]
    # The same pair is not also reported as an overlap.
    assert not any(f["check"] == "Q-004" for f in run_checks(
        [record("ORIGINAL", **ORIGINAL), record("REVISED", revises="04/04/2025", key="2025-04-04")], YEAR))


def test_the_message_names_the_printed_invoice_number() -> None:
    found = suggestions([record("ORIGINAL", ids=("SB-2025-0042",)),
                         record("REVISED", revises="SB-2025-0042", key="SB-2025-0042")])
    assert len(found) == 1 and "the earlier bill number SB-2025-0042" in found[0]["message"]


def test_a_date_or_number_that_matches_no_bill_suggests_nothing() -> None:
    assert suggestions([record("ORIGINAL", ids=("2025-04-04",)),
                        record("REVISED", revises="05/01/2025", key="2025-05-01")]) == []
    assert suggestions([record("ORIGINAL"), record("REVISED", revises="05/01/2025", key="2025-05-01")]) == []  # ids unknown
    assert suggestions([record("ORIGINAL", ids=("SB-1",)), record("REVISED", revises="SB-2", key="SB-2")]) == []


def test_a_bill_that_replaces_another_is_never_the_earlier_one_whatever_the_order() -> None:
    original = record("ORIGINAL", ids=("2025-04-04",))
    first = record("REV1", revises="04/04/2025", key="2025-04-04", ids=("2025-05-16",), quantity=105.12)
    second = record("REV2", revises="05/16/2025", key="2025-05-16", ids=("2025-06-20",), quantity=104.0)
    outcomes = []
    for order in ([original, first, second], [second, first, original], [first, second, original]):
        found = suggestions(order)
        outcomes.append(sorted((f["documents"][0], f["detail"].get("original_document_id")) for f in found))
        assert all(f["detail"].get("original_document_id") != "REV1" for f in found)  # never the newer bill
    assert outcomes == [[("REV1", "ORIGINAL")]] * 3


def test_several_possible_earlier_bills_are_not_guessed() -> None:
    found = suggestions([record("A", ids=("2025-04-04",)), record("B", ids=("2025-04-09",)),
                         record("REVISED", revises=REVISED_WITHOUT_REFERENCE)])
    assert len(found) == 1
    assert found[0]["detail"]["suggestion"] == "mark_which" and "original_document_id" not in found[0]["detail"]
    assert sorted(found[0]["detail"]["candidates"]) == ["A", "B"]
    assert "Mark which one it replaces" in found[0]["message"]
    # A printed date that names one of them is that one.
    named = suggestions([record("A", ids=("2025-04-04",)), record("B", ids=("2025-04-09",)),
                         record("REVISED", revises="04/09/2025", key="2025-04-09")])
    assert [f["detail"]["original_document_id"] for f in named] == ["B"]


def test_a_revised_bill_with_no_reference_suggests_the_only_candidate_and_keeps_the_overlap_finding() -> None:
    records = [record("ORIGINAL"), record("REVISED", revises=REVISED_WITHOUT_REFERENCE, quantity=105.12)]
    found = suggestions(records)
    assert len(found) == 1 and "an earlier bill" in found[0]["message"]
    assert found[0]["detail"]["original_document_id"] == "ORIGINAL"
    # Nothing printed to match on, so the overlap warning is not suppressed.
    assert any(f["check"] == "Q-004" for f in run_checks(records, YEAR))


def test_no_earlier_bill_in_the_engagement_suggests_nothing() -> None:
    assert suggestions([record("REVISED", revises="04/04/2025", key="2025-04-04")]) == []
    # Another account, other days, or a bill that is itself a revision is not the one replaced.
    assert suggestions([record("OTHER", account="9999-1", ids=("2025-04-04",)),
                        record("REVISED", revises="04/04/2025", key="2025-04-04")]) == []
    assert suggestions([record("APRIL", start="2025-04-01", end="2025-04-30", ids=("2025-04-04",)),
                        record("REVISED", revises="04/04/2025", key="2025-04-04")]) == []
    assert suggestions([record("ORIGINAL"), record("SECOND")]) == []


def test_a_missing_account_falls_back_to_the_same_facility() -> None:
    found = suggestions([record("ORIGINAL", account=None, ids=("X-123",)),
                         record("REVISED", account=None, revises="X-123", key="X-123")])
    assert len(found) == 1
    assert suggestions([record("ORIGINAL", account=None, facility="Elsewhere", ids=("X-123",)),
                        record("REVISED", account=None, revises="X-123", key="X-123")]) == []
