# Deterministic Extraction QA Consolidated Report

## Purpose

This test set evaluates **deterministic extraction logic** after document content has already been converted into `parser_output` JSON. It does not test OCR quality, raw PDF/image parsing, live AWS Textract behavior, upload APIs, review decisions, approved evidence projection, or regulatory calculation logic.

The QA fixture JSON files are the **expected answers**. This report is the **observed current behavior** from a sanity run against the current extraction services, plus analysis of why failures happened.

## Basis For Test Design

These 16 scenarios were chosen from the repo's current deterministic extraction contract. The target planner reads `reference-data/extraction-config/extraction_config_seed.json`, which currently configures two canonical evidence types: `CT-S1-FUELQTY` and `CT-S1-MOBFUEL`. The 16 QA pairs cover the configured fields for those types: facility, fuel type, activity quantity, activity unit, service-period dates, supplier, account number, split unit context, missing unit, negative no-extraction, and multi-record fuel rows.

The parser-output fixtures are **hand-authored but source-grounded**. The evidence pack and workbook to choose real values and source snippets, then shaped them into valid `parser_output` JSON so the test isolates deterministic extraction behavior. That means a failure in this report should be read as: "given parser output containing this information, did the deterministic extractor select the right candidate?" It should not be read as an OCR/parser failure.

## Test Materials

- Source evidence pack: `/Users/qinghuanyang/Downloads/Evidence_Pack_Generated_Review_Pack_Nora.docx`
- Answer workbook: `/Users/qinghuanyang/Downloads/AB_Baldwinsville_Scope1_Workbook.xlsx`
- Parser-output fixtures: `s1-test-suite/deterministic_extraction/parser_outputs/`
- Expected-answer QA fixtures: `s1-test-suite/deterministic_extraction/qa_pairs/`

## High-Level Summary

- Total QA pairs: **16**
- Passed against current code: **11**
- Failed against current code: **5**

The failures are shown first because they are the most useful for dev discussion. Passed cases are summarized afterward.

| Status | Count | Meaning |
|---|---:|---|
| Failed | 5 | Current extractor output differs from the expected QA fixture. |
| Passed | 11 | Current extractor returned the expected value/unit behavior. |

## Failure Cases First

### Failure Summary

| QA ID | Field | Test focus | Expected | Actual | Core issue |
|---|---|---|---|---|---|
| `EV-FUELQTY-001-Q006` | `service_period_end` | Service period end date anchor collision | '2023-01-31' | '32,400 MMBtu' | The parser input contains the correct end date (`To: 01/31/2023`), but the current anchor matcher treats `To` as a substring and matches `Total Usage`. It returns `32,400 MMBtu` instead of `2023-01-31`. |
| `EV-FUELQTY-002-Q001` | `activity_quantity` | Split value/unit context inference | 32400 MMBtu | 32400 | The numeric value is extracted correctly, but the unit is in a neighboring field (`Usage Unit: MMBtu`). The current extractor only detects units inside the extracted raw value, so unit becomes null. |
| `EV-FUELQTY-004-Q001` | `activity_quantity` | Negative should-not-extract guard | None | 2023 | This is a no-activity statement. The expected behavior is no found reportable usage value, but the broad numeric extraction grabs `2023` from the document ID/year context. |
| `EV-MOBFUEL-002-Q001` | `activity_quantity` | Multi-record row binding, ticket D2-23-0412 | 900 gallons | 2023 | The expected row is ticket `D2-23-0412` with `900` gallons. The parser input also contains dates with `2023`; current extraction does not bind the ticket to the row and grabs `2023`. |
| `EV-MOBFUEL-002-Q002` | `activity_quantity` | Multi-record row binding, ticket D2-23-1187 | 850 gallons | 2023 | The expected row is ticket `D2-23-1187` with `850` gallons. Current extraction again grabs `2023` from date text instead of the row-specific quantity. |

### EV-FUELQTY-001-Q006: Service period end date anchor collision

- Document fixture: `EV-FUELQTY-001` (`natural_gas_bill`)
- Canonical type / field: `CT-S1-FUELQTY` / `service_period_end`
- Test focus: Checks whether `To` can extract the end date without matching inside `Total Usage`.
- Result: **failed**
- Error analysis: The parser input contains the correct end date (`To: 01/31/2023`), but the current anchor matcher treats `To` as a substring and matches `Total Usage`. It returns `32,400 MMBtu` instead of `2023-01-31`.

Parser input JSON excerpt:

```json
{
  "document_id": "EV-FUELQTY-001",
  "page_text": "Document ID: EV-NG-2023-001\nNational Fuel Gas Company - Natural Gas Statement\nCustomer: Anheuser-Busch Baldwinsville Brewery\nService Address: 4797 River Road, Baldwinsville, NY 13027\nAccount Number: ACC-2023-BWV-001\nBill Number: NFG-23-BWV-0001\nService Period: Jan 1, 2023 to Jan 31, 2023\nFrom: 01/01/2023\nTo: 01/31/2023\nMeter Serial Number: NFG-BWV-239871\nFuel Type: Natural Gas\nUsage Unit: MMBtu\nTotal Usage: 32,400 MMBtu\nSupplier: National Fuel Gas Company",
  "key_value_pairs_of_interest": [
    {
      "pair_id": "kv-fuelqty-001-qty",
      "page_number": 1,
      "sheet_name": null,
      "key": "Total Usage",
      "value": "32,400 MMBtu",
      "confidence": 0.99,
      "key_source_reference_id": null,
      "value_source_reference_id": null
    },
    {
      "pair_id": "kv-fuelqty-001-to",
      "page_number": 1,
      "sheet_name": null,
      "key": "To",
      "value": "01/31/2023",
      "confidence": 0.99,
      "key_source_reference_id": null,
      "value_source_reference_id": null
    }
  ]
}
```

Failure-relevant fields:
- **Correct input exists:** `To: 01/31/2023`
- **Distractor input exists:** `Total Usage: 32,400 MMBtu`
- **Bug signal:** anchor `To` matched the distractor line.

Expected answer JSON:

```json
{
  "qa_id": "EV-FUELQTY-001-Q006",
  "canonical_type_id": "CT-S1-FUELQTY",
  "field_id": "service_period_end",
  "answer": {
    "value": "2023-01-31",
    "unit": null,
    "raw_value": "01/31/2023",
    "period_start": null,
    "period_end": "2023-01-31",
    "record_id": null
  },
  "source_expectation": {
    "source_text_contains": "To: 01/31/2023",
    "source_kind": [
      "page_text"
    ],
    "page_number": 1,
    "sheet_name": null,
    "cell_or_range": null
  }
}
```

Actual output JSON:

```json
{
  "qa_id": "EV-FUELQTY-001-Q006",
  "status": "failed",
  "actual_candidate": {
    "raw_value": "32,400 MMBtu",
    "normalized_value": "32,400 MMBtu",
    "unit": null,
    "validation_flags": []
  }
}
```

Expected-vs-actual callout:
- **Expected:** value `2023-01-31`, unit `None`
- **Actual:** value `32,400 MMBtu`, unit `None`, flags `none`

### EV-FUELQTY-002-Q001: Split value/unit context inference

- Document fixture: `EV-FUELQTY-002` (`natural_gas_bill_split_unit`)
- Canonical type / field: `CT-S1-FUELQTY` / `activity_quantity`
- Test focus: Checks whether a numeric value can inherit a nearby unit field.
- Result: **failed**
- Error analysis: The numeric value is extracted correctly, but the unit is in a neighboring field (`Usage Unit: MMBtu`). The current extractor only detects units inside the extracted raw value, so unit becomes null.

Parser input JSON excerpt:

```json
{
  "document_id": "EV-FUELQTY-002",
  "page_text": "Document ID: EV-NG-2023-001\nMeter ID: NFG-BWV-239871\nUsage: 32,400\nUsage Unit: MMBtu",
  "key_value_pairs": [
    {
      "pair_id": "kv-fuelqty-002-usage",
      "page_number": 1,
      "sheet_name": null,
      "key": "Usage",
      "value": "32,400",
      "confidence": 0.99,
      "key_source_reference_id": null,
      "value_source_reference_id": null
    },
    {
      "pair_id": "kv-fuelqty-002-unit",
      "page_number": 1,
      "sheet_name": null,
      "key": "Usage Unit",
      "value": "MMBtu",
      "confidence": 0.99,
      "key_source_reference_id": null,
      "value_source_reference_id": null
    }
  ]
}
```

Failure-relevant fields:
- **Extracted value source:** `Usage: 32,400`
- **Nearby unit source:** `Usage Unit: MMBtu`
- **Bug signal:** unit context is present but not associated with the value.

Expected answer JSON:

```json
{
  "qa_id": "EV-FUELQTY-002-Q001",
  "canonical_type_id": "CT-S1-FUELQTY",
  "field_id": "activity_quantity",
  "answer": {
    "value": 32400,
    "unit": "MMBtu",
    "raw_value": "32,400",
    "period_start": null,
    "period_end": null,
    "record_id": "NFG-BWV-239871"
  },
  "source_expectation": {
    "source_text_contains": "Usage Unit: MMBtu",
    "source_kind": [
      "page_text"
    ],
    "page_number": 1,
    "sheet_name": null,
    "cell_or_range": null
  }
}
```

Actual output JSON:

```json
{
  "qa_id": "EV-FUELQTY-002-Q001",
  "status": "failed",
  "actual_candidate": {
    "raw_value": "32,400",
    "normalized_value": 32400,
    "unit": null,
    "validation_flags": [
      "unit_missing"
    ]
  }
}
```

Expected-vs-actual callout:
- **Expected:** value `32400`, unit `MMBtu`
- **Actual:** value `32400`, unit `None`, flags `unit_missing`

### EV-FUELQTY-004-Q001: Negative should-not-extract guard

- Document fixture: `EV-FUELQTY-004` (`standby_no_activity_statement`)
- Canonical type / field: `CT-S1-FUELQTY` / `activity_quantity`
- Test focus: Checks that no reportable usage is extracted from a no-activity statement.
- Result: **failed**
- Error analysis: This is a no-activity statement. The expected behavior is no found reportable usage value, but the broad numeric extraction grabs `2023` from the document ID/year context.

Parser input JSON excerpt:

```json
{
  "document_id": "EV-FUELQTY-004",
  "page_text": "Document ID: EV-RFO-2023-001\nResidual fuel oil backup boiler standby statement\nFuel Deliveries Recorded: 0 gallons\nFuel Consumption Recorded: 0 gallons\nCombustion Hours Recorded: 0 hours\nAnnual Emissions Activity: No activity",
  "key_value_pairs": [
    {
      "pair_id": "kv-fuelqty-004-fuel-deliveries",
      "page_number": 1,
      "sheet_name": null,
      "key": "Fuel Deliveries Recorded",
      "value": "0 gallons",
      "confidence": 0.99,
      "key_source_reference_id": null,
      "value_source_reference_id": null
    },
    {
      "pair_id": "kv-fuelqty-004-activity",
      "page_number": 1,
      "sheet_name": null,
      "key": "Annual Emissions Activity",
      "value": "No activity",
      "confidence": 0.99,
      "key_source_reference_id": null,
      "value_source_reference_id": null
    }
  ]
}
```

Failure-relevant fields:
- **Negative evidence:** `Annual Emissions Activity: No activity`
- **Distractor number:** `2023` appears in the document ID/year context.
- **Bug signal:** extractor should return no found value but grabs a year.

Expected answer JSON:

```json
{
  "qa_id": "EV-FUELQTY-004-Q001",
  "canonical_type_id": "CT-S1-FUELQTY",
  "field_id": "activity_quantity",
  "answer": {
    "value": null,
    "unit": null,
    "raw_value": null,
    "period_start": null,
    "period_end": null,
    "record_id": null
  },
  "source_expectation": {
    "source_text_contains": null,
    "source_kind": [],
    "page_number": null,
    "sheet_name": null,
    "cell_or_range": null
  }
}
```

Actual output JSON:

```json
{
  "qa_id": "EV-FUELQTY-004-Q001",
  "status": "failed",
  "actual_candidate": {
    "raw_value": "2023",
    "normalized_value": 2023,
    "unit": null,
    "validation_flags": [
      "unit_missing"
    ]
  }
}
```

Expected-vs-actual callout:
- **Expected:** value `None`, unit `None`
- **Actual:** value `2023`, unit `None`, flags `unit_missing`

### EV-MOBFUEL-002-Q001: Multi-record row binding, ticket D2-23-0412

- Document fixture: `EV-MOBFUEL-002` (`fleet_fuel_delivery_detail`)
- Canonical type / field: `CT-S1-MOBFUEL` / `activity_quantity`
- Test focus: Checks whether a ticket ID binds to the correct row quantity.
- Result: **failed**
- Error analysis: The expected row is ticket `D2-23-0412` with `900` gallons. The parser input also contains dates with `2023`; current extraction does not bind the ticket to the row and grabs `2023`.

Parser input JSON excerpt:

```json
{
  "document_id": "EV-MOBFUEL-002",
  "page_text": "Document ID: EV-DIESEL-2023-001\nDelivery Date | Ticket No. | Gallons Delivered | Tank / Equipment | Use Category\n03/14/2023 | D2-23-0412 | 900 | GEN-001 day tank / bulk tank | Emergency standby\n07/21/2023 | D2-23-1187 | 850 | GEN-001 day tank / bulk tank | Emergency standby\n11/08/2023 | D2-23-1964 | 1,050 | GEN-001 day tank / bulk tank | Emergency standby",
  "table_rows": [
    [
      "Delivery Date",
      "Ticket No.",
      "Gallons Delivered",
      "Tank / Equipment",
      "Use Category"
    ],
    [
      "03/14/2023",
      "D2-23-0412",
      "900",
      "GEN-001 day tank / bulk tank",
      "Emergency standby"
    ],
    [
      "07/21/2023",
      "D2-23-1187",
      "850",
      "GEN-001 day tank / bulk tank",
      "Emergency standby"
    ],
    [
      "11/08/2023",
      "D2-23-1964",
      "1,050",
      "GEN-001 day tank / bulk tank",
      "Emergency standby"
    ]
  ]
}
```

Failure-relevant fields:
- **Row identifier:** `D2-23-0412`
- **Correct row quantity:** `900` gallons
- **Distractor values:** delivery dates contain `2023`.
- **Bug signal:** extractor grabs the year instead of binding row identifier to quantity.

Expected answer JSON:

```json
{
  "qa_id": "EV-MOBFUEL-002-Q001",
  "canonical_type_id": "CT-S1-MOBFUEL",
  "field_id": "activity_quantity",
  "answer": {
    "value": 900,
    "unit": "gallons",
    "raw_value": "900",
    "period_start": null,
    "period_end": null,
    "record_id": "D2-23-0412"
  },
  "source_expectation": {
    "source_text_contains": "D2-23-0412",
    "source_kind": [
      "page_text"
    ],
    "page_number": 1,
    "sheet_name": null,
    "cell_or_range": null
  }
}
```

Actual output JSON:

```json
{
  "qa_id": "EV-MOBFUEL-002-Q001",
  "status": "failed",
  "actual_candidate": {
    "raw_value": "2023",
    "normalized_value": 2023,
    "unit": null,
    "validation_flags": [
      "unit_missing"
    ]
  }
}
```

Expected-vs-actual callout:
- **Expected:** value `900`, unit `gallons`
- **Actual:** value `2023`, unit `None`, flags `unit_missing`

### EV-MOBFUEL-002-Q002: Multi-record row binding, ticket D2-23-1187

- Document fixture: `EV-MOBFUEL-002` (`fleet_fuel_delivery_detail`)
- Canonical type / field: `CT-S1-MOBFUEL` / `activity_quantity`
- Test focus: Checks whether a second ticket ID binds to the correct row quantity.
- Result: **failed**
- Error analysis: The expected row is ticket `D2-23-1187` with `850` gallons. Current extraction again grabs `2023` from date text instead of the row-specific quantity.

Parser input JSON excerpt:

```json
{
  "document_id": "EV-MOBFUEL-002",
  "page_text": "Document ID: EV-DIESEL-2023-001\nDelivery Date | Ticket No. | Gallons Delivered | Tank / Equipment | Use Category\n03/14/2023 | D2-23-0412 | 900 | GEN-001 day tank / bulk tank | Emergency standby\n07/21/2023 | D2-23-1187 | 850 | GEN-001 day tank / bulk tank | Emergency standby\n11/08/2023 | D2-23-1964 | 1,050 | GEN-001 day tank / bulk tank | Emergency standby",
  "table_rows": [
    [
      "Delivery Date",
      "Ticket No.",
      "Gallons Delivered",
      "Tank / Equipment",
      "Use Category"
    ],
    [
      "03/14/2023",
      "D2-23-0412",
      "900",
      "GEN-001 day tank / bulk tank",
      "Emergency standby"
    ],
    [
      "07/21/2023",
      "D2-23-1187",
      "850",
      "GEN-001 day tank / bulk tank",
      "Emergency standby"
    ],
    [
      "11/08/2023",
      "D2-23-1964",
      "1,050",
      "GEN-001 day tank / bulk tank",
      "Emergency standby"
    ]
  ]
}
```

Failure-relevant fields:
- **Row identifier:** `D2-23-1187`
- **Correct row quantity:** `850` gallons
- **Distractor values:** delivery dates contain `2023`.
- **Bug signal:** extractor grabs the year instead of binding row identifier to quantity.

Expected answer JSON:

```json
{
  "qa_id": "EV-MOBFUEL-002-Q002",
  "canonical_type_id": "CT-S1-MOBFUEL",
  "field_id": "activity_quantity",
  "answer": {
    "value": 850,
    "unit": "gallons",
    "raw_value": "850",
    "period_start": null,
    "period_end": null,
    "record_id": "D2-23-1187"
  },
  "source_expectation": {
    "source_text_contains": "D2-23-1187",
    "source_kind": [
      "page_text"
    ],
    "page_number": 1,
    "sheet_name": null,
    "cell_or_range": null
  }
}
```

Actual output JSON:

```json
{
  "qa_id": "EV-MOBFUEL-002-Q002",
  "status": "failed",
  "actual_candidate": {
    "raw_value": "2023",
    "normalized_value": 2023,
    "unit": null,
    "validation_flags": [
      "unit_missing"
    ]
  }
}
```

Expected-vs-actual callout:
- **Expected:** value `850`, unit `gallons`
- **Actual:** value `2023`, unit `None`, flags `unit_missing`

## Passed Cases At The Back

The cases below passed against the current deterministic extractor. They still remain useful regression tests because they cover the baseline configured extraction behavior.

| QA ID | Field | Test focus | Expected | Actual | Notes |
|---|---|---|---|---|---|
| `EV-FUELQTY-001-Q001` | `facility_name` | Stationary fuel facility name extraction | 'Anheuser-Busch Baldwinsville Brewery' | 'Anheuser-Busch Baldwinsville Brewery' | clean pass |
| `EV-FUELQTY-001-Q002` | `fuel_type` | Stationary fuel type extraction | 'Natural Gas' | 'Natural Gas' | clean pass |
| `EV-FUELQTY-001-Q003` | `activity_quantity` | Stationary quantity with unit | 32400 MMBtu | 32400 MMBtu | clean pass |
| `EV-FUELQTY-001-Q004` | `activity_unit` | Stationary unit extraction | 'MMBtu' MMBtu | 'MMBtu' MMBtu | clean pass |
| `EV-FUELQTY-001-Q005` | `service_period_start` | Service period start date | '2023-01-01' | '2023-01-01' | clean pass |
| `EV-FUELQTY-001-Q007` | `supplier_name` | Supplier name extraction | 'National Fuel Gas Company' | 'National Fuel Gas Company' | clean pass |
| `EV-FUELQTY-001-Q008` | `account_number` | Account number extraction | 'ACC-2023-BWV-001' | 'ACC-2023-BWV-001' | clean pass |
| `EV-FUELQTY-003-Q001` | `activity_quantity` | Missing-unit handling | 32400 | 32400 | passes with flag(s): unit_missing |
| `EV-MOBFUEL-001-Q001` | `fuel_type` | Mobile fuel type extraction | 'Diesel (No. 2 Distillate)' | 'Diesel (No. 2 Distillate)' | clean pass |
| `EV-MOBFUEL-001-Q002` | `activity_quantity` | Mobile fuel quantity extraction | 2800 gallons | 2800 gallons | passes with flag(s): unit_conversion_not_implemented |
| `EV-MOBFUEL-001-Q003` | `activity_unit` | Mobile fuel unit extraction | 'gallons' gallons | 'gallons' gallons | clean pass |

## Passed Case Details

### EV-FUELQTY-001-Q001: Stationary fuel facility name extraction

- Document fixture: `EV-FUELQTY-001` (`natural_gas_bill`)
- Canonical type / field: `CT-S1-FUELQTY` / `facility_name`
- Test focus: Checks key/value or anchor extraction for facility identity.
- Expected: value `Anheuser-Busch Baldwinsville Brewery`, unit `None`
- Actual: value `Anheuser-Busch Baldwinsville Brewery`, unit `None`, flags `none`
- Result: **passed**

### EV-FUELQTY-001-Q002: Stationary fuel type extraction

- Document fixture: `EV-FUELQTY-001` (`natural_gas_bill`)
- Canonical type / field: `CT-S1-FUELQTY` / `fuel_type`
- Test focus: Checks extraction of `Natural Gas` from a clear fuel-type field.
- Expected: value `Natural Gas`, unit `None`
- Actual: value `Natural Gas`, unit `None`, flags `none`
- Result: **passed**

### EV-FUELQTY-001-Q003: Stationary quantity with unit

- Document fixture: `EV-FUELQTY-001` (`natural_gas_bill`)
- Canonical type / field: `CT-S1-FUELQTY` / `activity_quantity`
- Test focus: Checks comma removal, number parsing, and unit detection from one raw value.
- Expected: value `32400`, unit `MMBtu`
- Actual: value `32400`, unit `MMBtu`, flags `none`
- Result: **passed**

### EV-FUELQTY-001-Q004: Stationary unit extraction

- Document fixture: `EV-FUELQTY-001` (`natural_gas_bill`)
- Canonical type / field: `CT-S1-FUELQTY` / `activity_unit`
- Test focus: Checks direct extraction of `MMBtu`.
- Expected: value `MMBtu`, unit `MMBtu`
- Actual: value `MMBtu`, unit `MMBtu`, flags `none`
- Result: **passed**

### EV-FUELQTY-001-Q005: Service period start date

- Document fixture: `EV-FUELQTY-001` (`natural_gas_bill`)
- Canonical type / field: `CT-S1-FUELQTY` / `service_period_start`
- Test focus: Checks slash-date normalization to ISO date.
- Expected: value `2023-01-01`, unit `None`
- Actual: value `2023-01-01`, unit `None`, flags `none`
- Result: **passed**

### EV-FUELQTY-001-Q007: Supplier name extraction

- Document fixture: `EV-FUELQTY-001` (`natural_gas_bill`)
- Canonical type / field: `CT-S1-FUELQTY` / `supplier_name`
- Test focus: Checks utility/supplier name extraction.
- Expected: value `National Fuel Gas Company`, unit `None`
- Actual: value `National Fuel Gas Company`, unit `None`, flags `none`
- Result: **passed**

### EV-FUELQTY-001-Q008: Account number extraction

- Document fixture: `EV-FUELQTY-001` (`natural_gas_bill`)
- Canonical type / field: `CT-S1-FUELQTY` / `account_number`
- Test focus: Checks optional account identifier extraction.
- Expected: value `ACC-2023-BWV-001`, unit `None`
- Actual: value `ACC-2023-BWV-001`, unit `None`, flags `none`
- Result: **passed**

### EV-FUELQTY-003-Q001: Missing-unit handling

- Document fixture: `EV-FUELQTY-003` (`natural_gas_bill_missing_unit`)
- Canonical type / field: `CT-S1-FUELQTY` / `activity_quantity`
- Test focus: Checks that the extractor does not invent a unit when none exists in parser output.
- Expected: value `32400`, unit `None`
- Actual: value `32400`, unit `None`, flags `unit_missing`
- Result: **passed**

### EV-MOBFUEL-001-Q001: Mobile fuel type extraction

- Document fixture: `EV-MOBFUEL-001` (`fuel_delivery_receipt`)
- Canonical type / field: `CT-S1-MOBFUEL` / `fuel_type`
- Test focus: Checks diesel product/fuel type extraction.
- Expected: value `Diesel (No. 2 Distillate)`, unit `None`
- Actual: value `Diesel (No. 2 Distillate)`, unit `None`, flags `none`
- Result: **passed**

### EV-MOBFUEL-001-Q002: Mobile fuel quantity extraction

- Document fixture: `EV-MOBFUEL-001` (`fuel_delivery_receipt`)
- Canonical type / field: `CT-S1-MOBFUEL` / `activity_quantity`
- Test focus: Checks `2,800 gallons` quantity extraction.
- Expected: value `2800`, unit `gallons`
- Actual: value `2800`, unit `gallons`, flags `unit_conversion_not_implemented`
- Result: **passed**

### EV-MOBFUEL-001-Q003: Mobile fuel unit extraction

- Document fixture: `EV-MOBFUEL-001` (`fuel_delivery_receipt`)
- Canonical type / field: `CT-S1-MOBFUEL` / `activity_unit`
- Test focus: Checks direct extraction of `gallons`.
- Expected: value `gallons`, unit `gallons`
- Actual: value `gallons`, unit `gallons`, flags `none`
- Result: **passed**

## How To Read This Report

- `qa_pairs/*.qa.json` files are the expected-answer source of truth.
- This report shows observed current behavior and failure analysis.
- The JSON excerpts in failure cases are intentionally focused, not full parser-output files. The full JSON files live under `parser_outputs/` and `qa_pairs/`.
- Failed cases here are focused on deterministic extraction because the parser-output fixtures already contain the relevant source text/table content.
- Parser/OCR tests should be run separately using raw documents and parser expectations.
