# Vocabulary Loader (PR2)

The vocabulary loader reads the Vocabulary Library workbook as runtime reference data for S1 document identification.

- Source workbook: `Vocabulary_Library*.xlsx` under `reference-data/`.
- Required sheets: `Canonical_Types`, `Variants`.
- Required columns are validated before loading.
- Rows are treated as mutable data; column names are treated as stable contract.
- Canonical and variant records are keyed by stable IDs (`canonical_type_id`, `variant_id`).
- Variants join to canonical types via `canonical_type_id` and orphan variants fail loudly.
- `multi_type` values are parsed to booleans.
- `confidence_threshold_default` supports numeric and provisional text formats.

The loader does not perform extraction, regulatory verification, or methodology evaluation.
