"""Supplier and account gaps found by the NPL dry run: a letterhead that runs over two lines, an email's From
header, a card statement's issuer, a portal export's footer, and which numbers are accounts."""

from __future__ import annotations

from typing import Any

import pytest

from backend.app.services.electricity_extractor import ElectricityExtractor
from backend.app.services.extraction_target_service import ExtractionTargetService
from backend.app.services.mobile_combustion_extractor import MobileCombustionExtractor
from backend.app.services.stationary_combustion_extractor import StationaryCombustionExtractor
from backend.tests.services.test_stationary_combustion_extractor import _by_field, _measured_output, _text_output


@pytest.fixture(scope="module")
def gas() -> list[dict]:
    return ExtractionTargetService().get_targets_for_canonical_type("CT-S1-FUELQTY")


@pytest.fixture(scope="module")
def electric() -> list[dict]:
    return ExtractionTargetService().get_targets_for_canonical_type("CT-S2-ELEC")


@pytest.fixture(scope="module")
def mobile() -> list[dict]:
    return ExtractionTargetService().get_targets_for_canonical_type("CT-S1-MOBFUEL")


def _value(fields: dict[str, dict], name: str) -> Any:
    return fields.get(name, {}).get("normalized_value")


# --- a letterhead name that runs over two lines ---------------------------------------------------------------
def _electric_bill(top: list[tuple[str, float, float, float, float]]) -> list[tuple[str, float, float, float, float]]:
    return top + [("Electric Service Statement", 0.359, 0.046, 0.3, 0.016), ("Account Number", 0.598, 0.123, 0.15, 0.011),
                  ("3348-221905", 0.761, 0.123, 0.15, 0.011), ("Total kWh", 0.631, 0.236, 0.1, 0.01),
                  ("107,880 kWh", 0.66, 0.255, 0.1, 0.01)]


def _supplier(layout: list[tuple[str, float, float, float, float]], targets: list[dict]) -> Any:
    extractor = ElectricityExtractor()
    found = extractor._supplier(extractor._rows(_measured_output(layout)))
    return found.raw if found is not None else None


@pytest.mark.parametrize(("first", "second", "full"), [
    ("RAINIER SOUND", "POWER & LIGHT", "RAINIER SOUND POWER & LIGHT"),
    ("RAINIER SÖUND", "POWER & LIGHT", "RAINIER SÖUND POWER & LIGHT"),
    ("SIERRA BASIN", "UTILITIES", "SIERRA BASIN UTILITIES"),
    ("GRAND VALLEY", "GAS & ELECTRIC", "GRAND VALLEY GAS & ELECTRIC"),
    ("PUGET LAKE", "LIGHT & POWER", "PUGET LAKE LIGHT & POWER"),
    ("COLUMBIA RIVER", "WATER & POWER", "COLUMBIA RIVER WATER & POWER"),
    ("EAST COUNTY", "UTILITY DISTRICT", "EAST COUNTY UTILITY DISTRICT"),
    ("MÜLLER 東京", "UTILITIES", "MÜLLER 東京 UTILITIES"),
])
def test_a_letterhead_name_on_two_lines_is_read_whole(electric: list[dict], first: str, second: str, full: str) -> None:
    layout = _electric_bill([(first, 0.085, 0.045, 0.2, 0.02), (second, 0.085, 0.07, 0.2, 0.014)])

    assert _supplier(layout, electric) == full


@pytest.mark.parametrize("second", [
    "Natural gas service", "PO BOX 3310 TACOMA", "100 MAIN STREET", "ACCOUNTS PAYABLE 98401",
    "ACME MANUFACTURING CO",           # the customer's name block
    "BILLING DEPARTMENT", "NATURAL GAS SERVICE", "ENERGY FOR LIFE", "CUSTOMER CARE", "NORTHGATE PROVISIONS INC",
    "DEPT OF ACCOUNTS", "MÜLLER KÄSEREI LLC", "POWER & LIGHT SERVICES", "ELECTRIC CORP",
])
def test_a_tagline_an_address_or_a_digit_line_under_the_name_is_not_part_of_it(electric: list[dict], second: str) -> None:
    layout = _electric_bill([("RAINIER SOUND", 0.085, 0.045, 0.2, 0.02), (second, 0.085, 0.07, 0.2, 0.014)])

    assert _supplier(layout, electric) == "RAINIER SOUND"


def test_a_second_line_more_than_half_a_line_below_does_not_join(electric: list[dict]) -> None:
    apart = _electric_bill([("RAINIER SOUND", 0.085, 0.045, 0.2, 0.02), ("POWER & LIGHT", 0.085, 0.085, 0.2, 0.014)])
    touching = _electric_bill([("RAINIER SOUND", 0.085, 0.045, 0.2, 0.02), ("POWER & LIGHT", 0.085, 0.07, 0.2, 0.014)])

    assert _supplier(apart, electric) == "RAINIER SOUND"
    assert _supplier(touching, electric) == "RAINIER SOUND POWER & LIGHT"


def test_a_name_that_already_ends_in_an_organisation_word_takes_nothing_from_below(electric: list[dict]) -> None:
    layout = _electric_bill([("RAINIER SOUND POWER", 0.085, 0.045, 0.2, 0.02), ("LIGHT", 0.085, 0.07, 0.2, 0.014)])

    assert _supplier(layout, electric) == "RAINIER SOUND POWER"


def test_a_line_far_under_the_name_or_in_another_column_is_not_part_of_it(electric: list[dict]) -> None:
    far = _electric_bill([("RAINIER SOUND", 0.085, 0.045, 0.2, 0.02), ("POWER & LIGHT", 0.085, 0.2, 0.2, 0.014)])
    beside = _electric_bill([("RAINIER SOUND", 0.085, 0.045, 0.2, 0.02), ("POWER & LIGHT", 0.4, 0.07, 0.2, 0.014)])

    assert _supplier(far, electric) == "RAINIER SOUND" and _supplier(beside, electric) == "RAINIER SOUND"


# --- an email bill -------------------------------------------------------------------------------------------
EMAIL_BODY = ["To: ap@northgateprovisions.example", "Sent: Tue, 06 May 2025 08:14:22 -0700",
              "Subject: Your April 2025 electric statement is ready - Account 3348-221905"]


def _email(lines: list[str], targets: list[dict]) -> dict[str, dict]:
    return _by_field(ElectricityExtractor().extract(_text_output("\n".join(lines)), targets, "EV-1").candidates)


def _email_bill(from_header: str, letterhead: list[str]) -> list[str]:
    return [from_header, *EMAIL_BODY, *letterhead, "Your April 2025 electric statement is ready",
            "Hello Northgate Provisions Inc.,", "Statement date: 05/06/2025", "Billing period: 04/01/2025 - 04/30/2025",
            "Total usage: 101,070 kWh"]


def test_an_email_bills_supplier_is_the_letterhead_in_its_body_not_the_from_header(electric: list[dict]) -> None:
    lines = _email_bill("From: Rainier Sound Power & Light <ebill@rainiersoundpower.example>",
                        ["Rainier Sound Power & Light"])

    assert _value(_email(lines, electric), "supplier_name") == "Rainier Sound Power & Light"


@pytest.mark.parametrize(("header", "name"), [
    ("From: Rainier Sound Power & Light <ebill@rainiersoundpower.example>", "Rainier Sound Power & Light"),
    ('From: "Rainier Sound Power & Light" <ebill@rainiersoundpower.example>', "Rainier Sound Power & Light"),
    ("From: Stadtwerke Zürich Energie AG <rechnung@stadtwerke.example>", "Stadtwerke Zürich Energie AG"),
])
def test_without_a_letterhead_the_display_name_of_the_from_header_is_the_supplier(
        electric: list[dict], header: str, name: str) -> None:
    fields = _email(_email_bill(header, []), electric)

    supplier = _value(fields, "supplier_name")
    assert supplier == name and "<" not in supplier and "@" not in supplier


@pytest.mark.parametrize("header", ["From: ebill@rainiersoundpower.example", "From: <ebill@rainiersoundpower.example>",
                                    "From: Maria Müller <maria@example.com>"])
def test_an_address_alone_or_a_person_names_no_supplier(electric: list[dict], header: str) -> None:
    assert _value(_email(_email_bill(header, []), electric), "supplier_name") is None


def test_a_greeting_to_the_customer_is_not_a_letterhead(gas: list[dict]) -> None:
    lines = ["From: Cedarline Gas & Power <bill@cedarline.example>", "Subject: Your statement", "Hello Northgate Provisions Inc.,",
             "Your statement is ready", "Total Usage: 900 therms"]

    outcome = StationaryCombustionExtractor().extract(_text_output("\n".join(lines)), gas, "EV-1")

    assert _value(_by_field(outcome.candidates), "supplier_name") == "Cedarline Gas & Power"


def test_an_account_that_is_only_in_the_subject_or_the_prose_of_an_email_is_not_read(electric: list[dict]) -> None:
    lines = _email_bill("From: Rainier Sound Power & Light <ebill@rainiersoundpower.example>", ["Rainier Sound Power & Light"])
    lines.append("Your statement for account 3348-221905 is now available.")

    assert _value(_email(lines, electric), "account_number") is None


def test_an_account_labelled_in_the_body_of_an_email_is_read(electric: list[dict]) -> None:
    lines = _email_bill("From: Rainier Sound Power & Light <ebill@rainiersoundpower.example>", ["Rainier Sound Power & Light"])
    lines.append("Account number: 3348-221905")

    assert _value(_email(lines, electric), "account_number") == "3348-221905"


# --- a fleet card statement ----------------------------------------------------------------------------------
def _fleet(extra_top: list[tuple[str, float, float, float, float]] | None = None, *, sized: bool = True,
           card_column: bool = True) -> list[tuple[str, float, float, float, float]]:
    top = [("QUILLFIELD FLEET CARD SERVICES – Zürich", 0.045, 0.026, 0.4, 0.026 if sized else 0.012),
           ("Quarterly Transaction Statement", 0.719, 0.03, 0.2, 0.016),
           ("Account QF-6620-1187 · Statement date 10/03/2025", 0.45, 0.05, 0.4, 0.012)]
    header = [("Date", 0.073, 0.12, 0.07, 0.012), ("Unit", 0.24, 0.12, 0.05, 0.012),
              ("Merchant / Location", 0.369, 0.12, 0.2, 0.012), ("Product", 0.609, 0.12, 0.1, 0.012),
              ("Gallons", 0.725, 0.12, 0.07, 0.012)]
    if card_column:
        header.append(("Card", 0.194, 0.12, 0.05, 0.012))
    rows: list[tuple[str, float, float, float, float]] = []
    for index, (date, card, unit, merchant, product, gallons) in enumerate([
            ("07/01/2025", "4471", "TRK-01", "Puyallup Express Fuel, Puyallup WA", "Diesel #2", "116.485"),
            ("07/02/2025", "4497", "VAN-03", "Lakewood Corner Fuel, Lakewood WA", "Unleaded Regular", "26.355")]):
        y = 0.14 + 0.02 * index
        rows += [(date, 0.073, y, 0.07, 0.012), (unit, 0.24, y, 0.05, 0.012), (merchant, 0.369, y, 0.2, 0.012),
                 (product, 0.609, y, 0.1, 0.012), (gallons, 0.725, y, 0.07, 0.012)]
        if card_column:
            rows.append((card, 0.194, y, 0.05, 0.012))
    return top + (extra_top or []) + header + rows


@pytest.fixture
def station_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    """A fleet card statement read the old way: the station as the merchant, the card as the account."""

    monkeypatch.setattr(MobileCombustionExtractor, "CARD_STATEMENT_AS_ISSUER", False)


def _records(layout: list[tuple[str, float, float, float, float]], targets: list[dict]) -> dict[int | None, dict[str, Any]]:
    outcome = MobileCombustionExtractor().extract(_measured_output(layout), targets, "EV-1")
    records: dict[int | None, dict[str, Any]] = {}
    for candidate in outcome.candidates:
        records.setdefault(candidate["record_index"], {})[candidate["field_name"]] = candidate["normalized_value"]
    return records


def test_a_fleet_statements_supplier_is_the_issuer_and_its_account_the_labelled_one(mobile: list[dict]) -> None:
    records = _records(_fleet(), mobile)

    assert len(records) == 2
    for fields in records.values():
        assert fields["merchant_or_supplier"] == "QUILLFIELD FLEET CARD SERVICES – Zürich"
        assert fields["account_number"] == "QF-6620-1187"  # not the card numbers 4471, 4497
    assert [records[i]["card_number"] for i in sorted(k for k in records if k is not None)] == ["****4471", "****4497"]


def test_the_issuer_is_on_by_default_and_a_card_is_its_own_field_only_on_a_card_statement(mobile: list[dict]) -> None:
    assert MobileCombustionExtractor.CARD_STATEMENT_AS_ISSUER is True
    receipt = MobileCombustionExtractor().extract(
        _text_output("ROUTE 9 FUEL STOP ÅRE\nDiesel 12.457 G @ $3.459/G\nCard ****1234\n"), mobile, "EV-1")

    assert _value(_by_field(receipt.candidates), "card_number") is None


def test_the_station_of_each_transaction_is_where_it_was_fuelled(mobile: list[dict]) -> None:
    records = _records(_fleet(), mobile)

    assert [records[i]["fueling_location"] for i in sorted(k for k in records if k is not None)] == [
        "Puyallup Express Fuel, Puyallup WA", "Lakewood Corner Fuel, Lakewood WA"]


def test_a_statement_with_no_sized_letterhead_or_no_card_column_keeps_its_merchants(mobile: list[dict]) -> None:
    for layout in (_fleet(sized=False), _fleet(card_column=False)):
        merchants = {r["merchant_or_supplier"] for r in _records(layout, mobile).values()}
        assert "QUILLFIELD FLEET CARD SERVICES – Zürich" not in merchants


def test_a_card_statement_with_no_labelled_account_keeps_the_card_numbers_as_before(mobile: list[dict]) -> None:
    layout = [row for row in _fleet() if not row[0].startswith("Account QF")]

    accounts = {r.get("account_number") for r in _records(layout, mobile).values()}

    assert accounts <= {"4471", "4497", None}


def test_a_pump_receipt_has_no_issuer(mobile: list[dict]) -> None:
    text = "ROUTE 9 FUEL STOP ÅRE\nDiesel 12.457 G @ $3.459/G\nTotal $43.09\n"

    outcome = MobileCombustionExtractor().extract(_text_output(text), mobile, "EV-1")

    assert _value(_by_field(outcome.candidates), "merchant_or_supplier") == "ROUTE 9 FUEL STOP ÅRE"


# --- a portal export or a page footer --------------------------------------------------------------------------
def _export(footer: str, *, head: list[str] | None = None, tail: list[str] | None = None) -> list[str]:
    return [*(head or []), "Account Number\tMeter Number\tBill Start Date\tBill End Date\tUsage (therms)",
            "4417-2290-31\tGM-0083315\t04/01/2025\t04/30/2025\t4730", *(tail or []), footer]


def _gas(lines: list[str], targets: list[dict]) -> dict[str, dict]:
    return _by_field(StationaryCombustionExtractor().extract(_text_output("\n".join(lines)), targets, "EV-1").candidates)


@pytest.mark.parametrize(("footer", "name"), [
    ("Data exported 07/08/2025 from Sierra Basin Energy Co. MyAccount portal. Amounts exclude prior balances.",
     "Sierra Basin Energy Co."),
    ("Data exported on 07/08/2025 from Stadtwerke Zürich Energie AG portal", None),
    ("© 2025 Sierra Basin Énergie Co. All rights reserved", "Sierra Basin Énergie Co."),
    ("© Sierra Basin Gas Company | Privacy", "Sierra Basin Gas Company"),
])
def test_a_portal_export_names_its_supplier_in_the_footer(gas: list[dict], footer: str, name: str | None) -> None:
    supplier = _value(_gas(_export(footer), gas), "supplier_name")

    if name is None:
        assert supplier is None  # "Energie AG": not an organisation word the reader trusts
    else:
        assert supplier == name


@pytest.mark.parametrize("footer", ["Data exported 07/08/2025 from the portal", "© 2025 All rights reserved",
                                    "Data exported 07/08/2025 from Müller", "Page 1 of 1"])
def test_a_footer_that_names_no_organisation_names_no_supplier(gas: list[dict], footer: str) -> None:
    assert _value(_gas(_export(footer), gas), "supplier_name") is None


def test_the_footer_ranks_below_the_letterhead_the_labels_and_the_payee(gas: list[dict]) -> None:
    footer = "Data exported 07/08/2025 from Sierra Basin Energy Co. MyAccount portal"

    assert _value(_gas(_export(footer, head=["Supplier: Cedarline Gas & Power"]), gas), "supplier_name") == "Cedarline Gas & Power"
    assert _value(_gas(_export(footer, tail=["REMIT TO: ACME ENERGY CO"]), gas), "supplier_name") == "ACME ENERGY CO"
    assert _value(_gas(_export(footer, head=["Acme Gas Company"]), gas), "supplier_name") == "Acme Gas Company"


def test_with_the_issuer_switch_off_a_fleet_statement_keeps_each_transactions_merchant_and_card(
        mobile: list[dict], station_mode: None) -> None:
    records = _records(_fleet(), mobile)

    assert {r["merchant_or_supplier"] for r in records.values()} == {
        "Puyallup Express Fuel, Puyallup WA", "Lakewood Corner Fuel, Lakewood WA"}
    assert {r["account_number"] for r in records.values()} == {"4471", "4497"}


# --- fix round 1 of #289: vendors, forwarded mail, cards ------------------------------------------------------
@pytest.mark.parametrize("footer", [
    "\u00a9 Oracle Utilities", "\u00a9 2025 Itron Energy Inc.", "Powered by Opower Energy Co.", "Built by Zuora Systems Inc.",
    "Developed by Hansen Software Inc.", "\u00a9 2025 Landis Power Co. All rights reserved",
    "\u00a9 2025 Müller Cloud Platform Inc. All rights reserved", "\u00a9 2025 Bidgely Technologies Inc.",
    "Data exported 07/08/2025 from Oracle Utilities Co. portal",
])
def test_a_software_vendor_in_a_footer_is_never_the_supplier(gas: list[dict], footer: str) -> None:
    assert _value(_gas(_export(footer), gas), "supplier_name") is None


@pytest.mark.parametrize("line", ["Powered by Itron Energy Inc.", "Built by SAP Utilities Co.", "\u00a9 Oracle Utilities Co."])
def test_a_vendor_line_at_the_top_is_not_a_letterhead(gas: list[dict], line: str) -> None:
    assert _value(_gas(_export("Page 1 of 1", head=[line]), gas), "supplier_name") is None


def test_a_footer_name_is_the_last_resort_and_flagged_low_confidence(gas: list[dict]) -> None:
    footer = "Data exported 07/08/2025 from Sierra Basin Energy Co. MyAccount portal"
    candidate = _gas(_export(footer), gas)["supplier_name"]

    assert candidate["normalized_value"] == "Sierra Basin Energy Co."
    assert candidate["confidence"] < 0.5  # under the review threshold: a reviewer confirms it


def test_a_from_header_ranks_above_a_footer(electric: list[dict]) -> None:
    lines = _email_bill("From: Rainier Sound Power & Light <ebill@rainiersoundpower.example>", [])
    lines.append("\u00a9 2025 Sierra Basin Energy Co. All rights reserved")

    assert _value(_email(lines, electric), "supplier_name") == "Rainier Sound Power & Light"


@pytest.mark.parametrize("marker", ["Subject: Fwd: Your April 2025 electric statement", "---------- Forwarded message ----------",
                                    "-----Original Message-----"])
def test_the_from_header_of_a_forwarded_email_is_not_the_supplier(electric: list[dict], marker: str) -> None:
    lines = _email_bill("From: Maria Müller Energy Co <maria@northgateprovisions.example>", [])
    lines.insert(2, marker)

    assert _value(_email(lines, electric), "supplier_name") is None


def test_a_from_name_that_is_the_customer_is_not_the_supplier(electric: list[dict]) -> None:
    lines = _email_bill("From: Northgate Provisions Inc <ap@northgateprovisions.example>", [])

    assert _value(_email(lines, electric), "supplier_name") is None


# cards: always "****" and the last four digits of the card's own digits, whatever the length
def _card_statement(card: str) -> list[tuple[str, float, float, float, float]]:
    layout = _fleet()
    return [("4471" if row[0] == "4471" else row[0], *row[1:]) if row[0] != "4471" else (card, *row[1:]) for row in layout]


@pytest.mark.parametrize(("card", "masked"), [
    ("4111222233334", "****3334"),            # 13 digits
    ("41112222333344", "****3344"),           # 14 digits (Diners)
    ("4111222233334444", "****4444"),         # 16
    ("4111 2222 3333 4444", "****4444"),
    ("4111-2222-3333-4444-123", "****4444"),  # a grouped number with a trailing group: its own last four, not 4123
    ("4111 2222 3333 4444 12", "****4444"),
    ("****0417", "****0417"), ("4471", "****4471"), ("x-4471", "****4471"),
])
def test_a_card_is_stored_as_stars_and_its_own_last_four_digits(mobile: list[dict], card: str, masked: str) -> None:
    records = _records(_card_statement(card), mobile)

    first = records[1]
    assert first["card_number"] == masked
    if len(card.replace(" ", "").replace("-", "")) > 8:
        assert card not in str(records) and card.replace(" ", "") not in str(records)  # the full number is nowhere


@pytest.mark.parametrize("card", ["4111222233334", "41112222333344", "4111222233334444", "4111 2222 3333 4444 123"])
def test_a_card_number_is_masked_in_the_context_label_and_snippet_too(mobile: list[dict], card: str) -> None:
    outcome = MobileCombustionExtractor().extract(_measured_output(_card_statement(card)), mobile, "EV-1")

    for candidate in outcome.candidates:
        for text in (candidate["raw_value"], candidate["normalized_value"], candidate.get("display_label"),
                     *[v for v in candidate["source_reference"].values() if isinstance(v, str)]):
            assert not isinstance(text, str) or card not in text, (candidate["field_name"], text)
            assert not isinstance(text, str) or card.replace(" ", "") not in text.replace(" ", "").replace("-", "")


def test_a_document_that_is_not_a_card_statement_gets_no_card_placeholder(mobile: list[dict]) -> None:
    receipt = MobileCombustionExtractor().extract(
        _text_output("ROUTE 9 FUEL STOP ÅRE\nDiesel 12.457 G @ $3.459/G\nCard ****1234\n"), mobile, "EV-1")
    statement = MobileCombustionExtractor().extract(_measured_output(_fleet()), mobile, "EV-1")

    assert "card_number" not in {c["field_name"] for c in receipt.candidates}
    assert "card_number" in {c["field_name"] for c in statement.candidates}


def test_masked_card_helper() -> None:
    from backend.app.services.mobile_combustion_extractor import masked_card, mask_card_numbers

    assert masked_card("no digits here") is None
    assert masked_card("4111-2222-3333-4444-12") == "****4444"
    assert mask_card_numbers("paid with 41112222333344 and 4111 2222 3333 4444 12") == "paid with ****3344 and ****4444"
