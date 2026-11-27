"""Sorting the misses on multi-record files (``--sort-misses``): made-up documents, no answer key."""

from __future__ import annotations

from backend.tools.accuracy.misses import (
    ELSEWHERE, NO_TEXT, NOT_PRINTED, PRINTED_MISSED, keyed_multi_record, printed_in, record_fields, render_sort, sort_miss,
    sort_misses,
)
from backend.tools.accuracy.keys import KeyCell
from backend.tools.accuracy.model import MATCH, MISSED, ExtractedDoc, Item, Outcome

LINES = ("Acme Fuels - Fuel Log", "Account 88-1200", "2025-01-02 | GEN-1 | Diesel | 1,204.5",
         "2025-01-03 | GEN-2 | Diesel | ", "Total 1,292.5 gal")


def doc(filename: str = "Plant_North_Log.xlsx") -> ExtractedDoc:
    items = [Item("activity_quantity", 1204.5, 1204.5, "gal", 0.9, record=1),
             Item("activity_quantity", None, None, None, 0.0, record=2),
             Item("account_number", "x", "x", None, 0.6, flags=("ai_suggested",), record=2)]
    return ExtractedDoc(filename=filename, canonical_type_id="CT-S1-FUELQTY", items=items, line_texts=LINES,
                        record_texts={1: (LINES[2],), 2: (LINES[3],)})


def miss(family: str, expected: str, record: int | None = 2, status: str = MISSED) -> Outcome:
    return Outcome("SET", "Plant_North_Log.xlsx", family, status, expected=expected, record=record)


def test_numbers_dates_ids_and_names_are_found_as_printed() -> None:
    assert printed_in("number", "1204.5", LINES) and printed_in("number", "1,292.50", LINES)
    assert not printed_in("number", "1204", LINES)
    assert printed_in("date", "01/03/2025", LINES) and printed_in("date", "Jan 2, 2025", LINES)
    assert not printed_in("date", "2025-02-03", LINES)
    assert printed_in("id", "881200", LINES) and printed_in("name", "ACME FUELS", LINES)
    assert not printed_in("id", "12", LINES)  # too short to count


def test_a_miss_is_sorted_by_where_its_value_is_printed() -> None:
    d = doc()
    assert sort_miss(miss("activity_quantity", "88.0"), d) == NOT_PRINTED
    assert sort_miss(miss("period_start", "2025-01-03"), d) == PRINTED_MISSED  # on record 2's own row
    assert sort_miss(miss("activity_quantity", "1204.5"), d) == ELSEWHERE  # record 1's row, not record 2's
    assert sort_miss(miss("account", "88-1200"), d) == ELSEWHERE  # a header line
    assert sort_miss(miss("activity_quantity", "1204.5", record=None), d) == PRINTED_MISSED  # some record's row
    assert sort_miss(miss("facility", "Plant North", record=None), d) == ELSEWHERE  # the file name


def test_only_misses_on_multi_record_files_are_counted() -> None:
    single = ExtractedDoc(filename="one.pdf", canonical_type_id="CT-S2-ELEC",
                          items=[Item("account_number", None, None, None, 0.0)])
    outcomes = [miss("account", "88-1200"), miss("account", "88-1200", status=MATCH),
                Outcome("SET", "one.pdf", "account", MISSED, expected="88-1200")]
    counts = sort_misses(outcomes, {"Plant_North_Log.xlsx": doc(), "one.pdf": single})
    assert counts == {"account": {NOT_PRINTED: 0, PRINTED_MISSED: 0, ELSEWHERE: 1, NO_TEXT: 0}}
    assert record_fields({"a": doc(), "b": single}) == {"files": 1, "fields": 3, "empty": 1, "ai_filled": 1}
    text = render_sort("SET", counts, record_fields({"a": doc()}))
    assert "88-1200" not in text and "Plant" not in text  # counts only


def _cell(filename: str, label: str, location: str = "") -> KeyCell:
    return KeyCell("SET", filename, "Plant", "Fuel log", "fuel", label, "1", "gal", location)


def test_a_file_the_key_gives_several_records_for_is_counted_even_if_read_as_one() -> None:
    cells = [_cell("log.csv", "[row 1 01/02/2025] fuel added"), _cell("log.csv", "[row 2 01/03/2025] fuel added"),
             _cell("bill.pdf", "supplier"), _cell("bill.pdf", "account")]
    assert keyed_multi_record(cells) == {"log.csv"}
    one = ExtractedDoc(filename="log.csv", canonical_type_id="CT-S1-FUELQTY",
                       items=[Item("activity_quantity", None, None, None, 0.0)], line_texts=("Fuel 410.5 gal",))
    outcomes = [Outcome("SET", "log.csv", "activity_quantity", MISSED, expected="410.5")]
    assert sort_misses(outcomes, {"log.csv": one}) == {}  # the extractor made one record of it
    assert sort_misses(outcomes, {"log.csv": one}, keyed_multi_record(cells)) == {
        "activity_quantity": {NOT_PRINTED: 0, PRINTED_MISSED: 1, ELSEWHERE: 0, NO_TEXT: 0}}


def test_numbers_are_read_by_the_apps_own_reader() -> None:
    assert not printed_in("number", "120", ["Fuel 1,20 gal"])  # an ambiguous comma is not a printed 120
    assert not printed_in("number", "880", ["Menge 88,0 l"])
    assert printed_in("number", "1234.56", ["Total €1.234,56"])
    assert printed_in("number", "1234.567", ["Menge 1234,567 l", "Preis 88,0"], decimal_comma=True)
    assert not printed_in("number", "1234567", ["Menge 1234,567 l"])


def test_a_file_with_no_text_is_its_own_class() -> None:
    blank = ExtractedDoc(filename="scan.pdf", items=[])
    assert sort_miss(Outcome("SET", "scan.pdf", "account", MISSED, expected="88-1200"), blank) == NO_TEXT
