# Verification Rule Loader

Subsystem 2 PR10 adds typed runtime verification rule loading.

The PR1 methodology loader already reads the verification-rule workbook into
raw methodology records. PR10 converts those records into runtime verification
rule objects that expose provisional status and resolvable `Applies_To`
references.

PR10 does not execute rules.

## Runtime Rule Shape

Runtime rules include:

```text
rule_id
layer
rule_type
assertion
applies_to
grain_key
rule_expression
source
status
notes
is_provisional
resolvable_applies_to
unresolved_applies_to
source_workbook
source_sheet
source_row_number
```

`resolvable_applies_to` contains concrete `Field_ID`s that resolve to
methodology registry rows.

`unresolved_applies_to` contains prose targets or unknown field references. PR10
records them without executing or expanding them.

## Current Workbook Counts

The current verification rule workbook loads:

| Metric | Count |
|---|---:|
| Total rules | 89 |
| CROSS rules | 15 |
| `status = Active` | 67 |
| `status = CONFIRM` | 15 |
| `status = OPEN` | 3 |

`CONFIRM` rules are marked `is_provisional = True`.

## Usage

```python
from backend.app.reference.verification_rule_loader import (
    load_default_verification_rules,
)

rules = load_default_verification_rules()
```

Or with an already-loaded methodology bundle:

```python
rules = load_verification_rules(bundle)
```

## Non-Goals

PR10 does not:

- execute rules,
- calculate pass/fail outcomes,
- expand prose `Applies_To` targets,
- decide rule severity,
- run recomputation.

Those belong to later verification engine PRs.
