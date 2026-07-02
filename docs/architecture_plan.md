# Sustentra Architecture Plan

## Target Architecture

The final target architecture is a Next.js frontend plus FastAPI backend.

## Legacy Positioning

The old Streamlit demo is reference only. It is not the production runtime and is retained only for migration guidance.

## Pilot Objective

The first pilot scope is:

1. Real file upload.
2. Extraction with source traceability.
3. Human review decisions.
4. Approved evidence record persistence.

## Deferred Scope

Validation, calculation, and gap analysis remain later-phase or demo-only until they are powered by real approved evidence.

## Structural Layers

- Frontend: route-driven review and evidence workflows.
- Backend: ingestion, processing, extraction, review APIs.
- Contracts: versioned JSON Schema definitions.
- Reference Data: preserved legacy libraries and fixtures.
