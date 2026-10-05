export type ProcessingState =
  | "not_ingested"
  | "ingested"
  | "typed"
  | "extracted"
  | "blocked";

export type TypeReviewBand = "auto_accepted" | "needs_review" | "cannot_determine" | null;

export type FacilityState =
  | "resolved"
  | "unresolved"
  | "multiple"
  | "not_facility_scoped";

export type PeriodState = "resolved" | "unresolved" | "spans_multiple";

export type FieldState =
  | "populated"
  | "missing_requestable"
  | "missing_not_requestable"
  | "system_key"
  | "not_applicable";

export type ReviewStatus =
  | "unreviewed"
  | "accepted"
  | "corrected"
  | "keyed_by_reviewer";

export type ValueProperty =
  | "estimated_read"
  | "unit_missing"
  | "unit_ambiguous"
  | "format_mismatch";

export type ContainerState =
  | "populated"
  | "empty_nothing_yet"
  | "empty_filtered"
  | "loading"
  | "error_degraded"
  | "dependency_blocked";

export type StateDimension =
  | "processing"
  | "facilityResolution"
  | "periodResolution"
  | "field"
  | "valueProperty"
  | "check"
  | "review"
  | "readiness"
  | "disposition"
  | "request";

export type EvidenceDisposition = "active" | "withdrawn";
