# Methodology Value Store

Subsystem 2 PR5 adds an engagement-specific methodology value snapshot. It
projects approved S1 evidence fields through the PR4 mapping service into
methodology `Field_ID` / `data_schema_field` values.

PR5 changes the handoff from:

```text
approved evidence field
```

to:

```text
engagement-specific methodology value
```

## Inputs

The service consumes an approved evidence aggregate from
`ApprovedEvidenceService`, with fields such as:

```text
approved_evidence_id
engagement_id
evidence_id
document_id
evidence_type
fields[].field_name
fields[].approved_value
fields[].approved_unit
fields[].source_reference
fields[].review_decision_id
```

It uses:

- `ApprovedEvidenceMappingService` from PR4 to find methodology targets.
- `MethodologyRegistryService` from PR3 to copy methodology row metadata such as
  `grain`.

## Output Record

Each projected value has:

```text
methodology_value_id
engagement_id
evidence_id
document_id
methodology_field_id
data_schema_field
grain
record_key
approved_value
approved_unit
source_reference
approved_evidence_id
review_decision_id
value_origin = approved_evidence
created_at
```

## Projection Behavior

- One approved field can create zero, one, or multiple methodology values.
- Unmapped approved fields are reported in `unmapped_fields`.
- Deprecated mappings are excluded by default because PR4 excludes deprecated
  mappings from normal runtime queries.
- Projection preserves source traceability from approved evidence.
- Re-projecting the same `approved_evidence_id` replaces that approved-evidence
  snapshot in the repository.

## Record Key Policy

`record_key` is provisional in PR5.

If `source_reference` contains one of the following, PR5 uses it:

```text
record_key
record_id
row_id
line_item_id
```

Otherwise PR5 falls back to:

```text
evidence_id::document_id::field_name
```

ESG still needs to confirm grain-specific record keys for common grains such as:

```text
facility
fuel_record
delivery_point
billing_period
emission_factor_set
```

## Persistence

PR5 includes:

```text
backend/app/repositories/methodology_value_repository.py
```

The repository follows the existing local backend pattern:

- in-memory repository for tests/transient use,
- JSONL repository under ignored `local-data/` for local persistence.

Default JSONL path:

```text
local-data/methodology-values/methodology_values.jsonl
```

## Non-Goals

PR5 does not:

- evaluate completeness,
- evaluate conditions,
- run verification rules,
- execute calculations,
- derive computed methodology rows,
- decide final ESG grain semantics.

Those belong to later S2 PRs.
