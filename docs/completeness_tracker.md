# Completeness Tracker

Subsystem 2 PR7 adds the first completeness gate over methodology rows. It
answers whether required methodology rows have approved evidence-backed values
before later verification or calculation work runs.

The tracker implements the two guardrails most likely to cause bad document
requests if ignored:

- CX-01: only request evidence for rows whose `Value_Origin` is `extracted`.
- CX-12: conditional rows only apply when their condition evaluates true.

## Inputs

`CompletenessTrackerService.evaluate(...)` consumes:

```text
engagement_id
methodology_values
runtime_condition_values
requirement_level = Core
```

`methodology_values` are PR5 value-store records.

`runtime_condition_values` are passed to the PR6 condition evaluator and keyed
by field/reference ID.

## Result Statuses

| Status | Meaning |
|---|---|
| `complete` | A methodology value exists for the required row. |
| `missing_required` | Required row is requestable (`Value_Origin = extracted`) and has no value. |
| `not_applicable` | Row condition evaluated false; the row is not missing. |
| `provisional_condition_unknown` | Row condition is unknown or unsupported; requires review rather than automatic missing. |
| `not_requestable_value_origin` | Row has no value, but its `Value_Origin` is not requestable evidence, such as `computed`, `verifier_determined`, or `assigned`. |

## Output Shape

The service returns:

```text
engagement_id
status_counts
results[]
```

Each row result includes:

```text
field_id
layer
value_origin
requirement_level
condition
condition_status
status
methodology_value_ids
reason
```

The JSON contract lives at:

```text
contracts/completeness_result.schema.json
```

## Behavior

- Rows are evaluated from `list_required_rows("Core")` by default.
- Rows with false conditions return `not_applicable`, never `missing_required`.
- Rows with unknown or unsupported conditions return
  `provisional_condition_unknown`.
- Missing `computed`, `verifier_determined`, and `assigned` rows are
  `not_requestable_value_origin`.
- Missing `extracted` rows are `missing_required`.

## Non-Goals

PR7 does not:

- execute verification rules,
- run formulas,
- derive computed fields,
- resolve edge joins,
- decide final ESG wording for missing-field reports.

Those belong to later S2 PRs.
