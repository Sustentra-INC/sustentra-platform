# Local Parser Smoke Testing (PR4.1)

This harness runs the PR4 parser runtime against local sample documents to check
`parser_output` completeness. It does **not** perform field extraction, ESG value
evaluation, `extraction_candidate` generation, review decisions, or approved
evidence — only parser-layer output is exercised.

## Local samples are ignored

Sample documents and generated outputs live under:

```
local-samples/parser-smoke/inputs/
local-samples/parser-smoke/outputs/
```

The entire `local-samples/` tree is git-ignored. Sample documents are private
and are **not** committed to the repository. Do not stage or commit them.

## How to run

```bash
python backend/scripts/parser_smoke.py \
  --input-dir "local-samples/parser-smoke/inputs" \
  --output-dir "local-samples/parser-smoke/outputs"
```

Both arguments default to the paths above, so `python backend/scripts/parser_smoke.py`
works without flags. The script:

- iterates files in the input directory (non-recursive), skipping hidden files;
- calls `ParserService.parse_document(...)` for each file;
- writes one `<safe_stem>.parser_output.json` per input file;
- writes `parser_smoke_report.md` and `parser_smoke_summary.json`.

It makes no AWS, OpenAI, network, or OCR calls and never modifies the inputs.

## What the report means

For each file the report records `parser_name`, `status`, page/text-block/table/
key-value/source-reference counts, and warnings. It also computes a single
parser-completeness signal:

```
usable_for_extraction_later =
  status in {parsed, partial} AND (text_blocks + tables + key_value_pairs) > 0
```

This indicates the parser produced traceable content that a **future** extraction
PR could consume.

## What the report does not mean

`usable_for_extraction_later` is a parser signal only. It does **not** mean any
ESG field was found, validated, or extracted. It says nothing about extraction
candidates, review outcomes, or approved evidence. Those belong to later PRs
(PR5+).
