# Subsystem 1 Frontend

This is the home for the React implementation of Subsystem 1:

- Evidence Workspace
- Extraction Review
- S1-specific data adapters
- S1 fixtures used to exercise unsupported/degraded states
- S1 type definitions and view models

Components in this feature should render from S1 view models rather than raw
backend responses. Backend fields such as `processing_status`,
`classification_status`, `parser_status`, and extraction candidate fields need
to be translated in `adapters/` before they reach React components.

Do not reuse files from `frontend/legacy-demo/` unless they are intentionally
rewritten to satisfy `FRONTEND_CONSTRAINTS.md` and the Subsystem 1 build spec.
