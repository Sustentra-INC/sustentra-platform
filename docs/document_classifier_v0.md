# Document Classifier v0 (PR3)

`ClassificationService` now performs deterministic S1 document identification using vocabulary variant signals.

- Inputs considered: `file_name`, optional `extracted_text`, and parser-output text fragments.
- Signal groups: `filename_patterns`, `layout_features`, `header_terms`, `key_phrases`.
- Matching is case-insensitive substring matching.
- Confidence is computed from fixed signal-group weights.
- Candidate confidence is compared to each variant threshold.

Output is a `document_classification_result`-shaped dictionary with stable IDs (`canonical_type_id`, `variant_id`), candidate matches, and review flags.

Statuses produced in v0:

- `classified`
- `low_confidence`
- `multi_type_candidate`
- `unclassified`
- `failed`

Low-confidence and multi-type outcomes route to review. v0 does not implement LLM calls, OCR, parser runtime execution, or extraction generation.
