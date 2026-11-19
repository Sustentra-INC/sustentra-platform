"""Where a bill lands (EXT-022): the bill's own layouts read to the right Setup facility, and a near miss never does.

The NPL set's bills named their site in a "SERVICE FOR:" block (with the colon), in "Company - Site" form, with
"Rd" for "Road", with a suite, or at a second address on the same bill. None of them reached its facility."""

from __future__ import annotations

from typing import Any

import pytest

from backend.app.services.electricity_extractor import CANONICAL_TYPE_ID, ElectricityExtractor
from backend.app.services.evidence_tree_service import EvidenceTreeService
from backend.app.services.extraction_target_service import ExtractionTargetService
from backend.app.services.reviewed_evidence import match_facility
from backend.tests.services.test_calculation_lines import _lines_with_docs
from backend.tests.services.test_engagement_recalculation_service import FakeStore, _own
from backend.tests.services.test_year_end_bills import _layout

FRESNO = {"facilityId": "F1", "name": "Fresno Plant", "address": "4410 E Jensen Ave, Fresno, CA 93725"}
SACRAMENTO = {"facilityId": "F2", "name": "Sacramento Warehouse", "address": "1820 Richards Blvd, Sacramento, CA 95811"}
TACOMA = {"facilityId": "F3", "name": "Tacoma Distribution Center",
          "address": "2200 Port of Tacoma Road, Tacoma, WA 98421"}
ZURICH = {"facilityId": "F4", "name": "Müller Käserei – Zürich", "address": "10 Quay Way, Zürich"}
SETUP = [FRESNO, SACRAMENTO, TACOMA, ZURICH]
COMPANY = "Northgate Provisions Inc."


def _match(name: Any = None, address: Any = None, company: Any = COMPANY, facilities: list[dict] = SETUP) -> str | None:
    found = match_facility(name, address, facilities, company)
    return found["name"] if found else None


# --- the extractor: the site in a "SERVICE FOR:" block ---------------------------------------------------------
@pytest.fixture(scope="module")
def targets() -> list[dict]:
    return ExtractionTargetService().get_targets_for_canonical_type(CANONICAL_TYPE_ID)


def _read(parser_output: dict, targets: list[dict]) -> dict[str, Any]:
    outcome = ElectricityExtractor().extract(parser_output, targets, "EV-1")
    assert outcome.halt_reason is None, outcome.halt_reason
    return {c["field_name"]: c["normalized_value"] for c in outcome.candidates if c["record_index"] is None}


MAILING = ["NORTHGATE PROVISIONS INC", "ATTN ACCOUNTS PAYABLE", "555 CAPITOL MALL STE 900", "SACRAMENTO CA 95814"]


def test_the_service_for_block_with_a_colon_gives_the_site_and_address(targets: list[dict]) -> None:
    read = _read(_layout(["NORTHGATE PROVISIONS INC", "FRESNO PLANT", "4410 E JENSEN AVE", "FRESNO CA 93725"],
                         MAILING, heading="SERVICE FOR:"), targets)
    assert read["facility_name"] == "FRESNO PLANT"  # not the customer's name
    assert read["service_address"] == "4410 E JENSEN AVE, FRESNO CA 93725"


def test_a_non_ascii_service_for_block_with_a_colon_is_read_whole(targets: list[dict]) -> None:
    read = _read(_layout(["Müller Käserei AG", "Käserei Zürich Nord", "12 Bahnhofstraße", "8001 Zürich"],
                         ["Müller Käserei AG", "Postfach 77", "3000 Bern"], heading="Service for:"), targets)
    assert read["facility_name"] == "Käserei Zürich Nord"
    assert read["service_address"] == "12 Bahnhofstraße, 8001 Zürich"


def test_the_bill_to_name_is_still_never_the_site(targets: list[dict]) -> None:
    read = _read(_layout(["NORTHGATE PROVISIONS INC", "4410 E JENSEN AVE", "FRESNO CA 93725"], MAILING,
                         heading="SERVICE FOR:"), targets)
    assert read["facility_name"] is None
    assert read["service_address"] == "4410 E JENSEN AVE, FRESNO CA 93725"


# --- the extractor: two meters at two addresses on one bill ----------------------------------------------------
def _meter_bill() -> dict[str, Any]:
    lines = ["Rainier Süd Power & Light", "Electric Service Statement", "Account Number: 3348-221905",
             "Customer: NORTHGATE PROVISIONS INC", "Billing Period: 09/01/2025 – 09/30/2025 (30 days)",
             "Meter | Service Address | On-Peak kWh | Off-Peak kWh | Total kWh",
             "RS-7781204 | 2200 PORT OF TACOMA RD | 44,120 | 66,480 | 110,600",
             "RS-7781266 | 2210 PORT OF TACOMA RD | 3,215 | 5,425 | 8,640",
             "This statement includes 2 meters billed under one account."]
    blocks = [{"block_id": f"B{i}", "page_number": 1, "text": line, "source_reference_id": f"S{i}", "confidence": 0.99}
              for i, line in enumerate(lines)]
    return {"document_id": "DOC-1", "text_blocks": blocks, "pages": [], "tables": [], "source_references": []}


def test_each_meter_keeps_its_own_service_address(targets: list[dict]) -> None:
    outcome = ElectricityExtractor().extract(_meter_bill(), targets, "EV-1")
    assert outcome.halt_reason is None
    by_record: dict[Any, dict[str, Any]] = {}
    for c in outcome.candidates:
        by_record.setdefault(c["record_index"], {})[c["field_name"]] = c["normalized_value"]
    assert sorted((r["service_address"], r["activity_quantity"]) for r in by_record.values()) == [
        ("2200 PORT OF TACOMA RD", 110.6), ("2210 PORT OF TACOMA RD", 8.64)]


# --- match_facility: exact after normalisation, never a near miss ---------------------------------------------------
@pytest.mark.parametrize("address", [
    "4410 E JENSEN AVE", "4410 East Jensen Avenue", "4410 E. Jensen Ave., Fresno, CA 93725",
    "Fresno Plant, 4410 E Jensen Ave, Fresno CA 93725", "4410 e jensen ave fresno ca"])
def test_the_same_street_address_in_any_usps_spelling_matches(address: str) -> None:
    assert _match(address=address) == "Fresno Plant"


@pytest.mark.parametrize(("address", "expected"), [
    ("2200 PORT OF TACOMA RD", "Tacoma Distribution Center"),
    ("2200 Port of Tacoma Rd, Tacoma, WA 98421", "Tacoma Distribution Center"),
    ("Northgate Provisions Inc., 1820 Richards Boulevard, Sacramento, CA 95811", "Sacramento Warehouse"),
    ("1820 RICHARDS BLVD.", "Sacramento Warehouse"),
    ("10 Quay Way, Zürich", "Müller Käserei – Zürich"),
])
def test_road_rd_boulevard_blvd_and_other_spellings_match(address: str, expected: str) -> None:
    assert _match(address=address) == expected


@pytest.mark.parametrize("address", [
    "2210 Port of Tacoma Rd",            # the annex: not a Setup facility
    "2210 PORT OF TACOMA RD, TACOMA WA 98421",
    "22000 Port of Tacoma Road",         # one digit more
    "220 Port of Tacoma Road",           # one digit fewer
    "2200A Port of Tacoma Road",         # a letter the Setup address does not have
    "Port of Tacoma Road",               # no house number: never optional
    "2200 Port of Tacoma",               # stops inside the street name
    "2200 Port of Tacoma Rd, Tacoma, WA 98422",  # another postal code
    "4410 E Jensen Ave, Fresno, CA 93726",
    "1820 Richards Blvd, Sacramento, CA 95814",
    "10 Quay Way, Zurich",               # not the same word: no fuzzy match
])
def test_a_near_miss_never_matches(address: str) -> None:
    assert _match(address=address) is None


def test_a_name_matches_after_case_punctuation_and_dashes() -> None:
    assert _match(name="FRESNO  PLANT") == "Fresno Plant"
    assert _match(name="Müller Käserei — Zürich") == "Müller Käserei – Zürich"  # an em dash for an en dash
    assert _match(name="Müller Käserei - Zürich") == "Müller Käserei – Zürich"
    assert _match(name="Sacramento Warehouse.") == "Sacramento Warehouse"
    assert _match(name="Sacramento") is None
    assert _match(name="Sacramento Warehouse 2") is None


@pytest.mark.parametrize("name", ["Northgate Provisions Inc. – Sacramento Warehouse",
                                  "Northgate Provisions Inc - Sacramento Warehouse",
                                  "NORTHGATE PROVISIONS INC. — SACRAMENTO WAREHOUSE",
                                  "Northgate Provisions – Sacramento Warehouse"])
def test_company_dash_site_matches_the_site_when_the_company_is_the_engagements(name: str) -> None:
    assert _match(name=name) == "Sacramento Warehouse"


def test_another_companys_site_of_the_same_name_does_not_match() -> None:
    assert _match(name="Acme – Sacramento Warehouse") is None
    assert _match(name="Acme Köln GmbH – Sacramento Warehouse") is None
    assert _match(name="Northgate Provisions Inc. – Sacramento Warehouse", company="Acme") is None
    assert _match(name="Northgate Provisions Inc. – Sacramento Warehouse", company=None) is None


def test_a_suite_is_ignored_only_when_setup_has_none() -> None:
    assert _match(address="1820 Richards Boulevard, Suite 200, Sacramento, CA 95811") == "Sacramento Warehouse"
    assert _match(address="1820 Richards Blvd Ste 200") == "Sacramento Warehouse"
    suite = {"facilityId": "F5", "name": "Capitol Office", "address": "555 Capitol Mall, Suite 900, Sacramento, CA"}
    assert _match(address="555 Capitol Mall Ste 900", facilities=[suite]) == "Capitol Office"
    assert _match(address="555 Capitol Mall #900, Sacramento, CA", facilities=[suite]) == "Capitol Office"
    assert _match(address="555 Capitol Mall Ste 901", facilities=[suite]) is None
    assert _match(address="555 Capitol Mall, Sacramento, CA", facilities=[suite]) is None  # which suite?


def test_a_name_and_an_address_that_name_different_facilities_keep_the_name_first() -> None:
    # the same order as before: the name decides when it matches
    assert _match(name="Fresno Plant", address="2200 Port of Tacoma Rd") == "Fresno Plant"


# --- end to end: the document lands on its facility's line ------------------------------------------------------
def _bill(name: str | None, address: str | None) -> dict[str, tuple]:
    record: dict[str, tuple] = {
        "activity_quantity": (31.0, "MWh"), "activity_unit": ("MWh", None), "energy_type": ("electricity", None),
        "service_period_start": ("2025-03-01", None), "service_period_end": ("2025-03-31", None)}
    if name:
        record["facility_name"] = (name, None)
    if address:
        record["service_address"] = (address, None)
    return record


def _filed(name: str | None, address: str | None, company: str | None = COMPANY) -> dict[str, list[str]]:
    store = FakeStore()
    store.add_document("MAR", "CT-S2-ELEC", [_bill(name, address)])
    engagement = {"id": "ENG-1", "client_name": company, "reporting_period_start": "2025-01-01",
                  "reporting_period_end": "2025-12-31", "settings": {"facilities": SETUP}}
    return _lines_with_docs(EvidenceTreeService(store, store, store).tree(engagement, _own, None))


def test_a_company_dash_site_bill_is_filed_on_the_site() -> None:
    assert _filed("Northgate Provisions Inc. – Sacramento Warehouse", None) == {
        "s2:purchased_energy:electricity:f2": ["MAR"]}


def test_another_companys_bill_with_the_same_site_name_is_left_unplaced() -> None:
    assert _filed("Acme – Sacramento Warehouse", None) == {}


def test_the_annex_address_leaves_the_bill_unplaced_and_the_main_address_places_it() -> None:
    assert _filed(None, "2210 PORT OF TACOMA RD") == {}
    assert _filed(None, "2200 PORT OF TACOMA RD") == {"s2:purchased_energy:electricity:f3": ["MAR"]}


# --- fix round 1: every fitting facility is collected; streets with no USPS suffix; punctuation boundaries ----------
def _only(address: Any = None, name: Any = None, *rows: tuple[str, str]) -> str | None:
    facilities = [{"facilityId": f"X{i}", "name": n, "address": a} for i, (n, a) in enumerate(rows)]
    found = match_facility(name, address, facilities, COMPANY)
    return found["name"] if found else None


def test_the_facility_whose_suite_agrees_wins_over_the_plain_street_row() -> None:
    rows = (("Hauptsitz Zürich", "100 Main St, München"), ("Büro 300", "100 Main St Ste 300, München"))
    assert _only("100 Main St Ste 300, München", None, *rows) == "Büro 300"
    assert _only("100 Main Street #300, München", None, *rows) == "Büro 300"
    assert _only("100 Main St, München", None, *rows) == "Hauptsitz Zürich"
    assert _only("100 Main St Ste 999, München", None, *rows) == "Hauptsitz Zürich"  # a suite Setup lacks is ignored


def test_a_street_only_bill_on_a_street_two_sites_share_matches_neither() -> None:
    rows = (("Springfield Plant", "100 Main St, Springfield, IL"), ("Peoria Plant", "100 Main St, Peoria, IL"))
    assert _only("100 Main St", None, *rows) is None
    assert _only("100 Main Street, Peoria", None, *rows) == "Peoria Plant"
    assert _only("100 Main St, Springfield, IL 62701", None, *rows) == "Springfield Plant"
    twins = (("Werk A", "5 Via Roma, Zürich"), ("Werk B", "5 Via Roma, Zürich"))
    assert _only("5 Via Roma", None, *twins) is None
    assert _only(None, "Werk A", *(("Werk A", "x"), ("Werk A", "y"))) is None  # one name, two sites: nothing matched


def test_fl_is_florida_and_a_town_called_ste_is_not_a_suite() -> None:
    miami = (("Miami Café", "100 Main St, Miami, FL 33101"),)
    assert _only("100 Main St", None, *miami) == "Miami Café"
    assert _only("100 Main Street, Miami, Florida".replace("Florida", "FL"), None, *miami) == "Miami Café"
    assert _only("100 Main St, Miami, FL 33101", None, *miami) == "Miami Café"
    genevieve = (("Sainte Müller", "12 Main St, Ste. Genevieve, MO 63670"),)
    assert _only("12 Main St", None, *genevieve) == "Sainte Müller"
    assert _only("12 Main Street, Ste. Genevieve, MO", None, *genevieve) == "Sainte Müller"
    assert _only("12 Main St FL 3, Miami", None, *(("Etage", "12 Main St Fl 3, Miami"),)) == "Etage"  # a real floor


@pytest.mark.parametrize("address", ["15 Broadway", "1211 Avenue of the Americas", "500 Highway 99", "PO Box 1234",
                                     "One Market Plaza", "Bahnhofstrasse 12, 8001 Zurich", "100 Main"])
def test_an_identical_address_with_no_usps_suffix_still_matches(address: str) -> None:
    assert _only(address, None, ("Ort Ä", address)) == "Ort Ä"
    assert _only(address.upper(), None, ("Ort Ä", address)) == "Ort Ä"


def test_routes_end_the_street_at_their_number_and_a_different_number_is_another_street() -> None:
    setup = (("Fresno Café", "500 Highway 99, Fresno, CA 93706"),)
    assert _only("500 Hwy 99", None, *setup) == "Fresno Café"
    assert _only("500 State Route 99, Fresno", None, *(("Rte", "500 State Rte 99, Fresno"),)) == "Rte"
    assert _only("500 Highway 98, Fresno", None, *setup) is None
    assert _only("500 Highway 99, Madera", None, *setup) is None


def test_a_direction_after_the_suffix_belongs_to_the_street_only_when_no_comma_separates_it() -> None:
    west = (("Sacramento Ä", "100 Main St W, Sacramento"),)
    assert _only("100 Main St, West Sacramento", None, *west) is None  # West Sacramento is a city
    assert _only("100 Main Street West, Sacramento", None, *west) == "Sacramento Ä"
    assert _only("100 Main St W", None, *west) == "Sacramento Ä"
    city = (("West Ä", "100 Main St, West Sacramento"),)
    assert _only("100 Main St, West Sacramento, CA", None, *city) == "West Ä"
    assert _only("100 Main St W, Sacramento", None, *city) is None


def test_a_po_box_number_is_never_a_house_number() -> None:
    assert _only("PO Box 100, Main St", None, ("Büro", "100 Main St")) is None
    assert _only("P.O. Box 100, 100 Main St", None, ("Büro", "100 Main St")) == "Büro"  # the street after it counts
    assert _only("PO Box 100", None, ("Büro", "100 Main St")) is None


def test_unit_and_hash_are_the_same_unit() -> None:
    row = (("Büro 4", "555 Capitol Mall Unit 4, Sacramento"),)
    assert _only("555 Capitol Mall #4, Sacramento", None, *row) == "Büro 4"
    assert _only("555 Capitol Mall, Suite 4, Sacramento", None, *row) == "Büro 4"
    assert _only("555 Capitol Mall #5, Sacramento", None, *row) is None


def test_two_consecutive_street_lines_are_one_address_with_the_first_street() -> None:
    assert _only("100 Main St, 200 Oak Ave, Zürich", None, ("Büro", "100 Main St, Zürich")) == "Büro"
    assert _only("200 Oak Ave, 100 Main St, Zürich", None, ("Büro", "100 Main St, Zürich")) is None


def test_site_address_and_premises_address_columns_keep_each_meters_address(targets: list[dict]) -> None:
    for header in ("Site Address", "Premises Address"):
        text = _meter_bill_with(header)
        outcome = ElectricityExtractor().extract(text, targets, "EV-1")
        by_record: dict[Any, dict[str, Any]] = {}
        for c in outcome.candidates:
            by_record.setdefault(c["record_index"], {})[c["field_name"]] = c["normalized_value"]
        assert sorted(r["service_address"] for r in by_record.values()) == [
            "2200 PORT OF TACOMA RD", "2210 PORT OF TACOMA RD"], header


def _meter_bill_with(header: str) -> dict[str, Any]:
    bill = _meter_bill()
    for block in bill["text_blocks"]:
        if block["text"].startswith("Meter | Service Address"):
            block["text"] = block["text"].replace("Service Address", header)
    return bill
