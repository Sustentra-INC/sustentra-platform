# Highlight matcher fixtures

## `utility_bill_textract.json` — SYNTHETIC, not a real capture

This file is **hand-built**, not a real AWS Textract `AnalyzeDocument` response.
It was generated to exercise `value_block_matcher` with realistic block/geometry
structure (LINE blocks with child WORD blocks, normalized 0..1 boxes).

It is **tidy by construction** and has **not** been validated against a genuine
document. Real Textract output is messier — see the "where it will break on real
Textract" section of the PR / `docs/findings-extraction-path.md`. Known gaps this
fixture does not represent:

- words split in unexpected places, or units glued to numbers (`182,400kWh`)
- OCR character substitutions (`l82,400`, `O` for `0`)
- numbers that live in **TABLE cells**, which are not LINE blocks
- skewed / rotated scans (Polygon vs axis-aligned BoundingBox)

Jack is sourcing a sanitized real capture. When it lands, add it beside this one
and keep this file only as the tidy baseline. Do not present this as evidence the
matcher works on real documents — it proves the matcher's logic, not its
robustness to real OCR noise.
