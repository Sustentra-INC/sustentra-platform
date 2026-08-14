# S2 Gap Records

Subsystem 2 PR13 converts S2 findings into gap records for S3.

S2 emits findings. S3 later aggregates, prioritizes, and translates them into
practitioner-facing reports.

## Gap Record Shape

```text
gap_record_id
engagement_id
evidence_id
document_id
field_id
stage = S2
substage = completeness | derivation | verification | recompute
gap_type
root_cause_code
assertion
severity
source_reference
rule_id
created_at
```

Contract:

```text
contracts/gap_record_v0.schema.json
```

## Emitted Substages

| Source | Emitted when |
|---|---|
| Completeness | `missing_required`, `provisional_condition_unknown` |
| Verification | `failed`, `cannot_verify`, `provisional`, `unsupported` |
| Derivation | Any status except `derived` |
| Recompute | Any status except `matched` |

## Non-Goals

PR13 does not:

- aggregate findings,
- write practitioner-facing wording,
- apply materiality thresholds,
- decide final ESG gap taxonomy.

Those belong to S3 and later review.
