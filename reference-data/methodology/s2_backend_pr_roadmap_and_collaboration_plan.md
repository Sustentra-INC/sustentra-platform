# Subsystem 2 Backend Build Plan  
**For:** Jack, Claire, ESG team  
**Draft date:** 2026-07-24  
**Scope:** How to start Subsystem 2 after the S1 backend, split into PR-sized backend work packages, and how Jack + Claire can collaborate.

---

## 0. Executive summary

The right way to start Subsystem 2 is **not** to jump directly into formula math or RAG. The safest path is to first make the methodology spreadsheets loadable, validated, queryable, and connected to S1 approved evidence.

S1 now produces:

```text
uploaded document
→ parser_output
→ extraction_candidate
→ review_decision
→ approved_evidence
```

Subsystem 2 should consume **approved evidence**, not raw documents and not unreviewed extraction candidates.

The first Subsystem 2 backend milestone should be:

```text
approved_evidence
→ methodology field value store
→ completeness tracker
→ derivation
→ verification rules
→ stage-specific gap records
```

The biggest engineering risks are:

1. **Mapping mismatch:** current S1 extraction fields such as `activity_quantity`, `fuel_type`, and `service_period_start` are not yet aligned to official methodology `Field_ID`s such as `S1-STC-010`.
2. **CX-01 guard:** the system must never request documents for `computed` or `verifier_determined` fields.
3. **CX-12 applicability:** conditional rows must be skipped when their condition is false, not treated as missing.
4. **Cross-file joins:** Scope 1 and Scope 2 must not directly join each other. They only connect through GEN and EDGES.
5. **Rule execution ambiguity:** 15 rules are marked `CONFIRM`; build the rule framework, but mark uncertain arithmetic as provisional until Nora/domain review confirms it.

Recommended next backend work:

```text
S2-PR1  Methodology workbook loader
S2-PR2  Methodology integrity checks
S2-PR3  Runtime methodology registry/index
S2-PR4  Approved evidence → Methodology Field_ID mapping
S2-PR5  Field value store / engagement methodology snapshot
S2-PR6  Condition/applicability evaluator
S2-PR7  Completeness tracker + S1→S2 gate
S2-PR8  Edge resolution service
S2-PR9  Derivation engine v0
S2-PR10 Verification rules loader
S2-PR11 Verification engine v0
S2-PR12 Calculation/recompute engine v0
S2-PR13 S2 gap record emission
S2-PR14 S2 backend orchestration + smoke test
```

---

## 1. What “S2” means in this plan

There is naming collision:

- **Subsystem 2** = methodology / benchmarking / verification backend.
- **Scope 2** = GHG Scope 2 purchased electricity / steam / heat / cooling schema.

This plan uses:

```text
Subsystem 2 = the whole methodology verification subsystem.
Scope 2 layer = the purchased-energy schema inside the Subsystem 2 spreadsheets.
```

---

## 2. Source materials inspected

### 2.1 System Structure Proposal

Main architectural points used:

- The proposed system separates:
  1. Read documents correctly.
  2. Check values.
  3. Map failures into assurance-facing gaps.
- S1 handles document intake, classification, extraction, source traceability, and human review.
- Subsystem 2 is where extracted/approved values are checked against regulation and methodology.
- S3 receives gap records and maps them to assurance assertions; S3 should not detect original failures itself.
- RAG is a read/explanation layer, not the core verification engine.

### 2.2 Subsystem 2 Methodology Data Schema Engineering Brief

Key instructions used:

- The five files are the spec:
  1. `S2_General_Methodology_Schema_v.1.xlsx`
  2. `S2_Scope1_Data_Schema_v.1.xlsx`
  3. `S2_Scope2_Data_Schema_v.1.xlsx`
  4. `S2_Cross_Layer_Edge_Table_v1.xlsx`
  5. `S2_Verification_Rules_v.1.xlsx`
- Files 1–3 define data.
- File 4 defines cross-layer connections.
- File 5 defines checks.
- All joins use `Field_ID`.
- `Derived_From` is same-file only.
- EDGES is the only cross-file reference table.
- RULES reference schema fields through `Applies_To`.
- Build order:
  ```text
  GEN tables
  → Scope 1 / Scope 2 schemas
  → edge resolution
  → completeness tracker with CX-01 and CX-12
  → derivation
  → rules engine
  ```

### 2.3 Uploaded spreadsheet inventory

I inspected the uploaded S2 spreadsheets and confirmed the following structure.

| File | Main sheet | Rows | Main role |
|---|---:|---:|---|
| `S2_General_Methodology_Schema_v.1.xlsx` | `1_Schema` | 51 | GEN shared layer: inventory, org boundary, period, gases, GWP, exclusions, roll-up |
| `S2_Scope1_Data_Schema_v.1.xlsx` | `1_Schema` | 139 | Scope 1 data schema: stationary, mobile, fugitive, process combustion |
| `S2_Scope2_Data_Schema_v.1.xlsx` | `S2_Schema` | 89 | Scope 2 data schema: purchased electricity, steam, heat, cooling |
| `S2_Cross_Layer_Edge_Table_v1.xlsx` | `Edge_Table` | 114 | Cross-layer dependencies between GEN and scopes |
| `S2_Verification_Rules_v.1.xlsx` | `Verification_Rules` | 89 | Rules to check completeness, accuracy, classification, cutoff |

### 2.4 Key counts from uploaded files

#### GEN

| Metric | Count |
|---|---:|
| Rows | 51 |
| `Value_Origin = extracted` | 42 |
| `Value_Origin = verifier_determined` | 8 |
| `Value_Origin = computed` | 1 |
| Rows with non-empty `Condition` | 10 |
| Rows with non-empty `Vocabulary_Reference` | 25 |
| Rows with non-empty `Derived_From` | 33 |

#### Scope 1 layer

| Metric | Count |
|---|---:|
| Rows | 139 |
| `Value_Origin = extracted` | 77 |
| `Value_Origin = assigned` | 31 |
| `Value_Origin = computed` | 27 |
| `Value_Origin = verifier_determined` | 4 |
| Rows with non-empty `Condition` | 88 |
| Rows with non-empty `Vocabulary_Reference` | 134 |
| Rows with non-empty `Derived_From` | 119 |

#### Scope 2 layer

| Metric | Count |
|---|---:|
| Rows | 89 |
| `Value_Origin = extracted` | 64 |
| `Value_Origin = assigned` | 11 |
| `Value_Origin = computed` | 11 |
| `Value_Origin = verifier_determined` | 3 |
| Rows with non-empty `Condition` | 34 |
| Rows with non-empty `Vocabulary_Reference` | 29 |
| Rows with non-empty `Derived_From` | 34 |

#### EDGES

| Metric | Count |
|---|---:|
| Total edges | 114 |
| S1 edges | 78 |
| S2 edges | 36 |
| `GEN_TO_SCOPE` | 101 |
| `SCOPE_TO_GEN` | 13 |
| `Reference_Type = fk` | 60 |
| `Reference_Type = rule_input` | 27 |
| `Reference_Type = scope` | 14 |
| `Reference_Type = writes_to` | 9 |
| `Reference_Type = disclosed_via` | 4 |

#### RULES

| Metric | Count |
|---|---:|
| Total rules | 89 |
| S1 rules | 52 |
| CROSS rules | 15 |
| S2 rules | 13 |
| GEN rules | 9 |
| `Type = recompute` | 29 |
| `Type = invariant` | 28 |
| `Type = fail-check` | 9 |
| `Type = gate` | 7 |
| `Type = guard` | 6 |
| `Type = limit` | 5 |
| `Type = routing` | 5 |
| `Status = Active` | 67 |
| `Status = CONFIRM` | 15 |
| `Status = OPEN` | 3 |

---

## 3. Current S1 backend state and why it matters for Subsystem 2

The platform now has a strong S1 backend skeleton:

```text
upload + local storage
→ parser_output
→ classification
→ extraction targets
→ extraction candidates
→ review decisions
→ approved evidence
→ pipeline run summary
```

This gives Subsystem 2 a stable upstream source:

```text
approved_evidence
```

However, there is still a **handoff mismatch**:

Current extraction config seed fields are product/pilot labels such as:

```text
facility_name
service_address
fuel_type
activity_quantity
activity_unit
service_period_start
service_period_end
supplier_name
account_number
```

The methodology spreadsheets use official `Field_ID`s such as:

```text
S1-STC-010
S2-MTR-020
GEN.RUP-010 style rows
```

Therefore, Subsystem 2 cannot start by “running rules” directly. It needs a mapping layer:

```text
approved_evidence.field_name
→ methodology Field_ID
→ Data_Schema_Field(s)
→ grain
→ requirement level
→ condition
→ rule applicability
```

This mapping is the most important early S2 build task.

---

## 4. Proposed Subsystem 2 architecture

### 4.1 Data flow

```text
S1 approved_evidence
        │
        ▼
S2 Field Mapping Layer
        │
        ▼
Methodology Field Value Store
        │
        ▼
Completeness Tracker / S1→S2 Gate
        │
        ▼
Condition Applicability Evaluator
        │
        ▼
Derived Field Engine
        │
        ▼
Verification Rule Engine
        │
        ▼
S2 Gap Records
        │
        ▼
S3 Gap Analysis / Assurance Mapping
```

### 4.2 Runtime components

| Component | Purpose | Consumes | Produces |
|---|---|---|---|
| Methodology loader | Read the five S2 spreadsheets into typed runtime objects | `.xlsx` files | schema rows, edges, rules |
| Methodology integrity validator | Validate the files are internally coherent | loaded methodology data | validation report |
| Methodology registry/index | Query by `Field_ID`, layer, grain, `Value_Origin`, condition, vocabulary reference | loaded methodology data | runtime index |
| Approved evidence mapper | Map reviewed S1 fields to methodology fields | approved evidence | field value records |
| Field value store | Store engagement-specific values by Field_ID and grain | mapped values | methodology engagement snapshot |
| Condition evaluator | Decide whether conditional rows apply | field values + condition expressions | applicable / not applicable / unknown |
| Completeness tracker | Identify missing extracted fields | methodology rows + field values | completeness results / gap records |
| Edge resolver | Resolve GEN↔Scope links | EDGES table | resolved upstream/downstream values |
| Derivation engine | Compute derived rows from `Derived_From` | field values | derived field values |
| Verification rule loader | Load 89 rules into typed objects | RULES workbook | rule objects |
| Verification engine | Run rule types | field values, derived values, edges | verification results |
| Gap record emitter | Turn missing/invalid results into S2 gap records | tracker/results | gap records for S3 |

---

## 5. PR roadmap for Subsystem 2

The PRs below are numbered as S2-specific PRs. In the GitHub repo, these can continue the global numbering after the current backend PRs.

---

### S2-PR0 — S1→S2 boundary audit

**Goal:** Confirm exactly what S1 currently produces and what Subsystem 2 should consume.

**Why first:** If the S1 approved evidence shape does not map cleanly to methodology `Field_ID`s, every later S2 service will be unstable.

**Backend work:**

- Inspect current `approved_evidence.schema.json`.
- Inspect `reference-data/extraction-config/extraction_config_seed.json`.
- Produce a mapping inventory:
  ```text
  S1 approved_evidence field_name
  → candidate methodology Field_ID
  → confidence / notes
  ```
- Identify where `regulatory_field_id` / `methodology_field_id` is currently missing or null.
- Add a doc:
  ```text
  docs/s1_to_s2_handoff_audit.md
  ```

**Claire / ESG work:**

- Confirm which S1 extracted fields should map to which methodology `Field_ID`s.
- Mark each mapping as:
  ```text
  confirmed
  provisional
  wrong
  needs new S1 extraction field
  ```
- Identify required fields that S1 currently cannot produce.

**Tests:**

- Documentation-only PR can skip code tests except existing backend tests.
- If a JSON/CSV mapping fixture is added, test it loads and has no duplicate mapping keys.

**Do not build:**

- No completeness tracker.
- No rules.
- No calculations.

---

### S2-PR1 — Methodology workbook loader

**Goal:** Load the five methodology spreadsheets into typed Python records.

**Backend work:**

Add:

```text
backend/app/reference/methodology_loader.py
backend/app/domain/methodology.py
backend/tests/reference/test_methodology_loader.py
docs/methodology_loader.md
```

Loader should support:

```text
GEN schema rows
Scope 1 schema rows
Scope 2 schema rows
EDGES rows
RULES rows
```

Typed domain objects:

```text
MethodologySchemaRow
MethodologyEdge
VerificationRule
MethodologyBundle
```

The loader should parse:

```text
Field_ID
Grain
Data_Schema_Field(s)
Calculation_Role
Value_Origin
Requirement_Level
Condition
Vocabulary_Reference
Derived_From
Node_ID
Rule_ID
Rule Type
Assertion
Applies_To
```

**Tests:**

- Workbook loads without external services.
- Main row counts match:
  ```text
  GEN = 51
  S1 = 139
  S2 = 89
  EDGES = 114
  RULES = 89
  ```
- Expected sheets exist.
- Required columns exist.
- Superseded tabs are ignored.

**Claire / ESG work:**

- Confirm the five file names are the authoritative v1 files.
- Confirm which tabs are superseded and should not be loaded.
- Review the typed model names for conceptual accuracy.

**Do not build:**

- No rule execution.
- No calculations.
- No completeness tracker.

---

### S2-PR2 — Methodology integrity validation

**Goal:** Validate the methodology source files before building runtime logic.

**Backend work:**

Add:

```text
backend/app/services/methodology_integrity_service.py
backend/tests/services/test_methodology_integrity_service.py
docs/methodology_integrity_checks.md
```

Checks:

```text
1. Every Field_ID is unique across GEN/S1/S2 or globally unambiguous.
2. Every EDGES Scope_Field_ID resolves to a real Scope 1 or Scope 2 row.
3. Every EDGES GEN_Field_ID resolves to a real GEN row.
4. Every RULES Applies_To Field_ID resolves.
5. Every Derived_From reference resolves within the same file.
6. Derived_From never crosses files.
7. Scope 1 never directly joins Scope 2.
8. EDGES is the only cross-file reference layer.
9. CX-01 exposure count can be computed.
10. CX-12 conditional rows can be identified.
```

**Tests:**

- Integrity report passes on current files, except documented open statuses.
- Fails on synthetic broken fixtures.

**Claire / ESG work:**

- Review integrity warnings.
- Decide which warning categories are acceptable:
  ```text
  Active
  CONFIRM
  OPEN
  BLOCKED
  Pending_GEN_Update
  ```
- Confirm if `assigned` should be treated separately from `extracted`, `computed`, and `verifier_determined`.

**Do not build:**

- No rules engine.
- No calculations.

---

### S2-PR3 — Methodology registry / runtime index

**Goal:** Make the loaded methodology queryable by backend services.

**Backend work:**

Add:

```text
backend/app/services/methodology_registry_service.py
backend/tests/services/test_methodology_registry_service.py
docs/methodology_registry.md
```

Capabilities:

```text
get_row(field_id)
list_rows(layer=GEN/S1/S2)
list_by_value_origin(extracted/computed/verifier_determined/assigned)
list_required_rows(requirement_level=Core)
list_rows_by_vocabulary_reference(canonical_type_id)
list_conditions()
list_derived_rows()
list_rules_for_field(field_id)
list_edges_for_field(field_id)
```

**Why important:** Later services should not directly parse spreadsheets; they should query the registry.

**Claire / ESG work:**

- Confirm query shapes correspond to how reviewers think about requirements.
- Mark high-priority rows for the first methodology smoke test.

**Do not build:**

- No engagement-specific values.
- No completeness gaps yet.

---

### S2-PR4 — Approved evidence → Methodology Field_ID mapping

**Goal:** Map S1 approved evidence fields to official methodology `Field_ID`s.

**Backend work:**

Add a mapping file:

```text
reference-data/methodology/approved_evidence_field_mapping_seed.json
```

Example mapping shape:

```json
{
  "canonical_type_id": "CT-S1-FUELQTY",
  "approved_field_name": "activity_quantity",
  "methodology_field_id": "S1-STC-010",
  "data_schema_field": "quantity_combusted",
  "mapping_status": "provisional",
  "notes": "Maps reviewed stationary fuel quantity to S1 stationary combustion fuel record."
}
```

Add:

```text
backend/app/reference/approved_evidence_mapping_loader.py
backend/app/services/approved_evidence_mapping_service.py
backend/tests/reference/test_approved_evidence_mapping_loader.py
backend/tests/services/test_approved_evidence_mapping_service.py
```

**Important:** This mapping should not pretend to be final. It should have statuses:

```text
confirmed
provisional
needs_domain_review
deprecated
```

**Claire / ESG work:**

- Own the content of the mapping seed.
- Confirm which S1 evidence types and fields map to which methodology fields.
- Identify fields needing new extraction configs.

**Do not build:**

- No rule execution.
- No calculations.

---

### S2-PR5 — Methodology field value store / engagement snapshot

**Goal:** Convert approved evidence into an engagement-specific methodology value snapshot.

**Backend work:**

Add:

```text
backend/app/domain/methodology_value.py
backend/app/repositories/methodology_value_repository.py
backend/app/services/methodology_value_service.py
backend/tests/services/test_methodology_value_service.py
docs/methodology_value_store.md
```

Record shape:

```text
methodology_value_id
engagement_id
evidence_id
document_id
methodology_field_id
data_schema_field
grain
record_key
approved_value
approved_unit
source_reference
approved_evidence_id
review_decision_id
value_origin = approved_evidence
created_at
```

**Key design issue:** `Grain` tells you what one record represents. For example:

```text
fuel_record
delivery_point
facility_x_scope_x_scope2_method_x_gas
```

The value store must support multiple records per field when the grain requires it.

**Claire / ESG work:**

- Confirm what should be used as `record_key` for common grains:
  ```text
  facility
  fuel_record
  delivery_point
  billing_period
  emission_factor_set
  ```
- Provide 2–3 example approved evidence records and expected value-store output.

**Do not build:**

- No completeness tracker yet.
- No derivation.

---

### S2-PR6 — Condition / applicability evaluator

**Goal:** Evaluate whether a conditional methodology row applies.

**Backend work:**

Add:

```text
backend/app/services/condition_evaluator.py
backend/tests/services/test_condition_evaluator.py
docs/condition_evaluator.md
```

Support a safe subset first:

```text
FIELD_ID = value
FIELD_ID IN (a, b, c)
AND
OR
parentheses only if simple
```

Output:

```text
applicable
not_applicable
unknown
unsupported_condition
```

**Required behavior:**

- If condition is false → row is not applicable, not missing.
- If condition is unknown → do not silently pass; emit provisional/needs-review status.

**Claire / ESG work:**

- Triage conditions into:
  ```text
  simple now
  needs runtime parameter
  needs domain clarification
  unsupported for v0
  ```
- Confirm expected behavior for ambiguous/unknown conditions.

**Do not build:**

- No rule execution.
- No arithmetic.

---

### S2-PR7 — Completeness tracker + S1→S2 gate

**Goal:** Determine which required extracted methodology fields are missing before verification.

**Backend work:**

Add:

```text
backend/app/services/completeness_tracker_service.py
backend/tests/services/test_completeness_tracker_service.py
contracts/completeness_result.schema.json
docs/completeness_tracker.md
```

Rules:

```text
1. Only rows with Value_Origin = extracted may trigger document/evidence requests.
2. Do not request documents for computed fields.
3. Do not request documents for verifier_determined fields.
4. Conditional rows only apply when their Condition is true.
5. False condition means not applicable, not missing.
6. Unknown condition means needs review/provisional, not automatic missing.
```

Output:

```text
complete
missing_required
not_applicable
provisional_condition_unknown
not_requestable_value_origin
```

**Why this PR matters:** It implements CX-01 and CX-12, the two guards most likely to break production if ignored.

**Claire / ESG work:**

- Review missing-field report format.
- Confirm what counts as “Core required” for MVP.
- Help write expected missing/not-applicable cases.

**Do not build:**

- No formulas.
- No verification rules beyond CX-01/CX-12.

---

### S2-PR8 — Edge resolution service

**Goal:** Resolve GEN↔Scope dependencies using EDGES without direct S1↔S2 joins.

**Backend work:**

Add:

```text
backend/app/services/edge_resolution_service.py
backend/tests/services/test_edge_resolution_service.py
docs/edge_resolution.md
```

Support edge `Reference_Type` semantics:

| Reference type | Runtime treatment |
|---|---|
| `fk` | Real join / foreign key |
| `rule_input` | Rule reads GEN value; not a schema join |
| `scope` | Precondition / applicability context |
| `writes_to` | Scope output populates GEN row |
| `disclosed_via` | Scope owns content; GEN carries disclosure |

**Important test:** `rule_input` must not be treated as a foreign key join.

**Claire / ESG work:**

- Review edge semantics.
- Confirm any open/pending edges before they become hard failures.

**Do not build:**

- No rule execution.
- No derived calculations yet.

---

### S2-PR9 — Derivation engine v0

**Goal:** Compute derived fields using `Derived_From`.

**Backend work:**

Add:

```text
backend/app/services/derivation_service.py
backend/tests/services/test_derivation_service.py
docs/derivation_engine.md
```

Rules:

```text
1. Derived_From is same-file only.
2. Never cross files through Derived_From.
3. Cross-layer values must go through EDGES.
4. Derived output should carry lineage.
5. Unsupported derivations should return provisional/unsupported, not fake results.
```

Start with non-arithmetic or simple derivations:

```text
copy
sum
roll-up placeholder
dependency lineage
```

Do not attempt all formulas in the first PR.

**Claire / ESG work:**

- Identify 5–10 safe derived fields to use as v0 fixtures.
- Mark formula-sensitive rows as deferred/provisional.

---

### S2-PR10 — Verification rules loader

**Goal:** Load the 89 verification rules into typed runtime objects.

**Backend work:**

Add:

```text
backend/app/reference/verification_rule_loader.py
backend/app/domain/verification_rule.py
backend/tests/reference/test_verification_rule_loader.py
docs/verification_rule_loader.md
```

Parse:

```text
Rule_ID
Layer
Type
Assertion
Applies_To
Grain_Key
Rule_Expression
Source
Status
Notes
```

Do not execute rules yet.

**Tests:**

- 89 rules load.
- 15 CROSS rules identified.
- Rule statuses counted.
- `Applies_To` references resolve to methodology registry rows.
- `CONFIRM` rules load but are marked provisional.

**Claire / ESG work:**

- Review rule type taxonomy.
- Confirm which rules should be executed in the first verification engine PR.

---

### S2-PR11 — Verification engine v0

**Goal:** Execute the simplest rule types.

**Backend work:**

Add:

```text
backend/app/services/verification_engine_service.py
backend/tests/services/test_verification_engine_service.py
contracts/verification_result.schema.json
docs/verification_engine.md
```

Start with:

```text
guard
gate
limit
simple invariant
```

Do not start with complicated recompute rules.

Rule result statuses:

```text
passed
failed
not_applicable
provisional
unsupported
cannot_verify
```

Important behavior:

- `limit` rules should honestly report cannot verify when client evidence cannot prove the rule.
- `CONFIRM` rules should produce provisional results.
- Materiality is deferred; every non-zero delta can be flagged for now.

**Claire / ESG work:**

- Provide expected behavior for 5–10 rules.
- Confirm wording for `cannot_verify` vs `failed`.

---

### S2-PR12 — Calculation / recompute engine v0

**Goal:** Start recomputation on one narrow calculation path.

**Recommendation:** Choose one of these first:

1. Scope 1 stationary combustion fuel-based quantity.
2. Scope 2 location-based electricity total.

Choose the one with better available approved evidence and formula clarity.

**Backend work:**

Add:

```text
backend/app/services/recompute_service.py
backend/tests/services/test_recompute_service.py
docs/recompute_engine.md
```

For v0:

```text
inputs
→ formula module
→ computed result
→ compare against reported value
→ delta
```

Do not implement every fuel/factor/GWP path at once.

**Claire / ESG work:**

- Pick the first calculation path.
- Confirm formula inputs.
- Confirm expected output with a small workbook example.
- Flag uncertain formula rules marked `CONFIRM`.

---

### S2-PR13 — S2 gap record emission

**Goal:** Convert completeness/verification/calculation failures into stage-specific gap records for S3.

**Backend work:**

Add:

```text
contracts/gap_record_v0.schema.json update if needed
backend/app/services/s2_gap_record_service.py
backend/tests/services/test_s2_gap_record_service.py
docs/s2_gap_records.md
```

Gap record fields should include:

```text
gap_record_id
engagement_id
evidence_id
document_id
field_id
stage = S2
substage = completeness | derivation | verification | recompute
gap_type
root_cause_code
assertion
severity
source_reference
rule_id
created_at
```

**Important:** S2 emits findings; S3 later aggregates and maps them into practitioner-facing reports.

**Claire / ESG work:**

- Confirm gap type names.
- Confirm assertion category mapping expected from rules.
- Review practitioner-facing wording.

---

### S2-PR14 — S2 backend orchestration + smoke test

**Goal:** Add a single service/API path that runs Subsystem 2 over approved evidence.

**Backend work:**

Add:

```text
backend/app/services/s2_orchestration_service.py
backend/app/api/methodology.py
backend/scripts/s2_smoke.py
backend/tests/services/test_s2_orchestration_service.py
docs/s2_backend_smoke.md
```

Flow:

```text
approved_evidence
→ methodology value store
→ completeness tracker
→ conditions
→ derivations
→ rules
→ gap records
→ summary
```

Response summary:

```text
methodology_run_id
engagement_id
field_value_count
missing_required_count
not_applicable_count
verification_result_count
gap_record_count
provisional_count
```

**Claire / ESG work:**

- Review smoke output and confirm whether it is understandable.
- Provide 1–2 engagement scenarios.

---

## 6. Jack + Claire collaboration plan

### 6.1 Split responsibilities

| Area | Jack | Claire |
|---|---|---|
| Backend architecture | Owns implementation | Reviews whether model matches domain intent |
| Spreadsheet loader | Implements loader/tests | Confirms authoritative tabs and columns |
| Mapping S1 to S2 | Implements mapping loader/service | Owns field mapping content and domain correctness |
| Conditions | Implements evaluator | Triages conditions and expected applicability |
| Completeness tracker | Implements CX-01/CX-12 logic | Reviews missing/not-applicable output |
| Rules | Implements loader/engine | Reviews rule semantics and expected outputs |
| Calculations | Implements recompute service | Confirms formula inputs and expected outputs |
| QA fixtures | Converts fixtures to tests | Drafts expected behavior examples |
| Docs | Writes engineering docs | Writes/reviews ESG-readable explanations |

### 6.2 Recommended working pattern per PR

For each PR:

```text
1. Jack writes a short PR scope note.
2. Claire reviews source files and writes expected behavior examples.
3. Jack implements loader/service/tests.
4. Claire reviews generated reports or test fixtures.
5. Jack finalizes docs and safety notes.
6. Both agree on what remains intentionally deferred.
```

### 6.3 What Claire can do immediately

Claire can help before more backend code exists by preparing:

```text
docs/domain_notes/s2_field_mapping_review.md
docs/domain_notes/s2_condition_triage.md
docs/domain_notes/s2_rule_priority_list.md
docs/domain_notes/s2_known_ambiguities.md
```

Recommended first Claire tasks:

1. Confirm the five uploaded files are the only S2 source of truth.
2. Confirm superseded tabs to ignore.
3. Review `S1-STC-010`, `S1-MOB-*`, and `S2-MTR-*` rows as first MVP scope.
4. Draft a mapping table:
   ```text
   S1 approved field → methodology Field_ID → data_schema_field → notes
   ```
5. Mark rules as:
   ```text
   run now
   load only
   provisional
   blocked
   needs Nora
   ```

---

## 7. What not to build yet

Do not start with these:

```text
Full RAG
Frontend methodology UI
Full S3 assurance report
All 89 rules executing perfectly
All GHG formula paths
All external factor connectors
Materiality thresholds
Cloud deployment
```

These depend on the foundation:

```text
methodology loader
registry
mapping
condition evaluator
completeness tracker
edge resolver
```

---

## 8. Critical design rules

### 8.1 Subsystem 2 consumes approved evidence

Do not let S2 read directly from:

```text
raw documents
parser_output
extraction_candidate
```

It should consume:

```text
approved_evidence
```

unless a future design intentionally supports provisional/unreviewed verification.

### 8.2 Never request documents for computed/verifier fields

The completeness tracker must only request evidence for:

```text
Value_Origin = extracted
```

Do not request evidence for:

```text
computed
verifier_determined
```

This is the CX-01 guard.

### 8.3 Conditional rows are not automatically missing

If `Condition` is false:

```text
not_applicable
```

not:

```text
missing
```

This is the CX-12 guard.

### 8.4 Scope 1 and Scope 2 never directly join

Allowed:

```text
Scope 1 → GEN
Scope 2 → GEN
GEN → Scope 1
GEN → Scope 2
```

Not allowed:

```text
Scope 1 → Scope 2
Scope 2 → Scope 1
```

Use EDGES.

### 8.5 `rule_input` is not a foreign key

`rule_input` means a rule consumes a GEN value. It does not mean the schema row has a join relationship.

---

## 9. Missing information / decisions before full S2 completion

The backend can start now, but full completion needs these decisions:

| Needed decision | Owner | Why it matters |
|---|---|---|
| S1 approved evidence → Methodology `Field_ID` mapping | Claire + Jack | Without this, approved S1 output cannot populate S2 fields |
| First MVP calculation path | Claire + Nora + Jack | Avoid trying to implement all formulas at once |
| Runtime engagement parameters | ESG/domain | Needed for assurance level, GWP basis, reporting year, materiality, etc. |
| How to handle `CONFIRM` rules | Claire + Nora | 15 rules may need formula confirmation |
| Node_ID/statute database availability | Domain/product | Required for S2a regulation anchoring and later RAG |
| Materiality threshold behavior | Domain/advisor | Currently every non-zero delta is expected to be a finding |
| Multi-record grain keys | Claire + Jack | Needed for fuel deliveries, facilities, delivery points, multiple Scope 2 methods |

---

## 10. Recommended first two weeks

### Week 1

**Jack**

- S2-PR1 loader.
- S2-PR2 integrity validator.
- Basic docs.

**Claire**

- Confirm source files and ignored tabs.
- Review loader model names.
- Start S1→S2 mapping table.

### Week 2

**Jack**

- S2-PR3 registry/index.
- S2-PR4 mapping loader/service.

**Claire**

- Finish first mapping set for:
  ```text
  CT-S1-FUELQTY
  CT-S1-MOBFUEL
  possibly CT-S2-ELEC
  ```
- Provide expected mapping fixtures.

### Week 3

**Jack**

- S2-PR5 field value store.
- S2-PR6 condition evaluator.

**Claire**

- Triage conditions.
- Identify top fields that should be completeness-checked first.

### Week 4

**Jack**

- S2-PR7 completeness tracker.
- S2-PR8 edge resolver.

**Claire**

- Review missing/not-applicable reports.
- Confirm CX-01/CX-12 behavior on examples.

---

## 11. Recommended first MVP scope

To avoid building too broadly, start with:

```text
GEN core rows needed for inventory/facility/period/gas context
Scope 1 stationary fuel quantity
Scope 1 mobile fuel quantity
Maybe one Scope 2 electricity delivery point path
```

Do not start by trying to implement:

```text
all fugitive emissions
all process combustion
all Scope 2 market-based instruments
all 89 rules
all cross-layer recomputes
```

---

## 12. Suggested repo structure for S2 backend

```text
backend/app/domain/methodology.py
backend/app/domain/methodology_value.py
backend/app/domain/verification_rule.py
backend/app/domain/completeness.py
backend/app/domain/verification_result.py

backend/app/reference/methodology_loader.py
backend/app/reference/verification_rule_loader.py
backend/app/reference/approved_evidence_mapping_loader.py

backend/app/services/methodology_registry_service.py
backend/app/services/methodology_integrity_service.py
backend/app/services/approved_evidence_mapping_service.py
backend/app/services/methodology_value_service.py
backend/app/services/condition_evaluator.py
backend/app/services/completeness_tracker_service.py
backend/app/services/edge_resolution_service.py
backend/app/services/derivation_service.py
backend/app/services/verification_engine_service.py
backend/app/services/recompute_service.py
backend/app/services/s2_gap_record_service.py
backend/app/services/s2_orchestration_service.py

backend/app/api/methodology.py
backend/app/repositories/methodology_value_repository.py

reference-data/methodology/
reference-data/methodology/approved_evidence_field_mapping_seed.json

docs/methodology_loader.md
docs/methodology_integrity_checks.md
docs/s1_to_s2_handoff_audit.md
docs/completeness_tracker.md
docs/verification_engine.md
docs/s2_backend_smoke.md
```

---

## 13. Acceptance definition for “S2 started correctly”

S2 is started correctly when the repo can:

```text
1. Load all five S2 methodology files.
2. Validate their integrity.
3. Query rows by Field_ID.
4. Map at least one approved evidence example to methodology Field_IDs.
5. Store methodology field values by engagement.
6. Run CX-01 and CX-12 completeness checks.
7. Emit a readable completeness result.
```

S2 should **not** be considered started correctly if it jumps directly to:

```text
LLM verification
hardcoded formula outputs
manual spreadsheet lookups
direct Scope 1 ↔ Scope 2 joins
requesting documents for computed fields
```

---

## 14. Bottom-line recommendation

Start Subsystem 2 with loaders, validation, registry, mapping, and completeness.

Do not begin with rules math.

The first hard deliverable should be:

```text
Approved S1 evidence can populate a methodology field store,
and the tracker can say which Core extracted fields are present, missing, not applicable, or not requestable.
```

That gives the team a stable foundation for derivation, verification, calculation, and eventually S3 gap analysis.
