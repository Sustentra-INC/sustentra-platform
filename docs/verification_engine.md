# Verification Engine

Subsystem 2 PR11 adds the first verification engine. It executes only the
safest rule subset and intentionally does not evaluate arbitrary
`Rule_Expression` text.

## Inputs

```text
engagement_id
RuntimeVerificationRule[]
methodology_values
```

Rules come from the PR10 verification rule loader. Methodology values come from
the PR5 value store.

## Supported v0 Rule Types

| Rule type | PR11 behavior |
|---|---|
| `guard` | Passes if all concrete `Applies_To` fields have populated methodology values; otherwise fails. |
| `gate` | Same v0 behavior as `guard`. |
| `invariant` | Same v0 behavior as `guard`. |
| `limit` | Returns `cannot_verify`; PR11 does not yet know enough evidence semantics to prove limits. |
| `CONFIRM` status | Returns `provisional`. |
| Other rule types | Return `unsupported`. |
| Prose-only `Applies_To` | Returns `not_applicable` in PR11. |

Blank or null approved values do not satisfy a rule. Valid `0` and `False`
values count as populated.

## Result Statuses

```text
passed
failed
not_applicable
provisional
unsupported
cannot_verify
```

The result contract is:

```text
contracts/verification_result.schema.json
```

## Non-Goals

PR11 does not:

- execute recompute rules,
- evaluate arbitrary rule-expression prose,
- run calculations,
- apply materiality thresholds,
- emit S2 gap records.

Those belong to PR12 and PR13.
