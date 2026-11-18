"""Regressions from the staging GHG test set (13 Nov): documents that came back "Needs a document type".

Fixtures are tiny generated files (fictional values); nothing here touches the network.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

openpyxl = pytest.importorskip("openpyxl")

from backend.app.repositories.extraction_result_repository import InMemoryExtractionResultRepository  # noqa: E402
from backend.app.services.classification_service import ClassificationService  # noqa: E402
from backend.app.services.pipeline_orchestration_service import PipelineOrchestrationService  # noqa: E402


class _Runs:
    """Run store that keeps nothing (the tests read the returned run)."""

    def __getattr__(self, name: str) -> Any:
        return lambda *args, **kwargs: None


def _read(path: Path) -> dict:
    service = PipelineOrchestrationService(
        pipeline_repository=_Runs(), extraction_result_repository=InMemoryExtractionResultRepository()
    )
    return service.process_local_document(str(path), "eng-1", persist_run=False)


def _values(result: dict, field: str) -> list[Any]:
    return [i["normalized_value"] for i in result["extraction_result"]["items"] if i["field_name"] == field]


def _xlsx(path: Path, rows: list[list[Any]], sheet: str = "Sheet1") -> Path:
    workbook = openpyxl.Workbook()
    sheet_ = workbook.active
    sheet_.title = sheet
    for row in rows:
        sheet_.append(row)
    workbook.save(path)
    return path


GAS_BILL = """Mill Creek Natural Gas Co.
Natural Gas Invoice
Invoice date: February 6, 2025
Account: NG-552-019-447
Service location: Riverside Plant, 410 Mill Road, Springfield, OR 97477
Service from January 1, 2025 through January 31, 2025 (31 days)
Meter Reading
Meter  Read on January 1, 2025  Read on January 31, 2025  Usage (CCF)
MC-30098217  58,214  64,906  6,692
Heat content: 1.037 therms per CCF
Charges
Customer charge  $38.00
Amount due  $6,206.16
"""


def test_gas_bill_in_ccf_is_recognised_as_stationary_fuel(tmp_path: Path) -> None:
    path = tmp_path / "bill.txt"
    path.write_text(GAS_BILL)
    result = _read(path)
    run = result["pipeline_run"]
    assert run["canonical_type_id"] == "CT-S1-FUELQTY"
    assert _values(result, "activity_quantity") == [6692]
    assert _values(result, "activity_unit") == ["ccf"]
    assert _values(result, "service_period_start") == ["2025-01-01"]
    assert _values(result, "service_period_end") == ["2025-01-31"]
    assert _values(result, "account_number") == ["NG-552-019-447"]
    assert _values(result, "supplier_name") == ["Mill Creek Natural Gas Co."]


def test_gas_portal_export_is_recognised_with_account_and_supplier(tmp_path: Path) -> None:
    path = _xlsx(
        tmp_path / "export.xlsx",
        [
            ["Account", "Meter", "Start Date", "End Date", "Usage", "Unit", "Amount"],
            ["NG-552-019-447", "MC-30098217", "2025-04-01", "2025-04-30", 4612.4, "therms", 4137.92],
            ["NG-552-019-447", "MC-30098217", "2025-05-01", "2025-05-31", 3288.9, "therms", 2961.69],
            [None] * 7,
            ["Exported from Mill Creek Natural Gas Co. Business Portal 07/08/2025 14:02 PT."],
        ],
        sheet="UsageExport",
    )
    result = _read(path)
    assert result["pipeline_run"]["canonical_type_id"] == "CT-S1-FUELQTY"
    assert result["classification_result"]["status"] == "classified"  # no kWh: not an electricity export
    assert _values(result, "service_period_start") == ["2025-04-01", "2025-05-01"]
    assert _values(result, "account_number") == ["NG-552-019-447"] * 2
    assert _values(result, "supplier_name") == ["Mill Creek Natural Gas Co."] * 2
    assert _values(result, "activity_unit") == ["MMBtu"] * 2  # therms, converted


def test_mileage_log_with_gallons_is_mobile_combustion(tmp_path: Path) -> None:
    path = _xlsx(
        tmp_path / "Mileage_2025.xlsx",
        [
            ["Vehicle ID", "Vehicle Type", "Model Year", "Fuel", "Month", "Miles", "Gallons"],
            ["HW-T01", "Box truck (26 ft)", 2019, "Diesel", "Jan-2025", 1668, 176.3],
            ["HW-V03", "Cargo van", 2022, "Gasoline", "Jan-2025", 1390, 91.5],
        ],
    )
    result = _read(path)
    assert result["pipeline_run"]["canonical_type_id"] == "CT-S1-MOBFUEL"
    assert _values(result, "activity_quantity") == [176.3, 91.5]
    assert _values(result, "fuel_type") == ["diesel", "gasoline"]
    assert _values(result, "transaction_date") == ["2025-01-01", "2025-01-01"]


def test_mileage_log_without_fuel_stays_distance_only(tmp_path: Path) -> None:
    path = _xlsx(
        tmp_path / "Mileage_2025.xlsx",
        [["Vehicle ID", "Odometer", "Miles", "Trip Date", "Driver"], ["HW-T01", 100, 20, "2025-01-02", "A"]],
    )
    assert _read(path)["classification_result"]["primary_canonical_type_id"] == "CT-S1-TRANSACT"


REFRIGERANT_INVOICE = """POLAR RIDGE
Refrigerant Supply
Invoice No.  Invoice Date  PO Number
PRS-090455  09/12/2025  STG-PO-25-0711
Item  Description  Cyl.  Lbs / Cyl.  Total Lbs  Price / Lb  Amount
R134A-30  Refrigerant R-134a (HFC-134a), 30 lb returnable cylinder  4  30  120  $9.85  $1,182.00
Subtotal  $1,374.50
TOTAL DUE  $1,409.50
Total refrigerant shipped: 120 lb (4 cylinders x 30 lb).
"""


def test_refrigerant_purchase_invoice_is_recognised(tmp_path: Path) -> None:
    path = tmp_path / "invoice.txt"
    path.write_text(REFRIGERANT_INVOICE)
    result = _read(path)
    assert result["pipeline_run"]["canonical_type_id"] == "CT-S1-REFRSVC"
    assert result["classification_result"]["status"] == "classified"
    assert _values(result, "refrigerant_type") == ["HFC-134a"]
    assert _values(result, "refrigerant_added") == [120]  # "Total Lbs" is a mass, not a package count


def test_diesel_generator_log_is_not_a_company_summary(tmp_path: Path) -> None:
    path = tmp_path / "Generator_Diesel_2025.csv"
    path.write_text(
        "Date,Hours Run,Fuel Added (gal),Fuel Type,Operator\n"
        "01/07/2025,1.0,9.6,Diesel (ULSD No. 2),R. Okafor\n"
        "01/13/2025,1.5,16.0,Diesel (ULSD No. 2),M. Serrano\n"
    )
    result = _read(path)
    primary = result["classification_result"]["primary_canonical_type_id"]
    assert not str(primary).startswith("CT-GHG-")
    assert result["pipeline_run"]["canonical_type_id"] in ("CT-S1-FUELQTY", "CT-S1-MOBFUEL")
    assert _values(result, "activity_quantity") == [9.6, 16.0]


def test_company_inventory_workbook_is_still_a_summary() -> None:
    text = (
        "Scope 1 Scope 2 tCO2e GWP Location-based Market-based reporting year "
        "Stationary combustion Mobile combustion"
    )
    result = ClassificationService().classify({"file_name": "Company_GHG_Inventory_2025.xlsx", "extracted_text": text})
    assert result["primary_canonical_type_id"] == "CT-GHG-WORKBOOK"


def test_one_generic_header_does_not_make_a_summary() -> None:
    result = ClassificationService().classify(
        {"file_name": "generator_log.csv", "extracted_text": "Date Fuel type Operator"}
    )
    assert not str(result["primary_canonical_type_id"]).startswith("CT-GHG-") or result["status"] != "classified"


def test_electricity_bill_is_not_taken_for_gas() -> None:
    text = "Account Number Service Address Billing Period Usage kWh Total Usage 148,560 kWh Amount due $16,984.55"
    result = ClassificationService().classify({"file_name": "bill.pdf", "extracted_text": text})
    assert result["primary_canonical_type_id"] != "CT-S1-FUELQTY" or result["status"] != "classified"


def test_client_note_in_therms_is_not_taken_for_a_bill(tmp_path: Path) -> None:
    path = tmp_path / "Notes.txt"
    path.write_text(
        "Hi all, here is what I pulled from the gas account. January was 4,480 therms. "
        "In February we used 4,120 therms. The meter is CG-6620193.\n"
    )
    assert _read(path)["pipeline_run"]["canonical_type_id"] is None
