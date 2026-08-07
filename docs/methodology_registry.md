# Methodology Registry

Subsystem 2 PR3 adds a runtime registry/index over the loaded methodology
bundle. The registry lets later backend services query methodology rows, edges,
and rules without reading the source spreadsheets directly.

The registry consumes a `MethodologyBundle` produced by
`backend.app.reference.methodology_loader`. It does not parse Excel files.

## Usage

```python
from backend.app.reference.methodology_loader import load_default_methodology_bundle
from backend.app.services.methodology_registry_service import MethodologyRegistryService

bundle = load_default_methodology_bundle()
registry = MethodologyRegistryService(bundle)

row = registry.get_row("INV-010")
scope2_rows = registry.list_rows(layer="S2")
core_rows = registry.list_required_rows()
rules = registry.list_rules_for_field("ORG-030")
edges = registry.list_edges_for_field("S2-EFS-010")
```

## Supported Queries

| Method | Purpose |
|---|---|
| `get_row(field_id)` | Return one schema row by `Field_ID`, or `None` if absent. |
| `list_rows(layer=None)` | Return all schema rows, or rows for `GEN`, `S1`, or `S2`. |
| `list_by_value_origin(value_origin)` | Return rows with matching `Value_Origin`; matching is case-insensitive. |
| `list_required_rows(requirement_level="Core")` | Return rows with matching `Requirement_Level`; default is `Core`. |
| `list_rows_by_vocabulary_reference(canonical_type_id)` | Return rows linked to a canonical vocabulary/document type ID. |
| `list_conditions()` | Return rows with non-empty `Condition`. |
| `list_derived_rows()` | Return rows with non-empty `Derived_From`. |
| `list_rules_for_field(field_id)` | Return rules that explicitly apply to a concrete `Field_ID`. |
| `list_edges_for_field(field_id)` | Return edges that reference a field directly or through an expanded wildcard. |

## Wildcards

PR2 validates edge wildcard references such as `S2-EFS-*`. PR3 makes those
wildcard-backed edges queryable.

For example, if an edge references:

```text
S2-EFS-*
```

then:

```python
registry.list_edges_for_field("S2-EFS-010")
```

returns that edge when `S2-EFS-010` exists in the loaded methodology schema.

## Rule Scope

`list_rules_for_field(field_id)` only indexes concrete `Field_ID` references in
`Applies_To`. It does not expand prose targets such as:

```text
Any row with a non-null Condition
ALL — every row with Value_Origin
```

Those prose rule targets remain non-executable in PR3 and are recorded by PR2
as informational integrity findings.

## Current Real Bundle Counts

The current methodology bundle indexes:

| Query | Count |
|---|---:|
| All schema rows | 279 |
| GEN rows | 51 |
| Scope 1 rows | 139 |
| Scope 2 rows | 89 |
| `Value_Origin = extracted` | 183 |
| `Value_Origin = assigned` | 42 |
| `Value_Origin = computed` | 39 |
| `Value_Origin = verifier_determined` | 15 |
| `Requirement_Level = Core` | 235 |
| Rows with `Condition` | 132 |
| Rows with `Derived_From` | 186 |
| Rows referencing `CT-S2-EAC` | 9 |

## Non-Goals

PR3 does not:

- load or parse spreadsheets,
- map approved S1 evidence into methodology fields,
- create engagement-specific values,
- evaluate conditions,
- execute verification rules,
- compute completeness gaps,
- run calculations or derivations.

Those belong to later S2 PRs.
