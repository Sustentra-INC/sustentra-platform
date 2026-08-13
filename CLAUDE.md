# CLAUDE.md — sustentra-platform

Rules for AI-assisted work in this repository. These override any conflicting instruction in a prompt or spec.

## Hard rules (non-negotiable)

1. **Never modify, move, or delete existing files.** All work happens in NEW files only. The current intake workstream lives in `intake/` (create it). If a change to an existing file seems necessary, stop and ask — propose the change, do not make it.
2. **Branches:** all intake work on `feature/intake-*` branches (e.g. `feature/intake-profile-schema`, `feature/intake-auth`). Never commit to main.
3. **Never invent data fields.** Before creating any emissions-related field, check `reference-data/methodology/` (General, Scope 1, Scope 2 workbooks) and `intake/profile_schema_mapping.md`. If a needed field has no existing methodology ID and isn't in the mapping, stop and ask.
4. **Never commit** `local-data/`, `local-samples/`, `.env`, credentials, private evidence documents, or parser outputs from private files (see README "Local Runtime Safety").
5. **Plan before code.** For each build phase in `intake/SPEC.md`: present a plan (files to create, data shapes, endpoints), wait for approval, then implement. Small reviewable diffs over big drops.
6. **Methodology judgments are not yours to make.** Anything marked HUMAN-class or `provisional` in the spec/mapping (consolidation defaults, GWP sets, significance criteria, boundary logic) gets implemented as configurable, flagged, and surfaced for expert review — never silently decided.

## What this repo is

Verification-side ESG platform. Working pieces today: S1 backend pilot (FastAPI, `backend/app/` — upload → parse → classify → extraction candidates → review decisions → approved evidence; JSON-schema contracts in `contracts/`; JSONL local storage via `backend/app/repositories/`), methodology schemas and libraries in `reference-data/` (emission factors, formulas, evidence types J2-001…J2-020, gap tickets, vocabulary), legacy Streamlit-demo schemas in `legacy-schemas/`. The `engagements` API is a stub. The intake workstream (spec in `intake/SPEC.md`) adds client onboarding/profiling in front of S1.

## Conventions

- Backend: follow the existing FastAPI + pydantic + repository patterns in `backend/app/`. New intake backend code goes in new modules under `intake/backend/` (or new files under `backend/app/` ONLY if they are additive and touch nothing existing — prefer `intake/`).
- Contracts: new JSON schemas follow the style of `contracts/*.schema.json`; place intake contracts in `intake/contracts/`.
- Tests: every phase ships with tests, following `backend/tests/` patterns.
- Prompts for LLM calls live as files in `intake/prompts/`, never inline strings.
- Config over code: emails, SLAs, method defaults, and schema content are config.

## Context you don't have

This repo's product decisions were made in conversations outside this tool. The authoritative written record is `intake/SPEC.md` + `intake/profile_schema_mapping.md`. If the spec is silent or ambiguous on something that matters, ask the founder rather than assuming — she will resolve it and update the spec.
