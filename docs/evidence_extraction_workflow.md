# Evidence Extraction Workflow

1. Engagement is created.
2. Document metadata is registered and file is stored.
3. Processing run is started for the document.
4. Parser adapter extracts structural text/tables and source anchors.
5. Extraction adapter produces field candidates with confidence.
6. Candidates are attached to evidence records.
7. Reviewer accepts, edits, rejects, or requests clarification per field.
8. Approved values are persisted as approved evidence output.

## Traceability Rule

Every candidate and approved field must retain a source reference object linking to page/sheet/cell/snippet context.
