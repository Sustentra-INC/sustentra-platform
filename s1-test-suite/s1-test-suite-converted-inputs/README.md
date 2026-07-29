# Converted S1 Production Parser Inputs

The original evidence source was only:
`Evidence_Pack_Generated_Review_Pack_Nora.docx`

The production ParserService does not support DOCX. Therefore this directory
contains derived fixtures for testing supported parser routes.

## Important limitation

These are NOT original client-native PDFs/XLSX files.

They test:
- parser routing
- downstream extraction pipeline behavior
- classification/target/candidate stages

They do NOT measure:
- true OCR accuracy on original scans
- native PDF table extraction quality
- native Excel parsing quality

## Inputs

- production_inputs/text/
  - TextParser fixtures

- production_inputs/pdf/
  - PDFParser fixtures (derived)

- production_inputs/excel/
  - Excel-style table fixtures (CSV derived from source tables)

## Recommended usage

Use:

EV-NG-2023-001
- PDF/text extraction path
- key-value + table extraction

EV-INV-2023-001
- Excel/table extraction path

EV-BIO-2023-003
- table extraction path

EV-RFO-2023-001
- text/anchor extraction path

EV-BLR003-2023-001
- operational record extraction path

Keep the original DOCX as the human annotation/reference source.
