"""Generate the EXT-001 stationary-combustion golden samples (synthetic PDFs).

    python scripts/generate_stationary_combustion_samples.py

Writes ``s1-test-suite/stationary_combustion/documents/*.pdf`` and the matching
``expected/*.expected.json``. Every supplier, customer, address and account is
fictional. The PDFs are committed; rerun this only to change a sample, then review
the diff of both the PDF and its expectation.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import fitz  # pymupdf

ROOT = Path(__file__).resolve().parents[1] / "s1-test-suite" / "stationary_combustion"
DOCS = ROOT / "documents"
EXPECTED = ROOT / "expected"

PAGE_W, PAGE_H = 612, 792  # US Letter
FONT = "helv"
BOLD = "hebo"


class Page:
    def __init__(self, document: fitz.Document) -> None:
        self.page = document.new_page(width=PAGE_W, height=PAGE_H)

    def text(self, x: float, y: float, value: str, size: float = 10, bold: bool = False) -> None:
        self.page.insert_text((x, y), value, fontsize=size, fontname=BOLD if bold else FONT)

    def right(self, x_right: float, y: float, value: str, size: float = 10, bold: bool = False) -> None:
        width = fitz.get_text_length(value, fontname=BOLD if bold else FONT, fontsize=size)
        self.text(x_right - width, y, value, size, bold)

    def rule(self, x0: float, y: float, x1: float) -> None:
        self.page.draw_line((x0, y), (x1, y), width=0.6)

    def table(
        self,
        x: float,
        y: float,
        columns: list[tuple[str, float, str]],
        rows: list[list[str]],
        ruled: bool = True,
        row_h: float = 16,
    ) -> float:
        """columns: (header, width, align 'l'|'r'). Returns the y after the table."""
        x_pos = x
        for header, width, align in columns:
            if align == "r":
                self.right(x_pos + width - 4, y, header, 9, bold=True)
            else:
                self.text(x_pos + 2, y, header, 9, bold=True)
            x_pos += width
        total_w = sum(c[1] for c in columns)
        if ruled:
            self.rule(x, y + 4, x + total_w)
        y += row_h
        for row in rows:
            x_pos = x
            for (_, width, align), cell in zip(columns, row):
                if align == "r":
                    self.right(x_pos + width - 4, y, cell, 9)
                else:
                    self.text(x_pos + 2, y, cell, 9)
                x_pos += width
            y += row_h
        if ruled:
            self.rule(x, y - row_h + 4, x + total_w)
        return y


def save(document: fitz.Document, name: str) -> str:
    DOCS.mkdir(parents=True, exist_ok=True)
    path = DOCS / name
    document.set_metadata({"producer": "sustentra-ext001-samples", "creationDate": "", "modDate": ""})
    document.save(path, garbage=4, deflate=True, no_new_id=True)
    document.close()
    return name


def expect(document_id: str, file_name: str, description: str, **payload: Any) -> None:
    EXPECTED.mkdir(parents=True, exist_ok=True)
    data = {"document_id": document_id, "file": file_name, "description": description, **payload}
    (EXPECTED / f"{document_id}.expected.json").write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------------------
def sc01_single_meter_therms() -> None:
    doc = fitz.open()
    p = Page(doc)
    p.text(50, 60, "Lakeshore Gas Company", 18, bold=True)
    p.text(50, 76, "PO Box 4410, Erie, PA 16512  |  lakeshoregas.example", 8)
    p.right(562, 60, "NATURAL GAS SERVICE STATEMENT", 11, bold=True)
    p.text(50, 120, "Customer:", 10, bold=True)
    p.text(140, 120, "Harborview Cold Storage LLC")
    p.text(50, 136, "Service Address:", 10, bold=True)
    p.text(140, 136, "210 Dock Street, Erie, PA 16507")
    p.text(50, 152, "Account Number:", 10, bold=True)
    p.text(140, 152, "4410-77812-03")
    p.text(340, 120, "Bill Date: 02/06/2024")
    p.text(340, 136, "Service Period: 01/03/2024 - 02/01/2024")
    p.text(340, 152, "Rate: GS-2 Commercial Firm")
    p.text(50, 196, "Meter Reading Detail", 11, bold=True)
    p.table(
        50,
        216,
        [("Meter Number", 110, "l"), ("Previous Read", 90, "r"), ("Current Read", 90, "r"),
         ("Difference (CCF)", 100, "r"), ("Therm Factor", 70, "r"), ("Usage (Therms)", 90, "r")],
        [["LG-5503318", "48,112", "49,358", "1,246", "1.031", "1,284"]],
    )
    p.text(50, 290, "Charges", 11, bold=True)
    p.text(50, 308, "Customer charge")
    p.right(562, 308, "$38.50")
    p.text(50, 324, "Distribution 1,284 therms @ $0.4120")
    p.right(562, 324, "$529.01")
    p.text(50, 340, "Gas supply 1,284 therms @ $0.6385")
    p.right(562, 340, "$819.83")
    p.text(50, 364, "Amount Due", 11, bold=True)
    p.right(562, 364, "$1,387.34", 11, bold=True)
    name = save(doc, "SC-01_lakeshore_gas_single_meter_therms.pdf")
    expect(
        "SC-01", name, "Natural gas bill, one meter, usage in therms (converted to MMBtu); labels and values in separate columns.",
        expected_classification="CT-S1-FUELQTY", expected_halt=None,
        document_fields={
            "facility_name": "Harborview Cold Storage LLC",
            "service_address": "210 Dock Street, Erie, PA 16507",
            "supplier_name": "Lakeshore Gas Company",
            "account_number": "4410-77812-03",
        },
        records=[{
            "record_hint": "LG-5503318", "fuel_type": "natural_gas", "activity_quantity": 128.4, "activity_unit": "MMBtu",
            "raw_quantity": "1,284", "raw_unit": "therm",
            "service_period_start": "2024-01-03", "service_period_end": "2024-02-01",
        }],
    )


def sc02_multi_meter_ccf() -> None:
    doc = fitz.open()
    p = Page(doc)
    p.text(50, 58, "PIEDMONT RIDGE NATURAL GAS", 16, bold=True)
    p.text(50, 74, "Commercial Billing Department", 9)
    p.text(50, 112, "Facility: Ridgeview Medical Office Park")
    p.text(50, 128, "Service Location: 1800 Ridgeview Parkway, Greenville, SC 29607")
    p.text(50, 144, "Account No: PRN-0098-221")
    p.text(380, 112, "Statement Date: 03/04/2024")
    p.text(380, 128, "Amount Due: $2,968.11")
    p.text(50, 186, "Usage by Meter", 11, bold=True)
    p.table(
        50,
        206,
        [("Meter #", 95, "l"), ("From", 70, "l"), ("To", 70, "l"), ("Prev Read", 70, "r"),
         ("Pres Read", 70, "r"), ("Usage", 70, "r"), ("Unit", 50, "l")],
        [
            ["PR-A1173", "01/29/2024", "02/27/2024", "20,511", "21,894", "1,383", "CCF"],
            ["PR-A1174", "01/30/2024", "02/28/2024", "7,203", "7,951", "748", "CCF"],
        ],
    )
    p.text(50, 270, "Total Usage")
    p.right(415, 270, "2,131")
    p.text(420, 270, "CCF")
    p.text(50, 300, "Thank you for choosing Piedmont Ridge Natural Gas.", 8)
    name = save(doc, "SC-02_piedmont_ridge_multi_meter_ccf.pdf")
    common = {"fuel_type": "natural_gas", "activity_unit": "ccf", "raw_unit": "ccf"}
    expect(
        "SC-02", name, "Natural gas bill, two meters with different read dates, usage in CCF; one record per meter; total row ignored.",
        expected_classification="CT-S1-FUELQTY", expected_halt=None,
        document_fields={
            "facility_name": "Ridgeview Medical Office Park",
            "service_address": "1800 Ridgeview Parkway, Greenville, SC 29607",
            "supplier_name": "PIEDMONT RIDGE NATURAL GAS",
            "account_number": "PRN-0098-221",
        },
        records=[
            {"record_hint": "PR-A1173", "activity_quantity": 1383, "raw_quantity": "1,383",
             "service_period_start": "2024-01-29", "service_period_end": "2024-02-27", **common},
            {"record_hint": "PR-A1174", "activity_quantity": 748, "raw_quantity": "748",
             "service_period_start": "2024-01-30", "service_period_end": "2024-02-28", **common},
        ],
    )


def sc03_multi_period_dth() -> None:
    doc = fitz.open()
    p = Page(doc)
    p.text(50, 60, "Great Plains Energy Transport", 16, bold=True)
    p.text(50, 76, "Interstate & Local Distribution of Natural Gas", 9)
    p.text(50, 110, "CORRECTED INVOICE - supersedes invoice 77120", 10, bold=True)
    p.text(50, 134, "Bill To")
    p.text(50, 148, "Prairie Grain Processors Inc.")
    p.text(50, 162, "Plant 2 - 900 Elevator Road")
    p.text(50, 176, "Salina, KS 67401")
    p.text(330, 134, "Customer Account")
    p.text(450, 134, "GPE-31-5520")
    p.text(330, 148, "Commodity")
    p.text(450, 148, "Natural Gas")
    p.text(330, 162, "Invoice Date")
    p.text(450, 162, "April 9, 2024")
    p.text(50, 214, "Measured Deliveries", 11, bold=True)
    p.table(
        50,
        234,
        [("Meter", 90, "l"), ("Service Period", 200, "l"), ("Volume (Mcf)", 90, "r"), ("Heat Value", 70, "r"),
         ("Dth", 62, "r")],
        [
            ["GP-7781", "Feb 1, 2024 to Feb 29, 2024", "2,940.0", "1.034", "3,039.96"],
            ["GP-7781", "Mar 1, 2024 to Mar 31, 2024", "2,612.5", "1.031", "2,693.49"],
        ],
        ruled=False,
    )
    p.text(50, 296, "Total Dth", 10, bold=True)
    p.right(562, 296, "5,733.45", 10, bold=True)
    name = save(doc, "SC-03_great_plains_multi_period_dth.pdf")
    common = {"record_hint": "GP-7781", "fuel_type": "natural_gas", "activity_unit": "MMBtu", "raw_unit": "Dth"}
    expect(
        "SC-03", name, "Corrected natural gas invoice with two service periods for one meter, energy in Dth; volume column must not be picked; one record per period.",
        expected_classification="CT-S1-FUELQTY", expected_halt=None,
        document_fields={
            "facility_name": "Prairie Grain Processors Inc.",
            "service_address": None,
            "supplier_name": "Great Plains Energy Transport",
            "account_number": "GPE-31-5520",
        },
        records=[
            {"activity_quantity": 3039.96, "raw_quantity": "3,039.96",
             "service_period_start": "2024-02-01", "service_period_end": "2024-02-29", **common},
            {"activity_quantity": 2693.49, "raw_quantity": "2,693.49",
             "service_period_start": "2024-03-01", "service_period_end": "2024-03-31", **common},
        ],
    )


def sc04_heating_oil_ticket() -> None:
    doc = fitz.open()
    p = Page(doc)
    p.text(50, 60, "Northfield Fuel & Heating Oil Co.", 16, bold=True)
    p.text(50, 76, "Est. 1958  -  24 hr burner service", 9)
    p.right(562, 60, "DELIVERY TICKET", 13, bold=True)
    p.right(562, 76, "Ticket No. 0084213", 10)
    p.text(50, 116, "Customer: St. Brendan Parish School")
    p.text(50, 132, "Ship To: 45 Chapel Hill Rd, Northfield, MA 01360")
    p.text(50, 148, "Customer Acct: NF-1182")
    p.text(380, 116, "Delivery Date: 12/14/2023")
    p.text(380, 132, "Truck: 7    Driver: R. Okafor")
    p.table(
        50,
        190,
        [("Product", 210, "l"), ("Tank", 60, "l"), ("Gallons Delivered", 110, "r"), ("Price/Gal", 70, "r"),
         ("Amount", 62, "r")],
        [["#2 Heating Oil", "T-1", "742.6", "$3.899", "$2,895.40"]],
    )
    p.text(50, 250, "Meter start 118,442.0   Meter stop 119,184.6", 9)
    p.text(50, 276, "Received by: ____________________", 9)
    name = save(doc, "SC-04_northfield_heating_oil_ticket.pdf")
    expect(
        "SC-04", name, "Heating oil delivery ticket; quantity in gallons; delivery date is both period start and end.",
        expected_classification="CT-S1-FUELQTY", expected_halt=None,
        document_fields={
            "facility_name": "St. Brendan Parish School",
            "service_address": "45 Chapel Hill Rd, Northfield, MA 01360",
            "supplier_name": "Northfield Fuel & Heating Oil Co.",
            "account_number": "NF-1182",
        },
        records=[{
            "record_hint": "T-1", "fuel_type": "fuel_oil", "activity_quantity": 742.6, "activity_unit": "gal",
            "raw_quantity": "742.6", "raw_unit": "gal",
            "service_period_start": "2023-12-14", "service_period_end": "2023-12-14",
        }],
    )


def sc05_propane_invoice_liters() -> None:
    doc = fitz.open()
    p = Page(doc)
    p.text(50, 60, "Boreal Propane Ltd.", 16, bold=True)
    p.text(50, 76, "Supplier: Boreal Propane Ltd.  GST 81123 4471 RT0001", 8)
    p.right(562, 60, "INVOICE", 14, bold=True)
    p.text(50, 116, "Sold To")
    p.text(140, 116, "Cedar Lake Lodge")
    p.text(50, 132, "Delivered To")
    p.text(140, 132, "12 Shoreline Road, Huntsville, ON P1H 2J4")
    p.text(50, 148, "Account #")
    p.text(140, 148, "BP-60417")
    p.text(380, 116, "Invoice Date: 2024-01-22")
    p.text(380, 132, "Delivery Date: 2024-01-19")
    p.table(
        50,
        186,
        [("Description", 230, "l"), ("Qty", 80, "r"), ("UOM", 50, "l"), ("Unit Price", 80, "r"), ("Total", 72, "r")],
        [["Propane (HD-5) bulk delivery", "1,915.3", "L", "$0.869", "$1,664.40"],
         ["Tank rental - 1000 USWG", "1", "EA", "$22.00", "$22.00"]],
    )
    p.text(50, 250, "Total due in 30 days. Interest 2% per month on overdue accounts.", 8)
    name = save(doc, "SC-05_boreal_propane_invoice_liters.pdf")
    expect(
        "SC-05", name, "Propane invoice in litres with ISO dates and a non-fuel line item (tank rental) that must be ignored.",
        expected_classification="CT-S1-FUELQTY", expected_halt=None,
        document_fields={
            "facility_name": "Cedar Lake Lodge",
            "service_address": "12 Shoreline Road, Huntsville, ON P1H 2J4",
            "supplier_name": "Boreal Propane Ltd.",
            "account_number": "BP-60417",
        },
        records=[{
            "record_hint": None, "fuel_type": "propane", "activity_quantity": 1915.3, "activity_unit": "L",
            "raw_quantity": "1,915.3", "raw_unit": "L",
            "service_period_start": "2024-01-19", "service_period_end": "2024-01-19",
        }],
    )


def sc06_bulk_diesel_statement() -> None:
    doc = fitz.open()
    p = Page(doc)
    p.text(50, 60, "Summit Bulk Fuels", 16, bold=True)
    p.text(50, 76, "Monthly Statement of Deliveries", 10)
    p.text(50, 112, "Customer: Tri-County Water Reclamation District")
    p.text(50, 128, "Site: Standby Generator Plant, 77 Weir Lane, Lodi, CA 95240")
    p.text(50, 144, "Account Number: SBF-2290")
    p.text(380, 112, "Statement Period: 05/01/2024 - 05/31/2024")
    p.table(
        50,
        186,
        [("Date", 75, "l"), ("Invoice", 70, "l"), ("Product", 150, "l"), ("Gallons", 80, "r"), ("Amount", 80, "r")],
        [
            ["05/03/2024", "88120", "Ultra Low Sulfur Diesel", "1,200.0", "$4,812.00"],
            ["05/17/2024", "88341", "Ultra Low Sulfur Diesel", "950.5", "$3,830.52"],
            ["05/29/2024", "88577", "Ultra Low Sulfur Diesel", "1,104.2", "$4,383.67"],
            ["Total", "", "", "3,254.7", "$13,026.19"],
        ],
    )
    name = save(doc, "SC-06_summit_bulk_diesel_statement.pdf")
    common = {"fuel_type": "diesel", "activity_unit": "gal", "raw_unit": "gal"}
    expect(
        "SC-06", name, "Monthly bulk diesel statement for standby generators; three deliveries become three records; the total row is not a record. "
        "Diesel can be stationary or mobile, and the classifier leans mobile here, so the pipeline must halt until a reviewer sets the type.",
        expected_classification="CT-S1-FUELQTY", expected_halt=None,
        reviewer_override="CT-S1-FUELQTY", expected_halt_without_override="unsupported_document",
        document_fields={
            "facility_name": "Standby Generator Plant",
            "service_address": "77 Weir Lane, Lodi, CA 95240",
            "supplier_name": "Summit Bulk Fuels",
            "account_number": "SBF-2290",
        },
        records=[
            {"record_hint": "88120", "activity_quantity": 1200.0, "raw_quantity": "1,200.0",
             "service_period_start": "2024-05-03", "service_period_end": "2024-05-03", **common},
            {"record_hint": "88341", "activity_quantity": 950.5, "raw_quantity": "950.5",
             "service_period_start": "2024-05-17", "service_period_end": "2024-05-17", **common},
            {"record_hint": "88577", "activity_quantity": 1104.2, "raw_quantity": "1,104.2",
             "service_period_start": "2024-05-29", "service_period_end": "2024-05-29", **common},
        ],
    )


def sc07_mcf_label_value() -> None:
    doc = fitz.open()
    p = Page(doc)
    p.text(50, 60, "Utility: Cascade Valley Gas Utilities", 13, bold=True)
    p.text(50, 100, "Facility Name: Riverbend Paper Mill")
    p.text(50, 116, "Service Address: 3 Mill Race Road, Longview, WA 98632")
    p.text(50, 132, "Account Number: CVG 22-81003-7")
    p.text(50, 148, "Fuel Type: Natural Gas - Industrial Interruptible")
    p.text(50, 172, "Period Start: 2024-06-01")
    p.text(250, 172, "Period End: 2024-06-30")
    p.text(50, 196, "Total Usage: 18,442.7 MCF")
    p.text(50, 212, "Average daily usage: 614.8 MCF")
    p.text(50, 236, "Total Current Charges: $112,804.15")
    name = save(doc, "SC-07_cascade_valley_mcf_label_value.pdf")
    expect(
        "SC-07", name, "Industrial gas bill with label: value lines only (no table), separate period start/end labels, usage in Mcf; the daily average must not be picked.",
        expected_classification="CT-S1-FUELQTY", expected_halt=None,
        document_fields={
            "facility_name": "Riverbend Paper Mill",
            "service_address": "3 Mill Race Road, Longview, WA 98632",
            "supplier_name": "Cascade Valley Gas Utilities",
            "account_number": "CVG 22-81003-7",
        },
        records=[{
            "record_hint": None, "fuel_type": "natural_gas", "activity_quantity": 18442.7, "activity_unit": "Mcf",
            "raw_quantity": "18,442.7", "raw_unit": "Mcf",
            "service_period_start": "2024-06-01", "service_period_end": "2024-06-30",
        }],
    )


def sc08_scanned_image_only() -> None:
    doc = fitz.open()
    page = doc.new_page(width=PAGE_W, height=PAGE_H)
    # A "scan": a grey raster with no text layer.
    pix = fitz.Pixmap(fitz.csGRAY, fitz.IRect(0, 0, 200, 260), False)
    pix.clear_with(200)
    page.insert_image(fitz.Rect(40, 40, 572, 752), pixmap=pix)
    name = save(doc, "SC-08_scanned_bill_no_text_layer.pdf")
    expect(
        "SC-08", name, "Scanned bill with no text layer (OCR disabled locally): must halt as unreadable.",
        expected_classification=None, expected_halt="unreadable_document",
        document_fields={}, records=[],
    )


def sc09_water_bill_unsupported() -> None:
    doc = fitz.open()
    p = Page(doc)
    p.text(50, 60, "Clearwater Municipal Water Authority", 15, bold=True)
    p.text(50, 100, "Account Number: CMW-55102")
    p.text(50, 116, "Service Address: 210 Dock Street, Erie, PA 16507")
    p.text(50, 132, "Billing Period: 01/01/2024 - 01/31/2024")
    p.table(
        50,
        170,
        [("Meter Number", 110, "l"), ("Previous Read", 90, "r"), ("Current Read", 90, "r"), ("Usage", 80, "r"),
         ("Unit", 60, "l")],
        [["W-88213", "4,411", "4,529", "118", "CCF"]],
    )
    p.text(50, 230, "Water and sewer service. Total usage 118 CCF (88,264 gallons).")
    p.text(50, 246, "Meter read by route 12.  Amount Due: $642.18")
    name = save(doc, "SC-09_water_bill_unsupported.pdf")
    expect(
        "SC-09", name, "Water bill that looks like a gas bill (meter, CCF, billing period) but burns no fuel: must halt as unsupported.",
        expected_classification=None, expected_halt="unsupported_document",
        document_fields={}, records=[],
    )


def main() -> None:
    for build in (
        sc01_single_meter_therms,
        sc02_multi_meter_ccf,
        sc03_multi_period_dth,
        sc04_heating_oil_ticket,
        sc05_propane_invoice_liters,
        sc06_bulk_diesel_statement,
        sc07_mcf_label_value,
        sc08_scanned_image_only,
        sc09_water_bill_unsupported,
    ):
        build()
    print(f"wrote {len(list(DOCS.glob('*.pdf')))} documents to {DOCS}")


if __name__ == "__main__":
    main()
