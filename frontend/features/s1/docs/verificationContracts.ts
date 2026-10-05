/**
 * REFERENCE ONLY — not wired to any component yet.
 *
 * These types mirror the verification/completeness services that live on
 * `origin/main` (backend/app/services/*, read read-only), so that when Screens
 * 5 (Check Coverage) and 6 (Verification results) move off fixtures the adapter
 * is a config change, not a rewrite. Each type names its backend source.
 *
 * The mapping notes at the bottom flag where the 09/16 spec's one-paragraph
 * descriptions of Screens 5 and 6 do NOT line up with what the backend returns
 * — those gaps need a frontend-owned layer (like the requests store).
 */

/* ---- MethodologyValue (S1 -> S2 handoff; domain/methodology_value.py) ---- */
export interface BackendMethodologyValue {
  methodology_value_id: string;
  engagement_id: string;
  evidence_id: string;
  document_id: string;
  methodology_field_id: string;
  data_schema_field: string;
  grain: string | null;
  record_key: string;
  approved_value: string | number | boolean | null;
  approved_unit: string | null;
  source_reference: Record<string, unknown>;
  approved_evidence_id: string;
  review_decision_id: string;
  value_origin: "approved_evidence";
  created_at: string;
}

/* ---- Completeness tracker (services/completeness_tracker_service.py) ---- */
export type BackendCompletenessStatus =
  | "complete"
  | "missing_required"
  | "not_applicable"
  | "provisional_condition_unknown"
  | "not_requestable_value_origin";

export interface BackendCompletenessRow {
  field_id: string;
  layer: string;
  value_origin: string | null;
  requirement_level: string | null;
  condition: string | null;
  condition_status: string | null;
  status: BackendCompletenessStatus;
  methodology_value_ids: string[];
  reason: string | null;
}

export interface BackendCompletenessResult {
  engagement_id: string;
  status_counts: Partial<Record<BackendCompletenessStatus, number>>;
  results: BackendCompletenessRow[];
}

/* ---- Runtime verification rule (domain/verification_rule.py) — Screen 5 ---- */
export interface BackendVerificationRule {
  rule_id: string;
  layer: string;
  rule_type: string | null; // guard | gate | invariant | limit | confirm | ...
  assertion: string | null; // "what it checks"
  applies_to: string[]; // "data points it applies to"
  grain_key: string | null;
  rule_expression: string | null;
  source: string | null;
  status: string | null;
  notes: string | null;
  is_provisional: boolean;
  resolvable_applies_to: string[];
  unresolved_applies_to: string[];
  source_workbook: string;
  source_sheet: string;
  source_row_number: number;
}

/* ---- Verification engine result (services/verification_engine_service.py) ---- */
export type BackendVerificationStatus =
  | "passed"
  | "failed"
  | "not_applicable"
  | "provisional"
  | "unsupported"
  | "cannot_verify";

export interface BackendVerificationRuleResult {
  rule_id: string;
  rule_type: string | null;
  assertion: string | null;
  status: BackendVerificationStatus;
  applies_to: string[];
  methodology_value_ids: string[];
  reason: string | null;
}

export interface BackendVerificationResult {
  engagement_id: string;
  status_counts: Partial<Record<BackendVerificationStatus, number>>;
  results: BackendVerificationRuleResult[];
}

/* ---- Recompute result (services/recompute_service.py) — Screen 6 ---- */
export type BackendRecomputeStatus = "matched" | "mismatch" | "missing_input" | "unsupported";

export interface BackendRecomputeResult {
  calculation_path: string;
  status: BackendRecomputeStatus;
  computed_value: number | null;
  reported_value: number | null;
  delta: number | null;
  unit: string | null;
  input_methodology_value_ids: string[];
  reason: string | null;
}

/* ---- Gap record (services/s2_gap_record_service.py) — Findings list ---- */
export interface BackendGapRecord {
  engagement_id: string;
  field_id: string;
  substage: "completeness" | "verification" | "derivation";
  gap_type: string;
  root_cause_code: string;
  assertion: string | null;
  severity: "high" | "medium";
  source_reference: Record<string, unknown> | null;
  rule_id: string | null;
}

/* ==========================================================================
   MAPPING NOTES — spec column  <-  backend field, and the gaps.

   Screen 5 (Check Coverage): row per rule, "grouped by the reason it cannot run".
     rule                 <- BackendVerificationRule.rule_id
     what it checks       <- BackendVerificationRule.assertion
     data points          <- BackendVerificationRule.applies_to
     status               <- map BackendVerificationStatus -> {can run | inputs
                             present only | cannot run}:
                             passed|failed -> "can run";
                             cannot_verify with methodology_value_ids -> "inputs present only";
                             not_applicable|unsupported|provisional -> "cannot run".
     reason               <- BackendVerificationRuleResult.reason
     GAP: the engine v0 does NOT evaluate rule_expression; passed/failed only
          means "the Applies_To fields have values", not that the assertion held.

   Screen 6 (Verification results) — Results tab, sections General/Scope 1/Scope 2:
     data point           <- MethodologyValue.methodology_field_id / data_schema_field
     reported value       <- BackendRecomputeResult.reported_value
     recomputed/expected  <- BackendRecomputeResult.computed_value
     delta                <- BackendRecomputeResult.delta
     check outcome        <- map: matched/passed->held; mismatch/failed->exception;
                             cannot_verify/unsupported/missing_input->could not check;
                             not_applicable->out of scope.
     examination state    <- NOT IN BACKEND. "not examined | examined, no exceptions |
                             finding raised" is a HUMAN disposition — must be a
                             frontend-owned persist layer (like the requests store).
     next action (me/client/none) <- NOT IN BACKEND. Human/workpaper field.

   Screen 6 — Findings list:
     data point           <- BackendGapRecord.field_id
     finding (one sentence)<- NOT IN BACKEND. gap_type/root_cause_code are codes,
                             not prose; the sentence is authored by the verifier.
     cause                <- BackendGapRecord.root_cause_code
     magnitude            <- PARTIAL. severity is high|medium only; a numeric
                             magnitude (from RecomputeResult.delta) is richer.
     status               <- human disposition (frontend), not in gap record.
     with the client since<- comes from the linked request's sent date (requests
                             store), not the gap record.

   Completeness tracker — DROPPED from the revised frontend spec. What it exposes:
     per required methodology field (by requirement level, default "Core"),
     whether a populated approved value exists, classified as complete |
     missing_required (requestable, value_origin "extracted") | not_applicable
     (condition false) | provisional_condition_unknown | not_requestable_value_origin
     (computed/verifier_determined/assigned). Plus status_counts. This is the
     "what is still missing that we can still ask the client for" gate — the
     engine behind "the in-scope list makes the product finite". With no
     frontend surface, the auditor never sees the methodology-derived requestable
     list; the Workspace Issue/Needs-you is a coarser, per-document proxy.
   ========================================================================== */
