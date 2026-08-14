# S1 Golden Test Suite

This fixture set validates the deterministic S1 pipeline stage by stage:

`document intake -> parser/OCR -> classification -> target planning -> candidate generation -> normalization -> source traceability`

## Source material

- `Evidence_Pack_Generated_Review_Pack_Nora.docx` was split by the stable `Document ID` headings.
- `AB_Baldwinsville_Scope1_Workbook.xlsx` is the authoritative gold-label source for:
  - equipment inventory
  - natural gas
  - biogas
  - BLR-003 monthly fuel records
  - propane
  - diesel
- Lab, aggregation, and RFO expectations are source-derived and are explicitly marked for review.

Do not replace workbook values with values inferred from the raw source documents. Several deliberate conflicts and suspicious values are part of the test set.

## Contents

- `raw_documents/docx/`
  - one DOCX per evidence ID
- `raw_documents/ocr_png/`
  - rendered PNG/PDF fixtures for five representative documents:
    - `EV-INV-2023-001`
    - `EV-NG-2023-001`
    - `EV-BIO-2023-003`
    - `EV-BLR003-2023-001`
    - `EV-PROP-2023-001`
- `stage_1_document_intake/document_manifest.json`
- `stage_2_parser_ocr/*.parser_expected.json`
- `stage_3_classification/classification_expected.json`
- `stage_4_extraction_targets/target_expected.json`
- `stage_5_extraction_candidates/*.expected.json`
- `stage_6_normalization/normalization_expected.json`
- `stage_7_evidence_validation/evidence_expected.json`
- `evaluation/`

## Baseline

Run the existing targeted suite from the repository root:

```bash
PYTHONPATH=. pytest \
  backend/tests/services/test_extraction_candidate_service.py \
  backend/tests/services/test_extraction_service.py \
  backend/tests/services/test_extraction_target_service.py \
  backend/tests/services/test_classification_service.py \
  backend/tests/services/test_pipeline_orchestration_service.py
```

Expected baseline at fixture-generation time: `55 passed`.

## Codex implementation task

Create a new test package without changing production behavior merely to make fixtures pass:

```text
backend/tests/golden_s1/
  conftest.py
  test_stage_1_intake.py
  test_stage_2_parser_ocr.py
  test_stage_3_classification.py
  test_stage_4_targets.py
  test_stage_5_candidates.py
  test_stage_6_normalization.py
  test_stage_7_traceability.py
  test_end_to_end_golden.py
```

Copy this suite into the repository under:

```text
backend/tests/fixtures/golden_s1/
```

or make the fixture root configurable with:

```bash
export S1_GOLDEN_FIXTURE_ROOT=/absolute/path/to/s1-test-suite
```

### Shared fixture loader

Implement a small loader that:

1. reads JSON with UTF-8,
2. resolves fixture paths relative to the suite root,
3. returns parametrized cases by `document_id`,
4. never edits the fixture files during tests.

## Stage 1: document intake

Use `stage_1_document_intake/document_manifest.json`.

Assert:

- every file exists,
- the stable document ID is preserved,
- upload/registration metadata references the correct document,
- repeated upload behavior is deterministic,
- document A is not associated with another engagement/project.

If the current service does not expose document registration at service-test level, test the repository or API layer separately rather than faking pipeline behavior.

## Stage 2: parser and OCR

### DOCX parser checks

For the five detailed documents, feed the individual DOCX to the real parser. Compare with the associated parser expectation using containment rather than exact serialization:

- normalize whitespace,
- compare text case-insensitively,
- require expected table headers and required rows/cells,
- do not require parser block ordering unless ordering is part of the parser contract.

### OCR checks

Feed the rendered PNG files from `raw_documents/ocr_png/<document_id>/` through the image/OCR adapter.

At present, image OCR is described as a stub. Mark these tests:

```python
@pytest.mark.xfail(reason="Image OCR adapter is not implemented")
```

Do not mock OCR and report the test as passing. Remove `xfail` only when a real OCR implementation exists.

## Stage 3: classification

Use `classification_expected.json`.

The fixture intentionally leaves `canonical_type_id` as `null` because canonical IDs must come from the committed extraction config, not be invented in the fixture.

For each case:

1. map `expected_document_type` / `expected_classification_group` to the actual canonical ID defined in `reference-data/extraction-config/extraction_config_seed.json`;
2. assert the classifier selects that ID when confidence meets the configured threshold;
3. separately test the override path;
4. report low-confidence skips as classification failures, not extraction misses.

If the committed config has no mapping for an expected type, fail with category `config_gap`.

## Stage 4: extraction target planning

Use `target_expected.json`.

Assert that the planned field IDs include the expected target fields. The extraction config remains the source of truth for `required_status`; this fixture does not override it.

Classify failures as:

- `config_gap`
- `classification_gap`
- `target_planning_gap`

## Stage 5: candidate extraction

Use every `stage_5_extraction_candidates/*.expected.json`.

Comparison rules:

- strings: trim/collapse whitespace; identifiers remain exact;
- numbers: compare numerically after removing commas/currency symbols;
- dates: normalize to ISO `YYYY-MM-DD`;
- units: compare against canonical units case-insensitively;
- list/table records: match records by stable key such as `unit_id`, not parser order.

For each expected field record:

- candidate exists,
- normalized value matches,
- unit matches where applicable,
- candidate belongs to the correct document,
- extraction method is supported,
- no high-confidence false positive is emitted for unrelated values.

Do not require a specific extraction method unless the production contract explicitly promises one. Different valid methods may produce the same correct candidate.

## Stage 6: normalization

Use `normalization_expected.json`.

Test normalization directly, without invoking parsing or classification. This isolates failures in:

- comma removal,
- numeric conversion,
- date normalization,
- unit detection.

Known missing unit conversions should be `xfail`, not silently accepted.

## Stage 7: evidence/source traceability

Use `evidence_expected.json`.

For every extracted field:

- source `document_id` equals the input document,
- source text exists,
- explicit values appear in or are faithfully derived from the source text,
- page/block/table/cell locator exists,
- no source reference points to a different document.

A correct value with the wrong source is a failure.

## End-to-end golden evaluation

Run each DOCX through:

```text
parse -> classify -> plan targets -> generate candidates -> normalize
```

Compare final candidates against stage 5 labels.

Write results to a new output directory, not into the committed fixture directory. Recommended:

```text
local-data/golden-s1-results/
  pipeline_results.csv
  failure_analysis.csv
  actual_candidates/
```

Use the provided CSV files as column templates.

Calculate at minimum:

- required-field recall,
- normalized-value exact accuracy,
- unit accuracy,
- source-reference presence rate,
- false-positive rate,
- document classification accuracy.

Failure categories:

```text
parser_gap
ocr_gap
classification_gap
config_gap
target_planning_gap
extraction_algorithm_gap
normalization_gap
source_traceability_gap
missing_feature
```

## Deliberate edge cases

Review `evaluation/failure_cases.json`.

Important cases:

- `EV-NG-2023-010`: suspicious October spike (`281,000 MMBtu`)
- `EV-NG-2023-012`: source period crosses into 2024, while workbook gold uses calendar December
- `EV-RFO-2023-001`: source no-use statement conflicts with workbook summary
- OCR PNG tests: currently expected to be unimplemented

Do not modify the expected answer to hide these conflicts. Extraction and reconciliation are separate capabilities.

## Suggested execution order

```bash
# 1. Existing regression suite
PYTHONPATH=. pytest backend/tests/services/...

# 2. Contract/config tests
PYTHONPATH=. pytest backend/tests/golden_s1/test_stage_1_intake.py \
  backend/tests/golden_s1/test_stage_3_classification.py \
  backend/tests/golden_s1/test_stage_4_targets.py

# 3. Detailed parser tests
PYTHONPATH=. pytest backend/tests/golden_s1/test_stage_2_parser_ocr.py

# 4. Method/normalization tests
PYTHONPATH=. pytest backend/tests/golden_s1/test_stage_5_candidates.py \
  backend/tests/golden_s1/test_stage_6_normalization.py

# 5. Traceability
PYTHONPATH=. pytest backend/tests/golden_s1/test_stage_7_traceability.py

# 6. Full golden run
PYTHONPATH=. pytest backend/tests/golden_s1/test_end_to_end_golden.py
```

## Pass criteria

A green run must mean:

- the parser read the relevant source correctly,
- the classifier selected the correct configured document type,
- target planning requested the correct fields,
- candidates match the workbook/source gold labels,
- normalization is correct,
- source traceability is correct.

Do not collapse all failures into `field_not_found`; preserve the earliest failing pipeline stage.
