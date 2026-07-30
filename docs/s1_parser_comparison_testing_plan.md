# S1 Parser Comparison Testing Plan

This plan covers parser-layer testing only:

```text
raw document fixture -> ParserService -> parser_output
```

It does not evaluate classification, deterministic extraction, normalization,
review, approved evidence, or calculations.

## Goals

The parser test should answer two questions:

1. Did the parser preserve the expected evidence content accurately enough for
   downstream extraction?
2. Did the parser return a valid `parser_output` structure with the fields the
   pipeline expects?

The test should run in two modes:

- `local`: `TEXTRACT_ENABLED=false`; uses deterministic/local parsers.
- `aws`: `TEXTRACT_ENABLED=true`; sends PDF/image fixtures to live AWS
  Textract. This mode requires credentials and can incur AWS costs.

## Parser Paths To Cover

| Parser path | Inputs needed | Expected output contract |
|-------------|---------------|--------------------------|
| `TextParser` | `.txt`, `.md` | `pages`, `text_blocks`, `source_references`; no structured table requirement |
| `CsvParser` | `.csv` | `pages`, row-level `text_blocks`, `source_references`, and one structured table |
| `ExcelParser` | `.xlsx`, `.xlsm` | `text_blocks`, `tables`, cell-level `source_references` |
| local `PdfParser` | embedded-text `.pdf` | `pages`, `text_blocks`, page-level `source_references`; tables are not guaranteed |
| local `ImageParser` | image files with `TEXTRACT_ENABLED=false` | failed parser output with `ocr_not_implemented` warning |
| live `AwsTextractParser` | scanned/image PDF or image with `TEXTRACT_ENABLED=true` | `pages`, `text_blocks`, and optionally `tables` / `key_value_pairs` |
| offline `TextractParser` | saved AWS Textract JSON | normalized `pages`, `text_blocks`, `tables`, `key_value_pairs` |

## Test Harness

Use:

```bash
PYTHONPATH=. python backend/scripts/parser_comparison_smoke.py
```

This runs local parser checks only and writes:

```text
local-data/parser-comparison-results/parser_comparison_report.md
local-data/parser-comparison-results/parser_comparison_results.csv
local-data/parser-comparison-results/parser_outputs/
```

By default the script exits 0 after writing the report, even when parser gaps
are found. Use `--fail-on-parser-gaps` when you want CI-style failure behavior.

To include live AWS Textract:

```bash
export AWS_PROFILE=<your-profile>
export TEXTRACT_REGION=us-east-1
PYTHONPATH=. python backend/scripts/parser_comparison_smoke.py --include-aws --aws-input-kind png
```

`--aws-input-kind` can be `png`, `pdf`, or `both`.

## Document Types Needed

Minimum recommended fixture set:

| Document type / style | Why needed | Local parser input | AWS parser input |
|-----------------------|------------|--------------------|------------------|
| Natural gas utility bill | Tests key S1 stationary fuel evidence, billing period, account, usage, unit, charges table | `.txt` and embedded-text `.pdf` | scanned/image `.pdf` or `.png` |
| Equipment inventory workbook/table | Tests Excel tables, cell traceability, equipment rows, headers | `.xlsx` and/or `.csv` | scanned/image `.pdf` or `.png` if visual inventory tables must be OCR-tested |
| Biogas meter log | Tests meter-log style text/table and non-pipeline fuel wording | `.txt` or `.csv` | scanned/image `.pdf` or `.png` |
| BLR-003 monthly fuel record | Tests monthly repeated fuel records and unit variants such as `Mcf` / short tons | `.txt` or `.csv` | scanned/image `.pdf` or `.png` |
| Propane annual fuel record | Tests mobile/stationary-like delivery totals, gallons units, supplier/account fields | `.txt` or `.csv` | scanned/image `.pdf` or `.png` |
| Diesel delivery detail | Tests multi-record delivery rows, ticket IDs, gallons delivered | `.txt` or `.csv` | scanned/image `.pdf` or `.png` |
| No-activity / standby statement | Tests that parser preserves zero/no-activity language and does not drop critical negative evidence | `.txt` | scanned/image `.pdf` or `.png` |
| Saved Textract JSON fixture | Tests offline Textract JSON normalizer deterministically without AWS credentials | `.json` only via `parse_textract_json(...)` | not applicable |

## Comparing Local And AWS

The same document scenario should be represented in both modes where practical:

- Local text/PDF/Excel checks tell us whether clone-and-test mode preserves
  enough content without AWS.
- AWS checks tell us whether scanned PDFs/images preserve the same content and
  whether Textract returns useful tables/key-value pairs.

Do not require identical serialization between local and AWS outputs. Compare
containment and contract-level structure:

- required text snippets are present;
- required table headers/rows are present when the parser promises tables;
- `parser_output` has required top-level fields;
- pages/text blocks/tables/key-value/source-reference fields are lists;
- warnings are structured.

## Preliminary AWS Parser Checks

The live AWS parser is considered preliminarily wired if:

- `ParserService` routes PDFs/images to `AwsTextractParser` only when
  `TEXTRACT_ENABLED=true`;
- text/CSV/Excel remain local even when Textract is enabled;
- `AwsTextractParser` calls `textract.analyze_document` with document bytes;
- the AWS response is normalized through `TextractParser`;
- failures return schema-shaped `parser_output` with a `textract_call_failed`
  warning instead of raising uncaught exceptions.
