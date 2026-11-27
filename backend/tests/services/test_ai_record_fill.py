"""Sustentra's AI fills a record's own empty fields in a file with several records (MVP-238).

A fake AI client and a fake ledger: no network, no database. The documents are built here (a fuel log as a
workbook, a two-bill bundle as a PDF), never read from test sets."""

from __future__ import annotations

import time
import tracemalloc
from typing import Any

from backend.app.adapters.parsers.base import build_source_reference, build_text_block
from backend.app.services import ai_record_fill as arf
from backend.app.services.ai_extraction import AI_SUGGESTED, AiExtraction, AssistOutcome
from backend.app.services.ai_locator import row_lines
from backend.app.services.halt_text import plain_note
from backend.tests.services.test_ai_extraction import ORG, FakeClaude, parsed, settings, target
from backend.tests.services.test_ai_routing import FakeLedger

SHEET = "Fuel Log"
HEADER = ["Date", "Unit", "Fuel", "Gallons", "Note"]
TARGETS = [
    target("transaction_date", "Transaction date", "date"),
    target("vehicle_or_equipment_id", "Equipment id"),
    target("fuel_type", "Fuel type"),
    target("activity_quantity", "Activity quantity", "quantity", ("gal", "L")),
    target("account_number", "Account number"),
    target("facility_name", "Facility name"),
]


def _cell_id(column: int, row: int) -> str:
    return f"xlsx-{SHEET}-{'ABCDEFGH'[column]}{row}"


def workbook(rows: list[list[str]]) -> dict[str, Any]:
    """A parser output shaped like the workbook parser's: one block per non-empty cell, row 1 the header."""

    blocks, references = [], []
    for row_number, row in enumerate([HEADER, *rows], start=1):
        for column, text in enumerate(row):
            if not text:
                continue
            block_id = _cell_id(column, row_number)
            reference_id = f"SRC-{block_id}"
            references.append(build_source_reference(
                reference_id, "DOC-1", sheet_name=SHEET, cell_or_range=f"{'ABCDEFGH'[column]}{row_number}",
                text_snippet=text, parser_block_ids=[block_id], source_kind="excel_cell"))
            blocks.append(build_text_block(block_id, text, source_reference_id=reference_id))
    return {"document_id": "DOC-1", "text_blocks": blocks, "source_references": references, "status": "parsed",
            "pages": [], "tables": [], "key_value_pairs": [], "warnings": []}


def item(field: str, record: int, value: Any = None, block: str | None = None, unit: str | None = None) -> dict[str, Any]:
    key = f"r{record}"
    return {
        "candidate_id": f"candidate::EV-1::DOC-1::{field}::r{record}", "evidence_id": "EV-1", "document_id": "DOC-1",
        "field_name": field, "display_label": f"{field} (row {record})", "raw_value": value, "normalized_value": value,
        "unit": unit, "confidence": 0.9 if value is not None else 0.0,
        "source_reference": {"source_reference_id": f"SRC-{block}" if block else f"missing::DOC-1::{field}",
                             "parser_block_ids": [block] if block else [], "record_key": key},
        "validation_flags": [] if value is not None else ["field_not_found"],
        "record_key": key, "record_index": record,
    }


def fuel_log(n: int = 12, empty_quantity: tuple[int, ...] = (3, 7, 11)) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """``n`` rows (records 1..n on sheet rows 2..n+1); every quantity is printed, the extractor missed some."""

    rows: list[list[str]] = []
    items: list[dict[str, Any]] = []
    for record in range(1, n + 1):
        row = record + 1
        quantity = f"{100 + record}.5"
        rows.append([f"2025-01-{(record % 28) + 1:02d}", f"GEN-{record}", "Diesel", quantity, f"tank {record}"])
        items += [
            item("transaction_date", record, rows[-1][0], _cell_id(0, row)),
            item("vehicle_or_equipment_id", record, f"GEN-{record}", _cell_id(1, row)),
            item("fuel_type", record, "diesel", _cell_id(2, 2)),  # the extractor cites row 2's fuel for every record
            item("activity_quantity", record, None if record in empty_quantity else float(quantity),
                 None if record in empty_quantity else _cell_id(3, row), None if record in empty_quantity else "gal"),
            item("account_number", record),
            item("facility_name", record),
        ]
    return workbook(rows), items


def reading(rid: str, field: str, value: str, quote: str, line: str, unit: str = "") -> dict[str, str]:
    return {"record_id": rid, "field_name": field, "value": value, "unit": unit, "quote": quote, "line": line}


def alias_of(parser_output: dict[str, Any], row: int) -> str:
    lines = row_lines(parser_output)
    return next(line.alias for line in lines if line.source_reference.get("cell_or_range") == f"A{row}")


def run(claude: FakeClaude | None, parser_output: dict[str, Any], items: list[dict[str, Any]], *,
        ledger: FakeLedger | None = None, targets: list[dict[str, Any]] = TARGETS, **over: Any
        ) -> tuple[AssistOutcome, FakeLedger]:
    ledger = ledger or FakeLedger()
    service = AiExtraction(settings=settings(**over), client_factory=lambda s: claude, ledger=ledger)
    outcome = service.assist(
        parser_output=parser_output, extraction_result={"evidence_id": "EV-1", "document_id": "DOC-1",
                                                        "candidate_count": len(items), "items": items},
        extraction_targets=targets, canonical_type_id="CT-S1-MOBFUEL", file_name="fuel-log.xlsx", org_id=ORG,
        engagement_id="ENG-1")
    return outcome, ledger


def by_key(outcome: AssistOutcome) -> dict[tuple[int, str], dict[str, Any]]:
    return {(i["record_index"], i["field_name"]): i for i in outcome.result["items"]}


def quantity_reading(parser_output: dict[str, Any], record: int, value: str | None = None) -> dict[str, str]:
    value = value or f"{100 + record}.5"
    return reading(f"R{record}", "activity_quantity", value, f"Diesel | {value}", alias_of(parser_output, record + 1),
                   "gal")


# --- the twelve-row log ------------------------------------------------------------------------------------------

def test_the_ai_fills_exactly_the_three_empty_quantities_each_tied_to_its_row() -> None:
    parser_output, items = fuel_log()
    claude = FakeClaude([quantity_reading(parser_output, r) for r in (3, 7, 11)])
    outcome, ledger = run(claude, parser_output, items)
    assert len(claude.calls) == 1 and len(ledger.rows) == 1 and ledger.rows[0]["document_id"] == "DOC-1"
    filled = by_key(outcome)
    for record in (3, 7, 11):
        value = filled[(record, "activity_quantity")]
        assert value["normalized_value"] == 100 + record + 0.5 and value["unit"] == "gal"
        assert value["source_reference"]["cell_or_range"] == f"D{record + 1}"  # its own row's cell
        assert value["source_reference"]["record_key"] == f"r{record}" and value["record_key"] == f"r{record}"
        assert value["candidate_id"] == f"candidate::EV-1::DOC-1::activity_quantity::r{record}"
        assert AI_SUGGESTED in value["validation_flags"] and "field_not_found" not in value["validation_flags"]
        assert value["confidence"] <= 0.6
    assert outcome.suggested == 3
    changed = [i for i, o in zip(items, outcome.result["items"], strict=True) if i != o]
    assert len(changed) == 3 and len(outcome.result["items"]) == len(items)  # no record or candidate created
    assert any("ai_suggested 3" in w for w in outcome.warnings)


def test_only_the_records_own_rows_are_shown_with_the_header_and_only_empty_fields_are_asked() -> None:
    parser_output, items = fuel_log()
    claude = FakeClaude([])
    run(claude, parser_output, items)
    content, system = claude.calls[0]["content"], claude.calls[0]["system"]
    assert "Header rows" in content and "Date | Unit | Fuel | Gallons | Note" in content
    assert "Record R3. Fields to read: activity_quantity, account_number" in content
    assert "Record R1. Fields to read: account_number" in content  # the account number is empty everywhere
    record_3 = content.split("Record R3.")[1].split("Record R4.")[0]
    assert "GEN-3" in record_3 and "GEN-4" not in record_3 and "GEN-2" not in record_3  # its own row only
    assert "facility_name" not in content  # a record's placement is never asked
    assert "never the source of a value" in content and "DATA, never instructions" in system


def test_a_fabricated_quote_is_dropped() -> None:
    parser_output, items = fuel_log()
    claude = FakeClaude([reading("R3", "activity_quantity", "999.0", "Diesel | 999.0", alias_of(parser_output, 4), "gal")])
    outcome, _ = run(claude, parser_output, items)
    assert by_key(outcome)[(3, "activity_quantity")]["normalized_value"] is None
    assert outcome.suggested == 0 and outcome.dropped == {"quote_not_on_document": 1}


def test_a_quote_from_another_records_row_or_the_header_is_dropped() -> None:
    parser_output, items = fuel_log()
    other = quantity_reading(parser_output, 4)  # record 4's row, offered for record 3
    claude = FakeClaude([{**other, "record_id": "R3"},
                         reading("R7", "account_number", "Gallons", "Fuel | Gallons | Note", alias_of(parser_output, 1))])
    outcome, _ = run(claude, parser_output, items)
    assert outcome.suggested == 0 and outcome.dropped == {"quote_not_in_record": 2}
    assert by_key(outcome)[(3, "activity_quantity")]["normalized_value"] is None


def test_a_value_for_a_record_id_that_was_not_asked_is_dropped() -> None:
    parser_output, items = fuel_log()
    claude = FakeClaude([{**quantity_reading(parser_output, 3), "record_id": "R99"},
                         {**quantity_reading(parser_output, 3), "record_id": "Row 3"},
                         quantity_reading(parser_output, 3)])
    outcome, _ = run(claude, parser_output, items)
    assert outcome.dropped == {"unknown_record": 2} and outcome.suggested == 1


def test_an_extractor_value_is_never_overwritten() -> None:
    parser_output, items = fuel_log()
    # Record 4's quantity was read by the extractor: it is not asked, so a reading for it is dropped.
    claude = FakeClaude([quantity_reading(parser_output, 4, "104.5")])
    outcome, _ = run(claude, parser_output, items)
    assert outcome.dropped == {"field_not_asked": 1}
    kept = by_key(outcome)[(4, "activity_quantity")]
    assert kept == next(i for i in items if i["record_index"] == 4 and i["field_name"] == "activity_quantity")
    # and fill() itself never writes over a value, whatever it is handed
    found = {(4, "activity_quantity"): [object()]}
    result, filled, _ = arf.fill({"items": items}, found)
    assert filled == 0 and result["items"] == items


def test_two_different_values_for_one_record_field_are_both_dropped() -> None:
    parser_output, _ = fuel_log()
    rows = [["2025-01-02", "GEN-1", "Diesel", "101.5", "top-up 12.0 gal"]]
    parser_output = workbook(rows)
    items = [item("transaction_date", 1, "2025-01-02", _cell_id(0, 2)), item("activity_quantity", 1),
             item("transaction_date", 2, "2025-01-03", None)]
    line = alias_of(parser_output, 2)
    claude = FakeClaude([reading("R1", "activity_quantity", "101.5", "Diesel | 101.5", line, "gal"),
                         reading("R1", "activity_quantity", "12.0", "top-up 12.0 gal", line, "gal")])
    outcome, _ = run(claude, parser_output, items)
    assert outcome.suggested == 0 and outcome.dropped == {"record_conflict": 1}


# --- spend, failures --------------------------------------------------------------------------------------------

def test_the_spend_limit_stops_mid_file_with_an_honest_partial_state() -> None:
    parser_output, items = fuel_log(50, empty_quantity=tuple(range(1, 51)))
    claude = FakeClaude([quantity_reading(parser_output, r) for r in range(1, 51)])
    ledger = FakeLedger(spent=994_000)  # $1 limit: the first call fits, the second reaches it
    outcome, ledger = run(claude, parser_output, items, ledger=ledger)
    assert len(claude.calls) == 2 and len(ledger.rows) == 2
    assert outcome.suggested == 40  # records 1-40, read before the limit
    assert outcome.not_read == "records 41–50"
    assert any(w.startswith("ai_read_in_part: Read in part: records 41–50 not read because this month's limit")
               for w in outcome.warnings)
    filled = by_key(outcome)
    assert filled[(40, "activity_quantity")]["normalized_value"] is not None
    assert filled[(41, "activity_quantity")]["normalized_value"] is None


def test_no_call_when_the_limit_is_already_reached() -> None:
    parser_output, items = fuel_log()
    claude = FakeClaude([])
    outcome, ledger = run(claude, parser_output, items, ledger=FakeLedger(spent=1_000_000))
    assert claude.calls == [] and ledger.rows == []
    assert outcome.result["items"] == items and any("limit" in w for w in outcome.warnings)


def test_a_failed_call_keeps_what_was_read_and_says_what_was_not() -> None:
    parser_output, items = fuel_log(30, empty_quantity=tuple(range(1, 31)))
    claude = FakeClaude([quantity_reading(parser_output, r) for r in range(1, 31)], fail_at=1)
    outcome, ledger = run(claude, parser_output, items)
    assert outcome.suggested == 20 and outcome.not_read == "records 21–30" and len(ledger.rows) == 1
    assert any("could not be reached" in w for w in outcome.warnings)


def test_ai_off_changes_nothing() -> None:
    parser_output, items = fuel_log()
    claude = FakeClaude([quantity_reading(parser_output, 3)])
    outcome, _ = run(claude, parser_output, items, ai_suggestions_enabled=False)
    assert claude.calls == [] and outcome.result["items"] == items


# --- hostile rows ---------------------------------------------------------------------------------------------------

def test_a_5000_row_log_is_batched_with_bounded_prompts_and_memory() -> None:
    n = 5_000
    parser_output, items = fuel_log(n, empty_quantity=tuple(range(1, n + 1)))
    claude = FakeClaude([])
    tracemalloc.start()
    began = time.monotonic()
    outcome, ledger = run(claude, parser_output, items, ai_monthly_cap_usd=100.0)
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert len(claude.calls) == n // arf.MAX_RECORDS_PER_CALL and len(ledger.rows) == len(claude.calls)
    assert max(len(call["content"]) for call in claude.calls) < 10_000
    assert outcome.not_read is None and outcome.suggested == 0
    assert peak < 400 * 1024 * 1024 and time.monotonic() - began < 60


def test_unicode_rows_are_read_and_quoted() -> None:
    rows = [["2025-01-02", "GÉN-1 Ñandú", "Gazole – B7", "1 204,5", "réservoir « nord »"],
            ["2025-01-03", "GÉN-2 Ñandú", "Gazole – B7", "88,0", "日本語 メモ"]]
    parser_output = workbook(rows)
    items = [item("transaction_date", 1, "2025-01-02", _cell_id(0, 2)), item("activity_quantity", 1),
             item("transaction_date", 2, "2025-01-03", _cell_id(0, 3)), item("activity_quantity", 2)]
    claude = FakeClaude([reading("R2", "activity_quantity", "88,0", "Gazole - B7 | 88,0", alias_of(parser_output, 3), "L")])
    targets = [target("transaction_date", "Transaction date", "date"),
               target("activity_quantity", "Activity quantity", "quantity", ("gal", "L"))]
    outcome, _ = run(claude, parser_output, items, targets=targets)
    content = claude.calls[0]["content"]
    assert "日本語 メモ" in content and "Ñandú" in content
    filled = by_key(outcome)[(2, "activity_quantity")]
    assert outcome.suggested == 1 and filled["normalized_value"] == 88.0  # a decimal comma is a decimal point
    assert by_key(outcome)[(1, "activity_quantity")]["normalized_value"] is None


def test_a_row_that_is_all_empty_is_not_asked_and_breaks_nothing() -> None:
    parser_output, items = fuel_log(3, empty_quantity=(2,))
    # Record 4: a blank sheet row (no cells), every field empty: it has no rows of its own.
    items += [item("transaction_date", 4), item("activity_quantity", 4), item("account_number", 4)]
    claude = FakeClaude([quantity_reading(parser_output, 2)])
    outcome, _ = run(claude, parser_output, items)
    assert "Record R4" not in claude.calls[0]["content"]
    assert outcome.suggested == 1
    assert "ai_extraction: records not asked by Sustentra's AI: 1 with no rows of their own." in outcome.warnings
    assert plain_note(outcome.warnings[0]) == outcome.warnings[0]  # shown as it is, no code to map


def test_no_call_when_every_printed_cell_of_each_row_is_already_read() -> None:
    rows = [["2025-01-02", "GEN-1", "Diesel", "101.5", ""], ["2025-01-03", "GEN-2", "Diesel", "88.0", ""]]
    parser_output = workbook(rows)
    items = []
    for record in (1, 2):
        row = record + 1
        items += [item("transaction_date", record, rows[record - 1][0], _cell_id(0, row)),
                  item("vehicle_or_equipment_id", record, f"GEN-{record}", _cell_id(1, row)),
                  item("fuel_type", record, "diesel", _cell_id(2, row)),
                  item("activity_quantity", record, 1.0, _cell_id(3, row), "gal"),
                  item("account_number", record)]
    claude = FakeClaude([])
    outcome, ledger = run(claude, parser_output, items)
    assert claude.calls == [] and ledger.rows == [] and outcome.result["items"] == items and outcome.warnings == []


# --- own rows -------------------------------------------------------------------------------------------------------

def test_a_line_cited_by_several_records_for_one_field_is_a_shared_header_line() -> None:
    parser_output, items = fuel_log(3)
    lines = row_lines(parser_output)
    rows = arf.record_rows(lines, items)
    # Row 2 is record 1's own row (its date and id), even though every record cites it for the fuel type.
    assert [lines[p].source_reference["cell_or_range"] for p in rows.own[1]] == ["A2"]
    assert [lines[p].source_reference["cell_or_range"] for p in rows.own[3]] == ["A4"]
    # The sheet's first row is the header; row 2 is an own row, so it is not shown as one.
    assert [lines[p].source_reference["cell_or_range"] for p in rows.header] == ["A1"]


def test_a_line_that_would_be_two_records_own_row_belongs_to_neither() -> None:
    parser_output, _ = fuel_log(2)
    items = [item("transaction_date", 1, "x", _cell_id(0, 2)), item("activity_quantity", 2, 1.0, _cell_id(3, 2)),
             item("activity_quantity", 1), item("transaction_date", 2)]
    rows = arf.record_rows(row_lines(parser_output), items)
    assert rows.own == {}


BUNDLE = [
    (1, "Harbor Gas Co - Statement 1"),        # L1 record 1
    (1, "Account Number 88-1200"),             # L2
    (1, "Service from 01/01/2025"),            # L3 record 1
    (2, "Harbor Gas Co - Statement 2"),        # L4 record 2
    (2, "Account Number 88-1200"),             # L5
    (2, "Service from 02/01/2025"),            # L6 record 2
]


def test_a_bill_in_a_bundle_takes_the_lines_between_its_own_on_its_page() -> None:
    parser_output = parsed(BUNDLE)
    blocks = [b["block_id"] for b in parser_output["text_blocks"]]
    items = [item("supplier_name", 1, "Harbor Gas Co", blocks[0]), item("service_period_start", 1, "2025-01-01", blocks[2]),
             item("account_number", 1),
             item("supplier_name", 2, "Harbor Gas Co", blocks[3]), item("service_period_start", 2, "2025-02-01", blocks[5]),
             item("account_number", 2, "88-1200", blocks[4])]
    claude = FakeClaude([reading("R1", "account_number", "88-1200", "Account Number 88-1200", "L2"),
                         reading("R1", "account_number", "88-1200", "Account Number 88-1200", "L5")])
    targets = [target("supplier_name", "Supplier"), target("service_period_start", "Start", "date"),
               target("account_number", "Account number")]
    outcome, _ = run(claude, parser_output, items, targets=targets)
    filled = by_key(outcome)[(1, "account_number")]
    assert filled["normalized_value"] == "88-1200" and filled["source_reference"]["page_number"] == 1
    assert outcome.suggested == 1 and outcome.dropped == {"quote_not_in_record": 1}
    assert by_key(outcome)[(2, "account_number")] == items[-1]


def test_a_repeated_header_or_a_line_placed_on_another_record_is_not_this_records_row() -> None:
    lines = [(1, "Statement 1 Harbor Gas"),      # L1 record 1
             (1, "Date Gallons Price"),          # L2 the column header, cited by both records
             (1, "Fee line 7.00 billed to 2"),   # L3 placed on record 2 by the extractor
             (1, "Delivered 2025-01-02 410.0"),  # L4 record 1
             (2, "Statement 2 Harbor Gas"),      # L5 record 2
             (2, "Date Gallons Price"),          # L6 the header repeated on page 2
             (2, "Delivered 2025-02-02 300.0")]  # L7 record 2
    parser_output = parsed(lines)
    blocks = [b["block_id"] for b in parser_output["text_blocks"]]
    items = [item("supplier_name", 1, "Harbor Gas", blocks[0]), item("activity_unit", 1, "gal", blocks[1]),
             item("transaction_date", 1, "2025-01-02", blocks[3]), item("activity_quantity", 1),
             item("supplier_name", 2, "Harbor Gas", blocks[4]), item("activity_unit", 2, "gal", blocks[1]),
             item("account_number", 2, "7.00", blocks[2]), item("transaction_date", 2, "2025-02-02", blocks[6])]
    document = row_lines(parser_output)
    rows = arf.record_rows(document, items)
    lines_of = {r: [document[p].alias for p in ps] for r, ps in rows.own.items()}
    assert lines_of[1] == ["L1", "L4"]  # not L2 (the header) nor L3 (placed on record 2)
    assert "L6" not in lines_of[2] and "L7" in lines_of[2]


# --- the stored number is the printed one -------------------------------------------------------------------------

QUANTITY_TARGETS = [target("transaction_date", "Transaction date", "date"),
                    target("activity_quantity", "Activity quantity", "quantity", ("gal", "L"))]


def _one_row_each(printed: list[str]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    rows = [[f"2025-01-0{i + 1}", f"GEN-{i + 1}", "Diesel", value, ""] for i, value in enumerate(printed)]
    items: list[dict[str, Any]] = []
    for record in range(1, len(printed) + 1):
        items += [item("transaction_date", record, rows[record - 1][0], _cell_id(0, record + 1)),
                  item("activity_quantity", record)]
    return workbook(rows), items


def test_the_number_stored_is_the_printed_token_never_the_ais_string() -> None:
    def answer(printed: list[str], said: list[str]) -> AssistOutcome:
        parser_output, items = _one_row_each(printed)
        claude = FakeClaude([reading(f"R{r}", "activity_quantity", said[r - 1], f"Diesel | {printed[r - 1]}",
                                     alias_of(parser_output, r + 1), "gal") for r in range(1, len(said) + 1)])
        return run(claude, parser_output, items, targets=QUANTITY_TARGETS)[0]

    # A US-style log: printed 880 / AI 88,0 and printed 120 / AI 1,20 are dropped; printed 1,204 / AI 1204 is
    # stored as printed.
    us = answer(["880", "120", "1,204"], ["88,0", "1,20", "1204"])
    filled = by_key(us)
    assert filled[(1, "activity_quantity")]["normalized_value"] is None
    assert filled[(2, "activity_quantity")]["normalized_value"] is None
    assert us.dropped == {"number_not_as_printed": 1, "invalid_value": 1}  # "1,20" is not one readable number
    assert filled[(3, "activity_quantity")]["normalized_value"] == 1204
    assert filled[(3, "activity_quantity")]["raw_value"] == "1,204"
    # A decimal-comma log: printed 88,0 / AI 880 is dropped.
    comma = answer(["88,0", "5,0"], ["880"])
    assert by_key(comma)[(1, "activity_quantity")]["normalized_value"] is None
    assert comma.dropped == {"number_not_as_printed": 1}


def test_a_decimal_comma_document_reads_its_ambiguous_commas_as_decimals() -> None:
    parser_output, items = _one_row_each(["1.234,5", "12,34"])
    claude = FakeClaude([reading("R2", "activity_quantity", "12,34", "Diesel | 12,34", alias_of(parser_output, 3), "L")])
    outcome, _ = run(claude, parser_output, items, targets=QUANTITY_TARGETS)
    assert by_key(outcome)[(2, "activity_quantity")]["normalized_value"] == 12.34


def test_an_ambiguous_comma_is_not_read_when_the_document_does_not_settle_it() -> None:
    parser_output, items = _one_row_each(["0,500", "1234,567"])
    claude = FakeClaude([reading("R1", "activity_quantity", "0,500", "Diesel | 0,500", alias_of(parser_output, 2), "gal"),
                         reading("R2", "activity_quantity", "1234,567", "Diesel | 1234,567",
                                 alias_of(parser_output, 3), "gal")])
    outcome, _ = run(claude, parser_output, items, targets=QUANTITY_TARGETS)
    assert outcome.suggested == 0 and outcome.dropped == {"invalid_value": 2}
