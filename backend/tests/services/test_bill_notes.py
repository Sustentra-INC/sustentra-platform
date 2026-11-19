"""EXT-025: account labels, estimated reads and revised bills, read from the bill's own words.

Estimated reads add the ``estimated_read`` flag to the quantity and never change its value. A revised bill keeps
the reference to the bill it replaces; the data quality check then suggests marking the earlier bill as
superseded (a suggestion only). Non-ASCII text throughout."""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest

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
from backend.app.services.stationary_combustion_extractor import StationaryCombustionExtractor


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


HEAD = (
    "Müller Käserei Stromversorgung – Zürich\nElectric Service Statement\n"
    "Account Number: 3348-221905\nBilling Period: 10/01/2025 - 10/31/2025\n"
)
USAGE = "Total kWh Used: 103,200 kWh\n"


# --- account labels ------------------------------------------------------------------------
PROPANE = "Delta Ridge Propane Co.\nPROPANE DELIVERY INVOICE\n{account}Fuel Type: Propane (LPG)\nDelivery Date\tGallons\n12/05/2025\t612.4\n"


@pytest.mark.parametrize(("line", "expected"), [
    ("Customer No.: DRP-30418\n", "DRP-30418"),
    ("Customer No: DRP-30418\n", "DRP-30418"),
    ("Cust. No.: 暖房-30418\n", "暖房-30418"),
    ("Client ID: KR-FR-2025-044\n", "KR-FR-2025-044"),
    ("Customer: Northgate Provisions Inc. Acct: NFS-08812\n", "NFS-08812"),
    ("Acct: 12-345\n", "12-345"),
    ("Acct. No. 98-7654\n", "98-7654"),
    ("Customer: Müller Käserei – Zürich Acct: MK-0042\n", "MK-0042"),
])
def test_common_account_labels_are_read(fuel_targets: list[dict], line: str, expected: str) -> None:
    account = _field(_fuel(PROPANE.format(account=line), fuel_targets), "account_number") \
        or _field(_fuel(PROPANE.format(account=line), fuel_targets), "account_number", 1)
    assert account is not None and account["normalized_value"] == expected


@pytest.mark.parametrize("line", [
    "Subject: Re: your Acct: 3348-221905\n",  # an email's subject line
    "Please quote your account 3348-221905 when you call us.\n",  # prose
    "Your account balance is on page 2 of 3.\n",
    "Acct: pending\n",  # no digit: not an identifier
])
def test_an_account_is_not_read_from_a_subject_or_prose(fuel_targets: list[dict], line: str) -> None:
    candidates = _fuel(PROPANE.format(account=line), fuel_targets)
    account = _field(candidates, "account_number") or _field(candidates, "account_number", 1)
    assert account is None or account["normalized_value"] in (None, "")


# --- estimated reads -----------------------------------------------------------------------
def test_a_sentence_about_an_estimated_read_flags_the_quantity_and_keeps_its_value(elec_targets: list[dict]) -> None:
    plain = _field(_electric(HEAD + USAGE, elec_targets), "activity_quantity")
    estimated = _field(_electric(HEAD + USAGE + "Your meter could not be read (Zugang). This bill is based on an "
                                 "ESTIMATED read.\n", elec_targets), "activity_quantity")
    assert plain is not None and estimated is not None
    assert ESTIMATED_FLAG not in plain["validation_flags"]
    assert ESTIMATED_FLAG in estimated["validation_flags"]
    assert (estimated["normalized_value"], estimated["raw_value"], estimated["unit"]) == (
        plain["normalized_value"], plain["raw_value"], plain["unit"])  # the value is never changed


@pytest.mark.parametrize("sentence", [
    "This is not an estimated read.",
    "E = Estimated read. A = Actual read.",  # a legend alone says nothing about this bill
    "Estimated annual usage: 1,200,000 kWh.",
])
def test_words_that_are_not_an_estimated_read_do_not_flag(elec_targets: list[dict], sentence: str) -> None:
    quantity = _field(_electric(HEAD + USAGE + sentence + "\n", elec_targets), "activity_quantity")
    assert quantity is not None and ESTIMATED_FLAG not in quantity["validation_flags"]


def test_a_read_type_cell_says_estimated(elec_targets: list[dict]) -> None:
    table = ("Meter\tRead Type\tkWh Used\nM-55012\tEstimated\t12,450\n")
    quantity = _field(_electric(HEAD + table, elec_targets), "activity_quantity")
    assert quantity is not None and ESTIMATED_FLAG in quantity["validation_flags"]
    actual = _field(_electric(HEAD + "Meter\tRead Type\tkWh Used\nM-55012\tActual\t12,450\n", elec_targets),
                    "activity_quantity")
    assert actual is not None and ESTIMATED_FLAG not in actual["validation_flags"]


def test_an_e_marker_needs_its_legend_and_a_read_type_heading() -> None:
    from backend.app.services.stationary_combustion_extractor import Cell, Row

    def row(*texts: str) -> Row:
        return Row(cells=[Cell(text=t, page=1, box=None, block_id=None, source_reference_id=None, confidence=None,
                               order=i) for i, t in enumerate(texts)], page=1)

    with_legend = [row("Meter", "Present Read", "Read Type"), row("M-1", "853,925 E", "1"),
                   row("E = Estimated read")]
    assert estimated_reads(with_legend).any()
    assert not estimated_reads(with_legend[:2]).any()  # no legend: an "E" is only a letter
    assert not estimated_reads([row("Time", "10:00", "EST"), row("Zone: EST")]).any()  # a time zone, no read type
    assert estimated_reads([row("Meter", "Read Type"), row("M-1", "EST")]).marked_rows


def test_the_marked_row_is_the_one_that_is_flagged_in_a_multi_meter_bill(elec_targets: list[dict]) -> None:
    table = ("Meter\tRead Type\tkWh Used\nM-1\tActual\t12,450\nM-2\tEstimated\t4,200\n")
    candidates = _electric(HEAD + table, elec_targets)
    flagged = {c["record_index"]: ESTIMATED_FLAG in c["validation_flags"]
               for c in candidates if c["field_name"] == "activity_quantity"}
    assert flagged in ({1: False, 2: True}, {None: True})  # per meter when the rows are told apart


# --- revised bills -------------------------------------------------------------------------
@pytest.mark.parametrize(("sentence", "reference"), [
    ("REVISED STATEMENT\nThis statement replaces the statement dated 04/04/2025 for service 10/01/2025 - 10/31/2025.",
     "04/04/2025"),
    ("Corrected bill. This bill supersedes bill no. INV-2025-889 (Reason: Zählerfehler).", "INV-2025-889"),
    ("This invoice corrects the invoice of March 4, 2025.", "March 4, 2025"),
    ("Revised bill: the previous bill for this period is replaced.", REVISED_WITHOUT_REFERENCE),
])
def test_a_revised_bill_keeps_the_reference_to_the_one_it_replaces(elec_targets: list[dict], sentence: str,
                                                                    reference: str) -> None:
    candidates = _electric(HEAD + USAGE + sentence + "\n", elec_targets)
    found = _field(candidates, REVISES_FIELD)
    assert found is not None and found["normalized_value"] == reference
    assert found["source_reference"]["text_snippet"]  # the reviewer can see where it was read
    quantity = _field(candidates, "activity_quantity")
    assert quantity is not None and quantity["normalized_value"] == 103.2  # nothing else changes


@pytest.mark.parametrize("sentence", [
    "The utility replaces meters every ten years.",
    "We replaced the meter on 03/01/2025.",
    "Statement of account for Müller Käserei.",
])
def test_ordinary_words_do_not_make_a_bill_a_revision(elec_targets: list[dict], sentence: str) -> None:
    assert _field(_electric(HEAD + USAGE + sentence + "\n", elec_targets), REVISES_FIELD) is None
    assert revision([]) is None


# --- the data quality suggestion -----------------------------------------------------------
def record(document: str, *, revises: str | None = None, account: str | None = "3348-221905",
           facility: str = "Tacoma DC", start: str = "2025-03-01", end: str = "2025-03-31",
           quantity: float = 107.88) -> EvidenceRecord:
    return EvidenceRecord(
        category="purchased_electricity", document_id=document, file_name=f"{document}.pdf", label=f"{document}.pdf",
        facility=facility, item=None, account=account, start=date.fromisoformat(start), end=date.fromisoformat(end),
        amounts=(quantity,), unit="MWh", periodic=True, revises=revises)


YEAR = (date(2025, 1, 1), date(2025, 12, 31))


def revision_findings(records: list[EvidenceRecord]) -> list[dict]:
    return [f for f in run_checks(records, YEAR) if f["trigger"] == "revised_bill_replaces_earlier"]


def test_a_revised_bill_suggests_marking_the_earlier_one_as_superseded() -> None:
    findings = revision_findings([record("ORIGINAL"), record("REVISED", revises="04/04/2025", quantity=105.12)])
    assert len(findings) == 1
    finding = findings[0]
    assert finding["detail"]["suggestion"] == "mark_superseded"
    assert finding["detail"]["original_document_id"] == "ORIGINAL"
    assert finding["documents"] == ["REVISED", "ORIGINAL"]
    assert "mark it as superseded" in finding["message"] and "04/04/2025" in finding["message"]
    # The same pair is not reported a second time as an overlap.
    pairs = [f for f in run_checks([record("ORIGINAL"), record("REVISED", revises="04/04/2025")], YEAR)
             if f["check"] in ("Q-003", "Q-004")]
    assert [f["trigger"] for f in pairs].count("revised_bill_replaces_earlier") == 1
    assert not any(f["check"] == "Q-004" for f in pairs)


def test_nothing_is_suggested_without_an_earlier_bill_to_mark() -> None:
    assert revision_findings([record("REVISED", revises="04/04/2025")]) == []
    # A bill of another account, another source or other days is not the one replaced.
    assert revision_findings([record("OTHER", account="9999-1"), record("REVISED", revises="04/04/2025")]) == []
    assert revision_findings([record("APRIL", start="2025-04-01", end="2025-04-30"),
                              record("REVISED", revises="04/04/2025")]) == []
    # A bill that says nothing about replacing another is not a revision.
    assert revision_findings([record("ORIGINAL"), record("SECOND")]) == []


def test_a_revised_bill_with_no_reference_still_suggests_and_names_no_date() -> None:
    findings = revision_findings([record("ORIGINAL"), record("REVISED", revises=REVISED_WITHOUT_REFERENCE)])
    assert len(findings) == 1 and "an earlier bill" in findings[0]["message"]


def test_a_missing_account_falls_back_to_the_same_facility() -> None:
    findings = revision_findings([record("ORIGINAL", account=None), record("REVISED", account=None, revises="X-123")])
    assert len(findings) == 1
    assert revision_findings([record("ORIGINAL", account=None, facility="Elsewhere"),
                              record("REVISED", account=None, revises="X-123")]) == []
