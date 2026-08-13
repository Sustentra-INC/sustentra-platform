# intake/config — the intake profile schema seed

Phase A of the intake workstream (`intake/SPEC.md` §9). This folder holds the
**configuration source of truth** for client onboarding. It contains no
application logic: later phases read these files.

## Files

| File | What it is |
|---|---|
| `profile_schema.json` | The profile schema seed. One entry per data point in `intake/profile_schema_mapping.md` (v0.2) §1–§8 — 38 entries covering 31 numbered mapping rows plus §7 method routes and §8 provenance. |
| `methodology_field_index.json` | **Generated.** Allow-list of every real methodology field ID (and its data schema field names), the controlled calculation-method values, and the J2 evidence type IDs. Do not hand-edit. |

Related files outside this folder:

- `intake/contracts/profile_schema.schema.json` — the structural contract the seed must satisfy
- `intake/scripts/extract_methodology_field_index.py` — regenerates the index from the workbooks
- `intake/scripts/validate_profile_schema.py` — validates the seed
- `intake/tests/test_profile_schema_seed.py` — the test suite

## Core principle

The intake defines **no new emissions data points**. Every seed entry either:

1. populates an existing methodology field (`target_type: methodology_field`),
2. sets an intake-only state/content field (`target_type: intake_field`), or
3. mirrors a legacy demo field (`target_type: legacy_field`),

and may trigger an evidence request from the J2 library.

`methodology_field_index.json` is the executable form of CLAUDE.md rule 3: the
validator rejects any field ID, sub-field name, method route, or J2 ID that does
not already exist in the repo's reference data.

## Running the checks

```sh
pip install -r intake/requirements.txt

python intake/scripts/validate_profile_schema.py   # validate the seed
python -m pytest intake/tests/                     # positive + negative tests
```

The validator's referential and coverage checks are pure Python and always run.
Deep JSON-Schema validation of the contract runs when `jsonschema` is installed;
without it the validator reports that one check was skipped rather than passing
silently.

To refresh the index after the methodology workbooks change:

```sh
python intake/scripts/extract_methodology_field_index.py           # rewrite
python intake/scripts/extract_methodology_field_index.py --check   # CI staleness check
```

## What is deliberately *not* settled here

Per CLAUDE.md rules 5 and 6, this seed flags rather than decides:

- **`provisional: true`** — a proposed default that is **not** methodologically
  approved. Consolidation approach, base year, GWP/gas universe, significance
  criteria and all five method routes are provisional pending expert (Todd)
  sign-off. They are listed in `open_items.pending_expert_signoff`.
- **`class_source: inferred_pending_confirmation`** — the mapping assigns no
  escalation class to these rows, so the class was inferred during Phase A and
  needs confirmation. Listed in `open_items.pending_class_confirmation`.
- **`question_content_ref`** — placeholders only. Final plain-language wording,
  explainers and the film vocabulary overlay are authored after the Vocabulary
  Library review (`intake/SPEC.md` §10).
- **`applicability_conditions[*].expression`** — conditions are *named* here;
  deterministic evaluation logic is built in Phase C.

## Invariant worth knowing

A screening "no" produces a **"screened, not present" completeness record**
(intake state) — never an `EXC-010` exclusion. `EXC-010` is reserved for sources
that exist and are excluded on materiality grounds, and requires
`sustentra_reviewer` action. The validator and tests enforce this separation
(mapping v0.2, audit FAIL 5).
