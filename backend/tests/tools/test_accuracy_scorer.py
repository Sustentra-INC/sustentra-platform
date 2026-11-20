"""The scorer on synthetic documents and synthetic keys (no real test data)."""

from backend.tools.accuracy.keys import KeyCell
from backend.tools.accuracy.model import MATCH, MISSED, NOT_TARGETED, UNSCORED, WRONG, ExtractedDoc, Item
from backend.tools.accuracy.report import baseline_payload, rates, summarize_set, tally
from backend.tools.accuracy.scorer import SetScorer

ELEC_TARGETS = frozenset({"facility_name", "service_address", "account_number", "supplier_name", "service_period_start",
                          "service_period_end", "energy_type", "activity_quantity", "activity_unit", "meter_number",
                          "statement_date"})
MOB_TARGETS = frozenset({"fuel_type", "activity_quantity", "activity_unit", "transaction_date", "merchant_or_supplier",
                         "vehicle_or_equipment_id", "account_number", "statement_date", "distance"})


def item(field: str, raw: object, value: object = None, unit: str | None = None, conf: float = 0.9,
         flags: tuple[str, ...] = (), record: int | None = 1, key: str | None = None) -> Item:
    return Item(field, raw, raw if value is None else value, unit, conf, flags, record, key)


def doc(items: list[Item], targets: frozenset[str] = ELEC_TARGETS, name: str = "a.pdf", type_id: str | None = "CT-S2-ELEC",
        halt: str | None = None) -> ExtractedDoc:
    return ExtractedDoc(name, "completed", type_id, halt, targets, items)


def cell(label: str, expected: str, unit: str = "", name: str = "a.pdf", facility: str = "Plant A",
         doc_type: str = "Electricity bill", location: str = "", trap: str = "") -> KeyCell:
    return KeyCell("T", name, facility, doc_type, "", label, expected, unit, location, {"trap": trap})


def score(cells: list[KeyCell], docs: list[ExtractedDoc]) -> SetScorer:
    scorer = SetScorer("T", cells, {d.filename: d for d in docs})
    scorer.score()
    return scorer


def status_of(scorer: SetScorer, family: str) -> list[str]:
    return [o.status for o in scorer.outcomes if o.family == family]


def test_match_wrong_missed_not_targeted() -> None:
    d = doc([
        item("account_number", "1111-222"),
        item("meter_number", "M-1"),
        item("statement_date", "02/03/2031", "2031-02-03"),
        item("supplier_name", None, None),  # field present, no value
    ])
    s = score([
        cell("account number", "1111 222"),  # formatting differs: still a match
        cell("meter number", "M-2"),  # a different id: wrong
        cell("statement date", "02/03/2031"),
        cell("supplier", "Acme Power"),  # no value: missed
        cell("billed demand", "163", "kW"),  # the extractor has no such field: not scored
    ], [d])
    assert status_of(s, "account") == [MATCH]
    assert status_of(s, "meter") == [WRONG]
    assert status_of(s, "statement_date") == [MATCH]
    assert status_of(s, "supplier") == [MISSED]
    assert status_of(s, "billed_demand") == [NOT_TARGETED]


def test_value_the_key_does_not_cover_is_unscored_not_wrong() -> None:
    d = doc([item("account_number", "111"), item("meter_number", "M-9"), item("supplier_name", "Acme")])
    s = score([cell("account number", "111")], [d])
    assert [o for o in s.outcomes if o.status == WRONG] == []
    assert s.extracted_unscored["meter_number"] == 1 and s.extracted_unscored["supplier_name"] == 1
    assert "account_number" not in s.extracted_unscored  # it was scored


def test_key_cells_that_are_not_readings_are_unscored() -> None:
    d = doc([item("account_number", "111")])
    s = score([
        cell("note: period crosses year end", "16", "days"),
        cell("platform_action", "count once"),
        cell("emission_factor", "0.4", "kg/kWh"),
        cell("some brand new field", "x"),
    ], [d])
    statuses = [o.status for o in s.outcomes if o.family not in ("facility", "document_recognition")]
    assert statuses == [UNSCORED] * 4
    assert s.unmapped_labels == {"some brand new field": 1}


def test_document_missing_from_folder_is_unscored() -> None:
    s = score([cell("supplier", "X", name="gone.pdf")], [])
    assert [o.status for o in s.outcomes] == [UNSCORED]
    assert s.outcomes[0].reason == "document_not_in_folder"


def test_silent_error_needs_no_flag() -> None:
    d = doc([
        item("account_number", "WRONG-1"),  # no flag: silent
        item("meter_number", "WRONG-2", flags=("ai_disagrees",)),  # flagged
        item("supplier_name", "Other Co", conf=0.3),  # low confidence: flagged
        item("statement_date", "01/02/2031", "2031-01-02", flags=("unit_converted",)),  # informational only: still silent
    ])
    s = score([
        cell("account number", "111"), cell("meter number", "M-1"), cell("supplier", "Acme"),
        cell("statement date", "02/02/2031"),
    ], [d])
    silent = {o.family: o.silent for o in s.outcomes if o.status == WRONG and o.family != "facility"}
    assert silent == {"account": True, "meter": False, "supplier": False, "statement_date": True}


def test_dates_must_be_the_same_day() -> None:
    d = doc([item("service_period_start", "03/16/2031 to 04/15/2031", "2031-03-16")])
    s = score([cell("service period start", "03/17/2031")], [d])
    assert status_of(s, "period_start") == [WRONG]


def test_numbers_as_printed_have_no_tolerance_but_conversions_do() -> None:
    printed = doc([item("activity_quantity", "1,200", 1200, "kWh"), item("activity_unit", "kWh")])
    s = score([cell("activity_quantity", "1201", "kWh")], [printed])
    assert status_of(s, "activity_quantity") == [WRONG]
    # read as printed (kWh) and stored in MWh: a conversion, within 0.1% of the key
    converted = doc([item("activity_quantity", "1,200", 1.2, "MWh", flags=("unit_converted",)),
                     item("activity_unit", "kWh", "MWh")])
    s2 = score([cell("activity_quantity", "1200", "kWh")], [converted])
    assert status_of(s2, "activity_quantity") == [MATCH]
    assert [o.exact for o in s2.outcomes if o.family == "activity_quantity"] == [True]
    off = doc([item("activity_quantity", "99", 1.25, "MWh"), item("activity_unit", "kWh", "MWh")])
    assert status_of(score([cell("activity_quantity", "1200", "kWh")], [off]), "activity_quantity") == [WRONG]


def test_unit_is_scored_with_the_quantity() -> None:
    d = doc([item("activity_quantity", "5012", 5012, "ccf"), item("activity_unit", "ccf")])
    s = score([cell("activity quantity (energy)", "5200.5", "therms")], [d])
    assert status_of(s, "activity_quantity") == [WRONG] and status_of(s, "activity_unit") == [WRONG]


def test_fleet_card_transaction_dates_are_not_a_service_period() -> None:
    """The 13 Nov scoring read transaction dates as the period start and made correct values look wrong."""

    d = doc([
        item("transaction_date", "07/04/2031", "2031-07-04", record=1, key="r1"),
        item("activity_quantity", "17.9", 17.9, "gal", record=1, key="r1"),
        item("transaction_date", "09/30/2031", "2031-09-30", record=2, key="r2"),
        item("activity_quantity", "10", 10, "gal", record=2, key="r2"),
    ], MOB_TARGETS, "fleet.pdf", "CT-S1-MOBFUEL")
    s = score([
        cell("service period start", "07/01/2031", name="fleet.pdf", doc_type="Fleet fuel card statement"),
        cell("service period end", "09/30/2031", name="fleet.pdf", doc_type="Fleet fuel card statement"),
    ], [d])
    outcomes = [o for o in s.outcomes if o.family in ("period_start", "period_end")]
    assert [o.status for o in outcomes] == [NOT_TARGETED, NOT_TARGETED]
    assert all(o.reason == "fleet_card_transaction_dates_are_not_a_service_period" for o in outcomes)
    assert [o for o in s.outcomes if o.status == WRONG] == []


def test_bundle_statements_are_found_by_the_period_the_key_gives() -> None:
    items = []
    for i, (start, end, qty) in enumerate([("2031-01-01", "2031-01-31", 10), ("2031-02-01", "2031-02-28", 20)], start=1):
        items += [item("service_period_start", start, start, record=i), item("service_period_end", end, end, record=i),
                  item("activity_quantity", str(qty), qty, "kWh", record=i), item("account_number", "A-1", record=i)]
    d = doc(items, name="bundle.pdf")
    s = score([
        cell("[Feb 2031] service period start", "02/01/2031", name="bundle.pdf"),
        cell("[Feb 2031] service period end", "02/28/2031", name="bundle.pdf"),
        cell("[Feb 2031] activity quantity (energy)", "20", "kWh", name="bundle.pdf"),
        cell("[Jan 2031] activity quantity (energy)", "11", "kWh", name="bundle.pdf"),  # the extractor read 10: wrong
        cell("[Jan 2031] service period start", "01/01/2031", name="bundle.pdf"),
        cell("account number", "A-1", name="bundle.pdf"),
    ], [d])
    assert status_of(s, "activity_quantity") == [MATCH, WRONG]
    assert status_of(s, "period_start") == [MATCH, MATCH] and status_of(s, "account") == [MATCH]


def test_a_record_the_extractor_never_made_is_missed() -> None:
    d = doc([item("service_period_start", "2031-01-01", record=1), item("service_period_end", "2031-01-31", record=1),
             item("activity_quantity", "10", 10, "kWh", record=1)], name="bundle.pdf")
    s = score([cell("[Mar 2031] service period start", "03/01/2031", name="bundle.pdf"),
               cell("[Mar 2031] activity quantity (energy)", "30", "kWh", name="bundle.pdf")], [d])
    assert [o.status for o in s.outcomes if o.family in ("period_start", "activity_quantity")] == [MISSED, MISSED]


def test_rows_of_a_spreadsheet_and_totals() -> None:
    items = []
    for i, qty in enumerate([4.0, 5.0, 6.5], start=1):
        items += [item("activity_quantity", str(qty), qty, "gal", record=i), item("fuel_type", "Diesel", "diesel", record=i)]
    d = doc(items, MOB_TARGETS, "log.xlsx", "CT-S1-MOBFUEL")
    s = score([
        cell("activity_quantity", "5", "gal", name="log.xlsx", location="row 3"),  # row 3 = second record (header is row 1)
        cell("activity_quantity_diesel", "15.5", "gal", name="log.xlsx", location="rows 2-4"),
        cell("total_activity_quantity", "99", "gal", name="log.xlsx"),
    ], [d])
    assert [o.status for o in s.outcomes if o.family == "activity_quantity"] == [MATCH]
    assert [o.status for o in s.outcomes if o.family == "activity_total"] == [MATCH, WRONG]


def test_per_vehicle_total_with_no_date_sums_the_vehicle_records() -> None:
    items = []
    for i, (veh, qty) in enumerate([("V-1", 10.0), ("V-2", 7.0), ("V-1", 5.0)], start=1):
        items += [item("activity_quantity", str(qty), qty, "gal", record=i),
                  item("vehicle_or_equipment_id", veh, record=i)]
    d = doc(items, MOB_TARGETS, "fleet.pdf", "CT-S1-MOBFUEL")
    s = score([cell("[V-1] fuel quantity", "15", "gal", name="fleet.pdf")], [d])
    assert status_of(s, "activity_quantity") == [MATCH]


def test_non_evidence_document_is_unscored_and_a_typed_one_is_wrong() -> None:
    clean = doc([], name="inv.xlsx", type_id=None, halt="unsupported_document")
    treated = doc([item("activity_quantity", "5", 5, "kWh")], name="note.txt")
    keys = [cell("Scope 1 total", "10", name="inv.xlsx", doc_type="Company-prepared GHG inventory (not source evidence)"),
            cell("supplier", "X", name="note.txt", doc_type="Client note (unstructured)")]
    s = score(keys, [clean, treated])
    assert [o.status for o in s.outcomes if o.reason == "non_evidence_document"] == [UNSCORED, UNSCORED]
    recog = {o.filename: o for o in s.outcomes if o.family == "non_evidence_rejected"}
    assert recog["inv.xlsx"].status == MATCH
    assert recog["note.txt"].status == WRONG and recog["note.txt"].silent


def test_unread_document_misses_what_the_extractor_reads_and_skips_what_it_does_not() -> None:
    d = ExtractedDoc("scan.pdf", "partial", None, "ocr_required", frozenset(), [])
    s = score([cell("supplier", "X", name="scan.pdf"), cell("billed demand", "5", "kW", name="scan.pdf")], [d])
    assert status_of(s, "supplier") == [MISSED]
    assert status_of(s, "billed_demand") == [NOT_TARGETED]
    assert status_of(s, "document_recognition") == [MISSED]


def test_facility_placement() -> None:
    right = doc([item("facility_name", "Plant A")], name="r.pdf")
    wrong_no_address = doc([item("facility_name", "Customer Inc.")], name="w.pdf")
    wrong_with_address = doc([item("facility_name", "Customer Inc."), item("service_address", "9 Elm St")], name="a.pdf")
    s = score([cell("supplier", "X", name=n, facility="Facility A: Plant A") for n in ("r.pdf", "w.pdf", "a.pdf")],
              [right, wrong_no_address, wrong_with_address])
    by_file = {o.filename: o for o in s.outcomes if o.family == "facility"}
    assert by_file["r.pdf"].status == MATCH
    assert by_file["w.pdf"].status == WRONG
    assert by_file["a.pdf"].status == UNSCORED  # address-only: needs the facility book


def test_rates_and_baseline_hold_counts_only() -> None:
    d = doc([item("account_number", "111"), item("meter_number", "BAD-77")], name="private-name.pdf")
    s = score([cell("account number", "111", name="private-name.pdf"), cell("meter number", "M-1", name="private-name.pdf")], [d])
    fam = tally(s.outcomes)
    assert rates(fam["account"])["precision"] == 1.0
    assert rates(fam["meter"])["precision"] == 0.0 and fam["meter"]["silent"] == 1
    summary = summarize_set("T", s.outcomes, documents_in_folder=1, documents_keyed=1, documents_not_found=0,
                            extracted_unscored={}, unmapped_labels={})
    payload = baseline_payload({"T": summary}, "rules-only")

    def strings(node: object) -> list[str]:
        if isinstance(node, dict):
            return [x for k, v in node.items() for x in [str(k), *strings(v)]]
        return [str(node)] if isinstance(node, str) else []

    blob = " ".join(strings(payload))
    for private in ("private-name", "M-1", "BAD-77", "Plant A"):
        assert private not in blob
    assert all(isinstance(v, int) for f in payload["sets"]["T"]["families"].values() for v in f.values())
