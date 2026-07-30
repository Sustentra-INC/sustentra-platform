# S1 Parser Test Material Specification

This document defines the raw test files and expected-answer files needed to
test every current parser path in the S1 evidence extraction repo.

The goal is to avoid false failures by matching expectations to the parser path
being tested:

- Local parsers test the current local parser contract.
- Live AWS Textract tests OCR/table/key-value behavior only when
  `TEXTRACT_ENABLED=true`.
- Deterministic extraction tests use normalized `parser_output` JSON and should
  not depend on the raw file format.

## 1. Test Modes

Every parser fixture should be evaluated in one or both modes.

| Mode | Environment | Purpose |
|------|-------------|---------|
| Local parser baseline | `TEXTRACT_ENABLED=false` | Confirms repo behavior without AWS credentials |
| Live Textract | `TEXTRACT_ENABLED=true` | Confirms PDF/image OCR through AWS Textract |

Expected outputs must state which mode they apply to.

## 2. Directory Layout

Use this strict layout for parser materials:

```text
s1-test-suite/
  parser_materials/
    raw/
      text/
      csv/
      excel/
      pdf_text/
      pdf_scanned/
      images/
      textract_json/
    expected/
      local/
      textract/
      extraction/
```

Recommended file naming:

```text
<DOCUMENT_ID>__<document_type>__<case_slug>.<ext>
```

Examples:

```text
EV-NG-2023-001__natural_gas_bill__single_meter.txt
EV-NG-2023-002__natural_gas_bill__scanned_table.pdf
EV-INV-2023-001__equipment_inventory__xlsx_table.xlsx
EV-MTR-2023-001__meter_photo__image_receipt.png
```

The `DOCUMENT_ID` must be stable and reused in the expected-answer file.

## 3. Expected Answer File Format

Each raw document should have a matching expected-answer JSON file.

File name:

```text
<DOCUMENT_ID>.expected.json
```

Minimum schema:

```json
{
  "document_id": "EV-NG-2023-001",
  "raw_file": "parser_materials/raw/text/EV-NG-2023-001__natural_gas_bill__single_meter.txt",
  "document_type": "natural_gas_bill",
  "applicable_modes": ["local", "textract"],
  "parser_expectations": {
    "local": {
      "expected_parser_names": ["text_parser"],
      "expected_status": ["parsed"],
      "text_contains": ["Natural Gas Invoice", "32,400 MMBtu"],
      "expected_table_headers": [],
      "expected_key_values": {}
    },
    "textract": null
  },
  "classification_expectations": {
    "expected_label": "natural_gas_bill"
  },
  "extraction_expectations": [
    {
      "canonical_type_id": "activity_amount",
      "expected_value": 32400,
      "expected_unit": "MMBtu",
      "required": true,
      "source_text_contains": "32,400 MMBtu"
    }
  ],
  "traceability_expectations": {
    "requires_source_reference": true,
    "expected_source_kind": ["page_text", "excel_cell"]
  },
  "notes": ""
}
```

Rules:

- Use `null` when a mode is not applicable.
- Do not expect local PDF parsing to return structured tables.
- Do not expect image OCR locally. Local image parsing should return the
  `ocr_not_implemented` warning unless Textract is enabled.
- Do not expect units if the raw document does not contain the unit nearby,
  unless the expected behavior is explicitly testing context inference.
- `source_text_contains` must appear in the raw document or parser output.

## 4. Parser Types To Test

### 4.1 Text Parser

Raw format:

- File extension: `.txt`, `.md`, or `.markdown`
- Encoding: UTF-8
- Use plain text lines, not screenshots pasted into documents.
- Include values and units on the same line for extraction tests where possible.

Recommended cases:

| Case | Raw file requirement | Expected parser behavior |
|------|----------------------|--------------------------|
| Single value | One clear value line, e.g. `Usage: 32,400 MMBtu` | `text_blocks` contains the line |
| Multiple records | Several meter/equipment rows in plain text | All rows appear in `text_blocks` or page text |
| Missing unit | Value appears without unit | Parser passes text through; extraction may fail or unit may be null |
| Date normalization | Include `Billing Period End: December 31, 2023` | Text contains original date |

Expected local parser fields:

```json
{
  "expected_parser_names": ["text_parser"],
  "expected_status": ["parsed"],
  "text_contains": ["Usage: 32,400 MMBtu"],
  "expected_table_headers": [],
  "expected_key_values": {}
}
```

### 4.2 CSV / Plain Delimited Text

Raw format:

- File extension: `.csv`
- UTF-8
- Header row required.
- Use comma delimiters and quote cells only when needed.

Recommended cases:

```csv
Meter ID,Previous Read,Current Read,Usage,Unit,Period End
NFG-BWV-239871,1200,33600,32400,MMBtu,2023-12-31
```

Expected behavior:

- Current repo routes `.csv` to `CsvParser`.
- Therefore expect both text content and one structured table object.

Expected local parser fields:

```json
{
  "expected_parser_names": ["csv_parser"],
  "expected_status": ["parsed"],
  "text_contains": [
    "Meter ID,Previous Read,Current Read,Usage,Unit,Period End",
    "NFG-BWV-239871,1200,33600,32400,MMBtu,2023-12-31"
  ],
  "expected_table_headers": ["Meter ID", "Previous Read", "Current Read", "Usage", "Unit", "Period End"],
  "expected_key_values": {}
}
```

### 4.3 Excel Parser

Raw format:

- File extension: `.xlsx` or `.xlsm`
- Real workbook file, not renamed CSV.
- Put test data in cells, not embedded screenshots.
- Use stable sheet names.
- Avoid merged cells for baseline tests; add a separate merged-cell stress case
  only if needed.

Recommended baseline workbook:

Sheet name:

```text
Inventory
```

Cells:

```text
A1 Unit ID
B1 Description
C1 Fuel Type
D1 Max Rated Capacity
E1 Capacity Unit
A2 BLR-003
B2 Boiler 3
C2 Natural Gas
D2 125
E2 MMBtu/hr
```

Expected local parser fields:

```json
{
  "expected_parser_names": ["openpyxl"],
  "expected_status": ["parsed"],
  "text_contains": ["BLR-003", "Natural Gas", "125", "MMBtu/hr"],
  "expected_table_headers": [
    "Unit ID",
    "Description",
    "Fuel Type",
    "Max Rated Capacity",
    "Capacity Unit"
  ],
  "expected_key_values": {}
}
```

Excel stress cases:

- Multiple sheets.
- Empty workbook/sheet.
- Header row not on row 1.
- Numeric cells formatted with commas.
- Dates stored as Excel dates.

Each stress case should have its own expected file.

### 4.4 Local PDF Parser

Raw format:

- File extension: `.pdf`
- Must contain embedded/selectable text for local parser tests.
- Do not use scanned-image PDFs for local parser success cases.
- Tables may appear visually, but local `PdfParser` should only be expected to
  return page text.

Recommended local PDF content:

```text
Natural Gas Invoice
Meter ID: NFG-BWV-239871
Billing Period End: December 31, 2023
Usage: 32,400 MMBtu
```

Expected local parser fields:

```json
{
  "expected_parser_names": ["pymupdf", "pdfplumber", "pdf_parser"],
  "expected_status": ["parsed", "partial"],
  "text_contains": [
    "Natural Gas Invoice",
    "NFG-BWV-239871",
    "32,400 MMBtu"
  ],
  "expected_table_headers": [],
  "expected_key_values": {}
}
```

Important:

- Do not require `tables` for local PDF parser tests.
- A visually tabular PDF can still be local-parser-pass if the text appears in
  `pages` or `text_blocks`.

### 4.5 Scanned PDF Through Textract

Raw format:

- File extension: `.pdf`
- Content may be scanned/image-based.
- Use only in `TEXTRACT_ENABLED=true` mode.
- Keep files small enough for synchronous Textract `AnalyzeDocument`.

Recommended scanned PDF content:

```text
Natural Gas Invoice
Meter ID: NFG-BWV-239871
Previous Read | Current Read | Usage | Unit
1,200         | 33,600       | 32,400 | MMBtu
```

Expected Textract parser fields:

```json
{
  "expected_parser_names": ["aws_textract"],
  "expected_status": ["parsed", "partial"],
  "text_contains": [
    "Natural Gas Invoice",
    "NFG-BWV-239871",
    "32,400",
    "MMBtu"
  ],
  "expected_table_headers": [
    "Previous Read",
    "Current Read",
    "Usage",
    "Unit"
  ],
  "expected_key_values": {}
}
```

Important:

- Textract table detection can vary with visual layout. For strict table tests,
  use clean grid lines, high contrast, and large readable text.
- If table structure is not essential to extraction, use `text_contains` as the
  required expectation and table headers as optional diagnostics.

### 4.6 Image Parser Through Textract

Raw format:

- File extension: `.png`, `.jpg`, `.jpeg`, `.tif`, `.tiff`, `.gif`, `.bmp`, or
  `.webp`
- Use high-resolution, upright images.
- Avoid glare, rotation, handwriting, and low contrast in baseline tests.
- Use only in `TEXTRACT_ENABLED=true` mode for successful OCR expectations.

Recommended image content:

```text
Fuel Delivery Receipt
Fuel Type: Diesel
Quantity: 7,500 gallons
Delivery Date: 2023-11-15
```

Expected Textract parser fields:

```json
{
  "expected_parser_names": ["aws_textract"],
  "expected_status": ["parsed", "partial"],
  "text_contains": [
    "Fuel Delivery Receipt",
    "Diesel",
    "7,500 gallons",
    "2023-11-15"
  ],
  "expected_table_headers": [],
  "expected_key_values": {
    "Fuel Type": "Diesel",
    "Quantity": "7,500 gallons"
  }
}
```

Local-mode expectation for the same image:

```json
{
  "expected_parser_names": ["image_ocr"],
  "expected_status": ["failed"],
  "expected_warning_codes": ["ocr_not_implemented"],
  "text_contains": [],
  "expected_table_headers": [],
  "expected_key_values": {}
}
```

### 4.7 Saved Textract JSON Normalizer

Raw format:

- File extension: `.json`
- Must be an AWS Textract response JSON with a top-level `Blocks` array.
- This tests `ParserService.parse_textract_json(...)`, not live AWS.

Minimum JSON example:

```json
{
  "Blocks": [
    {
      "Id": "line-1",
      "BlockType": "LINE",
      "Text": "Usage 32,400 MMBtu",
      "Page": 1,
      "Confidence": 99.0
    }
  ]
}
```

Expected parser fields:

```json
{
  "expected_parser_names": ["textract"],
  "expected_status": ["parsed"],
  "text_contains": ["Usage 32,400 MMBtu"],
  "expected_table_headers": [],
  "expected_key_values": {}
}
```

Use saved Textract JSON to create deterministic parser tests when live AWS
responses are too variable.

## 5. Extraction Expected Answer Format

For deterministic extraction, expected answers should be independent of raw
file type. The input to this stage is `parser_output`, not the original PDF,
Excel, text, or image file.

Use this format:

```json
{
  "document_id": "EV-NG-2023-001",
  "document_type": "natural_gas_bill",
  "extraction_expectations": [
    {
      "canonical_type_id": "activity_amount",
      "expected_value": 32400,
      "expected_unit": "MMBtu",
      "expected_period_end": "2023-12-31",
      "required": true,
      "source_text_contains": "32,400 MMBtu"
    },
    {
      "canonical_type_id": "meter_id",
      "expected_value": "NFG-BWV-239871",
      "expected_unit": null,
      "required": true,
      "source_text_contains": "NFG-BWV-239871"
    }
  ]
}
```

Rules:

- `expected_value` should be normalized when the extractor promises normalized
  output.
- `source_text_contains` should use the raw surface form from the parser output.
- If multiple records are expected, provide one object per record and include a
  stable identifier such as `meter_id`, `unit_id`, or `row_label`.
- Use `required=false` only for optional diagnostics.

## 6. Minimum Recommended Fixture Set

Create at least these fixtures before running a full S1 parser comparison.

| ID | Parser path | Raw type | Purpose |
|----|-------------|----------|---------|
| `EV-TXT-001` | Local text | `.txt` | Simple single-value extraction |
| `EV-CSV-001` | Local text CSV | `.csv` | Delimited multi-record extraction |
| `EV-XLSX-001` | Excel | `.xlsx` | Structured workbook table |
| `EV-PDFTXT-001` | Local PDF | embedded-text `.pdf` | PDF text extraction baseline |
| `EV-PDFSCAN-001` | Textract | scanned `.pdf` | OCR and table detection |
| `EV-IMG-001` | Textract/local image stub | `.png` or `.jpg` | Image OCR versus local stub |
| `EV-TEXJSON-001` | Offline Textract JSON | `.json` | Deterministic Textract normalizer |

## 7. Pass/Fail Classification

Classify failures this way:

| Category | Meaning |
|----------|---------|
| `fixture_error` | Raw document does not contain the expected content |
| `parser_contract_mismatch` | Expected-answer file asks for output the parser does not promise |
| `local_parser_limitation` | Local parser cannot OCR or structure the document |
| `textract_runtime_error` | AWS credentials, permissions, region, request size, or Textract call failed |
| `textract_ocr_gap` | Textract ran but did not detect required text/table/key-value content |
| `classification_gap` | Parser output is usable but document type is wrong |
| `config_gap` | Required canonical type is missing from extraction config |
| `target_planning_gap` | Config exists but target was not planned |
| `extraction_algorithm_gap` | Target exists but deterministic extraction missed or misread it |
| `normalization_gap` | Raw candidate found but value/unit/date normalization is wrong |
| `traceability_gap` | Candidate exists but lacks valid source reference |

Only `classification_gap`, `config_gap`, `target_planning_gap`,
`extraction_algorithm_gap`, `normalization_gap`, and `traceability_gap` should
be counted as S1 code/product gaps after fixture and parser-contract issues are
removed.

## 8. Fixture Creation Checklist

Before adding a fixture to the test suite:

- Raw file opens normally in a standard viewer.
- Raw file extension matches the intended parser route.
- Expected-answer file points to the exact raw file.
- Expected text appears visibly in the raw file.
- Units are present where unit extraction is expected.
- Multi-record tests include stable record identifiers.
- Local PDF tests use embedded/selectable text.
- Scanned PDF/image tests are marked Textract-only for success expectations.
- Expected table assertions are not required for local PDF parser tests.
- Expected JSON includes `applicable_modes`.
