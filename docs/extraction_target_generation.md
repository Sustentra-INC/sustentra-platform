# Extraction Target Generation (PR5)

PR5 adds the first runtime layer that answers:

> Given a classified document `canonical_type_id`, which fields should S1 try to
> extract?

It does **not** extract any values. It selects *which fields to attempt* and
returns their target metadata. Extracting actual values into
`extraction_candidate` records happens later, in PR6.

## Three distinct concepts

```
ExtractionConfig    = instructions / target metadata (how a field could be found)
ExtractionTarget    = selected fields to attempt for a classified document
ExtractionCandidate = actual extracted value from parser_output (PR6, not this PR)
```

- **ExtractionConfig** rows live in
  `reference-data/extraction-config/extraction_config_seed.json` and follow
  `contracts/extraction_config.schema.json`. They describe a field, its
  `canonical_type_id`, value type, requiredness, hints, and permitted extraction
  methods — as configuration only.
- **ExtractionTarget** is a config selected for a specific classified document,
  returned as a dictionary with a deterministic `target_id`:

  ```
  target::<canonical_type_id>::<field_id>
  ```

- **ExtractionCandidate** is an actual value pulled from `parser_output`. PR5
  never produces these and never reads `parser_output`.

## How the seed is used

`ExtractionConfigLoader`:

- loads the JSON array seed;
- validates required fields and enums (`value_type`, `required_status`,
  `extraction_methods`, `population_status`);
- normalizes pipe-delimited strings and lists into tuples;
- rejects duplicate `extraction_config_id` and duplicate
  `(canonical_type_id, field_id)` pairs.

`ExtractionTargetService`:

- filters configs by `canonical_type_id`;
- excludes `deprecated`/`archived` configs unless explicitly included;
- includes optional fields by default (toggle with `include_optional`);
- orders targets deterministically: `core` → `conditional` → `optional` →
  `derived`, then `field_id` ascending;
- maps a `document_classification_result`-shaped dict to targets:
  - `classified` → targets for `primary_canonical_type_id`;
  - `multi_type_candidate` → aggregated targets across the primary and every
    distinct candidate `canonical_type_id`;
  - `low_confidence` / `unclassified` / `failed` → empty list (no targets are
    attempted without a confident type).

## Why PR5 does not extract values

Separating *target planning* from *value extraction* keeps each stage testable
and auditable. Target metadata is stable configuration; extracted values require
`parser_output` and per-field logic, which belong to PR6 and later. Keeping PR5
free of extraction avoids coupling configuration to any specific parser output.

## How PR5 feeds PR6

PR6 will combine:

```
parser_output (PR4) + extraction targets (PR5) → extraction_candidate
```

Each target carries the metadata PR6 needs (anchor labels, value/unit patterns,
table/sheet hints, extraction methods, normalization) plus a stable `target_id`,
so extracted candidates can be traced back to the target that requested them.
