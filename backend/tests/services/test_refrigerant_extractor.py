"""CT-S1-REFRSVC: refrigerant service work orders and logs -> material-balance inputs."""

from __future__ import annotations

from typing import Any

import pytest

from backend.app.domain.refrigerants import find_refrigerant, parse_mass
from backend.app.services.extraction_service import ExtractionService
from backend.app.services.extraction_target_service import ExtractionTargetService
from backend.app.services.refrigerant_extractor import (
    HALT_UNSUPPORTED,
    PURCHASE_NOTE,
    RefrigerantServiceExtractor,
    classify_service,
)


@pytest.fixture(scope="module")
def targets() -> list[dict]:
    return ExtractionTargetService().get_targets_for_canonical_type("CT-S1-REFRSVC")


def _text_output(text: str, document_id: str = "DOC-1") -> dict[str, Any]:
    return {
        "document_id": document_id,
        "pages": [{"page_number": 1, "text": text}],
        "text_blocks": [{"block_id": "b1", "page_number": 1, "text": text, "confidence": None,
                         "bounding_box": None, "source_reference_id": None}],
        "tables": [], "key_value_pairs": [], "source_references": [],
    }


def _sheet_output(rows: list[list[Any]], document_id: str = "DOC-X") -> dict[str, Any]:
    """parser_output as the spreadsheet parser writes it: one text block per non-empty cell."""

    blocks, references = [], []
    for r, row in enumerate(rows, start=1):
        for c, value in enumerate(row):
            if value in (None, ""):
                continue
            ref = f"A{len(references) + 1}"
            cell = f"{chr(65 + c)}{r}"
            blocks.append({"block_id": f"openpyxl-Log-{cell}", "page_number": None, "text": str(value),
                           "confidence": None, "bounding_box": None, "source_reference_id": ref})
            references.append({"source_reference_id": ref, "document_id": document_id, "page_number": None,
                               "sheet_name": "Log", "cell_or_range": cell, "text_snippet": str(value),
                               "bounding_box": None, "parser_block_ids": [f"openpyxl-Log-{cell}"],
                               "source_kind": "excel_cell"})
    return {"document_id": document_id, "pages": [], "text_blocks": blocks, "tables": [], "key_value_pairs": [],
            "source_references": references}


def _by_field(candidates: list[dict], record_index: int | None = None) -> dict[str, dict]:
    return {c["field_name"]: c for c in candidates if c["record_index"] == record_index}


# --- names and amounts -----------------------------------------------------------------
@pytest.mark.parametrize(
    ("text", "name", "family"),
    [
        ("R410A", "R-410A", "blend"),
        ("Refrigerant: r-404a", "R-404A", "blend"),
        ("Puron", "R-410A", "blend"),
        ("R-134A", "HFC-134a", "hfc"),
        ("HFC134a", "HFC-134a", "hfc"),
        ("FM-200 clean agent", "HFC-227ea", "hfc"),
        ("R-32", "HFC-32", "hfc"),
        ("SF6 breaker", "SF6", "sf6"),
        ("R-744", "CO2", "co2"),
        ("Freon 22", "HCFC-22", "hcfc"),
        ("R-22", "HCFC-22", "hcfc"),
        ("CFC-12", "CFC-12", "cfc"),
        ("Halon 1301", "Halon 1301", "halon"),
        ("R-454B", "R-454B", "blend"),
        ("R-1234yf", "R-1234yf", "other"),
    ],
)
def test_find_refrigerant(text: str, name: str, family: str) -> None:
    found = find_refrigerant(text)
    assert found is not None and (found.name, found.family) == (name, family)
    assert found.montreal == (family in ("cfc", "hcfc", "halon"))


@pytest.mark.parametrize("text", ["Route 22", "Suite 410", "CO2e total", "Unit 45 lb", "no gas here"])
def test_find_refrigerant_ignores_lookalikes(text: str) -> None:
    assert find_refrigerant(text) is None


@pytest.mark.parametrize(
    ("text", "default", "value", "unit"),
    [
        ("4.5 lbs", None, 4.5, "lb"),
        ("4 lb 8 oz", None, 4.5, "lb"),
        ("12 lbs. 4 oz.", None, 12.25, "lb"),
        ("72 oz", None, 4.5, "lb"),
        ("2.1 kg", None, 2.1, "kg"),
        ("500 g", None, 0.5, "kg"),
        ("1,250 lb", None, 1250, "lb"),
        ("6.5", "Added (lb)", 6.5, "lb"),
        ("6.5", None, None, None),
    ],
)
def test_parse_mass(text: str, default: str | None, value: float | None, unit: str | None) -> None:
    mass = parse_mass(text, default)
    assert (mass.value if mass else None, mass.unit if mass else None) == (value, unit)


def test_service_type_wording() -> None:
    assert classify_service("Leak repair, recharged") == "service"
    assert classify_service("New unit installed") == "installation"
    assert classify_service("Unit decommissioned") == "disposal"
    # In free notes an equipment's install date is its age, not a new installation.
    assert classify_service("Install date: 2015-03-01. Leak found on coil.", notes=True) == "service"


# --- a work order --------------------------------------------------------------------------
WORK_ORDER = """Arctic Air Mechanical, Inc.
SERVICE WORK ORDER
Work Order #: WO-24817
Service Date: 03/14/2025
Customer: Richmond Refinery
Service Address: 4100 Deepwater Terminal Rd, Richmond, VA 23234
Equipment ID: RTU-3
Refrigerant Type: R-410A
Full Charge: 18 lb
Refrigerant Added: 6 lb 8 oz
Refrigerant Recovered: 0 lb
Reason for Service: Leak repair
"""


def test_work_order_is_one_record(targets: list[dict]) -> None:
    outcome = RefrigerantServiceExtractor().extract(_text_output(WORK_ORDER), targets, "EV-1")
    fields = _by_field(outcome.candidates)
    assert outcome.halt_reason is None and outcome.records == 1
    assert fields["refrigerant_type"]["normalized_value"] == "R-410A"
    assert (fields["refrigerant_added"]["normalized_value"], fields["refrigerant_added"]["unit"]) == (6.5, "lb")
    assert "unit_converted" in fields["refrigerant_added"]["validation_flags"]
    assert (fields["equipment_capacity"]["normalized_value"], fields["equipment_capacity"]["unit"]) == (18, "lb")
    assert fields["refrigerant_recovered"]["normalized_value"] == 0
    assert fields["service_date"]["normalized_value"] == "2025-03-14"
    assert fields["equipment_id"]["normalized_value"] == "RTU-3"
    assert fields["service_type"]["normalized_value"] == "service"
    assert fields["facility_name"]["normalized_value"] == "Richmond Refinery"
    assert fields["refrigerant_added"]["source_reference"]["text_snippet"] == "Refrigerant Added: 6 lb 8 oz"


def test_hcfc_is_flagged(targets: list[dict]) -> None:
    text = WORK_ORDER.replace("R-410A", "R-22")
    fields = _by_field(RefrigerantServiceExtractor().extract(_text_output(text), targets, "EV-1").candidates)
    assert fields["refrigerant_type"]["normalized_value"] == "HCFC-22"
    assert "montreal_protocol_gas" in fields["refrigerant_type"]["validation_flags"]


def test_bare_amount_is_kept_and_flagged_without_a_unit(targets: list[dict]) -> None:
    text = WORK_ORDER.replace("Refrigerant Added: 6 lb 8 oz", "Refrigerant Added: 6.5")
    fields = _by_field(RefrigerantServiceExtractor().extract(_text_output(text), targets, "EV-1").candidates)
    assert fields["refrigerant_added"]["normalized_value"] == 6.5
    assert fields["refrigerant_added"]["unit"] is None and "unit_missing" in fields["refrigerant_added"]["validation_flags"]


def test_a_document_without_a_refrigerant_halts(targets: list[dict]) -> None:
    text = "Valley HVAC\nService Date: 03/14/2025\nReplaced belt and filters on RTU-3.\n"
    outcome = RefrigerantServiceExtractor().extract(_text_output(text), targets, "EV-1")
    assert outcome.candidates == [] and outcome.halt_reason["code"] == HALT_UNSUPPORTED


# --- a log ---------------------------------------------------------------------------------
LOG_ROWS = [
    ["Date", "Equipment", "Refrigerant", "Service Type", "Added (lb)", "Recovered (lb)", "Full Charge (lb)"],
    ["01/22/2025", "Chiller CH-1", "R-134a", "Leak repair", "45", "0", "650"],
    ["08/18/2025", "RTU-12", "R-410A", "New unit installed", "21", "0", "20"],
    ["12/05/2025", "Chiller CH-2", "R-134a", "Decommissioned", "0", "580", "600"],
    ["Total", "", "", "", "66", "580", ""],
]


def test_log_in_plain_text_is_one_record_per_line(targets: list[dict]) -> None:
    text = "Refrigerant Management Log 2025\n" + "\n".join("    ".join(r) for r in LOG_ROWS[:-1]) + "\nTotal    66\n"
    outcome = RefrigerantServiceExtractor().extract(_text_output(text), targets, "EV-1")
    assert outcome.records == 3
    first, second, third = (_by_field(outcome.candidates, i) for i in (1, 2, 3))
    assert (first["refrigerant_type"]["normalized_value"], first["refrigerant_added"]["normalized_value"]) == (
        "HFC-134a", 45)
    assert first["refrigerant_added"]["unit"] == "lb"  # from the "Added (lb)" header
    assert second["service_type"]["normalized_value"] == "installation"
    assert third["service_type"]["normalized_value"] == "disposal"
    assert (third["refrigerant_recovered"]["normalized_value"], third["equipment_capacity"]["normalized_value"]) == (
        580, 600)
    assert third["service_date"]["normalized_value"] == "2025-12-05"
    assert "record 3" in third["refrigerant_type"]["display_label"]


def test_log_in_a_spreadsheet_matches_columns_by_letter(targets: list[dict]) -> None:
    rows = [list(r) for r in LOG_ROWS]
    rows[1][5] = ""  # an empty Recovered cell must not shift the Full Charge value left
    outcome = RefrigerantServiceExtractor().extract(_sheet_output(rows), targets, "EV-1")
    assert outcome.records == 3  # the Total row is not a record
    first = _by_field(outcome.candidates, 1)
    assert first["refrigerant_recovered"]["normalized_value"] is None
    assert first["equipment_capacity"]["normalized_value"] == 650
    reference = first["refrigerant_added"]["source_reference"]
    assert (reference["sheet_name"], reference["cell_or_range"]) == ("Log", "E2")


def test_extraction_service_routes_refrigerant_targets(targets: list[dict]) -> None:
    result = ExtractionService().extract({"parser_output": _text_output(WORK_ORDER), "extraction_targets": targets,
                                          "evidence_id": "EV-1"})
    assert result["record_count"] == 1
    assert {item["field_name"] for item in result["items"]} >= {"refrigerant_type", "refrigerant_added"}


def test_confirms_needs_a_refrigerant_and_an_amount() -> None:
    extractor = RefrigerantServiceExtractor()
    assert extractor.confirms(_text_output(WORK_ORDER))
    assert not extractor.confirms(_text_output("Chiller CH-1 uses R-134a. Annual inspection passed.\n"))


# --- review findings: misreads that would change the material balance --------------------
@pytest.mark.parametrize(
    ("text", "kind"),
    [
        ("Replaced failed compressor, installed new filter drier, evacuated and recharged", "service"),
        ("Replaced TXV; old valve disposed", "service"),
        ("Seasonal start-up", None),  # read as a service downstream
        ("Commissioning check", None),
        ("Installed new rooftop unit RTU-12", "installation"),
        ("New RTU-12 installed", "installation"),
        ("Chiller CH-2 retired and scrapped", "disposal"),
        ("Removed from service", "disposal"),
        ("Disposal", "disposal"),
        ("Installation", "installation"),
    ],
)
def test_only_the_equipment_itself_makes_an_installation_or_disposal(text: str, kind: str | None) -> None:
    assert classify_service(text) == kind


def test_a_repair_work_order_stays_a_service(targets: list[dict]) -> None:
    text = ("Refrigerant Type: R-410A\nRefrigerant Added: 8 lbs\nSystem Charge: 10 lbs\n"
            "Work Performed: Replaced failed compressor, installed new filter drier, evacuated and recharged\n")
    fields = _by_field(RefrigerantServiceExtractor().extract(_text_output(text), targets, "EV-1").candidates)
    assert fields["service_type"]["normalized_value"] == "service"


def test_an_invoice_unit_column_is_the_unit_not_the_equipment(targets: list[dict]) -> None:
    text = ("Item    Description    Qty    Unit    Price\n"
            "1    R-410A refrigerant    6    LB    210.00\n"
            "2    R-404A refrigerant    12    OZ    95.00\n")
    outcome = RefrigerantServiceExtractor().extract(_text_output(text), targets, "EV-1")
    first, second = _by_field(outcome.candidates, 1), _by_field(outcome.candidates, 2)
    assert (first["refrigerant_added"]["normalized_value"], first["refrigerant_added"]["unit"]) == (6, "lb")
    assert (second["refrigerant_added"]["normalized_value"], second["refrigerant_added"]["unit"]) == (0.75, "lb")
    assert first["equipment_id"]["normalized_value"] is None


def test_a_cylinder_size_multiplies_the_quantity(targets: list[dict]) -> None:
    text = "Description    Qty    Price\nR-410A refrigerant 25 lb cylinder    2    300.00\n"
    fields = _by_field(RefrigerantServiceExtractor().extract(_text_output(text), targets, "EV-1").candidates)
    added = fields["refrigerant_added"]
    assert (added["normalized_value"], added["unit"]) == (50, "lb")
    assert "quantity_times_package_size" in added["validation_flags"]


def test_cooling_tonnage_is_not_a_refrigerant_charge(targets: list[dict]) -> None:
    text = "Refrigerant Type: R-410A\nCapacity: 5 tons\nRefrigerant Added: 3 lb\n"
    fields = _by_field(RefrigerantServiceExtractor().extract(_text_output(text), targets, "EV-1").candidates)
    assert fields["equipment_capacity"]["normalized_value"] is None
    assert fields["refrigerant_added"]["normalized_value"] == 3


# --- the facility is the site, never the company that is billed ----------------------------------
INVOICE_SHAPE = """Cold Crest Mechanical Services
REFRIGERANT SERVICE INVOICE
Invoice No: CC-2025-0912
{parties}Equipment ID: RTU-3
Refrigerant Type: R-410A
Full Charge: 18 lb
Refrigerant Added: 6 lb
Service Date: 09/12/2025
"""


def _site_of(parties: str, targets: list[dict]) -> str | None:
    outcome = RefrigerantServiceExtractor().extract(_text_output(INVOICE_SHAPE.format(parties=parties)), targets, "EV-1")
    assert outcome.halt_reason is None
    return _by_field(outcome.candidates).get("facility_name", {}).get("normalized_value") or None


@pytest.mark.parametrize(
    ("parties", "site"),
    [
        ("Bill To: Staging-Test Foods Inc.\nService Location: Riverside Plant\n", "Riverside Plant"),
        ("Bill To: Staging-Test Foods Inc.\nShip To: Riverside Plant\n", "Riverside Plant"),
        ("Customer: Staging-Test Foods Inc.\nSite: Müller Käserei – Zürich\n", "Müller Käserei – Zürich"),
        ("Bill To: Staging-Test Foods Inc.\nService Location: 東京工場\n", "東京工場"),
        ("Bill To: Staging-Test Foods Inc.\nSite: Staging-Test Foods Inc. – Riverside Plant\n",
         "Staging-Test Foods Inc. – Riverside Plant"),
    ],
)
def test_the_service_site_is_the_facility_and_the_bill_to_is_not(targets: list[dict], parties: str, site: str) -> None:
    assert _site_of(parties, targets) == site


@pytest.mark.parametrize("label", ["Bill To", "Sold To", "Customer", "Account Name"])
def test_a_bill_to_name_alone_is_not_a_facility_in_strict_mode(
        targets: list[dict], monkeypatch: pytest.MonkeyPatch, label: str) -> None:
    monkeypatch.setattr("backend.app.services.stationary_combustion_extractor.BILL_TO_NAME_IS_LAST_RESORT_FACILITY", False)
    assert _site_of(f"{label}: Staging-Test Foods Inc.\n", targets) is None


# --- a service log with one line per visit, as a contractor prints it (NPL refrigerant log) -------------
def _grid_output(rows: list[list[tuple]], document_id: str = "DOC-LOG") -> dict[str, Any]:
    """parser_output for a PDF page: each row is a list of (text, left, width[, height]); rows are 0.025 apart.
    A cell with empty text is a gap in the table (nothing is drawn there)."""

    blocks: list[dict] = []
    for r, row in enumerate(rows):
        for c, (text, left, width, *height) in enumerate(row):
            if not text:
                continue
            blocks.append({
                "block_id": f"p1-r{r}-c{c}", "page_number": 1, "text": text, "confidence": None,
                "bounding_box": {"left": left, "top": 0.05 + 0.025 * r, "width": width,
                                 "height": height[0] if height else 0.013},
                "source_reference_id": None,
            })
    return {"document_id": document_id, "pages": [{"page_number": 1, "text": ""}], "text_blocks": blocks,
            "tables": [], "key_value_pairs": [], "source_references": []}


# column x positions of the printed log: date, equipment, refrigerant (+ full charge, right-aligned), added, recovered,
# technician, notes
X = {"date": (0.05, 0.06), "equipment": (0.12, 0.14), "gas": (0.293, 0.04), "charge": (0.43, 0.02),
     "added": (0.50, 0.025), "recovered": (0.607, 0.016), "tech": (0.639, 0.057), "notes": (0.74, 0.17)}


def _log_row(date: str, equipment: str, gas: str, charge: str, added: str, recovered: str, tech: str,
             notes: str) -> list[tuple[str, float, float]]:
    values = [date, equipment, gas, charge, added, recovered, tech, notes]
    return [(text, *X[name]) for text, name in zip(values, X, strict=True)]


LOG_HEAD: list[list[tuple]] = [
    [("POLAR POINT MECHANICAL SERVICES", 0.05, 0.4, 0.03)],  # the letterhead is the largest text
    [("Refrigerant Service & Leak Log – Calendar Year 2025 (01/01/2025 – 12/31/2025)", 0.05, 0.8)],
    [("Customer: Northgate Provisions Inc. · Site: Sacramento Warehouse, 1820 Richards Boulevard, Sacramento, CA 95811",
      0.05, 0.9)],
    # the parser read "Refrigerant" and the right-aligned "Full Charge (lb)" as one line
    [("Date", 0.05, 0.027), ("Equipment", 0.12, 0.061), ("RefrigerantFull Charge (lb)", 0.293, 0.159),
     ("Added (lb)", 0.465, 0.06), ("Recovered (lb)", 0.54, 0.083), ("Technician", 0.639, 0.061), ("Notes", 0.74, 0.033)],
]
LOG_LINES = [
    _log_row("02/11/2025", "RACK-A Walk-in freezer rack", "R-404A", "180", "12.5", "0.0", "José Muñoz",
             "Leak at TXV flare fitting – repaired"),
    _log_row("04/08/2025", "CH-1 Dock process chiller", "R-134a", "95", "6.0", "0.0", "Renée Côté",
             "Low charge alarm; valve core replaced"),
    _log_row("05/27/2025", "RACK-A Walk-in freezer rack", "R-404A", "180", "8.0", "0.0", "José Muñoz",
             "Routine top-up, leak check OK"),
    _log_row("08/19/2025", "CH-1 Dock process chiller", "R-134a", "95", "4.5", "0.0", "Zoë Brandão",
             "Top-up after compressor service"),
]
LOG_TOTALS: list[list[tuple[str, float, float]]] = [
    [("Refrigerant", 0.05, 0.08), ("Total Added 2025 (lb)", 0.3, 0.15), ("Total Recovered (lb)", 0.5, 0.15)],
    [("R-404A", 0.05, 0.05), ("20.5", 0.3, 0.03), ("0.0", 0.5, 0.02)],
    [("R-134a", 0.05, 0.05), ("10.5", 0.3, 0.03), ("0.0", 0.5, 0.02)],
]


def _log_records(rows: list[list[tuple[str, float, float]]], targets: list[dict]) -> dict[int, dict[str, dict]]:
    outcome = RefrigerantServiceExtractor().extract(_grid_output(rows), targets, "EV-1")
    assert outcome.halt_reason is None
    indexes = sorted({c["record_index"] for c in outcome.candidates if c["record_index"] is not None})
    if not indexes:  # a log with one line is one record, with no record number
        return {1: _by_field(outcome.candidates)}
    return {i: _by_field(outcome.candidates, i) for i in indexes}


def _value(fields: dict[str, dict], name: str) -> tuple[Any, Any]:
    return fields[name]["normalized_value"], fields[name]["unit"]


def test_each_service_line_of_a_log_is_its_own_record(targets: list[dict]) -> None:
    records = _log_records([*LOG_HEAD, *LOG_LINES, *LOG_TOTALS], targets)
    assert len(records) == 4  # the totals table below the lines is not more records
    first, second = records[1], records[2]
    assert _value(first, "service_date") == ("2025-02-11", None)
    assert first["equipment_id"]["normalized_value"] == "RACK-A Walk-in freezer rack"
    assert _value(first, "refrigerant_type") == ("R-404A", None)
    assert _value(first, "refrigerant_added") == (12.5, "lb")
    assert _value(first, "refrigerant_recovered") == (0, "lb")
    assert _value(first, "equipment_capacity") == (180, "lb")
    assert _value(second, "refrigerant_type") == ("HFC-134a", None)
    assert _value(second, "refrigerant_added") == (6, "lb")
    assert _value(second, "equipment_capacity") == (95, "lb")
    # the totals the log prints are the sum of its lines per gas, never read as lines of their own
    by_gas: dict[str, float] = {}
    for fields in records.values():
        gas = fields["refrigerant_type"]["normalized_value"]
        by_gas[gas] = by_gas.get(gas, 0) + fields["refrigerant_added"]["normalized_value"]
    assert by_gas == {"R-404A": 20.5, "HFC-134a": 10.5}


def test_a_technician_keeps_accents_and_is_not_the_service_provider(targets: list[dict]) -> None:
    records = _log_records([*LOG_HEAD, *LOG_LINES], targets)
    assert [r["technician"]["normalized_value"] for r in records.values()] == [
        "José Muñoz", "Renée Côté", "José Muñoz", "Zoë Brandão"]
    # the company is the letterhead, the same on every line
    assert {r["service_provider"]["normalized_value"] for r in records.values()} == {"POLAR POINT MECHANICAL SERVICES"}


def test_a_blank_line_between_service_lines_does_not_end_the_log(targets: list[dict]) -> None:
    rows = [*LOG_HEAD, LOG_LINES[0], [], LOG_LINES[1], [("", 0, 0)], LOG_LINES[2], LOG_LINES[3]]
    assert len(_log_records(rows, targets)) == 4


def test_a_recovered_only_line_is_a_record_with_no_amount_added(targets: list[dict]) -> None:
    removed = _log_row("09/30/2025", "CH-1 Dock process chiller", "R-134a", "95", "", "14.0", "Renée Côté",
                       "Recovered before compressor swap")
    records = _log_records([*LOG_HEAD, LOG_LINES[0], removed], targets)
    assert len(records) == 2
    line = records[2]
    assert _value(line, "refrigerant_recovered") == (14, "lb")
    assert line["refrigerant_added"]["normalized_value"] is None  # blank, never read from a neighbouring cell
    assert _value(line, "refrigerant_type") == ("HFC-134a", None)
    assert line["technician"]["normalized_value"] == "Renée Côté"


def test_non_ascii_names_and_kilograms_in_a_log_survive(targets: list[dict]) -> None:
    head = list(LOG_HEAD)
    head[3] = [(text.replace("(lb)", "(kg)"), left, width) for text, left, width in head[3]]
    line = _log_row("2025-03-04", "冷凍機 No.2 – Zürich", "R-410A", "40", "3.2", "0.4", "山田 太郎",
                    "Fuite réparée – raccord")
    records = _log_records([*head, line], targets)
    only = records[1]
    assert _value(only, "refrigerant_added") == (3.2, "kg") and _value(only, "refrigerant_recovered") == (0.4, "kg")
    assert only["equipment_id"]["normalized_value"] == "冷凍機 No.2 – Zürich"
    assert only["technician"]["normalized_value"] == "山田 太郎"


def test_words_that_are_not_headers_are_never_split() -> None:
    from backend.app.services.refrigerant_extractor import Cell, Row

    def row(*texts: str) -> Row:
        return Row([Cell(t, 1, {"left": 0.1 * i, "top": 0.1, "width": 0.1, "height": 0.01}, None, None, None, i)
                    for i, t in enumerate(texts)], 1)

    split = RefrigerantServiceExtractor._split_glued_headers
    assert [c.text for c in split(row("RefrigerantFull Charge (lb)")).cells] == ["Refrigerant", "Full Charge (lb)"]
    for plain in ("RACK-A Walk-in freezer rack", "AirHandler", "Notes", "McDonald Added", "José Muñoz"):
        assert split(row(plain)).cells[0].text == plain


# --- a supplier's invoice: refrigerant bought, counted in cylinders --------------------------------------
def _invoice(table: str) -> dict[str, Any]:
    return _text_output(
        "WESTBAY REFRIGERANT SUPPLY    INVOICE\n"
        "Invoice Date    09/17/2025\n"
        f"{table}"
        "Subtotal    $1,775.00\n"
        "Total refrigerant shipped: 4 cylinders × 25 lb = 100 lb R-410A (net weight).\n")


def test_cyl_is_a_unit_not_an_equipment_and_a_purchase_is_named_as_one(targets: list[dict]) -> None:
    table = ("Item    Description    Qty    Unit    Unit Price    Amount\n"
             "R410A-25    Refrigerant R-410A, 25 lb disposable cylinder    4    cyl    $395.00    $1,580.00\n")
    outcome = RefrigerantServiceExtractor().extract(_invoice(table), targets, "EV-1")
    fields = _by_field(outcome.candidates)
    assert fields["equipment_id"]["normalized_value"] is None  # "cyl" is how the line is counted
    added = fields["refrigerant_added"]
    assert (added["normalized_value"], added["unit"]) == (100, "lb")
    assert added["display_label"] == "Refrigerant purchased"
    assert {"quantity_times_package_size", "purchase_not_equipment_charge"} <= set(added["validation_flags"])
    assert fields["refrigerant_recovered"]["normalized_value"] is None
    # the reviewer is told in plain words, once for the document
    assert outcome.notes == [PURCHASE_NOTE] and "not an emission until it is charged into equipment" in PURCHASE_NOTE


@pytest.mark.parametrize(("unit_word"), ["cyl", "cylinder", "Cylinders", "drum", "ea", "each", "pcs"])
def test_package_words_in_the_unit_column_are_never_equipment(targets: list[dict], unit_word: str) -> None:
    table = ("Item    Description    Qty    Unit    Unit Price    Amount\n"
             f"R410A-25    Refrigerant R-410A, 25 lb cylinder    2    {unit_word}    $395.00    $790.00\n")
    fields = _by_field(RefrigerantServiceExtractor().extract(_invoice(table), targets, "EV-1").candidates)
    assert fields["equipment_id"]["normalized_value"] is None
    assert fields["refrigerant_added"]["normalized_value"] == 50


def test_kilograms_and_pounds_convert_exactly_both_ways(targets: list[dict]) -> None:
    table = ("Item    Description    Qty    Unit    Unit Price    Amount\n"
             "R410A-11    Refrigerant R-410A, 11.3 kg cylinder    3    cyl    $300.00    $900.00\n")
    added = _by_field(RefrigerantServiceExtractor().extract(_invoice(table), targets, "EV-1").candidates)[
        "refrigerant_added"]
    assert (added["normalized_value"], added["unit"]) == (33.9, "kg")  # kept in the document's unit, flagged as a purchase
    from backend.app.domain import fuel_units

    assert fuel_units.convert_exact(100, "lb", "kg") == pytest.approx(45.359237)
    assert fuel_units.convert_exact(45.359237, "kg", "lb") == pytest.approx(100)
    assert fuel_units.convert_exact(33.9, "kg", "lb") == pytest.approx(33.9 / 0.45359237)


def test_a_work_order_with_materials_is_not_a_purchase(targets: list[dict]) -> None:
    text = ("Equipment ID: RTU-3\nService Date: 09/12/2025\nWork Performed: Leak repaired and recharged\n"
            "Description    Qty    Unit    Unit Price    Amount\n"
            "R-410A refrigerant 25 lb cylinder    1    cyl    $395.00    $395.00\n")
    added = _by_field(RefrigerantServiceExtractor().extract(_text_output(text), targets, "EV-1").candidates)[
        "refrigerant_added"]
    assert "purchase_not_equipment_charge" not in added["validation_flags"]
    assert added["display_label"] != "Refrigerant purchased"


def test_a_log_is_never_a_purchase(targets: list[dict]) -> None:
    outcome = RefrigerantServiceExtractor().extract(_grid_output([*LOG_HEAD, *LOG_LINES]), targets, "EV-1")
    added = [c for c in outcome.candidates if c["field_name"] == "refrigerant_added"]
    assert added and all("purchase_not_equipment_charge" not in c["validation_flags"] for c in added)
    assert outcome.notes == []


def test_a_header_run_together_with_a_space_is_cut_too_and_an_equipment_register_is_not_a_log(
        targets: list[dict]) -> None:
    """The staging log: "Refrigerant Full Charge (kg)" is one header cell over two data cells, and an
    equipment register above the log has a Refrigerant column too but no amounts."""

    register = [
        [("Equipment Register", 0.05, 0.2)],
        [("Equipment ID", 0.05, 0.1), ("Description", 0.2, 0.1), ("Refrigerant", 0.45, 0.07), ("Full Charge (kg)", 0.6, 0.12)],
        [("HW-RC-01", 0.05, 0.08), ("Walk-in cooler, condensing unit", 0.2, 0.22), ("R-404A", 0.45, 0.05), ("18.2", 0.6, 0.03)],
    ]
    head = [[("Date", 0.05, 0.04), ("Equipment ID", 0.15, 0.1), ("Refrigerant Full Charge (kg)", 0.3, 0.22),
             ("Added (kg)", 0.55, 0.07), ("Recovered (kg)", 0.64, 0.09), ("Technician", 0.75, 0.08),
             ("Work Performed", 0.85, 0.12)]]
    line = [("04/09/2025", 0.05, 0.07), ("HW-RF-02", 0.15, 0.07), ("R-404A", 0.3, 0.05), ("24.5", 0.45, 0.03),
            ("24.50", 0.56, 0.04), ("21.30", 0.66, 0.04), ("T. Vasquez-Hale", 0.75, 0.1), ("Leak at evaporator coil", 0.85, 0.12)]
    other = [("06/27/2025", 0.05, 0.07), ("HW-RC-01", 0.15, 0.07), ("R-404A", 0.3, 0.05), ("18.2", 0.45, 0.03),
             ("3.15", 0.56, 0.03), ("0.00", 0.66, 0.03), ("R. Delacroix", 0.75, 0.08), ("Schrader core replaced", 0.85, 0.12)]
    records = _log_records([*register, *head, line, other], targets)
    assert len(records) == 2  # the register is not a service line
    first = records[1]
    assert first["equipment_id"]["normalized_value"] == "HW-RF-02"
    assert _value(first, "refrigerant_added") == (24.5, "kg") and _value(first, "refrigerant_recovered") == (21.3, "kg")
    assert _value(first, "equipment_capacity") == (24.5, "kg")
    assert first["technician"]["normalized_value"] == "T. Vasquez-Hale"


def test_a_supplier_invoice_priced_per_pound_is_a_purchase_even_with_a_site_called_maintenance(
        targets: list[dict]) -> None:
    text = ("POLAR RIDGE Refrigerant Supply\n"
            "BILL TO    SHIP TO\n"
            "Staging-Test Foods Inc.    Riverside Plant - Maintenance\n"
            "Item    Description    Cyl.    Lbs / Cyl.    Total Lbs    Price / Lb    Amount\n"
            "R134A-30    Refrigerant R-134a (HFC-134a), 30 lb returnable cylinder    4    30    120    $9.85    $1,182.00\n"
            "Total refrigerant shipped: 120 lb (4 cylinders x 30 lb). 1 lb = 0.4536 kg.\n")
    added = _by_field(RefrigerantServiceExtractor().extract(_text_output(text), targets, "EV-1").candidates)[
        "refrigerant_added"]
    assert (added["normalized_value"], added["unit"]) == (120, "lb")
    assert added["display_label"] == "Refrigerant purchased"
    assert "purchase_not_equipment_charge" in added["validation_flags"]


# --- review fixes: recovered is never booked as added; a totals table is not service lines ------------------
RECOVERED_HEADERS = ["Amount Removed (lb)", "Qty Removed (lb)", "Quantity Recovered (lb)", "Amount Reclaimed (lb)",
                     "Refrigerant Removed (lb)", "Quantity Removed (lb)", "Amount Recovered (lb)"]


def _recovery_rows(header: str, number_left: float) -> list[list[tuple]]:
    head = [("Date", 0.05, 0.04), ("Equipment", 0.15, 0.08), ("Refrigerant", 0.3, 0.08), (header, 0.45, 0.14),
            ("Technician", 0.65, 0.08)]
    row = [("10/02/2025", 0.05, 0.07), ("CH-1", 0.15, 0.04), ("R-134a", 0.3, 0.05), ("95.0", number_left, 0.03),
           ("J. Doe", 0.65, 0.05)]
    return [head, row]


@pytest.mark.parametrize("header", RECOVERED_HEADERS)
@pytest.mark.parametrize("number_left", [0.45, 0.56])  # left-aligned and right-aligned numbers
def test_a_recovery_header_is_recovered_never_added_in_a_boxed_log(
        targets: list[dict], header: str, number_left: float) -> None:
    only = _log_records(_recovery_rows(header, number_left), targets)[1]
    assert _value(only, "refrigerant_recovered") == (95, "lb")
    assert only["refrigerant_added"]["normalized_value"] is None
    assert only["technician"]["normalized_value"] == "J. Doe"


@pytest.mark.parametrize("header", RECOVERED_HEADERS)
def test_a_recovery_header_is_recovered_never_added_in_plain_text(targets: list[dict], header: str) -> None:
    text = (f"Date    Equipment    Refrigerant    {header}    Technician\n"
            "10/02/2025    CH-1    R-134a    95.0    J. Doe\n")
    fields = _by_field(RefrigerantServiceExtractor().extract(_text_output(text), targets, "EV-1").candidates)
    assert (fields["refrigerant_recovered"]["normalized_value"], fields["refrigerant_recovered"]["unit"]) == (95, "lb")
    assert fields["refrigerant_added"]["normalized_value"] is None


@pytest.mark.parametrize("header", ["Amount Added", "Qty Added", "Amount Removed", "Quantity Recovered",
                                    "Equipment ID", "Service Type", "Date Serviced", "Full Charge", "Work Performed",
                                    "Total Recovered", "Refrigerant Type", "Gas Type"])
def test_real_headers_are_never_cut(header: str) -> None:
    from backend.app.services.refrigerant_extractor import Cell, Row

    row = Row([Cell(header, 1, {"left": 0.1, "top": 0.1, "width": 0.2, "height": 0.01}, None, None, None, 0)], 1)
    assert RefrigerantServiceExtractor._split_glued_headers(row) is row


@pytest.mark.parametrize("glued", ["Amount Removed", "Added Recovered", "Qty Added Qty Removed", "Date Equipment"])
def test_two_columns_that_are_not_the_refrigerant_are_never_cut_apart(glued: str) -> None:
    from backend.app.services.refrigerant_extractor import Cell, Row

    row = Row([Cell(glued, 1, {"left": 0.1, "top": 0.1, "width": 0.2, "height": 0.01}, None, None, None, 0)], 1)
    assert [c.text for c in RefrigerantServiceExtractor._split_glued_headers(row).cells] == [glued]


def test_the_gas_beside_an_amount_column_is_cut_both_ways() -> None:
    from backend.app.services.refrigerant_extractor import Cell, Row

    def cut(text: str) -> list[str]:
        row = Row([Cell(text, 1, {"left": 0.1, "top": 0.1, "width": 0.2, "height": 0.01}, None, None, None, 0)], 1)
        return [c.text for c in RefrigerantServiceExtractor._split_glued_headers(row).cells]

    assert cut("RefrigerantFull Charge (lb)") == ["Refrigerant", "Full Charge (lb)"]
    assert cut("Refrigerant Full Charge (kg)") == ["Refrigerant", "Full Charge (kg)"]
    assert cut("Gas Added (lb)") == ["Gas", "Added (lb)"]


# a totals table whose columns line up with the log's, under its own header
ALIGNED_TOTALS: list[list[tuple]] = [
    [("Totals by refrigerant", 0.05, 0.2)],
    [("Gas", 0.293, 0.03), ("Added (lb)", 0.465, 0.06), ("Recovered (lb)", 0.54, 0.083)],
    [("R-404A", 0.293, 0.04), ("20.5", 0.50, 0.025), ("0.0", 0.607, 0.016)],
    [("R-134a", 0.293, 0.04), ("10.5", 0.50, 0.025), ("0.0", 0.607, 0.016)],
]
HEADERLESS_SUMMARY: list[list[tuple]] = [
    [("Summary", 0.05, 0.2)],
    [("", 0, 0), ("", 0, 0), ("R-404A", 0.293, 0.04), ("20.5", 0.50, 0.025), ("0.0", 0.607, 0.016)],
    [("", 0, 0), ("", 0, 0), ("R-134a", 0.293, 0.04), ("10.5", 0.50, 0.025), ("0.0", 0.607, 0.016)],
]


@pytest.mark.parametrize("totals", [ALIGNED_TOTALS, HEADERLESS_SUMMARY], ids=["aligned table", "headerless rows"])
def test_a_totals_table_under_the_log_is_never_counted_twice(targets: list[dict], totals: list[list[tuple]]) -> None:
    from backend.app.services.refrigerant_extractor import TOTALS_NOTE

    outcome = RefrigerantServiceExtractor().extract(_grid_output([*LOG_HEAD, *LOG_LINES, *totals]), targets, "EV-1")
    records = _by_record(outcome.candidates)
    assert len(records) == 4
    by_gas: dict[str, float] = {}
    for fields in records.values():
        gas = fields["refrigerant_type"]["normalized_value"]
        by_gas[gas] = by_gas.get(gas, 0) + fields["refrigerant_added"]["normalized_value"]
    assert by_gas == {"R-404A": 20.5, "HFC-134a": 10.5}  # not 41 lb: the totals are not lines
    assert TOTALS_NOTE in outcome.notes


def _by_record(candidates: list[dict]) -> dict[int, dict[str, dict]]:
    indexes = sorted({c["record_index"] for c in candidates if c["record_index"] is not None})
    return {i: _by_field(candidates, i) for i in indexes}


def test_a_totals_table_in_kilograms_still_matches_the_lines_in_pounds(targets: list[dict]) -> None:
    totals = [row for row in ALIGNED_TOTALS]
    totals[1] = [("Gas", 0.293, 0.03), ("Added (kg)", 0.465, 0.06), ("Recovered (kg)", 0.54, 0.083)]
    totals[2] = [("R-404A", 0.293, 0.04), (f"{20.5 * 0.45359237:.4f}", 0.50, 0.025), ("0.0", 0.607, 0.016)]
    totals[3] = [("R-134a", 0.293, 0.04), (f"{10.5 * 0.45359237:.4f}", 0.50, 0.025), ("0.0", 0.607, 0.016)]
    outcome = RefrigerantServiceExtractor().extract(_grid_output([*LOG_HEAD, *LOG_LINES, *totals]), targets, "EV-1")
    assert len(_by_record(outcome.candidates)) == 4


def test_a_second_table_that_is_not_the_sum_of_the_first_is_more_service_lines(targets: list[dict]) -> None:
    more = [
        [("Date", 0.05, 0.04), ("Equipment", 0.15, 0.08), ("Refrigerant", 0.3, 0.08), ("Added (lb)", 0.45, 0.06),
         ("Recovered (lb)", 0.54, 0.08)],
        [("09/01/2025", 0.05, 0.07), ("RACK-B", 0.15, 0.05), ("R-404A", 0.3, 0.05), ("7.0", 0.45, 0.03),
         ("0.0", 0.54, 0.03)],
    ]
    outcome = RefrigerantServiceExtractor().extract(_grid_output([*LOG_HEAD, *LOG_LINES, *more]), targets, "EV-1")
    assert len(_by_record(outcome.candidates)) == 5
    assert outcome.notes == []


def test_a_log_line_with_a_date_and_no_equipment_is_still_a_service_line(targets: list[dict]) -> None:
    line = _log_row("09/01/2025", "", "R-404A", "180", "2.0", "0.0", "José Muñoz", "Top-up")
    records = _log_records([*LOG_HEAD, *LOG_LINES, line], targets)
    assert len(records) == 5 and records[5]["service_date"]["normalized_value"] == "2025-09-01"


# --- a contractor's invoice is not a purchase; a supplier's price list is -----------------------------------
def test_a_contractors_invoice_with_the_work_in_free_text_is_not_a_purchase(targets: list[dict]) -> None:
    text = ("ACME MECHANICAL SERVICES    INVOICE\nInvoice Date    09/12/2025\n"
            "Found leak at rooftop unit RTU-3 brazed joint, repaired and recharged system.\n"
            "Description    Qty    Unit    Unit Price    Amount\n"
            "R-410A refrigerant 25 lb cylinder    1    cyl    $395.00    $395.00\n"
            "Labor    3    hr    $120.00    $360.00\n")
    outcome = RefrigerantServiceExtractor().extract(_text_output(text), targets, "EV-1")
    added = _by_field(outcome.candidates)["refrigerant_added"]
    assert "purchase_not_equipment_charge" not in added["validation_flags"]
    assert added["display_label"] != "Refrigerant purchased" and outcome.notes == []


@pytest.mark.parametrize("price_header", ["Cost / Cyl", "Cost", "Ext.", "$/Cyl", "Unit Price", "Price Each"])
def test_a_supplier_invoice_is_a_purchase_whatever_its_price_column_is_called(
        targets: list[dict], price_header: str) -> None:
    table = (f"Item    Description    Qty    Unit    {price_header}    Amount\n"
             "R410A-25    Refrigerant R-410A, 25 lb disposable cylinder    4    cyl    $395.00    $1,580.00\n")
    added = _by_field(RefrigerantServiceExtractor().extract(_invoice(table), targets, "EV-1").candidates)[
        "refrigerant_added"]
    assert "purchase_not_equipment_charge" in added["validation_flags"]


def test_a_supplier_selling_by_the_pound_is_a_purchase(targets: list[dict]) -> None:
    text = ("WESTBAY REFRIGERANT SUPPLY    INVOICE\nInvoice Date    09/17/2025\n"
            "Item    Description    Qty    Unit    Unit Price    Amount\n"
            "R410A-BULK    Refrigerant R-410A bulk    100    lb    $15.00    $1,500.00\n")
    outcome = RefrigerantServiceExtractor().extract(_text_output(text), targets, "EV-1")
    added = _by_field(outcome.candidates)["refrigerant_added"]
    assert (added["normalized_value"], added["unit"]) == (100, "lb")
    assert "purchase_not_equipment_charge" in added["validation_flags"] and added["display_label"] == "Refrigerant purchased"


# --- the real layouts, as the parser reads them (fictional documents; no PDFs in the repo) --------------------
def _fixture(name: str) -> dict[str, Any]:
    import json
    from pathlib import Path

    return json.loads((Path(__file__).parent / "data" / name).read_text(encoding="utf-8"))


def test_the_staging_harbor_log_reads_as_eight_service_lines(targets: list[dict]) -> None:
    outcome = RefrigerantServiceExtractor().extract(_fixture("stg_harbor_refrigerant_service.parser.json"), targets, "EV-1")
    records = _by_record(outcome.candidates)
    assert len(records) == 8 and outcome.notes == []
    rows = [(r["service_date"]["normalized_value"], r["equipment_id"]["normalized_value"],
             r["refrigerant_type"]["normalized_value"], r["refrigerant_added"]["normalized_value"],
             r["refrigerant_recovered"]["normalized_value"], r["technician"]["normalized_value"])
            for r in records.values()]
    assert rows[0] == ("2025-01-22", "HW-RC-01", "R-404A", 2.4, 0, "T. Vasquez-Hale")
    assert rows[2] == ("2025-04-09", "HW-RF-02", "R-404A", 24.5, 21.3, "T. Vasquez-Hale")
    assert rows[4] == ("2025-08-05", "HW-AC-03", "R-410A", 9.8, 8.95, "M. Ibekwe")
    assert {r["refrigerant_added"]["unit"] for r in records.values()} == {"kg"}
    assert round(sum(r["refrigerant_added"]["normalized_value"] for r in records.values()
                     if r["refrigerant_type"]["normalized_value"] == "R-404A"), 2) == 33.1  # the log's own total
    assert {r["service_provider"]["normalized_value"] for r in records.values()} == {"ColdCrest Mechanical Services"}


def test_the_npl_sacramento_log_reads_as_eight_service_lines_with_accents_intact(targets: list[dict]) -> None:
    outcome = RefrigerantServiceExtractor().extract(_fixture("npl_sacramento_refrigerant_log.parser.json"), targets, "EV-1")
    records = _by_record(outcome.candidates)
    assert len(records) == 8  # the two totals rows are not lines (their amounts are the sums of the lines)
    assert [r["technician"]["normalized_value"] for r in records.values()] == [
        "José Muñoz", "Renée Côté", "José Muñoz", "Renée Côté", "Zoë Brandão", "José Muñoz", "Renée Côté", "Zoë Brandão"]
    totals: dict[str, float] = {}
    for r in records.values():
        gas = r["refrigerant_type"]["normalized_value"]
        totals[gas] = totals.get(gas, 0) + r["refrigerant_added"]["normalized_value"]
    assert totals == {"R-404A": 51.5, "HFC-134a": 13.5}
    assert {r["service_provider"]["normalized_value"] for r in records.values()} == {"POLAR POINT MECHANICAL SERVICES"}
