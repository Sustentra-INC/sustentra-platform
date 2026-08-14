# Condition Evaluator

Subsystem 2 PR6 adds a small condition/applicability evaluator for methodology
rows with non-empty `Condition`.

The evaluator is intentionally narrow. It decides whether a conditional row is
applicable before completeness checks request evidence for it.

## Supported Syntax

PR6 supports:

```text
FIELD_ID = value
FIELD_ID IN (a, b, c)
AND
OR
simple parentheses
```

Examples:

```text
ORG-010 = operational_control
S2-MTR-010 IN (location_based, market_based)
(A = yes OR B = yes) AND C = yes
```

Matching is case-insensitive after converting runtime values to strings.

## Result Statuses

`ConditionEvaluator.evaluate(condition, values)` returns:

| Status | Meaning |
|---|---|
| `applicable` | Condition is blank or evaluates true. |
| `not_applicable` | Condition evaluates false. The row should not be counted missing. |
| `unknown` | Required runtime value is missing or null. Downstream logic should mark this provisional/needs review. |
| `unsupported_condition` | Condition syntax is outside the safe PR6 subset. |

## Runtime Values

Runtime values are passed as a dictionary keyed by field/reference ID:

```python
ConditionEvaluator().evaluate(
    "S2-MTR-010 = market_based",
    {"S2-MTR-010": "market_based"},
)
```

If `S2-MTR-010` is missing or `None`, the result is `unknown`.

## Non-Goals

PR6 does not:

- execute verification rules,
- run formulas,
- compare numeric ranges,
- evaluate prose conditions,
- infer missing runtime parameters,
- decide completeness results by itself.

Completeness tracking starts in PR7 and consumes this evaluator.
