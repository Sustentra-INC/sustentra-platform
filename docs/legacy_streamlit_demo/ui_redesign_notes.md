# UI Redesign Notes

## Objective
Refactor the demo into a seven-page auditor-facing workflow while preserving:
- prepared mock analysis behavior,
- optional live NY Part 253 RAG support,
- canonical library integrity,
- Streamlit deployment compatibility.

## Key implementation choices
- Home page now acts as a workflow landing page.
- Old five pages were archived and removed from active sidebar navigation.
- Gap register and finding detail were merged into one card-driven Gap Analysis page.
- Regulatory assistant mode selector is hidden from users and controlled internally.

## Prepared-data disclosure
Every major workflow stage includes a visible statement that extraction/validation/calculation/gap outputs are precomputed for demo purposes.

## Data contract extensions
Analysis response now includes:
- audit_setup
- uploaded_demo_files
- evidence_results
- validation_results
- calculation_results
- reconciliation_summary
- gap_tickets
- chat_suggestions
- warnings
- errors

## Preview strategy
- Source preview prioritizes available manifest metadata and snippets.
- Unsupported source rendering paths clearly display "Original preview unavailable in current demo".
- No fabricated document images are introduced.

## Regulatory response safeguards
- No key/token logging.
- Legal disclaimer always visible.
- Citation warnings shown as reviewer warnings instead of hard API failures.

## Remaining known limitations
- Clean-path scenario is structurally supported but marked not available.
- Some calculation records are intentionally marked not_computed_in_current_demo where validated inputs are unavailable.
- Auditor actions are session-state only (no persistent backend yet).
