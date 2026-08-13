export type IntakeRole = "client_owner" | "client_member" | "sustentra_reviewer";

export interface IntakeUser {
  user_id: string;
  org_id: string;
  email: string;
  name: string;
  role: IntakeRole;
  session_expires_at: string;
}

export interface FieldOption {
  value: string;
  label: string;
  /** Present on industry options: selects the vocabulary overlay for later questions. */
  overlay_id?: string;
}

export type FieldInput =
  | "text"
  | "email"
  | "number"
  | "date"
  | "select"
  | "textarea"
  | "derived"
  | "overlay_dependent"
  // Interview-only shapes.
  | "yes_no"
  | "list";

export interface PopulatesTarget {
  target_type: "methodology_field" | "intake_field" | "legacy_field";
  field_id?: string;
  schema_field?: string;
  field_path?: string;
  intake_field?: string;
}

export interface SeedFormField {
  field_id: string;
  datapoint_id: string;
  label: string;
  help?: string;
  input: FieldInput;
  required: boolean;
  provisional?: boolean;
  requires_signoff?: string;
  provisional_reason?: string;
  options?: FieldOption[];
  options_ref?: string;
  vocabulary_open?: boolean;
  visible_when?: { field_id: string; equals: string };
  derived_from?: string;
  populates?: PopulatesTarget[] | PopulatesTarget;
  /** Interview fields only. */
  item_label?: string;
  default_value?: string | number | boolean;
  reveal_when?: { field: string; equals: string | boolean };
  creates_scope?: string;
}

export interface SeedFormStep {
  step_id: string;
  order: number;
  label: string;
  description: string;
  repeatable: boolean;
  min_items?: number;
  datapoint_ids: string[];
  fields: SeedFormField[];
}

export interface SeedFormSchema {
  form_name: string;
  form_version: string;
  copy_status: string;
  copy_note: string;
  overlay_id: string | null;
  steps: SeedFormStep[];
}

export interface FieldError {
  field: string;
  message: string;
  index?: number;
}

/** A submission rejected by the server, carrying per-field messages. */
export class SeedFormError extends Error {
  readonly errors: FieldError[];

  constructor(errors: FieldError[]) {
    super(`${errors.length} validation error(s)`);
    this.name = "SeedFormError";
    this.errors = errors;
  }
}

export type FormValues = Record<string, string>;

export interface SeedFormSubmitResult {
  org: {
    org_id: string;
    legal_name: string;
    profile_status: string;
    reporting_period_start: string;
    reporting_period_end: string;
  };
  sites: Array<{ site_id: string; site_name: string; site_type: string; ownership: string }>;
  submission: {
    seed_profile_id: string;
    provisional_values: Array<{ field_id: string; value: string; requires_signoff: string }>;
  };
}

/** A question served by the interview engine (Phase C2). */
export interface InterviewQuestion {
  datapoint_id: string;
  state_id: string;
  scope_ref: string | null;
  scope_label: string | null;
  section: string;
  grain: string;
  escalation_class: "AUTO" | "HUMAN" | "SYSTEM";
  question: string;
  explainer: string;
  answer_shape: "yes_no" | "single_select" | "composite";
  fields: SeedFormField[];
  status: string;
  value: Record<string, unknown> | null;
  not_sure_allowed: boolean;
}

export interface CoverageSection {
  section_id: string;
  label: string;
  order: number;
  total: number;
  complete: number;
}

export interface Coverage {
  complete: number;
  total: number;
  escalated: number;
  remaining: number;
  is_complete: boolean;
  label: string;
  note: string;
  sections: CoverageSection[];
}

export interface InterviewStep {
  next: InterviewQuestion | null;
  coverage: Coverage;
}

export interface AnswerResult extends InterviewStep {
  status: string;
  escalated: boolean;
}

export interface NotSureResult extends InterviewStep {
  explainer: string;
  /** A second explanation, when a model was available to write one. */
  another_way: string | null;
  message: string;
}

export interface SeedFormAnswers {
  profile_status?: string;
  company: FormValues;
  sites: FormValues[];
}

/** The model's reading of a typed answer (Phase D1). Never written until confirmed. */
export interface ParseOutcome {
  status: "proposed" | "clarify" | "escalated";
  datapoint_id: string;
  scope_ref: string | null;
  proposal: Record<string, unknown>;
  summary: string | null;
  confidence: number | null;
  clarifying_question: string | null;
  unresolved: unknown[];
  dropped_fields: string[];
  message: string | null;
  attempts: number;
}

export interface ParseResponse {
  outcome: ParseOutcome;
  coverage: Coverage;
  next: InterviewQuestion | null;
}

/** One row in the reviewer queue (Phase D2). */
export interface QueueItem {
  escalation_id: string;
  org_id: string;
  client: string;
  site: string | null;
  datapoint_id: string;
  question: string;
  trigger: string;
  why: string | null;
  created_at: string;
  hours_open: number;
  past_sla: boolean;
  notified: boolean;
  reminded: boolean;
}

export interface ReviewQueue {
  count: number;
  sla_hours: number;
  items: QueueItem[];
}

export interface EscalationHistoryEntry {
  at: string;
  actor: string;
  field: string | null;
  from: unknown;
  to: unknown;
}

export interface EscalationAuditEntry {
  at: string;
  actor_id: string;
  action: string;
  note: string | null;
}

/** Everything a reviewer needs to answer one question (Phase D2). */
export interface EscalationDetail extends QueueItem {
  status: string;
  explainer: string | null;
  answer_fields: SeedFormField[];
  answer_shape: "yes_no" | "single_select" | "composite" | null;
  attempts: Array<Record<string, unknown>>;
  seed_context: Record<string, unknown>;
  current_value: Record<string, unknown> | null;
  resolution_value: Record<string, unknown> | null;
  resolution_note: string | null;
  audit_trail: EscalationAuditEntry[];
  history: EscalationHistoryEntry[];
}

export interface ResolveResult {
  escalation: Record<string, unknown>;
  queue_count: number;
}

/** The profile page: the client's living record (Phase E). */
export interface ProfileCompany {
  legal_name: string | null;
  reporting_year: number | null;
  reporting_period_start: string | null;
  reporting_period_end: string | null;
  fiscal_year_basis: string | null;
  industry: string | null;
  industry_overlay_id: string | null;
  responsible_party: { name: string; role: string; email: string } | null;
  profile_status: string | null;
  provisional_fields: string[];
  updated_at: string | null;
}

export interface ProfileSite {
  site_id: string;
  site_name: string | null;
  address: Record<string, string> | null;
  site_type: string | null;
  operational_status: string | null;
  ownership: string | null;
  lease_type: string | null;
  ownership_note: string | null;
  period_in_scope_start: string | null;
  period_in_scope_end: string | null;
  provisional_fields: string[];
  deferred_boundary_fields: Array<Record<string, unknown>>;
  updated_at: string | null;
}

export interface ProfileDatapoint {
  datapoint_id: string;
  label: string | null;
  question: string | null;
  section: string;
  class: "AUTO" | "HUMAN" | "SYSTEM";
  grain: string;
  scope_ref: string | null;
  scope_label: string | null;
  status: string;
  status_label: string;
  complete_for_client: boolean;
  value: Record<string, unknown> | null;
  answered_by: string | null;
  answered_by_label: string | null;
  actor_id: string | null;
  value_basis: string | null;
  note: string | null;
  uncertainty_tier: string | null;
  ai_assisted: boolean;
  provisional_fields: string[];
  evidence_triggered: string[];
  escalation_id: string | null;
  with_team_since: string | null;
  updated_at: string | null;
}

export interface ProfileSection {
  section_id: string;
  label: string;
  order: number;
  complete: number;
  total: number;
  datapoints: ProfileDatapoint[];
}

export interface ProfileExclusion {
  datapoint_id: string;
  scope_label: string | null;
  status: string;
  value: Record<string, unknown>;
  confirmed_by: string | null;
  actor_id: string | null;
  methodology_field: string;
  updated_at: string | null;
}

export interface ProfileProvisionalValue {
  scope: string;
  scope_label: string | null;
  field_id: string;
  requires_signoff: string;
}

export interface Profile {
  org_id: string;
  generated_at: string;
  company: ProfileCompany;
  sites: ProfileSite[];
  coverage: Coverage;
  sections: ProfileSection[];
  boundary_decisions: ProfileDatapoint[];
  completeness_records: ProfileDatapoint[];
  exclusions: ProfileExclusion[];
  uncertainty: Array<{
    datapoint_id: string;
    label: string | null;
    scope_label: string | null;
    value_basis: string | null;
    uncertainty_tier: string | null;
  }>;
  with_the_team: ProfileDatapoint[];
  provisional_values: ProfileProvisionalValue[];
}

export interface ProfileHistoryEntry {
  at: string;
  action: string;
  entity_type: string;
  entity_id: string;
  datapoint_id: string | null;
  label: string | null;
  scope_ref: string | null;
  scope_label: string | null;
  field: string | null;
  old_value: unknown;
  new_value: unknown;
  actor_id: string;
  actor_role: string | null;
  reason: string | null;
}

export interface ProfileHistory {
  org_id: string;
  count: number;
  returned: number;
  entries: ProfileHistoryEntry[];
}
