# Findings: what the extraction path actually does today

Two findings surfaced while building the source-highlight feature. Both are
bigger than the highlight. Written to circulate.

## 1. Textract has never been enabled — extraction has been text-only

`parser_service.py` only routes a PDF or image to AWS Textract when the env var
**`TEXTRACT_ENABLED`** is truthy. It is unset. So every extraction the product
has run has gone through:

- **Digital PDFs → `pdf_parser`** (pdfminer). Reads an embedded text layer only.
- **Images (JPG/PNG) → `image_parser`**, which is an *explicit non-OCR stub*:
  it returns `failed` with `"Image OCR is not implemented in parser runtime v0."`
- **Scanned / photographed PDFs** (image-only, no text layer) → pdfminer returns
  little or nothing.

**What this means.** There is no OCR running anywhere in the product. The only
OCR capability (Textract) sits behind a disabled flag, and the image path is a
deliberate stub. So the documents clients most often send as photos or scans —
meter photos, phoned pictures of bills, scanned statements — currently extract
**nothing**. Extraction "quality" on that share of evidence is not low; it is
zero. Any belief that we have an OCR pipeline in operation is incorrect.

This is a product-readiness fact, not a highlight detail: turning on Textract
(cost + AWS access decision) is what makes scanned/photo evidence work at all,
and it is the prerequisite for the highlight too.

## 2. The bounding box is delegated to the LLM, which never sees geometry

`llm_extraction_service.py` asks the model for a `bounding_box` in its JSON
schema, but hands the model only `document_text` — no coordinates. The model
therefore cannot produce a correct box; it can only omit it or invent one.

**Can a fabricated box reach `source_reference`?**

- On the **wired path** (`extraction_service` → `ExtractionCandidateService`),
  `bounding_box` is hardcoded `None`. Safe — no box, fabricated or otherwise.
- On the **LLM path** (`LlmExtractionService`), the code does
  `"bounding_box": item.get("bounding_box") if isinstance(item.get("bounding_box"), dict) else None`
  — i.e. **if the model returns an object, it is passed straight into
  `source_reference.bounding_box` unvalidated.** So yes: on that path a
  model-fabricated box could reach `source_reference` and render on the document
  as if it were real provenance.

In a product whose whole premise is traceable evidence, a box drawn in the wrong
place is worse than any missing feature — it asserts a number came from a spot it
did not. The fix already in progress removes the risk: compute the box from real
Textract geometry, return **null** whenever the match is not certain, and drop
`bounding_box` from the LLM schema entirely (that last edit is in Jack's file).
