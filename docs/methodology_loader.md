# Methodology Workbook Loader

Subsystem 2 PR1 adds a read-only backend loader for the five core methodology
workbooks. The loader converts spreadsheet rows into typed Python records so
later S2 services can validate, index, map, derive, and verify methodology
fields without reading Excel files directly.

## Source Files

The authoritative core S2 methodology inputs currently live in:

```text
reference-data/methodology/
```

Loaded by PR1:

| Role | Workbook | Sheet |
|---|---|---|
| GEN schema | `S2_General_Methodology_Schema_v.1.xlsx` | `1_Schema` |
| Scope 1 schema | `S2_Scope1_Data_Schema_v.1.xlsx` | `1_Schema` |
| Scope 2 schema | `S2_Scope2_Data_Schema_v.1.xlsx` | `S2_Schema` |
| Cross-layer edges | `S2_Cross_Layer_Edge_Table_v1.xlsx` | `Edge_Table` |
| Verification rules | `S2_Verification_Rules_v.1.xlsx` | `Verification_Rules` |

Other tabs such as README, vocab, findings, open items, interface contracts,
and changelogs are intentionally ignored by the PR1 loader. They remain useful
reference material, but they are not runtime methodology rows.

## Typed Records

The loader returns a `MethodologyBundle` containing:

```text
MethodologySchemaRow
MethodologyEdge
VerificationRule
MethodologySourceFile
```

The bundle also exposes convenience indexes:

```text
schema_by_field_id
edges_by_id
rules_by_id
```

## Row Counts

The loader validates the expected PR1 counts:

| Source | Expected rows |
|---|---:|
| GEN schema | 51 |
| Scope 1 schema | 139 |
| Scope 2 schema | 89 |
| Cross-layer edges | 114 |
| Verification rules | 89 |

If any count changes, the workbook may be a new methodology version and the
loader expectations should be updated deliberately.

## Required Columns

Schema workbooks must include:

```text
Field_ID
Block
Grain
Data_Schema_Field(s)
Calculation_Role
Value_Origin
Requirement_Level
Condition
Vocabulary_Reference
Derived_From
Node_ID
```

Scope 2 uses the column name `Scope`; GEN and Scope 1 use
`Scope_Applicability`. The loader normalizes both into
`scope_applicability`.

Edge workbook must include:

```text
Edge_ID
Layer
Scope_Field_ID
Direction
Reference_Type
GEN_Field_ID
Status
```

Rules workbook must include:

```text
Rule_ID
Layer
Type
Assertion
Applies_To
Rule_Expression
Status
```

## Multi-Value Fields

The loader splits semicolon-delimited fields into tuples for runtime use:

```text
Data_Schema_Field(s)
Vocabulary_Reference
Derived_From
Scope_Field(s)
GEN_Field(s)
Applies_To
```

Blank values, `-`, and `N/A` are normalized to empty tuples.

## ESG SB253 Regulatory Files

The ESG team also provided:

```text
S2_SB253_Statute_Database_v.1.xlsx
S2_SB253_Regulatory_Schema_v.1.xlsx
S2_SB253_Regulatory Data Schema_Engineering_Brief_v1.docx
```

These are related, but they are not loaded by the PR1 core methodology loader.
They appear to define a separate Subsystem 2a regulatory anchor/rule package:

```text
SB253 statute nodes / CARB regulation nodes
SB253 regulation rules
node coverage map
regulatory engineering brief
```

They should be handled by a later regulatory-loader PR or S2a PR. Keeping them
separate avoids mixing methodology field definitions with statute/regulatory
anchor nodes before the S2 runtime contract is stable.

## Non-Goals

PR1 does not:

- execute verification rules,
- evaluate conditions,
- resolve cross-layer edges,
- calculate derived values,
- map S1 approved evidence into S2 fields,
- emit gaps.

Those belong to later S2 PRs.
