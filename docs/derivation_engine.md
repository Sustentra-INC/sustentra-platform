# Derivation Engine

Subsystem 2 PR9 adds a small v0 derivation engine over methodology rows with
`Derived_From`.

The engine is intentionally conservative. It carries lineage and only computes
safe copy/sum cases. It does not attempt to execute the full methodology formula
catalog.

## Supported v0 Behavior

| Case | Result |
|---|---|
| One same-layer dependency with one value | `derived`, copy value/unit |
| Multiple same-layer numeric dependencies with compatible units | `derived`, sum values |
| Missing dependency value | `missing_dependency` |
| Cross-layer `Derived_From` | `cross_layer_unsupported` |
| Nonnumeric or mixed-unit derivation | `unsupported_derivation` |

Every result includes:

```text
field_id
status
derived_value
derived_unit
dependency_field_ids
source_methodology_value_ids
reason
```

## Cross-Layer Rule

PR9 keeps this invariant:

```text
Derived_From is same-layer only.
Cross-layer values must go through EDGES.
```

For example, a GEN row derived from an S1 output returns
`cross_layer_unsupported` in PR9 rather than pretending the dependency can be
computed directly.

## Usage

```python
service = DerivationService(methodology_registry)

one_result = service.derive_field("S1-TOTAL-010", methodology_values)
all_results = service.derive_all(methodology_values)
```

`methodology_values` are PR5 methodology value records.

## Non-Goals

PR9 does not:

- run the verification rule engine,
- execute arbitrary formulas,
- resolve cross-layer values through EDGES,
- evaluate conditions,
- perform unit conversions,
- write derived values back to the value store.

Those belong to later PRs.
