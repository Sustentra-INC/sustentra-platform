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

## Content cues for company summaries and contracts (EXT-026)

- **Inventory summary.** A document with a title that names a GHG or emissions inventory, summary or report,
  Scope 1 and Scope 2 totals, a tonnes-CO2e unit (with or without the subscript, `tCO₂e`) and a reporting year
  is credited `CT-GHG-WORKBOOK` whatever its file is called. It is then a client-prepared summary document
  (`calculation_lines.SUMMARY_TYPES`), which Methodology review and Claude prefill read as the client's reports.
  It is read as itself and never as fuel evidence.
- **Contract.** `document_shape.looks_like_a_contract` (a heading that names an agreement or contract, at least five
  kinds of contract wording, and no usage figure or bill rows) stops a document as not-evidence, with a plain
  reason, after the classifier: it is never typed as a fuel or electricity record. A fuel bill that mentions an
  agreement in its terms has bill rows and no such heading, so it is still a bill.
