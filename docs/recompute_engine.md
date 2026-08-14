# Recompute Engine

Subsystem 2 PR12 adds a narrow recompute engine v0.

The first supported path is:

```text
scope1_stationary_combustion_fuel_based
```

It computes:

```text
fuel_quantity * emission_factor = computed emissions
```

and compares that value to reported emissions.

## Result Shape

```text
calculation_path
status
computed_value
reported_value
delta
unit
input_methodology_value_ids
reason
```

Statuses:

```text
matched
mismatch
missing_input
unsupported
```

Any non-zero delta is reported as `mismatch`. Materiality thresholds are
deferred.

## Non-Goals

PR12 does not:

- implement every Scope 1 fuel/factor/GWP path,
- fetch external emission factors,
- convert units,
- execute verification rules,
- emit gap records.

Those belong to later PRs and ESG formula review.
