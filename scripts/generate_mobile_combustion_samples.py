"""Generate the EXT-002 mobile-combustion golden samples (synthetic PDFs).

    python scripts/generate_mobile_combustion_samples.py

Writes ``s1-test-suite/mobile_combustion/documents/*.pdf`` and the matching
``expected/*.expected.json``. Every merchant, fleet, driver, plate and card number is
fictional. Rerun only to change a sample, then review both diffs.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import fitz  # pymupdf

sys.path.insert(0, str(Path(__file__).resolve().parent))
from generate_stationary_combustion_samples import PAGE_H, PAGE_W, Page  # noqa: E402

ROOT = Path(__file__).resolve().parents[1] / "s1-test-suite" / "mobile_combustion"
DOCS = ROOT / "documents"
EXPECTED = ROOT / "expected"
TYPE = "CT-S1-MOBFUEL"


def save(document: fitz.Document, name: str) -> str:
    DOCS.mkdir(parents=True, exist_ok=True)
    document.set_metadata({"producer": "sustentra-ext002-samples", "creationDate": "", "modDate": ""})
    document.save(DOCS / name, garbage=4, deflate=True, no_new_id=True)
    document.close()
    return name


def expect(document_id: str, file_name: str, description: str, **payload: Any) -> None:
    EXPECTED.mkdir(parents=True, exist_ok=True)
    data = {"document_id": document_id, "file": file_name, "description": description, **payload}
    (EXPECTED / f"{document_id}.expected.json").write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def rec(date: str, fuel: str, qty: float, raw_qty: str, unit: str, raw_unit: str, **more: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "transaction_date": date, "fuel_type": fuel, "activity_quantity": qty, "activity_unit": unit,
        "raw_quantity": raw_qty, "raw_unit": raw_unit, "biofuel_blend_pct": None,
    }
    base.update(more)
    return base


# ---------------------------------------------------------------------------------------
def mf01_fleet_card_statement() -> None:
    doc = fitz.open()
    p = Page(doc)
    p.text(40, 50, "Northline Fleet Card", 16, bold=True)
    p.text(40, 64, "Monthly Fleet Fuel Statement", 9)
    p.text(40, 96, "Account Number: NFC-20931")
    p.text(40, 110, "Fleet: Harborview Cold Storage LLC")
    p.text(380, 96, "Statement Period: 03/01/2024 - 03/31/2024")
    cols = [("Date", 52, "l"), ("Card", 52, "l"), ("Unit #", 40, "l"), ("Driver", 62, "l"), ("Merchant", 92, "l"),
            ("City", 64, "l"), ("Product", 70, "l"), ("Odometer", 50, "r"), ("Gallons", 44, "r"), ("Amount", 46, "r")]
    rows = [
        ["03/02/2024", "****0417", "T-101", "A. Rivera", "River Fuel Stop", "Akron, OH", "Diesel #2", "128,455", "42.310", "$164.97"],
        ["03/02/2024", "****0417", "T-101", "A. Rivera", "River Fuel Stop", "Akron, OH", "DEF", "128,455", "2.500", "$10.50"],
        ["03/05/2024", "****0522", "V-12", "J. Chen", "Corner Gas", "Kent, OH", "Unleaded Reg", "48,211", "15.880", "$51.75"],
        ["03/09/2024", "****0522", "V-12", "J. Chen", "Corner Gas", "Kent, OH", "Car Wash", "48,390", "1", "$9.00"],
        ["03/14/2024", "****0417", "T-101", "A. Rivera", "Lakeview Travel Ctr", "Erie, PA", "B20 Diesel", "129,102", "55.020", "$209.63"],
        ["03/21/2024", "****0630", "T-107", "M. Osei", "River Fuel Stop", "Akron, OH", "Diesel #2", "77,014", "38.905", "$150.85"],
    ]
    p.table(40, 146, cols, rows, row_h=15)
    name = save(doc, "MF-01_northline_fleet_card_statement.pdf")
    expect(
        "MF-01", name, "Fleet fuel-card statement: one record per fuel transaction; DEF and car wash lines skipped; "
        "odometer column ignored; masked card per line; B20 is diesel with a 20% blend.",
        expected_classification=TYPE, expected_halt=None,
        document_fields={},
        records=[
            rec("2024-03-02", "diesel", 42.31, "42.310", "gal", "gal", record_hint="T-101", vehicle_or_equipment_id="T-101",
                merchant_or_supplier="River Fuel Stop", fueling_location="Akron, OH", account_number="****0417"),
            rec("2024-03-05", "gasoline", 15.88, "15.880", "gal", "gal", record_hint="V-12", vehicle_or_equipment_id="V-12",
                merchant_or_supplier="Corner Gas", fueling_location="Kent, OH", account_number="****0522"),
            rec("2024-03-14", "diesel", 55.02, "55.020", "gal", "gal", record_hint="T-101", vehicle_or_equipment_id="T-101",
                merchant_or_supplier="Lakeview Travel Ctr", fueling_location="Erie, PA", account_number="****0417",
                biofuel_blend_pct=20),
            rec("2024-03-21", "diesel", 38.905, "38.905", "gal", "gal", record_hint="T-107", vehicle_or_equipment_id="T-107",
                merchant_or_supplier="River Fuel Stop", fueling_location="Akron, OH", account_number="****0630"),
        ],
    )


def mf02_pump_receipt() -> None:
    doc = fitz.open()
    page = doc.new_page(width=260, height=420)
    p = Page.__new__(Page)
    p.page = page
    p.text(20, 30, "ROUTE 9 FUEL STOP", 12, bold=True)
    p.text(20, 44, "1201 State Rte 9, Plattsburgh NY", 7)
    p.text(20, 70, "Date: 03/14/2024   07:42", 8)
    p.text(20, 84, "Receipt #: 004417", 8)
    p.text(20, 98, "Pump: 04", 8)
    p.text(20, 120, "UNLEADED REG", 9, bold=True)
    p.text(20, 134, "12.457 GAL @ $3.459/GAL", 9)
    p.text(20, 148, "FUEL TOTAL   $43.09", 9)
    p.text(20, 172, "Fleet Card: ****8814", 8)
    p.text(20, 186, "Vehicle: TRK-22", 8)
    p.text(20, 200, "Odometer: 48211", 8)
    p.text(20, 226, "THANK YOU - DRIVE SAFE", 7)
    name = save(doc, "MF-02_route9_pump_receipt.pdf")
    expect(
        "MF-02", name, "Single pump receipt (narrow page): quantity written as '12.457 GAL @ price'; fleet-card prompts give the vehicle.",
        expected_classification=TYPE, expected_halt=None,
        document_fields={},
        records=[rec("2024-03-14", "gasoline", 12.457, "12.457", "gal", "gal", record_hint=None,
                     vehicle_or_equipment_id="TRK-22", merchant_or_supplier="ROUTE 9 FUEL STOP",
                     transaction_id="004417", account_number="****8814")],
    )


def mf03_diesel_receipt_litres() -> None:
    doc = fitz.open()
    page = doc.new_page(width=280, height=420)
    p = Page.__new__(Page)
    p.page = page
    p.text(20, 30, "Laurentian Truck Stop Inc.", 11, bold=True)
    p.text(20, 44, "Hwy 17, Mattawa ON", 7)
    p.text(20, 70, "Transaction Date: 2024-02-07", 8)
    p.text(20, 84, "Transaction #: LTS-55810", 8)
    p.text(20, 110, "Product: Diesel Clear", 9)
    p.text(20, 124, "Volume: 182.40 L", 9)
    p.text(20, 138, "Price: 1.659 $/L", 9)
    p.text(20, 162, "Unit: T-118", 8)
    p.text(20, 176, "Driver: P. Lindqvist", 8)
    name = save(doc, "MF-03_laurentian_diesel_receipt_litres.pdf")
    expect(
        "MF-03", name, "Canadian diesel receipt in litres with ISO date; 'Unit: T-118' is the vehicle, not a unit of measure.",
        expected_classification=TYPE, expected_halt=None,
        document_fields={},
        records=[rec("2024-02-07", "diesel", 182.4, "182.40", "L", "L", record_hint=None,
                     vehicle_or_equipment_id="T-118", merchant_or_supplier="Laurentian Truck Stop Inc.",
                     transaction_id="LTS-55810")],
    )


def mf04_cng_invoice() -> None:
    doc = fitz.open()
    p = Page(doc)
    p.text(40, 56, "Bluewater CNG Fueling", 15, bold=True)
    p.text(40, 72, "Fleet fueling invoice - compressed natural gas", 9)
    p.text(40, 104, "Customer: Metro Refuse Services")
    p.text(40, 118, "Account #: BW-7720")
    p.text(380, 104, "Invoice #: CNG-2404")
    p.table(
        40, 160,
        [("Date", 80, "l"), ("Vehicle", 80, "l"), ("Product", 120, "l"), ("GGE", 70, "r"), ("Price/GGE", 80, "r"),
         ("Amount", 80, "r")],
        [["04/03/2024", "RT-31", "CNG", "61.4", "$2.49", "$152.89"],
         ["04/03/2024", "RT-32", "CNG", "58.9", "$2.49", "$146.66"],
         ["04/10/2024", "RT-31", "CNG", "63.2", "$2.49", "$157.37"]],
    )
    name = save(doc, "MF-04_bluewater_cng_invoice.pdf")
    common = {"merchant_or_supplier": "Bluewater CNG Fueling",
              "account_number": "BW-7720", "transaction_id": "CNG-2404"}
    expect(
        "MF-04", name, "CNG fleet invoice in gasoline gallon equivalents (kept as GGE); the price column is not the quantity. "
        "The vocabulary has no CNG fleet variant, so the classifier cannot pick a fuel type: halts until a reviewer sets it.",
        expected_classification=TYPE, expected_halt=None,
        reviewer_override=TYPE, expected_halt_without_override="unsupported_document",
        document_fields={},
        records=[
            rec("2024-04-03", "cng", 61.4, "61.4", "GGE", "GGE", record_hint="RT-31", vehicle_or_equipment_id="RT-31", **common),
            rec("2024-04-03", "cng", 58.9, "58.9", "GGE", "GGE", record_hint="RT-32", vehicle_or_equipment_id="RT-32", **common),
            rec("2024-04-10", "cng", 63.2, "63.2", "GGE", "GGE", record_hint="RT-31", vehicle_or_equipment_id="RT-31", **common),
        ],
    )


def mf05_forklift_propane() -> None:
    doc = fitz.open()
    p = Page(doc)
    p.text(40, 56, "Valley Propane Exchange", 15, bold=True)
    p.text(40, 72, "Forklift cylinder service", 9)
    p.text(40, 104, "Customer: Harborview Cold Storage LLC")
    p.text(40, 118, "Delivery Date: 05/06/2024")
    p.text(40, 132, "Invoice #: VPX-10422")
    p.text(40, 146, "Equipment: Forklift fleet FL-1 to FL-6")
    p.text(40, 176, "Product: Propane (forklift cylinders, 33.5 lb x 12)")
    p.text(40, 190, "Total Propane Weight: 402 lb")
    p.text(40, 204, "Cylinder deposit: $0.00")
    name = save(doc, "MF-05_valley_propane_forklift.pdf")
    expect(
        "MF-05", name, "Forklift (non-road) propane cylinder exchange: quantity by weight in lb; cylinder count is not the quantity. "
        "The classifier leans stationary (propane delivery) but the document says forklift: halts until a reviewer sets the type.",
        expected_classification=TYPE, expected_halt=None,
        reviewer_override=TYPE, expected_halt_without_override="unsupported_document",
        document_fields={},
        records=[rec("2024-05-06", "propane", 402, "402", "lb", "lb", record_hint=None,
                     vehicle_or_equipment_id="Forklift fleet FL-1 to FL-6", merchant_or_supplier="Valley Propane Exchange",
                     transaction_id="VPX-10422")],
    )


def mf06_uk_statement_two_pages() -> None:
    doc = fitz.open()
    cols = [("Date", 70, "l"), ("Vehicle", 80, "l"), ("Site", 140, "l"), ("Product", 90, "l"), ("Litres", 70, "r"),
            ("Net", 70, "r")]
    p1 = Page(doc)
    p1.text(40, 56, "Kestrel Fuelcard Ltd", 15, bold=True)
    p1.text(40, 72, "Fuel card statement", 9)
    p1.text(40, 104, "Account No: KF-118204")
    p1.text(380, 104, "Statement Date: 31/03/2024")
    p1.table(40, 150, cols, [
        ["04/03/2024", "KX19 ABC", "Kestrel Leeds Ring Rd", "Diesel", "68.40", "£96.10"],
        ["04/03/2024", "KX19 ABC", "Kestrel Leeds Ring Rd", "AdBlue", "10.00", "£8.90"],
        ["12/03/2024", "LM70 XYZ", "Kestrel York North", "Unleaded", "41.25", "£58.33"],
        ["19/03/2024", "KX19 ABC", "Kestrel Leeds Ring Rd", "Diesel", "71.06", "£99.84"],
    ])
    p1.text(260, 760, "Page 1 of 2", 8)
    p2 = Page(doc)
    p2.text(40, 50, "Kestrel Fuelcard Ltd - continued", 9)
    p2.table(40, 90, cols, [
        ["26/03/2024", "LM70 XYZ", "Kestrel York North", "Unleaded", "39.80", "£56.28"],
        ["28/03/2024", "PN21 QRS", "Kestrel Hull Docks", "Diesel", "84.12", "£118.19"],
    ])
    name = save(doc, "MF-06_kestrel_uk_statement_two_pages.pdf")
    common = {"account_number": "KF-118204"}
    expect(
        "MF-06", name, "UK fuel-card statement: litres, day-first dates (31/03), table continues on page 2 under a repeated header; AdBlue skipped.",
        expected_classification=TYPE, expected_halt=None,
        document_fields={},
        records=[
            rec("2024-03-04", "diesel", 68.4, "68.40", "L", "L", record_hint="KX19 ABC", vehicle_or_equipment_id="KX19 ABC",
                merchant_or_supplier="Kestrel Leeds Ring Rd", **common),
            rec("2024-03-12", "gasoline", 41.25, "41.25", "L", "L", record_hint="LM70 XYZ", vehicle_or_equipment_id="LM70 XYZ",
                merchant_or_supplier="Kestrel York North", **common),
            rec("2024-03-19", "diesel", 71.06, "71.06", "L", "L", record_hint="KX19 ABC", vehicle_or_equipment_id="KX19 ABC",
                merchant_or_supplier="Kestrel Leeds Ring Rd", **common),
            rec("2024-03-26", "gasoline", 39.8, "39.80", "L", "L", record_hint="LM70 XYZ", vehicle_or_equipment_id="LM70 XYZ",
                merchant_or_supplier="Kestrel York North", **common),
            rec("2024-03-28", "diesel", 84.12, "84.12", "L", "L", record_hint="PN21 QRS", vehicle_or_equipment_id="PN21 QRS",
                merchant_or_supplier="Kestrel Hull Docks", **common),
        ],
    )


def mf07_blends() -> None:
    doc = fitz.open()
    p = Page(doc)
    p.text(40, 56, "Prairie Co-op Fleet Fuel", 15, bold=True)
    p.text(40, 72, "Bulk fleet fuel - biofuel blends", 9)
    p.text(40, 104, "Account Number: PCF-3381")
    p.table(
        40, 150,
        [("Date", 80, "l"), ("Unit #", 70, "l"), ("Product", 150, "l"), ("Gallons", 80, "r"), ("Amount", 80, "r")],
        [["06/03/2024", "G-4", "B20 Biodiesel blend", "120.0", "$462.00"],
         ["06/03/2024", "G-5", "B100 Biodiesel", "80.0", "$356.00"],
         ["06/10/2024", "P-2", "E85 Flex Fuel", "22.5", "$63.90"],
         ["06/10/2024", "P-3", "Gasoline E10", "18.0", "$59.40"]],
    )
    name = save(doc, "MF-07_prairie_coop_biofuel_blends.pdf")
    common = {"account_number": "PCF-3381"}
    expect(
        "MF-07", name, "Biofuel blends: B20 -> diesel 20%, B100 -> biodiesel 100%, E85 -> e85 (flagged, outside allowed values), E10 -> gasoline 10%. "
        "The classifier confidently picks the stationary biofuel variant, but the fleet context contradicts it: halts until a reviewer sets the type.",
        expected_classification=TYPE, expected_halt=None,
        reviewer_override=TYPE, expected_halt_without_override="unsupported_document",
        document_fields={},
        records=[
            rec("2024-06-03", "diesel", 120.0, "120.0", "gal", "gal", record_hint="G-4", vehicle_or_equipment_id="G-4", biofuel_blend_pct=20, **common),
            rec("2024-06-03", "biodiesel", 80.0, "80.0", "gal", "gal", record_hint="G-5", vehicle_or_equipment_id="G-5", biofuel_blend_pct=100, **common),
            rec("2024-06-10", "e85", 22.5, "22.5", "gal", "gal", record_hint="P-2", vehicle_or_equipment_id="P-2", biofuel_blend_pct=85, **common),
            rec("2024-06-10", "gasoline", 18.0, "18.0", "gal", "gal", record_hint="P-3", vehicle_or_equipment_id="P-3", biofuel_blend_pct=10, **common),
        ],
    )


def mf08_photo_receipt() -> None:
    doc = fitz.open()
    page = doc.new_page(width=260, height=420)
    pix = fitz.Pixmap(fitz.csGRAY, fitz.IRect(0, 0, 120, 200), False)
    pix.clear_with(215)
    page.insert_image(fitz.Rect(10, 10, 250, 410), pixmap=pix)
    name = save(doc, "MF-08_photographed_receipt_no_text.pdf")
    expect("MF-08", name, "Photographed receipt with no text layer (OCR disabled locally): halts as unreadable.",
           expected_classification=None, expected_halt="unreadable_document", document_fields={}, records=[])


def mf09_ev_charging() -> None:
    doc = fitz.open()
    p = Page(doc)
    p.text(40, 56, "ChargeWay Fleet Charging", 15, bold=True)
    p.text(40, 72, "Monthly fleet charging statement", 9)
    p.text(40, 104, "Account Number: CW-5512")
    p.table(
        40, 150,
        [("Date", 80, "l"), ("Vehicle", 80, "l"), ("Station", 160, "l"), ("Energy (kWh)", 90, "r"), ("Amount", 80, "r")],
        [["04/02/2024", "EV-7", "Lot B Charger 2", "46.2", "$13.86"],
         ["04/05/2024", "EV-9", "Lot B Charger 1", "38.7", "$11.61"]],
    )
    name = save(doc, "MF-09_chargeway_ev_charging.pdf")
    expect("MF-09", name, "Fleet EV-charging statement (kWh): electricity is Scope 2, so it halts as unsupported.",
           expected_classification=None, expected_halt="unsupported_document", document_fields={}, records=[])


def main() -> None:
    for build in (mf01_fleet_card_statement, mf02_pump_receipt, mf03_diesel_receipt_litres, mf04_cng_invoice,
                  mf05_forklift_propane, mf06_uk_statement_two_pages, mf07_blends, mf08_photo_receipt,
                  mf09_ev_charging):
        build()
    print(f"wrote {len(list(DOCS.glob('*.pdf')))} documents to {DOCS}")


if __name__ == "__main__":
    _ = (PAGE_W, PAGE_H)
    main()
