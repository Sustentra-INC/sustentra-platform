# Current Demo Inventory

## Reuse Directly

- Legacy schemas copied to `legacy-schemas/copied_from_streamlit_demo/` as historical references.
- JSON libraries copied to `reference-data/`.
- Demo mock fixtures copied to `demo-fixtures/mock_outputs/`.
- Legacy documentation snapshot in `docs/legacy_streamlit_demo/`.

## Reuse After Refactor

- Streamlit data models and helper patterns from the legacy `src/` tree.
- Existing evidence-type and formula-library semantics.
- Existing review fixture shape as seed data for frontend state.

## Replace

- Streamlit page runtime and local state wiring.
- Monolithic page-level logic with backend API-driven workflow.
- Legacy end-to-end orchestration in UI callbacks.

## Defer

- Validation and calculation parity work.
- Gap analysis automation parity.
- Assistant parity beyond pilot retrieval and summarization.
