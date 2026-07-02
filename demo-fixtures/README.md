# Demo Fixtures

This folder stores copied fixtures from the ignored Streamlit reference demo.

- Source snapshot: `demo_package/intern/data/demo/mock_outputs/`
- Destination: `demo-fixtures/mock_outputs/`

## Expected Fixture Check

All expected fixture names were present at bootstrap time:

- mock_analysis_response.json
- mock_analysis_response_gap_path.json
- mock_analysis_response_clean_path.json
- mock_audit_setup.json
- mock_evidence_results.json
- mock_validation_results.json
- mock_calculation_results.json
- mock_reconciliation_summary.json
- mock_gap_tickets.json
- mock_workbook_results.json
- evidence_assets_manifest.json

If this list changes in future migrations, update this file with missing names and reasons.
