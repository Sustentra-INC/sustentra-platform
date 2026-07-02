# Data Flow

## Current demo flow
Workbook + evidence upload
-> selected prepared scenario load
-> adapted analysis response in session state
-> extraction review controls
-> validation checks and reasoning trail
-> calculation and reconciliation review
-> gap analysis actions
-> regulatory assistant context and chat

## Prepared scenario fixtures
- data/demo/mock_outputs/mock_analysis_response_gap_path.json
- data/demo/mock_outputs/mock_analysis_response_clean_path.json
- data/demo/mock_outputs/mock_analysis_response.json (backward-compatible default)

## Split fixture alignment
The default analysis response sections are synchronized with:
- mock_audit_setup.json
- mock_evidence_results.json
- mock_validation_results.json
- mock_calculation_results.json
- mock_reconciliation_summary.json
- mock_gap_tickets.json
- mock_workbook_results.json
- evidence_assets_manifest.json

## Regulatory assistant mode resolution
1. `AUDITOR_CHAT_MODE=real` -> always attempt live RAG first; on failure, return a live-unavailable message without switching to prepared answers.
2. `AUDITOR_CHAT_MODE=prepared` -> always use reviewed prepared answers only.
3. `AUDITOR_CHAT_MODE=auto` -> attempt live RAG when configuration exists; otherwise use prepared fallback.
4. `AUDITOR_CHAT_MODE=mock` -> alias for `prepared` (kept for backward compatibility).

## Assistant answer provider behavior
- Provider label `Live source-backed response` means the answer came from the Sustentra RAG API.
- Provider label `Prepared reviewed response` means a reviewed question matched and returned fixture-backed text.
- Provider label `Prepared fallback` means no reviewed prepared answer was available for that exact question.
- In `auto` mode, runtime live failures fall back to prepared only when an exact reviewed question match exists.
- In `auto` mode, unanswered custom questions return a clear unavailable message instead of synthesized text.

Configuration lookup order for RAG values:
1. os.environ
2. local .env
3. Streamlit secrets
