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
  message: string;
}

export interface SeedFormAnswers {
  profile_status?: string;
  company: FormValues;
  sites: FormValues[];
}
