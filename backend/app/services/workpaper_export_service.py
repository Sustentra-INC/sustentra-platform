"""The engagement's workpaper as an Excel file: what was reported, what was recalculated
and how, the evidence behind it, what the reviewer decided, and the open work.

Every number comes from the same recalculation the screens show; nothing is computed
here. Sheets: Summary, Final outputs, Roll-up, Categories (the emissions roll-up, when the
recalculation has one), Data points, Warnings (the data quality checks), Method (the Methodology
review answers), Working, Sources (from each calculation line to its documents), Evidence, Reviewed
values, Requests, Findings, Left out.

Text from documents, file names and people is written as text, never as a formula, and cleaned of the
characters a spreadsheet cannot hold. Every sheet is protected without a password, so nothing is changed
by accident.
"""

from __future__ import annotations

import hashlib
import io
import math
import re
from collections.abc import Callable, Mapping
from datetime import UTC, date, datetime
from typing import Any

from openpyxl import Workbook
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from backend.app.services import methodology_review
from backend.app.services.calculation_lines import CATEGORY_LABEL

_HEADER_FILL = PatternFill("solid", fgColor="E8EAF4")
_STATUS = {
    "within_tolerance": "Held",
    "exceeds_tolerance": "Exception",
    "not_reported": "Could not check (reported value not entered)",
    "no_evidence": "Could not check (no reviewed evidence)",
    "not_recalculated": "Out of scope (not recalculated yet)",
    "not_in_scope": "Not in scope (set in Setup)",
    "incomplete": "Not concluded (the total is missing categories)",
    "needs_unit": "Could not check (reported unit not confirmed: t or t CO2e)",
}
_REASON = {
    "lower_bound": "Already above the reported value, and the missing categories can only add",
    "reported_zero": "Reported as 0",
    "partial_total": "Missing categories could still change the result",
    "unit_unconfirmed": "Set whether the company reported tonnes of gas or t CO2e",
    "not_built": "Category not built yet",
    "no_evidence": "No reviewed evidence",
    "awaiting_inputs": "Evidence waiting on reviewer inputs",
    "set_out_of_scope": "Set out of scope in Setup",
}
_MISSING = {
    "not_built": "not built yet",
    "no_evidence": "no evidence",
    "awaiting_inputs": "waiting on inputs",
    "inputs_open": "questions open",
    "vehicle_groups_missing": "no vehicle groups for CH4/N2O",
    "gas_split_unknown": "blend's gas split unknown",
}
_SOURCE_STATUS = {
    "calculated": "Calculated",
    "partial": "Calculated, questions open",
    "awaiting_inputs": "Waiting on inputs",
    "confirmed_absent": "Confirmed absent (0)",
    "no_evidence": "No evidence",
    "not_built": "Not built yet",
}
_NODE_STATUS = {"complete": "Complete", "partial": "Partial", "not_available": "Not available"}
_LEFT_OUT = {
    "outside_reporting_period": "Outside the reporting period",
    "withdrawn": "Withdrawn by the reviewer",
    "duplicate": "Marked as a duplicate",
    "superseded": "Superseded by a newer document",
    "not_on_a_calculation_line": "Not on a calculation line",
    "montreal_protocol_gas": "A CFC or HCFC (Montreal Protocol gas), reported outside Scope 1",
}


MAX_CELL_CHARS = 32_767  # Excel's limit for the text in one cell
_CUT_NOTE = " … (cut: too long for one Excel cell)"
_FORMULA_STARTS = ("=", "+", "-", "@", "\t", "\r")

_TONNES = "#,##0.000"
_TINY = "0.00E+00"  # a mass below half a kilogram shown as 3 decimals would read 0.000
_PERCENT = '0.0"%"'  # a number already in percent (3.4 reads 3.4%)
_FRACTION = "0.0%"  # a share stored as a fraction (0.5 reads 50.0%)
_TONNE_UNIT = re.compile(r"^(t|tonnes?|metric tons?)( |$)", re.IGNORECASE)

# A format for one number: given the value and the row it is in, its number format (None: leave as is).
Format = Callable[[Any, list[Any]], str | None]


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _tonnes(value: Any, _row: list[Any] | None = None) -> str:
    """Tonnes to 3 decimals with thousands separators; a non-zero amount too small for that shows as 0.00E+00
    so it never reads as 0.000. Only the display changes: the cell keeps the full value."""

    if _is_number(value) and value != 0 and abs(value) < 0.0005:
        return _TINY
    return _TONNES


def _tonnes_if_unit(unit_column: int) -> Format:
    """Tonnes format when the row's unit (at ``unit_column``) is a tonne unit, else the cell is left as it is."""

    return lambda value, row: _tonnes(value) if _TONNE_UNIT.match(str(row[unit_column] or "").strip()) else None


def _percent(_value: Any, _row: list[Any]) -> str:
    return _PERCENT


def _fraction(_value: Any, _row: list[Any]) -> str:
    return _FRACTION


def _always_tonnes(value: Any, _row: list[Any]) -> str:
    return _tonnes(value)


def _sheet(book: Workbook, title: str, header: list[str], rows: list[list[Any]], widths: list[int], *,
           note: str | None = None, formats: Mapping[str, Format] | None = None) -> None:
    """One sheet: an optional note line, the header, then the rows. ``formats`` gives number formats by column name."""

    sheet = book.create_sheet(title)
    if note:
        sheet.append([_cell(note)])
        sheet["A1"].font = Font(italic=True)
    sheet.append(list(header))
    first = 3 if note else 2
    for cell in sheet[first - 1]:
        cell.font = Font(bold=True)
        cell.fill = _HEADER_FILL
    by_column = {index: formats[name] for index, name in enumerate(header) if formats and name in formats}
    for row in rows:
        clean = [_cell(v) for v in row]
        sheet.append(clean)
        for cell in sheet[sheet.max_row]:
            _pin_as_text(cell)
            rule = by_column.get(cell.column - 1)
            if rule is not None and _is_number(cell.value):
                cell.number_format = rule(cell.value, clean) or cell.number_format
    for index, width in enumerate(widths, start=1):
        sheet.column_dimensions[get_column_letter(index)].width = width
    for row_cells in sheet.iter_rows(min_row=first):
        for cell in row_cells:
            cell.alignment = Alignment(vertical="top", wrap_text=isinstance(cell.value, str) and len(cell.value) > 40)
    sheet.freeze_panes = f"A{first}"


def _cell(value: Any) -> Any:
    """A value fit for a cell: numbers as they are, anything else as text without the characters a spreadsheet
    refuses (control characters) and cut to Excel's cell limit. (Text that starts like a formula is pinned as text
    by ``_pin_as_text`` as the cell is written.)"""

    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return None if isinstance(value, float) and not math.isfinite(value) else value
    text = ILLEGAL_CHARACTERS_RE.sub("", str(value) if not isinstance(value, str) else value)
    if len(text) > MAX_CELL_CHARS:
        text = text[:MAX_CELL_CHARS - len(_CUT_NOTE)] + _CUT_NOTE
    return text


def _pin_as_text(cell: Any) -> None:
    """Text from a document, a file name or a person can start with = + - @ or a tab or carriage return, which a
    spreadsheet would run as a formula. Such a cell is kept as text (and marked so Excel shows it as typed)."""

    if isinstance(cell.value, str) and cell.value.startswith(_FORMULA_STARTS):
        cell.data_type = "s"
        cell.quotePrefix = True


def _when(value: Any) -> str:
    return str(value or "")[:19].replace("T", " ")


_MONTH_ABBR = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
_ISO_DAY = re.compile(r"^(\d{4})-(\d{2})-(\d{2})")


def _day(value: Any) -> str:
    """One date as a person reads it, "Oct 8, 2026" (en-US); anything else as it was given."""
    if isinstance(value, date):
        return f"{_MONTH_ABBR[value.month - 1]} {value.day}, {value.year}"
    text = str(value)
    match = _ISO_DAY.match(text)
    if not match:
        return text
    year, month, day = (int(part) for part in match.groups())
    if not 1 <= month <= 12 or not 1 <= day <= 31:
        return text
    return f"{_MONTH_ABBR[month - 1]} {day}, {year}"


def format_reporting_period(start: Any, end: Any) -> str:
    """The reporting period in the words the Output screen uses (frontend formatReportingPeriod),
    so the screen and its download agree: "Oct 8, 2026 – Dec 31, 2026", or the missing date
    named in its place while the engagement is still being set up."""

    if start and end:
        return f"{_day(start)} – {_day(end)}"
    if start:
        return f"{_day(start)} – end date not set"
    if end:
        return f"start date not set – {_day(end)}"
    return "Reporting period not set"


def _missing(items: list[dict[str, Any]] | None, labels: dict[str, str]) -> str:
    return "; ".join(f"{labels.get(m.get('source', ''), m.get('source'))}: "
                     f"{_MISSING.get(str(m.get('reason')), m.get('reason'))}" for m in items or [])


def _rollup_sheets(book: Workbook, rollup: dict[str, Any]) -> None:
    """Final outputs, the Steps 1a/1b/2 nodes, and each category's state."""

    categories = rollup.get("categories") or {}
    labels = {key: str(c.get("label") or key) for key, c in categories.items()}
    _sheet(
        book, "Final outputs",
        ["Workbook row", "Data point", "Requirement", "Unit", "Reported", "Recalculated", "Difference",
         "Difference %", "Within threshold", "Outcome", "Why", "Completeness", "Missing", "Counted as 0"],
        [[o.get("workbook_row"), o.get("label"), o.get("requirement"), o.get("unit"), o.get("reported"),
          o.get("recalculated"), o.get("difference"), o.get("difference_pct"),
          {True: "yes", False: "no"}.get(o.get("within_threshold"), ""),
          _STATUS.get(str(o.get("status")), o.get("status")), _REASON.get(str(o.get("reason")), o.get("reason")),
          _NODE_STATUS.get(str(o.get("completeness")), o.get("completeness")), _missing(o.get("missing"), labels),
          _missing(o.get("counted_as_zero"), labels)]
         for o in rollup.get("final_outputs") or []],
        [12, 52, 12, 10, 14, 14, 14, 13, 10, 40, 44, 14, 60, 60],
        formats={"Reported": _tonnes_if_unit(3), "Recalculated": _tonnes_if_unit(3), "Difference": _tonnes_if_unit(3),
                 "Difference %": _percent},
    )
    nodes = rollup.get("nodes") or {}
    steps = {step.get("key"): step.get("label") for step in rollup.get("steps") or []}
    order = [key for step in rollup.get("steps") or [] for key in step.get("node_keys") or []]
    _sheet(
        book, "Roll-up",
        ["Step", "Line", "t CO2e", "t of gas", "Status", "Adds up", "Missing", "Notes", "Counted as 0"],
        [[steps.get(nodes[key].get("step"), nodes[key].get("step")), nodes[key].get("label"), nodes[key].get("co2e_t"),
          nodes[key].get("mass_t"), _NODE_STATUS.get(str(nodes[key].get("status")), nodes[key].get("status")),
          nodes[key].get("formula"), _missing(nodes[key].get("missing"), labels), ", ".join(nodes[key].get("flags") or []),
          _missing(nodes[key].get("counted_as_zero"), labels)]
         for key in order if key in nodes],
        [40, 52, 14, 12, 14, 52, 60, 40, 60],
        formats={"t CO2e": _always_tonnes, "t of gas": _always_tonnes},
    )
    _sheet(
        book, "Categories",
        ["Category", "Scope", "Workbook row", "Status", "Open questions", "Reviewer's reason it is absent", "Notes"],
        [[c.get("label"), c.get("scope"), c.get("workbook_row"), _SOURCE_STATUS.get(str(c.get("status")), c.get("status")),
          c.get("open_items"), c.get("absent_reason"), ", ".join(c.get("flags") or [])]
         for c in categories.values()],
        [48, 10, 12, 26, 14, 44, 40],
    )

_CHECK_NAMES = {
    "missing_month": "Missing month",
    "incomplete_year": "Part of the period not covered",
    "duplicate_counting_risk": "Possible double counting",
    "duplicate_period_amount_with_different_invoice_id": "Same dates and amounts on different accounts",
    "same_document_reuploaded_with_different_file_name": "Same document uploaded twice",
    "duplicate_statement_in_same_file": "Statement printed twice in one file",
    "revised_bill_replaces_earlier": "Revised bill",
    "overlap_same_source_different_document_id": "Overlapping bills",
    "overlapping_period": "Overlapping bills",
    "cross_year_without_allocation_support": "Bill runs across the reporting period",
    "date_missing": "No service period on the bill",
}
_SEVERITY = {"warning": "Warning", "review": "Needs review", "info": "For information"}


def _range(text: Any) -> str:
    start, _, end = str(text).partition(" to ")
    return f"{_day(start)} – {_day(end)}" if end else _day(start)


def _finding_dates(detail: Any) -> str:
    if not isinstance(detail, Mapping):
        return ""
    if detail.get("overlap_start") and detail.get("overlap_end"):
        return f"{_day(detail['overlap_start'])} – {_day(detail['overlap_end'])}"
    for key in ("gaps", "missing_months"):
        found = detail.get(key)
        if isinstance(found, list) and found:
            return "; ".join(_range(g) for g in found)
    return ""


def _warning_rows(recalculation: Mapping[str, Any]) -> list[list[Any]]:
    """One row per data quality finding, in the words the API already gives. No findings: one row saying so."""

    rows: list[list[Any]] = []
    for finding in recalculation.get("quality_checks") or []:
        if not isinstance(finding, Mapping) or not finding.get("message"):
            continue
        trigger = str(finding.get("trigger") or "")
        records = finding.get("records")
        rows.append([
            _CHECK_NAMES.get(trigger) or trigger.replace("_", " ").capitalize() or "Check",
            _SEVERITY.get(str(finding.get("severity")), ""), finding.get("message"), finding.get("facility"),
            "; ".join(str(r) for r in records) if isinstance(records, list) else None,
            _finding_dates(finding.get("detail")) or None,
        ])
    return rows or [[None, None, "No warnings were found.", None, None, None]]


def _entity_answer(value: Mapping[str, Any]) -> str:
    value = methodology_review.upgrade_entity_value(dict(value))  # an entity saved before "Included" had its own key
    parts = [str(value["name"])]
    if value.get("facilities"):
        parts.append("Facilities: " + ", ".join(str(f) for f in value["facilities"]))
    for key, label in (("equity_share_pct", "Equity share"), ("financial_control", "Financial control")):
        if value.get(key) is not None:
            parts.append(f"{label}: {value[key]}%")
    for key, label in (("included", "Included"), ("control_quoted", "Operational control (as quoted)")):
        if value.get(key) is not None:
            parts.append(f"{label}: {value[key]}")
    return "; ".join(parts)


def _method_answer(field: Mapping[str, Any], value: Any) -> str:
    """A methodology answer in words. Raises when the value is not the shape its field takes (the row is skipped)."""

    kind = field["kind"]
    if kind in ("text", "enum"):
        if not isinstance(value, str):
            raise TypeError(kind)
        return value
    if kind == "date_range":
        text = f"{_day(value['start'])} – {_day(value['end'])}"
        return f"{text} ({value['basis']})" if value.get("basis") else text
    if kind == "multiselect":
        return "; ".join(f"{e['option']} ({e['wording']})" if e.get("wording") else str(e["option"]) for e in value)
    if kind == "entry_list":
        return "; ".join(f"{e['source_type']}: {e['method']}" for e in value)
    if kind == "gwp":
        text = f"{methodology_review.GWP_SET_LABELS.get(value['set'], value['set'])}, {value['horizon']}"
        return text + (f"; applies to: {value['applies_to']}" if value.get("applies_to") else "")
    if kind == "factor":
        return f"{value['database']}, {value['edition']}" if value.get("edition") else str(value["database"])
    if kind == "entity":
        return _entity_answer(value)
    raise TypeError(kind)


_SUGGESTED_BY = {"ai": "Sustentra's AI", "rules": "Sustentra's rules"}


def _where_read(suggestion: Mapping[str, Any]) -> tuple[str | None, str | None, Any]:
    """The quote, the file and the page a suggestion was read from (one value, or the entries of a list)."""

    evidence = [e for e in suggestion.get("evidence") or [] if isinstance(e, Mapping)]
    quote = suggestion.get("quote") if isinstance(suggestion.get("quote"), str) else None
    if not quote and evidence:
        quote = "\n".join(f"{e['label']}: {e['quote']}" if e.get("label") else str(e["quote"])
                          for e in evidence if e.get("quote"))
    files = [suggestion.get("file_name"), *(e.get("file_name") for e in evidence)]
    document = "; ".join(dict.fromkeys(str(f) for f in files if f)) or None
    references = [suggestion.get("source_reference"), *(e.get("source_reference") for e in evidence)]
    pages = [r["page_number"] for r in references
             if isinstance(r, Mapping) and isinstance(r.get("page_number"), int) and not isinstance(r["page_number"], bool)]
    unique = list(dict.fromkeys(pages))
    page: Any = unique[0] if len(unique) == 1 else ", ".join(str(p) for p in unique) or None
    return quote or None, document, page


def _method_row(item: Mapping[str, Any]) -> tuple[int, list[Any]] | None:
    field_id = str(item.get("item_key") or "")
    record = item.get("payload")
    if field_id == methodology_review.META_KEY or not isinstance(record, Mapping) or record.get("removed"):
        return None
    field = methodology_review.catalog_field(field_id) or methodology_review.row_field(field_id)
    if field is None:
        return None
    decision = record.get("decision") if isinstance(record.get("decision"), Mapping) else None
    suggestion = record.get("suggestion") if isinstance(record.get("suggestion"), Mapping) else None
    status = str((decision or {}).get("status") or methodology_review.PENDING)
    if status not in methodology_review.STATUSES:
        return None
    if status in (methodology_review.ACCEPTED, methodology_review.EDITED):
        answer: str | None = _method_answer(field, (decision or {}).get("value"))
    elif status == methodology_review.REJECTED:
        answer = None  # a rejected answer has no value
    elif suggestion is not None and suggestion.get("value") is not None:
        who = _SUGGESTED_BY.get(str(suggestion.get("origin")))
        answer = (f"Suggested by {who}, not decided: " if who else "Suggested, not decided: ") + _method_answer(
            field, suggestion["value"])
    else:
        answer = "No answer yet"
    quote, document, page = _where_read(suggestion) if suggestion is not None else (None, None, None)
    by: Any = (decision or {}).get("by") if status != methodology_review.PENDING else None
    name = (by.get("name") or by.get("login")) if isinstance(by, Mapping) else by
    at = _when((decision or {}).get("at")) if status != methodology_review.PENDING else None
    order = {f["field_id"]: i for i, f in enumerate(methodology_review.CATALOG)}
    group_order = {key: i for i, (key, _label) in enumerate(methodology_review.GROUPS)}
    rank = group_order.get(field["group"], len(group_order)) * 100_000 + order.get(field_id, 50_000)
    reason = (decision or {}).get("reason")
    return rank, [field["group_label"], field["label"], answer, status.capitalize(),
                  reason if isinstance(reason, str) and reason.strip() else None, quote, document, page,
                  name or None, at or None]


def _method_rows(items: list[dict[str, Any]]) -> list[list[Any]]:
    """The Methodology review answers, in the page's order. Removed rows, the page's own state row and anything
    that is not a record of a known field are left out: an unexpected payload never fails the download."""

    rows: list[tuple[int, int, list[Any]]] = []
    for position, item in enumerate(items):
        if not isinstance(item, Mapping) or item.get("kind") != methodology_review.KIND:
            continue
        try:
            built = _method_row(item)
        except (KeyError, TypeError, AttributeError, ValueError):
            continue
        if built is not None:
            rows.append((built[0], position, built[1]))  # rows added by the reviewer keep their saved order
    return [row for _rank, _position, row in sorted(rows, key=lambda r: (r[0], r[1]))]


_NO_FILE = "File name not recorded"
_NOT_ON_A_LINE = "Not on a line"
_RECORD_NUMBER = re.compile(r"^(?P<file>.*?)(?: \(record (?P<n>\d+)\))?$", re.DOTALL)
# The category result a calculation line's records are also counted in (its details list the same documents).
_LINE_FAMILY = {"stationary": "stationary_combustion", "biogenic": "stationary_combustion",
                "mobile": "mobile_combustion", "purchased_energy": "purchased_electricity_location_based",
                "fugitive": "fugitive_refrigerants"}
_DETAIL_NAMES = {"stationary_combustion": CATEGORY_LABEL["stationary"], "mobile_combustion": CATEGORY_LABEL["mobile"],
                 "fugitive_refrigerants": CATEGORY_LABEL["fugitive"],
                 "purchased_electricity_location_based": CATEGORY_LABEL["purchased_energy"]}


def _plain(name: Any) -> str:
    return str(name or "").replace("_", " ").strip().capitalize()


def _split_record(label: Any) -> tuple[str | None, str | None]:
    """A record label ("bill.pdf (record 3)") as its file name and "Record 3" (None when it has no number)."""

    match = _RECORD_NUMBER.match(str(label or ""))
    if not match or not match.group("file"):
        return None, None
    return match.group("file"), f"Record {match.group('n')}" if match.group("n") else None


def _amount(value: Any) -> tuple[Any, ...]:
    return (round(value, 9) if _is_number(value) else value,)


def _detail_entries(recalculation: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Every document each category counted (its details, by fuel or facility), in order. The market-based
    electricity and thermal results are left out: they are built from the same bills as the location-based ones."""

    found: list[dict[str, Any]] = []
    for key, category in (recalculation.get("categories") or {}).items():
        inputs = ((category or {}).get("details") or {}).get("inputs") if isinstance(category, Mapping) else None
        if not isinstance(inputs, list) or str(key).endswith("_market_based"):
            continue
        name = _DETAIL_NAMES.get(str(key)) or _plain(str(key).removesuffix("_location_based"))
        for entry in inputs:
            documents = entry.get("documents") if isinstance(entry, Mapping) else None
            for doc in documents if isinstance(documents, list) else []:
                if isinstance(doc, Mapping):
                    line = str(entry.get("fuel") or "")
                    if doc.get("service_type"):
                        line = f"{line} ({doc['service_type']})" if line else str(doc["service_type"])
                    found.append({"key": str(key), "category": name, "line": line or None, "doc": doc, "used": False})
    return found


def _page_lookup(register: Mapping[str, Any]) -> dict[tuple[str, str], Any]:
    """The page of a reviewed value by its document and its own value id, only where exactly one page is on record
    (a value the register read twice with different pages, or with none, is not given)."""

    pages: dict[tuple[str, str], set[Any]] = {}
    for value in register.get("values") or []:
        if isinstance(value, Mapping) and value.get("document_id") and value.get("candidate_id"):
            pages.setdefault((str(value["document_id"]), str(value["candidate_id"])), set()).add(value.get("page"))
    return {key: next(iter(found)) for key, found in pages.items() if len(found) == 1 and None not in found}


def _source_rows(recalculation: Mapping[str, Any], register: Mapping[str, Any]) -> list[list[Any]]:
    """From each calculation line to its documents, and from each category to the documents it counted.

    The line rows come from the calculation lines (and the records counted but on no line). Each one uses up the
    document the category lists for it, which also gives its record number. Whatever a category counted that no
    line row accounts for (categories without calculation lines, such as refrigerants and purchased steam) is listed
    after them, so every counted document appears once. Nothing is recomputed."""

    entries = _detail_entries(recalculation)
    pool: dict[tuple[Any, ...], list[dict[str, Any]]] = {}
    for entry in entries:
        doc = entry["doc"]
        pool.setdefault((entry["key"], doc.get("document_id"), *_amount(doc.get("quantity")), doc.get("unit")),
                        []).append(entry)
    pages = _page_lookup(register)
    lines = [ln for ln in recalculation.get("calculation_lines") or [] if isinstance(ln, Mapping)]
    unplaced = [ln for ln in recalculation.get("calculation_unplaced") or [] if isinstance(ln, Mapping)]
    families: set[str] = set()
    rows: list[list[Any]] = []
    for line in [*lines, *unplaced]:
        counts_toward = _LINE_FAMILY.get(str(line.get("counts_toward"))) or _LINE_FAMILY.get(str(line.get("category")))
        if counts_toward:
            families.add(counts_toward)
        category = CATEGORY_LABEL.get(str(line.get("category"))) or CATEGORY_LABEL.get(str(line.get("counts_toward"))
                                                                                       ) or _plain(line.get("category"))
        level2, label = line.get("level2"), line.get("label")
        name = _NOT_ON_A_LINE if line.get("key") is None and line in unplaced else (
            f"{level2}, {label}" if level2 and label and level2 != label else str(level2 or label or ""))
        step1 = line.get("step1")
        smb = line.get("smb") if isinstance(line.get("smb"), Mapping) else None
        # a refrigerant line still waiting for a GWP counts nothing: its records show their quantity, marked so
        waiting = (f"not counted: {smb.get('awaiting') or 'a GWP'} awaiting review" if smb is not None
                   and smb.get("gwp") is None and not smb.get("decided_gwp") and not smb.get("mixed") else None)
        for row in (step1.get("rows") if isinstance(step1, Mapping) else None) or []:
            if not isinstance(row, Mapping):
                continue
            counted = row.get("counted_quantity", row.get("quantity"))
            matches = pool.get((counts_toward, row.get("document_id"), *_amount(counted), row.get("unit")), [])
            free = next((m for m in matches if not m["used"]), None)
            if free is not None:
                free["used"] = True
            labels = {str(m["doc"].get("record")) for m in matches}
            file_name, record = _split_record(next(iter(labels)) if len(labels) == 1 else None)
            rows.append([category, name or None, row.get("file_name") or file_name or _NO_FILE, record,
                         row.get("quantity"), row.get("unit"), row.get("share_in_period"), waiting or counted,
                         pages.get((str(row.get("document_id")), str(row.get("candidate_id"))))])
    for entry in entries:
        if entry["used"]:
            continue
        doc = entry["doc"]
        file_name, record = _split_record(doc.get("record"))
        rows.append([entry["category"], _NOT_ON_A_LINE if entry["key"] in families else entry["line"],
                     file_name or _NO_FILE, record, None, doc.get("unit"), doc.get("share_in_period"),
                     doc.get("quantity"), None])
    return rows


def content_fingerprint(book: Workbook, exported_by: str) -> str:
    """A SHA-256 of what the workbook says: every sheet's name and every cell's value, in order, except the
    time the workbook was prepared (the Summary's "Exported" row keeps only who prepared it). An .xlsx file
    carries the time in its own properties and in its zip entries, so its bytes differ on every build; this
    does not, so two builds of the same figures by the same person have the same fingerprint."""

    digest = hashlib.sha256()
    for sheet in book.worksheets:
        digest.update(f"\x1esheet:{sheet.title}\n".encode())
        for row in sheet.iter_rows(values_only=True):
            if sheet.title == "Summary" and row and row[0] == "Exported":
                row = ("Exported", exported_by)
            digest.update(("\x1f".join("" if v is None else f"{type(v).__name__}:{v}" for v in row) + "\n").encode())
    return digest.hexdigest()


def build_workbook(
    *,
    engagement: dict[str, Any],
    recalculation: dict[str, Any],
    register: dict[str, list[dict[str, Any]]],
    items: list[dict[str, Any]],
    exported_by: str,
) -> bytes:
    return build_workbook_with_fingerprint(
        engagement=engagement, recalculation=recalculation, register=register, items=items, exported_by=exported_by
    )[0]


def build_workbook_with_fingerprint(
    *,
    engagement: dict[str, Any],
    recalculation: dict[str, Any],
    register: dict[str, list[dict[str, Any]]],
    items: list[dict[str, Any]],
    exported_by: str,
) -> tuple[bytes, str]:
    """The workbook's bytes and its ``content_fingerprint`` (what it says, without when it was prepared)."""

    book = Workbook()
    book.remove(book.active)
    settings = engagement.get("settings") or {}
    totals = recalculation.get("scope_totals") or {}

    rollup = recalculation.get("rollup") or {}

    def total(name: str) -> float | None:
        part = totals.get(name)
        return part["total_co2e"] if part else None

    def node(name: str) -> Any:
        value = (rollup.get("nodes") or {}).get(name) or {}
        return value.get("co2e_t") if value.get("status") == "complete" else (
            f"{value.get('co2e_t'):.4f} (partial)" if value.get("co2e_t") is not None else "Not available")

    summary: list[list[Any]] = [
        ["Engagement", engagement.get("name")],
        ["Company", engagement.get("client_name")],
        ["Reporting period", format_reporting_period(engagement.get("reporting_period_start"),
                                                     engagement.get("reporting_period_end"))],
        ["Regulation", settings.get("regulation")],
        ["Assurance level", settings.get("assuranceLevel")],
        ["Assurance standard", settings.get("assuranceStandard")],
        ["Boundary approach", settings.get("boundaryApproach")],
        ["Materiality tolerance (%)", recalculation.get("tolerance_pct")],
        ["GWP basis", recalculation.get("gwp_label") or recalculation.get("gwp_set")],
        ["Emission factors", "EPA GHG Emission Factors Hub 2025"],
        ["Scope 1 recalculated (t CO2e)", total("scope1")],
        ["Scope 2 location-based recalculated (t CO2e)", total("scope2_location")],
        ["Scope 2 market-based recalculated (t CO2e)", total("scope2_market")],
        *([["Inventory total, location-based (t CO2e)", node("inventory_location_total")],
           ["Inventory total, market-based (t CO2e)", node("inventory_market_total")]] if rollup else []),
        ["Documents read", recalculation.get("documents_considered")],
        ["Documents fully reviewed", recalculation.get("documents_reviewed")],
        ["Documents left out: not on a calculation line (see Left out)",
         len({d.get("document_id") for d in (recalculation.get("uncounted_values") or {}).get("documents") or []})],
        *([["WARNING", "Where each document sits could not be read: no value from the evidence is counted and "
                       "every total and difference is incomplete."]]
          if any(i.get("kind") == "record_placement" for i in recalculation.get("needs_input") or []) else []),
        ["Status", "Draft working paper, not an assurance opinion"],
        ["Protection", "Every sheet is protected without a password, so nothing is changed by accident. "
                       "You can still select and copy, and change column widths. To edit, unprotect a sheet in "
                       "Excel (Review, Unprotect Sheet)."],
        ["Exported", f"{datetime.now(UTC):%Y-%m-%d %H:%M} UTC by {exported_by}"],
    ]
    _sheet(book, "Summary", ["Item", "Value"], summary, [44, 70])
    for label, value in book["Summary"].iter_rows(min_row=2, max_col=2):
        if _is_number(value.value) and isinstance(label.value, str):
            if label.value.endswith("(t CO2e)"):
                value.number_format = _tonnes(value.value)
            elif label.value.endswith("(%)"):
                value.number_format = _PERCENT
    if rollup:
        _rollup_sheets(book, rollup)

    _sheet(
        book, "Data points",
        ["Workbook row", "Data point", "Unit", "Reported", "Recalculated", "Difference", "Difference %",
         "Outcome", "Inputs incomplete"],
        [[c.get("workbook_row"), c.get("data_point"), c.get("unit"), c.get("reported"), c.get("recalculated"),
          c.get("difference"), c.get("difference_pct"), _STATUS.get(str(c.get("status")), c.get("status")),
          "yes" if c.get("inputs_incomplete") else ""]
         for c in recalculation.get("comparisons") or []],
        [12, 52, 10, 14, 14, 14, 13, 44, 16],
        formats={"Reported": _tonnes_if_unit(2), "Recalculated": _tonnes_if_unit(2), "Difference": _tonnes_if_unit(2),
                 "Difference %": _percent},
    )

    _sheet(
        book, "Warnings", ["Check", "Severity", "What it found", "Facility", "Documents", "Dates"],
        _warning_rows(recalculation), [30, 16, 90, 28, 50, 30],
        note="Warnings are signals for the reviewer. They do not change the numbers in this workpaper.",
    )
    _sheet(
        book, "Method",
        ["Group", "Question", "Answer", "Status", "Reason", "Quote", "Document", "Page", "Decided by",
         "Decided at"],
        _method_rows(items), [24, 40, 60, 11, 40, 70, 36, 7, 22, 20],
    )

    working: list[list[Any]] = []
    for key, category in (recalculation.get("categories") or {}).items():
        if not category:
            continue
        for line in category.get("lines") or []:
            for step in line.get("steps") or []:
                inputs = "; ".join(
                    f"{name} = {i.get('value')} {i.get('unit') or ''}".strip()
                    + (f" [{i.get('source')}]" if i.get("source") else "")
                    for name, i in (step.get("inputs") or {}).items()
                )
                working.append([key, line.get("key"), step.get("label"), step.get("formula"), inputs,
                                step.get("result"), step.get("result_unit")])
        for step in category.get("steps") or []:
            inputs = "; ".join(f"{name} = {i.get('value')} {i.get('unit') or ''}".strip()
                               for name, i in (step.get("inputs") or {}).items())
            working.append([key, "(category total)", step.get("label"), step.get("formula"), inputs,
                            step.get("result"), step.get("result_unit")])
    _sheet(book, "Working", ["Category", "Line", "Step", "Formula", "Inputs (with source)", "Result", "Unit"],
           working, [30, 26, 30, 30, 90, 16, 10], formats={"Result": _tonnes_if_unit(6)})
    _sheet(
        book, "Sources",
        ["Category", "Line", "Document", "Record", "Quantity", "Unit", "Share counted in the period",
         "Quantity counted", "Page"],
        _source_rows(recalculation, register), [30, 40, 44, 12, 16, 10, 16, 16, 7],
        note="From each calculation line to the documents behind it. The share is the part of the bill's service "
             "period inside the reporting period. Where a category has no calculation lines, or a document is not "
             "on a line, only the amount counted is known.",
        formats={"Share counted in the period": _fraction},
    )

    documents = register.get("documents") or []
    with_claude = any(d.get("suggested_count") for d in documents)  # the column only exists when Claude read something
    _sheet(
        book, "Evidence",
        ["File", "Document type", "Uploaded", "Uploaded by", "Values extracted"]
        + (["Suggested by Sustentra's AI"] if with_claude else []),
        [[d.get("file_name"), d.get("canonical_type_id") or "Not identified", _when(d.get("uploaded_at")),
          d.get("uploaded_by"), d.get("candidate_count")] + ([d.get("suggested_count") or 0] if with_claude else [])
         for d in documents],
        [48, 22, 20, 30, 16] + ([20] if with_claude else []),
    )
    _sheet(
        book, "Reviewed values",
        ["File", "Record", "Field", "Extracted", "Unit", "Decision", "Reviewed value", "Reviewed unit",
         "Reviewer", "Reviewed at", "Page", "Source text"],
        [[v.get("file_name"), v.get("record_index"), v.get("field"), v.get("extracted"), v.get("unit"),
          v.get("decision"), v.get("reviewed_value"), v.get("reviewed_unit"), v.get("reviewer"),
          _when(v.get("reviewed_at")), v.get("page"), v.get("snippet")] for v in register.get("values") or []],
        [40, 8, 30, 18, 10, 14, 16, 12, 30, 20, 6, 60],
    )

    asks = [i["payload"] for i in items if i.get("kind") == "ask"]
    _sheet(
        book, "Requests",
        ["Item", "Type", "What is needed", "Facility", "Period", "State", "Raised by", "Raised at", "Request no."],
        [[(a.get("source") or {}).get("itemLabel"), a.get("type"), a.get("whatIsNeeded"),
          (a.get("source") or {}).get("facilityName"), (a.get("source") or {}).get("period"), a.get("state"),
          a.get("raisedByName"), _when(a.get("raisedAt")), a.get("requestNumber")] for a in asks],
        [40, 18, 60, 22, 22, 14, 18, 20, 12],
    )
    findings = [i["payload"] for i in items if i.get("kind") == "finding"]
    _sheet(
        book, "Findings",
        ["Data point", "Finding", "Cause", "Magnitude", "Status", "Registered by", "Registered at"],
        [[f.get("dataPointLabel"), f.get("sentence"), f.get("cause"), f.get("magnitude"), f.get("status"),
          f.get("registeredBy"), _when(f.get("registeredAt"))] for f in findings],
        [36, 60, 28, 16, 12, 18, 20],
    )
    _sheet(
        book, "Left out",
        ["Document / record", "Why it is not counted", "Dates"],
        [[e.get("record"), _LEFT_OUT.get(str(e.get("reason")), e.get("reason")), e.get("period")]
         for e in recalculation.get("excluded") or []],
        [56, 36, 26],
    )

    for sheet in book.worksheets:  # no password: the aim is no accidental edits; select, copy and column widths stay
        sheet.protection.sheet = True
        sheet.protection.formatColumns = False

    fingerprint = content_fingerprint(book, exported_by)
    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue(), fingerprint
