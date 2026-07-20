# Local Extraction Smoke Testing (PR6.1)

This harness runs the full local pipeline end-to-end against private, git-ignored
sample documents and reports **extraction_candidate completeness**:

```
sample docs (optional refresh)
  → parser_output JSON (PR4/PR4.1)
  → canonical_type_id selection
  → extraction targets (PR5)
  → extraction candidates (PR6)
  → candidate JSON + completeness report
```

It is a smoke harness only. It adds no product API, persistence, review
decisions, approved evidence, gap records, RAG, S2, OCR, or external calls, and
it never mutates parser outputs or sample documents.

## How it differs from parser smoke testing

- `parser_smoke.py` (PR4.1) checks **parser** completeness: did the parser turn
  a document into a usable `parser_output`?
- `extraction_smoke.py` (PR6.1) checks **extraction** completeness: given an
  existing `parser_output` and a canonical type, how many targeted fields does
  the deterministic extractor find?

## Local ignored outputs

Generated files are written under the ignored `local-samples/` tree:

```
local-samples/extraction-smoke/outputs/<safe_stem>.extraction_candidates.json
local-samples/extraction-smoke/outputs/extraction_smoke_report.md
local-samples/extraction-smoke/outputs/extraction_smoke_summary.json
```

An optional local mapping file may live at
`local-samples/extraction-smoke/config/document_type_mapping.json` (also ignored).

## How to run

From existing local parser outputs:

```bash
python backend/scripts/extraction_smoke.py \
  --parser-output-dir "local-samples/parser-smoke/outputs" \
  --output-dir "local-samples/extraction-smoke/outputs" \
  --default-canonical-type-id "CT-S1-FUELQTY"
```

Refresh parser outputs from sample documents first:

```bash
python backend/scripts/extraction_smoke.py \
  --input-doc-dir "local-samples/parser-smoke/inputs" \
  --parser-output-dir "local-samples/parser-smoke/outputs" \
  --output-dir "local-samples/extraction-smoke/outputs" \
  --refresh-parser-outputs \
  --default-canonical-type-id "CT-S1-FUELQTY"
```

Other flags: `--mapping-file`, `--include-deprecated`, and `--no-include-optional`
(optional targets are included by default).

## How canonical_type_id is selected

Priority order (this smoke pass does not run the PR3 classifier):

1. **Explicit mapping file** — by parser-output file name or by base stem.
2. **Embedded** `canonical_type_id` in the `parser_output`, if present.
3. **Default** `--default-canonical-type-id` (`CT-S1-FUELQTY`, which is covered
   by the committed extraction config seed).

Each document records both `canonical_type_id` and `canonical_type_source`
(`mapping` | `parser_output` | `default`).

## What the report means

For each document the report shows target/candidate counts, found/missing/
unsupported/low-confidence counts, average confidence, and per-field candidate
details (field name, raw/normalized value, unit, confidence, validation flags,
and a truncated source snippet). Metrics:

- `found_count` = candidates with a non-null `raw_value`
- `missing_count` = candidates with null `raw_value` or the `field_not_found` flag
- `unsupported_count` = candidates flagged `unsupported_extraction_method`
- `low_confidence_count` = candidates with confidence < 0.50

## What the report does not mean

This is deterministic candidate generation from existing `parser_output` and
extraction targets. It is **not** a human review result, approved evidence
record, regulatory validation, calculation result, or gap analysis. A found
candidate is not a verified value.
