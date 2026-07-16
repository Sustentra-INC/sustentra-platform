# Parser Output Runtime (PR4)

## Purpose

PR4 adds the first real document parsing layer for the Sustentra evidence
platform. It converts a local file into a normalized, tool-agnostic
`parser_output` object:

```
local document file → parser adapter → parser_output-shaped dict
```

It is deliberately narrow: PR4 does **not** perform field extraction, generate
`extraction_candidate` records, persist review decisions, run RAG, or evaluate
S2 methodology. It makes no external network, AWS, or OpenAI calls.

## What `parser_output` represents

`parser_output` is the normalized result of parsing a document *before* any
field extraction. It conforms to `contracts/parser_output.schema.json` and
includes:

- `parser_output_id`, `document_id`, `processing_run_id`
- `parser_name`, `parser_version`, `status`, `created_at`
- `pages` — page number and page text
- `text_blocks` — traceable chunks of text
- `tables` — row grids (used by Excel and Textract table blocks)
- `key_value_pairs` — normalized key/value pairs (Textract only in v0)
- `source_references` — traceability records linking output back to the document
- `warnings` — structured `{code, message, severity}` notes
- `raw_artifact_uri` — optional; left `null` in v0

`status` is one of `parsed`, `partial`, `empty`, or `failed`.

## Supported parser types in v0

| Input | Adapter | `parser_name` | Notes |
|-------|---------|---------------|-------|
| `.txt`, `.md`, `.markdown`, `.csv` | `TextParser` | `text_parser` | UTF-8 text; one page, one block per non-empty line |
| `.xlsx`, `.xlsm` | `ExcelParser` | `openpyxl` | Non-empty cells become blocks + source references; each sheet becomes a table |
| `.pdf` | `PdfParser` | `pymupdf` / `pdfplumber` | Embedded text only; graceful fallback if no dependency or unreadable file |
| image types | `ImageParser` | `image_ocr` | Explicit stub: `failed` + `ocr_not_implemented` warning |
| saved Textract JSON | `TextractParser` | `textract` | Normalizes existing JSON only; **never** calls AWS |

Routing is handled by `ParserService.parse_document(...)` using file extension
first, then an optional `mime_type` hint. Textract normalization is invoked
explicitly via `ParserService.parse_textract_json(...)`.

## What is intentionally not implemented

- Field/ESG value extraction and `extraction_candidate` generation
- LLM/OpenAI calls
- Live AWS Textract calls (only offline JSON normalization)
- Image OCR (explicit stub only)
- Review decisions, approved evidence, completeness gate, gap analysis
- Frontend, RAG, and S2 methodology logic
- Persistence and file-upload API wiring

## How source references are created

Each meaningful unit of parsed content produces a `source_reference` that ties
it back to the original document:

- **Text**: one reference per non-empty line, `source_kind = page_text`, with
  `page_number = 1` and a `text_snippet`.
- **Excel**: one reference per non-empty cell, `source_kind = excel_cell`, with
  `sheet_name` and `cell_or_range` (e.g. `A1`) and a `text_snippet`.
- **PDF**: one reference per page with extractable text, `source_kind =
  page_text`, with `page_number` and a `text_snippet`.
- **Textract**: references derived from Textract block ids and page numbers.

Text blocks carry a `source_reference_id` back-link, and source references carry
`parser_block_ids`, giving a two-way trace between normalized output and the
originating region of the document. Identifiers are deterministic where possible
so outputs are stable and testable.

## How this feeds future extraction

The parser runtime is the second stage of the planned pipeline:

```
PR2/PR3 classification
  → PR4 parser_output           (this PR)
  → PR5 extraction targets/config
  → PR6 extraction_candidate generation
  → PR7 review decisions
  → PR8 approved evidence
```

Later PRs will read `parser_output` (its `text_blocks`, `tables`,
`key_value_pairs`, and `source_references`) to generate `extraction_candidate`
records with full source traceability. Because every candidate can point at a
`source_reference_id`, extracted values remain auditable back to the exact page,
cell, or block they came from.
