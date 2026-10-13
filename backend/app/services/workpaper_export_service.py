"""The engagement's workpaper as an Excel file: what was reported, what was recalculated
and how, the evidence behind it, what the reviewer decided, and the open work.

Every number comes from the same recalculation the screens show; nothing is computed
here. Sheets: Summary, Data points, Working, Evidence, Reviewed values, Requests,
Findings, Left out.
"""

from __future__ import annotations

import io
from datetime import UTC, datetime
from typing import Any

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

_HEADER_FILL = PatternFill("solid", fgColor="E8EAF4")
_STATUS = {
    "within_tolerance": "Held",
    "exceeds_tolerance": "Exception",
    "not_reported": "Could not check (reported value not entered)",
    "no_evidence": "Could not check (no reviewed evidence)",
    "not_recalculated": "Out of scope (not recalculated yet)",
}
_LEFT_OUT = {
    "outside_reporting_period": "Outside the reporting period",
    "withdrawn": "Withdrawn by the reviewer",
    "duplicate": "Marked as a duplicate",
    "superseded": "Superseded by a newer document",
}


def _sheet(book: Workbook, title: str, header: list[str], rows: list[list[Any]], widths: list[int]) -> None:
    sheet = book.create_sheet(title)
    sheet.append(header)
    for cell in sheet[1]:
        cell.font = Font(bold=True)
        cell.fill = _HEADER_FILL
    for row in rows:
        sheet.append([_cell(v) for v in row])
    for index, width in enumerate(widths, start=1):
        sheet.column_dimensions[get_column_letter(index)].width = width
    for row in sheet.iter_rows(min_row=2):
        for cell in row:
            cell.alignment = Alignment(vertical="top", wrap_text=isinstance(cell.value, str) and len(cell.value) > 40)
    sheet.freeze_panes = "A2"


def _cell(value: Any) -> Any:
    if value is None or isinstance(value, (int, float, str)):
        return value
    return str(value)


def _when(value: Any) -> str:
    return str(value or "")[:19].replace("T", " ")


def build_workbook(
    *,
    engagement: dict[str, Any],
    recalculation: dict[str, Any],
    register: dict[str, list[dict[str, Any]]],
    items: list[dict[str, Any]],
    exported_by: str,
) -> bytes:
    book = Workbook()
    book.remove(book.active)
    settings = engagement.get("settings") or {}
    totals = recalculation.get("scope_totals") or {}

    def total(name: str) -> float | None:
        part = totals.get(name)
        return part["total_co2e"] if part else None

    summary = [
        ["Engagement", engagement.get("name")],
        ["Company", engagement.get("client_name")],
        ["Reporting period", f"{engagement.get('reporting_period_start') or '?'} to "
                             f"{engagement.get('reporting_period_end') or '?'}"],
        ["Regulation", settings.get("regulation")],
        ["Assurance level", settings.get("assuranceLevel")],
        ["Assurance standard", settings.get("assuranceStandard")],
        ["Boundary approach", settings.get("boundaryApproach")],
        ["Materiality tolerance (%)", recalculation.get("tolerance_pct")],
        ["GWP basis", recalculation.get("gwp_set")],
        ["Emission factors", "EPA GHG Emission Factors Hub 2025"],
        ["Scope 1 recalculated (t CO2e)", total("scope1")],
        ["Scope 2 location-based recalculated (t CO2e)", total("scope2_location")],
        ["Scope 2 market-based recalculated (t CO2e)", total("scope2_market")],
        ["Documents with reviewed values", recalculation.get("documents_considered")],
        ["Status", "Draft working paper, not an assurance opinion"],
        ["Exported", f"{datetime.now(UTC):%Y-%m-%d %H:%M} UTC by {exported_by}"],
    ]
    _sheet(book, "Summary", ["Item", "Value"], summary, [44, 70])

    _sheet(
        book, "Data points",
        ["Workbook row", "Data point", "Unit", "Reported", "Recalculated", "Difference", "Difference %",
         "Outcome", "Inputs incomplete"],
        [[c.get("workbook_row"), c.get("data_point"), c.get("unit"), c.get("reported"), c.get("recalculated"),
          c.get("difference"), c.get("difference_pct"), _STATUS.get(str(c.get("status")), c.get("status")),
          "yes" if c.get("inputs_incomplete") else ""]
         for c in recalculation.get("comparisons") or []],
        [12, 52, 10, 14, 14, 14, 13, 44, 16],
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
           working, [30, 26, 30, 30, 90, 16, 10])

    _sheet(
        book, "Evidence",
        ["File", "Document type", "Uploaded", "Uploaded by", "Values extracted"],
        [[d.get("file_name"), d.get("canonical_type_id") or "Not identified", _when(d.get("uploaded_at")),
          d.get("uploaded_by"), d.get("candidate_count")] for d in register.get("documents") or []],
        [48, 22, 20, 30, 16],
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

    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue()
