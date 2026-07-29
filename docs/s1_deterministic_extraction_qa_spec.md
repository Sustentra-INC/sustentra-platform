# S1 Deterministic Extraction QA Pair Specification

This document defines the QA-pair format needed to test S1 deterministic
extraction logic independently from raw-document parsing/OCR.

Use this spec when the question is:

> If the relevant document content is already available in parser output, can
> the current extraction logic find the right evidence value?

This is intentionally separate from parser testing. Raw PDFs, images, Excel
files, and Textract OCR quality should be tested elsewhere.

## 1. Current Repo Scope

The current committed extraction config seed supports deterministic extraction
targets for these canonical evidence types:

| Canonical type | Meaning in current config | Example document styles |
|----------------|---------------------------|-------------------------|
| `CT-S1-FUELQTY` | Stationary fuel consumption quantity | natural gas bill, stationary fuel invoice, utility invoice, stationary fuel summary |
| `CT-S1-MOBFUEL` | Mobile fuel consumption quantity | diesel receipt, fleet fuel card report, mobile fuel purchase summary |

The repo may contain broader vocabulary/reference data, but the deterministic
target planning service currently uses `reference-data/extraction-config/
extraction_config_seed.json`. In that seed, `equipment_inventory`,
`meter_reading_report`, and `emissions_report` are useful future/gap scenarios,
but they are not first-class configured deterministic extraction types yet.

## 2. Does The QA Format Change Across Document Types?

The QA-pair file format should stay the same across document styles and parser
sources.

What changes by canonical type or document style:

- `document_type`
- `canonical_type_id`
- `field_id`
- expected field aliases/questions/source wording
- expected values and units
- whether the expected answer is single-record or multi-record
- source text snippets used to prove traceability

The evaluator should be able to read every QA pair with the same schema.

Important distinction:

- `canonical_type_id` identifies the configured evidence type, such as
  `CT-S1-FUELQTY`.
- `field_id` identifies the specific field to extract, such as
  `activity_quantity`.

Do not put a field name like `activity_amount`, `fuel_type`, or
`reporting_period` in `canonical_type_id`.

## 3. Current Configured Fields To Test

### `CT-S1-FUELQTY`

| `field_id` | Label | Required status | Value type | Useful source labels |
|------------|-------|-----------------|------------|----------------------|
| `facility_name` | Facility name | core | string | Facility, Facility Name, Site, Location, Premises |
| `service_address` | Service or account address | conditional | string | Service Address, Service Location, Account Address, Billing Address |
| `fuel_type` | Fuel type | core | string | Fuel, Fuel Type, Commodity, Service Type |
| `activity_quantity` | Activity quantity | core | quantity | Total Usage, Gas Used, Usage, Quantity, Consumption |
| `activity_unit` | Activity unit | core | string | Unit, Units, UOM |
| `service_period_start` | Service period start | core | date | Service Period, Billing Period, From, Period Start, Read Date |
| `service_period_end` | Service period end | core | date | Service Period, Billing Period, To, Period End, Read Date |
| `supplier_name` | Supplier or utility name | conditional | string | Utility, Supplier, Provider, Company, Issued By |
| `account_number` | Account number | optional | string | Account Number, Account No, Account #, Acct |

### `CT-S1-MOBFUEL`

| `field_id` | Label | Required status | Value type | Useful source labels |
|------------|-------|-----------------|------------|----------------------|
| `fuel_type` | Fuel type | core | string | Fuel, Fuel Type, Product, Grade |
| `activity_quantity` | Activity quantity | core | quantity | Quantity, Gallons, Liters, Volume, Total |
| `activity_unit` | Activity unit | core | string | Unit, Units, UOM |

## 4. What The Extraction Test Consumes

The deterministic extraction test should consume a normalized parser-like input,
not a raw document.

Minimum test input:

```json
{
  "document_id": "EV-NG-2023-001",
  "document_type": "natural_gas_bill",
  "canonical_type_id": "CT-S1-FUELQTY",
  "parser_output": {
    "pages": [
      {
        "page_number": 1,
        "text": "Natural Gas Invoice\nMeter ID: NFG-BWV-239871\nUsage: 32,400 MMBtu"
      }
    ],
    "text_blocks": [],
    "tables": [],
    "key_value_pairs": [],
    "source_references": []
  },
  "qa_pairs": []
}
```

The parser output can come from:

- local text parser output
- local Excel parser output
- local PDF parser output
- live AWS Textract parser output
- saved Textract JSON normalizer output
- a hand-authored minimal parser output fixture

For algorithm testing, hand-authored parser output is acceptable as long as it
matches the repo's `parser_output` contract.

## 5. Recommended Directory Layout

```text
s1-test-suite/
  deterministic_extraction/
    parser_outputs/
      <DOCUMENT_ID>.parser_output.json
    qa_pairs/
      <DOCUMENT_ID>.qa.json
    reports/
```

Use one QA file per document.

## 6. QA File Format

File name:

```text
<DOCUMENT_ID>.qa.json
```

Top-level format:

```json
{
  "document_id": "EV-NG-2023-001",
  "document_type": "natural_gas_bill",
  "canonical_type_id": "CT-S1-FUELQTY",
  "parser_output_file": "../parser_outputs/EV-NG-2023-001.parser_output.json",
  "qa_pairs": [
    {
      "qa_id": "EV-NG-2023-001-Q001",
      "canonical_type_id": "CT-S1-FUELQTY",
      "field_id": "activity_quantity",
      "question": "What was the natural gas usage?",
      "answer": {
        "value": 32400,
        "unit": "MMBtu",
        "raw_value": "32,400 MMBtu",
        "period_start": null,
        "period_end": "2023-12-31",
        "record_id": "NFG-BWV-239871"
      },
      "source_expectation": {
        "source_text_contains": "32,400 MMBtu",
        "source_kind": ["page_text"],
        "page_number": 1,
        "sheet_name": null,
        "cell_or_range": null
      },
      "required": true,
      "match_rules": {
        "value_tolerance": 0,
        "case_sensitive": false,
        "allow_unit_aliases": true,
        "allow_missing_period": false
      },
      "notes": ""
    }
  ]
}
```

## 7. Required Fields And How To Generate Them

Every QA pair must include:

| Field | Required | Meaning |
|-------|----------|---------|
| `qa_id` | Yes | Stable unique ID for this expected answer; generate as `<DOCUMENT_ID>-Q###` |
| `canonical_type_id` | Yes | Configured evidence type, currently `CT-S1-FUELQTY` or `CT-S1-MOBFUEL` |
| `field_id` | Yes | Configured target field, such as `activity_quantity` or `fuel_type` |
| `question` | Yes | Human-readable prompt/field question |
| `answer.value` | Yes | Expected normalized answer value |
| `answer.unit` | Yes, nullable | Expected normalized unit, or `null` if no unit |
| `answer.raw_value` | Yes, nullable | Exact or near-exact surface value expected in source text; use `null` for negative should-not-extract cases |
| `required` | Yes | Whether this answer counts against pass/fail |
| `source_expectation.source_text_contains` | Yes, nullable | Text that should support the answer; use `null` for negative should-not-extract cases |

ID rules:

- Do not generate random `qa_id`s. They should be deterministic and stable
  across reruns.
- Use `<DOCUMENT_ID>-Q###`, starting at `Q001`.
- If a single scenario has multiple expected rows, increment the QA number:
  `EV-MOB-2023-001-Q001`, `EV-MOB-2023-001-Q002`, etc.
- `document_id` should be stable and should match the parser output document ID.
- `field_id` must be one of the configured field IDs listed in Section 3 unless
  the QA pair is explicitly marked as an aspirational gap test.

Top-level `document_type` rules:

- Use a human-readable document style label, for example
  `natural_gas_bill`, `fuel_delivery_receipt`, or `fleet_fuel_card_report`.
- This value is test metadata. The current target planner uses
  `canonical_type_id`, not this free-form document type.

Recommended fields:

| Field | Meaning |
|-------|---------|
| `answer.period_start` | Expected normalized period start date |
| `answer.period_end` | Expected normalized period end date |
| `answer.record_id` | Stable row/meter/unit/account identifier for multi-record cases |
| `source_expectation.page_number` | Expected page number for PDF/Textract/text outputs |
| `source_expectation.sheet_name` | Expected Excel sheet name |
| `source_expectation.cell_or_range` | Expected Excel source cell/range |
| `match_rules.value_tolerance` | Numeric tolerance for decimals/rounding |
| `match_rules.allow_unit_aliases` | Whether `MMBtu`, `mmbtu`, `MMBTU` can match |

## 8. Answer Value Rules

Use normalized values in `answer.value`.

Examples:

```json
{
  "raw_value": "32,400 MMBtu",
  "value": 32400,
  "unit": "MMBtu"
}
```

```json
{
  "raw_value": "125 MMBtu/hr",
  "value": 125,
  "unit": "MMBtu/hr"
}
```

```json
{
  "raw_value": "December 31, 2023",
  "value": "2023-12-31",
  "unit": null
}
```

For identifiers, keep strings as strings:

```json
{
  "raw_value": "BLR-003",
  "value": "BLR-003",
  "unit": null
}
```

Current normalization caveats:

- Numbers are normalized by removing commas and parsing the first numeric token.
- Dates normalize reliably for ISO dates and slash dates like `10/01/2023`.
- Month-name date ranges like `October 1, 2023 - October 31, 2023` are useful
  gap tests; the current parser may preserve the text, but the v0 normalizer is
  stronger on ISO/slash dates.
- Units are detected from the raw value string. Unit conversion is not
  implemented. For example, `500 therms` should currently expect
  `unit: "therms"` plus a `unit_conversion_not_implemented` flag, not a
  converted MMBtu value.

## 9. Scenario Coverage

Create QA pairs for all of these scenarios.

### 9.1 Simple Single Value

Purpose: baseline extraction. This checks whether a clearly labeled value can be
found when the label and value are on the same line or in the same key/value
pair.

Parser text:

```text
Total Usage: 32,400 MMBtu
```

QA:

```json
{
  "qa_id": "EV-SIMPLE-001-Q001",
  "canonical_type_id": "CT-S1-FUELQTY",
  "field_id": "activity_quantity",
  "question": "What is the total usage?",
  "answer": {
    "value": 32400,
    "unit": "MMBtu",
    "raw_value": "32,400 MMBtu",
    "period_start": null,
    "period_end": null,
    "record_id": null
  },
  "source_expectation": {
    "source_text_contains": "32,400 MMBtu",
    "source_kind": ["page_text"]
  },
  "required": true,
  "match_rules": {
    "value_tolerance": 0,
    "case_sensitive": false,
    "allow_unit_aliases": true,
    "allow_missing_period": true
  }
}
```

### 9.2 Value And Unit Split Across Nearby Fields

Purpose: test context inference. This means the numeric amount appears in one
place and the unit appears nearby, but not in the same raw value string.

Parser text:

```text
Usage: 32,400
Usage Unit: MMBtu
```

Expected result:

```json
{
  "qa_id": "EV-CONTEXT-001-Q001",
  "canonical_type_id": "CT-S1-FUELQTY",
  "field_id": "activity_quantity",
  "question": "What is the usage and unit?",
  "answer": {
    "value": 32400,
    "unit": "MMBtu",
    "raw_value": "32,400",
    "period_start": null,
    "period_end": null,
    "record_id": null
  },
  "source_expectation": {
    "source_text_contains": "Usage Unit: MMBtu",
    "source_kind": ["page_text"]
  },
  "required": true,
  "match_rules": {
    "value_tolerance": 0,
    "case_sensitive": false,
    "allow_unit_aliases": true,
    "allow_missing_period": true
  },
  "notes": "This is expected to fail unless the extractor supports nearby unit inference."
}
```

### 9.3 Missing Unit

Purpose: verify that missing units are handled honestly. If the parser output
does not contain a unit, the deterministic extractor should not invent one.

Parser text:

```text
Total Usage: 32,400
```

QA:

```json
{
  "qa_id": "EV-MISSING-UNIT-001-Q001",
  "canonical_type_id": "CT-S1-FUELQTY",
  "field_id": "activity_quantity",
  "question": "What is the total usage?",
  "answer": {
    "value": 32400,
    "unit": null,
    "raw_value": "32,400",
    "period_start": null,
    "period_end": null,
    "record_id": null
  },
  "source_expectation": {
    "source_text_contains": "Total Usage: 32,400",
    "source_kind": ["page_text"]
  },
  "required": true,
  "match_rules": {
    "value_tolerance": 0,
    "case_sensitive": false,
    "allow_unit_aliases": true,
    "allow_missing_period": true
  }
}
```

Do not expect `MMBtu` if the parser output does not contain `MMBtu`.

### 9.4 Date / Service Period

Purpose: test date extraction and normalization. In the current config, service
period dates are two separate fields: `service_period_start` and
`service_period_end`. Use one QA pair for the start date and one for the end
date.

Parser text:

```text
Billing Period: October 1, 2023 - October 31, 2023
```

QA:

```json
{
  "qa_id": "EV-DATE-001-Q001",
  "canonical_type_id": "CT-S1-FUELQTY",
  "field_id": "service_period_start",
  "question": "What is the billing period start date?",
  "answer": {
    "value": "2023-10-01",
    "unit": null,
    "raw_value": "October 1, 2023",
    "period_start": "2023-10-01",
    "period_end": null,
    "record_id": null
  },
  "source_expectation": {
    "source_text_contains": "October 1, 2023 - October 31, 2023",
    "source_kind": ["page_text"]
  },
  "required": true,
  "match_rules": {
    "value_tolerance": 0,
    "case_sensitive": false,
    "allow_unit_aliases": false,
    "allow_missing_period": false
  }
}
```

Create a second QA pair for `field_id: service_period_end` with
`answer.value: "2023-10-31"`.

### 9.5 Multi-Record Table

Purpose: test repeated row extraction. This means the source contains multiple
meters, vehicles, transactions, or line items, and the evaluator must confirm
the extractor can return the correct value for each record. Add one QA pair per
expected row.

Parser table:

```text
Meter ID | Usage | Unit | Period End
MTR-001  | 1200  | MMBtu | 2023-12-31
MTR-002  | 900   | MMBtu | 2023-12-31
```

QA:

```json
{
  "qa_id": "EV-MULTI-001-Q001",
  "canonical_type_id": "CT-S1-FUELQTY",
  "field_id": "activity_quantity",
  "question": "What usage was reported for meter MTR-001?",
  "answer": {
    "value": 1200,
    "unit": "MMBtu",
    "raw_value": "1200",
    "period_start": null,
    "period_end": "2023-12-31",
    "record_id": "MTR-001"
  },
  "source_expectation": {
    "source_text_contains": "MTR-001",
    "source_kind": ["excel_cell", "page_text"]
  },
  "required": true,
  "match_rules": {
    "value_tolerance": 0,
    "case_sensitive": false,
    "allow_unit_aliases": true,
    "allow_missing_period": false
  }
}
```

Important current-code limitation: the v0 table lookup returns the adjacent
cell after a matching anchor. It does not yet reliably bind arbitrary row-level
questions like "usage for MTR-001" to a specific column/row. Multi-record
fixtures are therefore expected to reveal extraction algorithm gaps unless the
parser output is shaped as simple key/value rows or the extractor is improved.

### 9.6 Key-Value Pair

Purpose: test key/value extraction from text or Textract key-value output.

Parser content:

```text
Fuel Type: Diesel
Quantity: 7,500 gallons
```

QA:

```json
{
  "qa_id": "EV-KV-001-Q001",
  "canonical_type_id": "CT-S1-MOBFUEL",
  "field_id": "fuel_type",
  "question": "What fuel type is reported?",
  "answer": {
    "value": "Diesel",
    "unit": null,
    "raw_value": "Diesel",
    "period_start": null,
    "period_end": null,
    "record_id": null
  },
  "source_expectation": {
    "source_text_contains": "Fuel Type: Diesel",
    "source_kind": ["page_text"]
  },
  "required": true,
  "match_rules": {
    "value_tolerance": 0,
    "case_sensitive": false,
    "allow_unit_aliases": false,
    "allow_missing_period": true
  }
}
```

### 9.7 Mobile Fuel Quantity

Purpose: test `CT-S1-MOBFUEL` quantity extraction using gallons or liters.

Parser content:

```text
Fuel Delivery Receipt
Product: Diesel
Quantity: 7,500 gallons
Transaction Date: 2023-11-15
```

QA:

```json
{
  "qa_id": "EV-MOB-001-Q001",
  "canonical_type_id": "CT-S1-MOBFUEL",
  "field_id": "activity_quantity",
  "question": "What mobile fuel quantity was purchased?",
  "answer": {
    "value": 7500,
    "unit": "gallons",
    "raw_value": "7,500 gallons",
    "period_start": null,
    "period_end": null,
    "record_id": null
  },
  "source_expectation": {
    "source_text_contains": "Quantity: 7,500 gallons",
    "source_kind": ["page_text"]
  },
  "required": true,
  "match_rules": {
    "value_tolerance": 0,
    "case_sensitive": false,
    "allow_unit_aliases": true,
    "allow_missing_period": true
  }
}
```

### 9.8 Negative / Should-Not-Extract

Purpose: verify the extractor does not hallucinate values.

This means the parser output is valid and belongs to a plausible document, but
it does not contain the field being asked for. A pass means the generated
candidate for that field has `raw_value: null` and usually has the
`field_not_found` validation flag. A fail means the extractor picked an
unrelated value just because it saw a number or a nearby word.

Parser text:

```text
This document confirms service availability. No usage quantity is reported.
```

QA:

```json
{
  "qa_id": "EV-NEG-001-Q001",
  "canonical_type_id": "CT-S1-FUELQTY",
  "field_id": "activity_quantity",
  "question": "What is the total usage?",
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
    "source_kind": []
  },
  "required": true,
  "match_rules": {
    "value_tolerance": 0,
    "case_sensitive": false,
    "allow_unit_aliases": true,
    "allow_missing_period": true
  },
  "notes": "Passes only if no found candidate is produced for CT-S1-FUELQTY/activity_quantity."
}
```

### 9.9 Aspirational Gap Tests

Purpose: intentionally document evidence patterns S1 may need but the current
seed config does not yet support.

Examples:

- `equipment_inventory`: equipment ID, combustion unit type, capacity,
  capacity unit.
- `meter_reading_report`: previous read, current read, usage by meter.
- `emissions_report`: reported emissions quantity, emissions unit, reporting
  year.

Mark these QA files with:

```json
{
  "expected_current_status": "non_evaluable_config_gap"
}
```

These should not be counted as extraction algorithm failures. They are coverage
or product/config gaps until the repo has configured canonical types and fields
for them.

## 10. Matching Rules

Default matching:

- Numeric values match after comma removal and numeric conversion.
- Strings match case-insensitively unless `case_sensitive=true`.
- Units match case-insensitively when `allow_unit_aliases=true`.
- Dates should match ISO `YYYY-MM-DD`.
- `null` expected value means no found candidate should be produced.

Recommended unit aliases:

```json
{
  "MMBtu": ["mmbtu", "MMBTU", "MMBtu"],
  "therms": ["therm", "therms"],
  "gallons": ["gal", "gallon", "gallons"],
  "kWh": ["kwh", "KWH", "kWh"],
  "metric tons CO2e": ["tCO2e", "mtCO2e", "metric tons CO2e"]
}
```

## 11. Report Columns

The deterministic extraction report should include one row per QA pair:

```text
qa_id
document_id
document_type
canonical_type_id
field_id
question
expected_value
expected_unit
actual_value
actual_unit
expected_period_start
expected_period_end
actual_period_start
actual_period_end
expected_record_id
actual_record_id
status
failure_category
failure_reason
source_reference_present
source_text_matched
```

Recommended `status` values:

- `passed`
- `failed`
- `skipped`
- `non_evaluable`

Recommended `failure_category` values:

- `config_gap`
- `target_planning_gap`
- `extraction_algorithm_gap`
- `normalization_gap`
- `traceability_gap`
- `test_fixture_gap`

## 12. Minimum QA Set

To test all current configured deterministic extraction scenarios, create at
least:

| ID pattern | Canonical type | Field | Scenario | Minimum QA count | What to provide |
|------------|----------------|-------|----------|------------------|-----------------|
| `EV-FUELQTY-001-Q001` | `CT-S1-FUELQTY` | `facility_name` | Anchor text | 1 | Parser text like `Facility Name: Demo Plant` |
| `EV-FUELQTY-001-Q002` | `CT-S1-FUELQTY` | `fuel_type` | Key/value or anchor text | 1 | Parser text like `Fuel Type: Natural Gas` |
| `EV-FUELQTY-001-Q003` | `CT-S1-FUELQTY` | `activity_quantity` | Simple value with unit | 1 | Parser text like `Total Usage: 32,400 MMBtu` |
| `EV-FUELQTY-001-Q004` | `CT-S1-FUELQTY` | `activity_unit` | Unit extraction | 1 | Parser text like `Unit: MMBtu` or quantity text containing `MMBtu` |
| `EV-FUELQTY-001-Q005` | `CT-S1-FUELQTY` | `service_period_start` | Date normalization | 1 | Parser text like `Service Period: 10/01/2023 - 10/31/2023` |
| `EV-FUELQTY-001-Q006` | `CT-S1-FUELQTY` | `service_period_end` | Date normalization | 1 | Same period text, expected end date |
| `EV-FUELQTY-001-Q007` | `CT-S1-FUELQTY` | `supplier_name` | Conditional string | 1 | Parser text like `Supplier: Demo Utility` |
| `EV-FUELQTY-001-Q008` | `CT-S1-FUELQTY` | `account_number` | Optional regex/string | 1 | Parser text like `Account Number: 123456` |
| `EV-FUELQTY-002-Q001` | `CT-S1-FUELQTY` | `activity_quantity` | Split value/unit context | 1 | Parser text with `Usage: 32,400` and nearby `Usage Unit: MMBtu` |
| `EV-FUELQTY-003-Q001` | `CT-S1-FUELQTY` | `activity_quantity` | Missing unit | 1 | Parser text with usage value but no unit; expected unit should be `null` |
| `EV-FUELQTY-004-Q001` | `CT-S1-FUELQTY` | `activity_quantity` | Negative should-not-extract | 1 | Parser text with no usage quantity; expected value should be `null` |
| `EV-MOBFUEL-001-Q001` | `CT-S1-MOBFUEL` | `fuel_type` | Mobile fuel key/value | 1 | Parser text like `Product: Diesel` |
| `EV-MOBFUEL-001-Q002` | `CT-S1-MOBFUEL` | `activity_quantity` | Mobile fuel quantity | 1 | Parser text like `Quantity: 7,500 gallons` |
| `EV-MOBFUEL-001-Q003` | `CT-S1-MOBFUEL` | `activity_unit` | Mobile fuel unit | 1 | Parser text like `Unit: gallons` or quantity text containing `gallons` |
| `EV-MOBFUEL-002-Q001` and `Q002` | `CT-S1-MOBFUEL` | `activity_quantity` | Multi-record table | 2 | Two vehicle/transaction rows, each with stable `record_id` |

Minimum current-config total: 16 QA pairs.

Recommended current document styles:

- `natural_gas_bill` mapped to `CT-S1-FUELQTY`
- `stationary_fuel_invoice` mapped to `CT-S1-FUELQTY`
- `utility_invoice` mapped to `CT-S1-FUELQTY` when it reports stationary fuel usage
- `fuel_delivery_receipt` mapped to `CT-S1-MOBFUEL` when it reports vehicle/mobile fuel
- `fleet_fuel_card_report` mapped to `CT-S1-MOBFUEL`

Recommended aspirational gap document styles:

- `equipment_inventory`
- `meter_reading_report`
- `emissions_report`

Use aspirational gap tests to show the dev team what is not yet represented in
the extraction config, not to score the current deterministic extractor as
wrong.
