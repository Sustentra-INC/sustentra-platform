# Libraries

Place reusable JSON libraries here for the demo runtime:

- evidence_type_library.json
- formula_library.json
- emission_factor_library.json
- gap_ticket_schema.json

Do not move existing root-level library files automatically. Copy them here manually only when the team is ready to standardize paths.

## Runtime library convention

For the demo, Streamlit and backend adapter code should read canonical copies from this folder:

- evidence_type_library.json
- formula_library.json
- emission_factor_library.json
- gap_ticket_schema.json

Root-level JSON files are preserved as original working copies and should not be deleted until all code paths are standardized.

