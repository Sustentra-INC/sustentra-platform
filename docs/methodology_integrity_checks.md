# Methodology Integrity Checks

Subsystem 2 PR2 adds static integrity validation for the loaded methodology
bundle. It validates that the five core methodology workbooks are internally
coherent enough for later registry, mapping, completeness, derivation, and rule
services to build on.

The validator consumes a `MethodologyBundle` from
`backend.app.reference.methodology_loader`. It does not read Excel files
directly.

## Report Shape

The service returns a `MethodologyIntegrityReport`:

```text
status: passed | passed_with_warnings | failed
findings: tuple[MethodologyIntegrityFinding]
summary: dict
```

Findings have:

```text
check_id
severity: error | warning | info
message
subject_id
source
```

`error` findings fail the report. `warning` findings indicate current workbook
compatibility issues that should be reviewed before later PRs depend on them.
`info` findings are non-blocking notes, usually prose rule targets that cannot
be resolved as exact `Field_ID`s in PR2.

## Implemented Checks

### Field IDs

- Every schema `Field_ID` must be unique across GEN, Scope 1, and Scope 2.

### Edges

- Every concrete edge `Scope_Field_ID` reference must resolve to a Scope 1 or
  Scope 2 schema row.
- Scope wildcards such as `S2-EFS-*` are expanded against loaded schema rows.
  The expanded rows must all resolve to Scope 1 or Scope 2 rows. A wildcard that
  matches no schema rows is an error.
- Every concrete edge `GEN_Field_ID` reference must resolve to a GEN schema row.
- Direct Scope 1 to Scope 2 joins are errors.

### Rules

- Every concrete `Applies_To` `Field_ID` reference must resolve to a schema row.
- Prose, registry-level, or wildcard `Applies_To` values are reported as info.
  Examples include phrases such as `Any row with a non-null Condition`.

### Derived From

- Every concrete `Derived_From` field reference must resolve.
- Same-layer `Derived_From` references pass.
- Cross-layer `Derived_From` references are warnings in PR2. The current
  methodology workbooks include a small number of GEN rollup/biogenic rows that
  point to Scope 1 or Scope 2 outputs. Later edge-resolution work should decide
  whether these stay as `Derived_From` references or move fully into EDGES/rules.

### CX Guards

- `CX-01` must exist.
- `CX-12` must exist.
- The report computes the CX-01 exposure count for rows whose `Value_Origin` is
  `computed` or `verifier_determined`.
- The report separately counts `assigned` rows because ESG still needs to
  confirm whether `assigned` should be treated like extracted, computed, or its
  own category in completeness tracking.
- The report computes the CX-12 conditional row count from rows with non-empty
  `Condition`.

## Current Workbook Result

Current core methodology files produce:

```text
status: passed_with_warnings
errors: 0
warnings: 4
info: 14
```

Summary counts:

| Metric | Count |
|---|---:|
| Schema rows | 279 |
| GEN rows | 51 |
| Scope 1 rows | 139 |
| Scope 2 rows | 89 |
| Edges | 114 |
| Rules | 89 |
| `Value_Origin = extracted` | 183 |
| `Value_Origin = assigned` | 42 |
| `Value_Origin = computed` | 39 |
| `Value_Origin = verifier_determined` | 15 |
| CX-01 computed/verifier-determined exposure | 54 |
| CX-12 conditional rows | 132 |

Warning findings:

| Check | Subject | Meaning |
|---|---|---|
| `derived_from_cross_layer` | `BIO-010` | GEN row references `S1-OUT-020` in `Derived_From`. |
| `derived_from_cross_layer` | `RUP-010` | GEN row references `S1-OUT-020` in `Derived_From`. |
| `derived_from_cross_layer` | `RUP-010` | GEN row references `S2-LOC-020` in `Derived_From`. |
| `derived_from_cross_layer` | `RUP-010` | GEN row references `S2-MKT-020` in `Derived_From`. |

`EDG-S2-024` uses `S2-EFS-*`, which currently resolves successfully to Scope 2
schema rows and is no longer a warning.

These are not PR2 blockers. They should be reviewed before PR8/PR9, where edge
resolution and derivation semantics become executable.

## Non-Goals

PR2 does not:

- evaluate conditions,
- run verification rules,
- resolve prose or registry-level rule targets,
- execute derivations,
- determine gap records,
- map S1 approved evidence to methodology fields.

Those belong to later S2 PRs.
