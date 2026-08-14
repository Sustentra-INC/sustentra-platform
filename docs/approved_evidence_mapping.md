# Approved Evidence Mapping

Subsystem 2 PR4 adds the definition-level mapping from approved S1 evidence
fields to official methodology `Field_ID`s and `Data_Schema_Field(s)`.

PR4 answers:

```text
When I receive approved field X of canonical type Y,
which methodology field(s) can it populate?
```

It does not create engagement-specific methodology values. That belongs to the
methodology field value store / engagement snapshot work in PR5.

## Seed File

The checked-in seed lives at:

```text
reference-data/methodology/approved_evidence_field_mapping_seed.json
```

The seed is intentionally small and provisional. It exists to exercise the
backend loader/service contract without pretending the S1-to-methodology mapping
catalog is complete.

Example record:

```json
{
  "canonical_type_id": "CT-S1-FUELQTY",
  "approved_field_name": "activity_quantity",
  "methodology_field_id": "S1-STC-010",
  "data_schema_field": "quantity_combusted",
  "mapping_status": "provisional",
  "notes": "Maps reviewed stationary fuel quantity to the stationary combustion quantity field."
}
```

The logical uniqueness key is:

```text
(canonical_type_id, approved_field_name, methodology_field_id, data_schema_field)
```

This allows one approved S1 field to map to multiple methodology targets when
the domain requires it.

## Statuses

Allowed mapping statuses:

| Status | Meaning |
|---|---|
| `confirmed` | ESG/domain-reviewed and accepted. |
| `provisional` | Structurally valid, likely correct, but not final domain content. |
| `needs_domain_review` | Structurally valid but explicitly requires ESG review. |
| `deprecated` | Retained for history but excluded from default runtime mapping queries. |

The initial seed does not invent `confirmed` mappings for test coverage.

## Loader

Loader module:

```text
backend/app/reference/approved_evidence_mapping_loader.py
```

The loader validates only seed structure:

- JSON object with a `mappings` list,
- required fields are present,
- `mapping_status` is one of the allowed statuses,
- exact duplicate logical keys are rejected.

The loader does not validate methodology references. That keeps it independent
from PR3's methodology registry.

## Service

Service module:

```text
backend/app/services/approved_evidence_mapping_service.py
```

The service accepts structurally loaded mappings plus a
`MethodologyRegistryService`. It validates:

- `methodology_field_id` resolves to a methodology row,
- `data_schema_field` exists on that methodology row.

These failures are hard errors. `provisional` and `needs_domain_review` describe
domain confidence, not structural validity.

Supported queries:

| Method | Purpose |
|---|---|
| `list_mappings(include_deprecated=False)` | List runtime mappings, excluding deprecated by default. |
| `list_by_canonical_type(canonical_type_id, include_deprecated=False)` | List mappings for one canonical approved-evidence type. |
| `list_by_approved_field(canonical_type_id, approved_field_name, include_deprecated=False)` | List mappings for one approved field; returns a tuple because mappings may be one-to-many. |
| `get_mapping(canonical_type_id, approved_field_name, methodology_field_id, data_schema_field)` | Return a singular mapping by full logical key. |
| `list_by_methodology_field(field_id, include_deprecated=False)` | List approved-evidence mappings that can populate a methodology `Field_ID`. |
| `list_by_status(status)` | List mappings by status, including `deprecated` when explicitly requested. |
| `list_unconfirmed()` | List `provisional` and `needs_domain_review` mappings. |

## Initial Seed Scope

The PR4 seed currently covers only:

| Canonical type | Approved field | Methodology target |
|---|---|---|
| `CT-S1-FUELQTY` | `fuel_type` | `S1-STC-010.fuel_type` |
| `CT-S1-FUELQTY` | `activity_quantity` | `S1-STC-010.quantity_combusted` |
| `CT-S1-FUELQTY` | `activity_unit` | `S1-STC-010.quantity_unit` |
| `CT-S1-MOBFUEL` | `fuel_type` | `S1-MOB-010.fuel_type` |
| `CT-S1-MOBFUEL` | `activity_quantity` | `S1-MOB-010.quantity_combusted` |
| `CT-S1-MOBFUEL` | `activity_unit` | `S1-MOB-010.quantity_unit` |

This is not a complete S1-to-S2 mapping catalog. ESG should expand and confirm
the mapping content over time.

## Non-Goals

PR4 does not:

- execute rules,
- run calculations,
- evaluate completeness,
- transform actual approved evidence records into methodology field values,
- decide final ESG mapping content.

Those belong to later S2 PRs and ESG review.
