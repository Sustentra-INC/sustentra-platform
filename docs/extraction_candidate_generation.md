# Extraction Candidate Generation (PR6)

PR6 adds the first value-extraction layer. It combines a normalized
`parser_output` (PR4) with extraction targets (PR5) to produce
`extraction_candidate` dictionaries that conform to
`contracts/extraction_candidate.schema.json`.

## Pipeline position

```
parser_output (PR4) + extraction_targets (PR5) → extraction_candidate (PR6)
```

## Four distinct concepts

```
ParserOutput      = what the parser saw (pages, blocks, tables, key/value, refs)
ExtractionTarget  = what the system should attempt to extract for a doc type
ExtractionCandidate = actual candidate value, source, confidence, and flags
ReviewDecision    = human decision later (PR7, not implemented here)
ApprovedEvidence  = downstream source of truth later (PR8, not implemented here)
```

## How candidates are generated

`ExtractionCandidateService.generate_candidates(parser_output, extraction_targets,
evidence_id)`:

1. iterates each target;
2. runs supported extraction methods (highest-confidence method first) until one
   yields a value;
3. normalizes the raw value and detects a unit where unit patterns exist;
4. attaches a `source_reference`;
5. returns exactly one candidate per target.

Inputs are never mutated and no external services are called. `document_id` is
taken from `parser_output`; a missing `document_id` raises `ValueError`.

Candidate IDs are deterministic:

```
candidate::<evidence_id>::<document_id>::<field_id>
```

## Supported v0 methods

| Method | Source | Base confidence |
|--------|--------|-----------------|
| `key_value_pair` | `parser_output.key_value_pairs` (anchor vs. key) | 0.90 |
| `regex` | text blocks then page text (`value_patterns`) | 0.85 |
| `anchor_text` | text blocks / page lines (value after anchor) | 0.80 |
| `table_lookup` | `parser_output.tables` (adjacent cell to anchor) | 0.75 |
| `excel_cell` | Excel `source_references` (right-neighbor cell) | 0.70 |

`llm_structured` and `manual_entry` are **not** implemented. A target whose only
methods are unsupported returns a missing candidate flagged
`unsupported_extraction_method` (confidence 0.10).

## Normalization limitations

Basic normalization only:

- numbers with commas → integers/floats (`"28,100"` → `28100`);
- simple dates → ISO (`"10/01/2023"` → `"2023-10-01"`);
- trimmed strings;
- unit detection from `unit_patterns` (`"28,100 MMBtu"` → value `28100`, unit
  `"MMBtu"`).

Full unit conversion is **not** implemented. When a detected unit differs from
the target's `normalization.target_unit`, the candidate is flagged
`unit_conversion_not_implemented`. Validation flags used:

- `field_not_found` — no value for a `core`/`conditional` target;
- `unit_missing` — numeric value found but no unit, when units are expected;
- `unit_conversion_not_implemented` — unit differs from target unit;
- `unsupported_extraction_method` — only unsupported methods were configured.

## Confidence scoring

Deterministic base confidence per method (table above); missing = 0.20;
unsupported = 0.10. When a parser block/table/pair confidence exists, the
candidate confidence is combined conservatively as
`min(method_confidence, parser_confidence)` and clamped to `[0, 1]`.

## Source reference behavior

For extracted candidates, the service prefers an existing entry from
`parser_output.source_references` (matched by block/table/key/value reference
id). If none exists it builds a minimal inline reference from the block, page,
key/value pair, or table. Missing candidates get a contract-valid empty
reference:

```
missing::<document_id>::<field_id>
```

Bounding boxes are never required.

## What remains for PR7 / PR8

PR6 stops at candidate generation. It does not record review decisions
(`ReviewDecision`, PR7) or project approved evidence (`ApprovedEvidence`, PR8),
and it adds no persistence, gap analysis, completeness gate, RAG, or S2 logic.
