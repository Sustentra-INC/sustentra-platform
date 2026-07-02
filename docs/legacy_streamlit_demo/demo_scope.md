# Demo Scope

## Purpose
This Streamlit demo presents an auditor-facing workflow for NY Part 253 review preparation.

## Workflow
1. Audit Setup
2. Evidence Intake
3. Extraction Review
4. Validation
5. Calculation & Reconciliation
6. Gap Analysis
7. Regulatory Assistant

## Demo data posture
- The current build uses prepared extraction, validation, calculation, and gap-analysis outputs.
- Uploaded files establish engagement context for workflow simulation.
- The formal ingestion and gap-analysis API is not yet connected.

## In-scope experience
- Audit-setup profile editing and session persistence.
- Upload-first engagement intake.
- Side-by-side source preview and extracted-field review.
- Explicit validation checks and deterministic outcomes.
- Reconciliation visibility from source evidence to variance/materiality.
- Card-based gap analysis with evidence/workbook/regulation navigation actions.
- Regulatory assistant with automatic real-RAG-or-fallback behavior.

## Out of scope for this build
- Live OCR or extraction execution.
- Live backend gap-generation execution.
- Database persistence for auditor actions.
