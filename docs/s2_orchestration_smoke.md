# S2 Orchestration Smoke Runtime

Subsystem 2 PR14 adds a thin backend orchestration layer over the PR5-PR13
services.

## Input Boundary

The orchestration service starts from an `ApprovedEvidence` object. It does not
parse raw documents, call S1 extraction, or read parser outputs. This preserves
the boundary:

```text
S1 review-approved evidence -> S2 methodology runtime
```

## Flow

```text
approved_evidence
  -> methodology value projection
  -> completeness tracker
  -> derivation engine
  -> verification engine
  -> S2 gap records
  -> methodology run summary
```

## Summary Fields

The PR14 summary contains:

```text
methodology_run_id
engagement_id
field_value_count
missing_required_count
not_applicable_count
verification_result_count
gap_record_count
provisional_count
```

## API

```text
POST /v1/methodology/s2/run
```

Request shape:

```json
{
  "approved_evidence": {},
  "runtime_condition_values": {},
  "persist_methodology_values": false
}
```

`runtime_condition_values` is optional. When omitted, S2 derives simple
condition values from projected methodology values by `methodology_field_id`.

## Local Smoke Script

```bash
PYTHONPATH=. .venv/bin/python backend/scripts/s2_smoke.py
```

Optional JSON output:

```bash
PYTHONPATH=. .venv/bin/python backend/scripts/s2_smoke.py \
  --output-json local-samples/s2-smoke/s2_smoke_result.json
```

The smoke script uses synthetic approved evidence and checked-in methodology
reference data. It is intended to verify wiring, counts, and contract shape, not
domain accuracy for a real engagement.
