# Migration Notes

## Bootstrap Summary

- Production skeleton created for frontend and backend.
- Legacy Streamlit assets copied into versioned preservation folders.
- Pilot-focused contracts defined for document, run, source, candidate, review, and approved evidence.

## Migration Guardrails

- Do not mutate preserved legacy schemas in place.
- Build new contracts in `contracts/` and map legacy payloads explicitly.
- Keep pilot endpoints stable while internals are implemented.

## Follow-Up Work

1. Implement storage and parser adapters behind contracts.
2. Add persistence models and migrations.
3. Wire frontend review pages to backend APIs.
4. Align deferred validation/calculation/gap schemas after pilot approval flow is stable.
