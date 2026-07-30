# Deterministic Extraction Bugfixes v0 (PR6.5)

PR6.5 is a narrow deterministic extractor bugfix release focused on five QA regressions in S1 candidate generation. It does not change contracts, APIs, review decisions, approved evidence behavior, upload/storage, or orchestration.

## What PR6.5 fixes

1. Anchor boundary collision fix:
- Short anchors now require label boundaries.
- Example: To matches To: 01/31/2023 but no longer matches Total Usage.

2. Split unit context inference:
- For numeric/quantity targets with missing unit, unit inference now checks nearby deterministic parser context.
- Sources include same-page key/value pairs, nearby page lines, and row/header context.
- Units are inferred only when expected unit or configured unit pattern is present.

3. No-activity suppression for activity_quantity:
- Strong no-activity signals now suppress broad numeric extraction for activity_quantity when no positive reportable usage/delivery/consumption quantity exists.
- This avoids false extraction of years/IDs in no-activity statements.

4. Numeric false-positive guard:
- activity_quantity numeric matching now rejects likely years, date fragments, and identifier fragments (document IDs, ticket IDs, account/invoice-like contexts) when not quantity-contextual.

5. Internal record/ticket row binding support:
- activity_quantity extraction can now use optional target-side row context hints (record_id and related hints) to bind to the correct table/line row and extract row-specific quantity.
- Quantity columns are preferred from headers such as Gallons Delivered, Quantity, Delivered, Usage, Consumption, and Total.

## Why these are deterministic extractor failures

The failing QA cases are parser-output-based fixtures. The relevant source text/table content is already present in parser_output, so these are deterministic selection/normalization issues in extraction logic, not OCR/Textract runtime issues.

## Known limitation

The public extraction_candidate contract is unchanged and still has no explicit record_id field. Row-binding is currently internal target-side behavior. If product workflows later require explicit row-level review semantics, a future contract PR may be needed.
