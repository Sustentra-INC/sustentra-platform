# Sustentra Intake & Onboarding — Build Specification v1.0

Target location in repo: `intake/SPEC.md`. Companion file: `intake/profile_schema_mapping.md` (the data-point → methodology field mapping, v0.2, ISO-14064-aligned). Repo rules live in `CLAUDE.md` at repo root and override anything ambiguous here.

## 1. Context

Sustentra is a verification-side ESG platform. The existing repo contains the S1 backend pilot (evidence upload → parse → classify → extraction candidates → reviewer decisions → approved evidence) and the S2 methodology schemas in `reference-data/methodology/` (General, Scope 1, Scope 2 workbooks). This feature adds the missing front door: an intake/onboarding flow where an SME client (v1 persona: an auditor's client with zero carbon-accounting background; first design partner: a film studio) builds their company profile, which then drives S1 evidence requests and S2 calculation inputs.

Core design principle: **the profile schema is config, the AI fills it, the database owns the state.** The intake defines no new emissions data points — every answer populates an existing methodology field ID, toggles a schema block, or triggers an evidence request (see mapping file).

## 2. Goal & success metrics

A client can log in, complete their Scope 1 & 2 profile through a guided flow, and end with (a) a stored, versioned profile page and (b) a generated evidence-request list feeding S1. Success metrics for v1: **% of profiles completed with zero escalations** and **median time-to-complete**. Instrument both from day one.

## 3. Workflow stages

**Stage 0 — Auth & org.** Magic-link email login (no passwords in v1). An org record per client company; users belong to one org. Roles: `client_owner`, `client_member`, `sustentra_reviewer` (internal).

**Stage 1 — Seed form (structured, not chat).** Fields per mapping §1: legal name + reporting year, responsible party (name/role/email), sites (name, address, status, site type), industry (v1: dropdown, "Film production facility" + "General"), reporting period, own/lease per site. Each site instantiates its own copy of the applicable screening tree.

**Stage 2 — Guided profiling interview (chat UI, schema-driven).** Loop: engine selects next unanswered applicable data point (applicability conditions in mapping) → question rendered in plain language with industry vocabulary → user answers via buttons/dropdowns/number fields where possible, free text only when narrative → LLM parses free text into structured fields → playback confirmation → status update → coverage meter refresh ("14 of 22 complete"). Every question has: canned plain-language explainer (one-tap "What does this mean?"), jargon tooltips, and a visible "Not sure" button that is never a failure state.

"Not sure" path: canned explainer → one LLM rephrase → auto-escalate with message "We've sent this to the Sustentra team — you'll have an answer within 24 hours. Let's keep going." Interview continues with next question.

"I don't know the value" path: always offer document upload ("upload the bill and we'll extract it" — converts the question into an S1 evidence request) plus the contact email vivian@sustentra.com (displayed to the user; messages route through the platform so Q&A attaches to the data point).

**Stage 3 — Escalation handling (async).** Triggers: (a) any HUMAN-class data point per the mapping (boundary/allocation/consolidation), (b) two failed clarification attempts on a required data point, (c) user explicitly asks for help, (d) parsed answer contradicts an earlier answer or seed-form fact. Escalations create a queue item + immediate email to vivian@sustentra.com and claire@sustentra.com containing: the question, the user's answer attempts, seed-form context, one-click resolution link. Reviewer resolves **in-platform** (resolution is written into the profile as the data point's answer, tagged `resolved_by_team`); user notified by email with a link back. SLA 24h; automatic reminder email at 12h if untouched. Notification channel: email only.

**Stage 4 — Profile → evidence requests.** On sufficient completion, compile: expected-document checklist (doc types × sites × months, from J2 evidence types per the mapping) rendered as an upload page, and the expected-completeness spec for S1's gate (expected meters × months derived from profile, replacing any hardcoded assumptions — but do NOT modify existing S1 code; expose the spec via a new intake API the existing pipeline can adopt later).

**Stage 5 — S1/S2 handoff rule ("safe to parse").** S1 may run immediately on documents tied to AUTO-class data points with no open contradiction flags. Documents dependent on HUMAN-class data points wait until the escalation resolves. Boundary answers are always human-confirmed before dependent processing.

**Stage 6 — Profile page.** The living record: company/sites, boundary decisions with rationale, every data point with status + answered-by (user / document / team) + linked evidence, "screened, not present" completeness records, genuine exclusions, uncertainty ratings, coverage state. Versioned: every change appended to an audit log (who, when, old → new). For a verification company the edit history is itself evidence.

## 4. State machine (DB-owned)

Each (org, site?, data_point_id) row carries exactly one status:
`unasked → asked → { answered | unknown | not_present | pending_documents | escalated } → resolved`
Rules: transitions enforced in application code; the LLM proposes updates, the app writes them. `not_present` = screening "no" (completeness record — NOT an exclusion). Genuine exclusions (source exists, excluded on materiality) use the EXC-010 pattern and require `sustentra_reviewer` action. `escalated` items block only their dependents, never the interview flow. All status changes timestamped and attributed.

## 5. Data model (new tables — do not modify existing storage)

`orgs`, `users`, `magic_link_tokens`, `sites` (FK → future FAC-010 alignment; store address, site_type, own/lease), `profile_datapoints` (schema config: id, section, field mappings, applicability condition, class AUTO/HUMAN/SYSTEM, question content ref), `datapoint_states` (org/site/datapoint status + value JSON + provenance + uncertainty tier), `escalations` (reuse the shape of `reference-data/config/libraries/gap_ticket_schema.json` where sensible), `audit_log`, `evidence_requests` (J2 type × site × period × status). Storage backend: follow whatever the existing repositories use (JSONL local pattern) unless the plan review decides otherwise — propose, don't assume.

## 6. LLM usage (Stage 2 only, v1)

Two calls per turn max: (1) parse the user's free-text answer against the target data point's field spec (structured JSON out, with confidence; low confidence → clarify once, then escalate); (2) rephrase an explainer only when the canned one failed. Question selection, applicability, coverage math, and status transitions are deterministic code, never LLM. All prompts live in `intake/prompts/` as files, not inline strings.

## 7. UI (React)

Screens: login (magic link request + landing), seed form (multi-step), interview (chat pane + coverage meter + "Not sure" affordance), evidence-request/upload list, profile page, internal review queue (list + resolution view). Follow the existing `frontend/` conventions if present and compatible; otherwise scaffold a new app under `intake/frontend/` — inspect first, propose in the build plan.

## 8. v1 scope cuts

English only. One industry overlay (film) + general fallback. Single org per user. No SSO, no password auth. Only simple method routes exposed (mapping §7); CEMS/waste-gas/SF6/process paths never surface in intake. No payment, no multi-language, no mobile-specific app (responsive web is enough).

## 9. Build order (each phase ends with a plan/diff review — wait for approval)

1. Phase A: schema seed — convert `profile_schema_mapping.md` into `intake/config/profile_schema.json` (+ validation script + tests)
2. Phase B: Stage 0 auth + org/site models + seed form API & UI
3. Phase C: state machine + deterministic interview engine (no LLM yet; buttons/dropdowns only)
4. Phase D: LLM parse/rephrase integration + escalation queue + emails
5. Phase E: evidence-request compilation + profile page + audit log
6. Phase F: instrumentation (the two success metrics)

## 10. Open items (do not resolve unilaterally — flag in plan)

- Methodology defaults pending expert (Todd) sign-off: consolidation default, base-year default, GWP/gas universe, significance-criteria template, method-route defaults. Ship as config marked `provisional: true`.
- Integration caveats from the workbooks' own flag sheets (General MTH-020 key, PER-020, gas-universe alignment, Scope 2 shared-key migration): confirm current code status with the team before wiring cross-layer keys.
- Question wording/content: schema ships with placeholder question text; final plain-language copy is authored separately after the Vocabulary Library review.

## 11. Escalation contacts (hardcode as config, not literals in code)

`ESCALATION_PRIMARY=vivian@sustentra.com`, `ESCALATION_SECONDARY=claire@sustentra.com`, `SLA_HOURS=24`, `REMINDER_HOURS=12`.
