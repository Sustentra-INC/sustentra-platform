# Deterministic Extraction QA Fixture Summary

Generated from:

- Evidence pack: `/Users/qinghuanyang/Downloads/Evidence_Pack_Generated_Review_Pack_Nora.docx`
- Answer workbook: `/Users/qinghuanyang/Downloads/AB_Baldwinsville_Scope1_Workbook.xlsx`

These fixtures follow `docs/s1_deterministic_extraction_qa_spec.md` and cover the 16 current-config minimum QA scenarios.

| QA ID | Canonical type | Field | Document style | Expected value | Expected unit | Notes |
|---|---|---|---|---:|---|---|
| `EV-FUELQTY-001-Q001` | `CT-S1-FUELQTY` | `facility_name` | `natural_gas_bill` | "Anheuser-Busch Baldwinsville Brewery" | null |  |
| `EV-FUELQTY-001-Q002` | `CT-S1-FUELQTY` | `fuel_type` | `natural_gas_bill` | "Natural Gas" | null |  |
| `EV-FUELQTY-001-Q003` | `CT-S1-FUELQTY` | `activity_quantity` | `natural_gas_bill` | 32400 | "MMBtu" |  |
| `EV-FUELQTY-001-Q004` | `CT-S1-FUELQTY` | `activity_unit` | `natural_gas_bill` | "MMBtu" | "MMBtu" |  |
| `EV-FUELQTY-001-Q005` | `CT-S1-FUELQTY` | `service_period_start` | `natural_gas_bill` | "2023-01-01" | null |  |
| `EV-FUELQTY-001-Q006` | `CT-S1-FUELQTY` | `service_period_end` | `natural_gas_bill` | "2023-01-31" | null |  |
| `EV-FUELQTY-001-Q007` | `CT-S1-FUELQTY` | `supplier_name` | `natural_gas_bill` | "National Fuel Gas Company" | null |  |
| `EV-FUELQTY-001-Q008` | `CT-S1-FUELQTY` | `account_number` | `natural_gas_bill` | "ACC-2023-BWV-001" | null |  |
| `EV-FUELQTY-002-Q001` | `CT-S1-FUELQTY` | `activity_quantity` | `natural_gas_bill_split_unit` | 32400 | "MMBtu" | Expected desired behavior: infer nearby Usage Unit. Current v0 likely returns unit null/unit_missing. |
| `EV-FUELQTY-003-Q001` | `CT-S1-FUELQTY` | `activity_quantity` | `natural_gas_bill_missing_unit` | 32400 | null | Fixture intentionally omits the unit; do not expect MMBtu. The current target may flag unit_missing. |
| `EV-FUELQTY-004-Q001` | `CT-S1-FUELQTY` | `activity_quantity` | `standby_no_activity_statement` | null | null | Negative should-not-extract case: no reportable usage quantity should be found even though zeros appear in the document. |
| `EV-MOBFUEL-001-Q001` | `CT-S1-MOBFUEL` | `fuel_type` | `fuel_delivery_receipt` | "Diesel (No. 2 Distillate)" | null |  |
| `EV-MOBFUEL-001-Q002` | `CT-S1-MOBFUEL` | `activity_quantity` | `fuel_delivery_receipt` | 2800 | "gallons" |  |
| `EV-MOBFUEL-001-Q003` | `CT-S1-MOBFUEL` | `activity_unit` | `fuel_delivery_receipt` | "gallons" | "gallons" |  |
| `EV-MOBFUEL-002-Q001` | `CT-S1-MOBFUEL` | `activity_quantity` | `fleet_fuel_delivery_detail` | 900 | "gallons" | Multi-record row binding test. Current v0 may not bind row IDs to quantities reliably. |
| `EV-MOBFUEL-002-Q002` | `CT-S1-MOBFUEL` | `activity_quantity` | `fleet_fuel_delivery_detail` | 850 | "gallons" | Multi-record row binding test. Current v0 may not bind row IDs to quantities reliably. |
