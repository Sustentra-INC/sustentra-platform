/**
 * Setup's in-scope data-point model. The actual field list is still being
 * defined by product, so these rows are placeholders — but the SHAPE is fixed
 * now so nothing has to be retrofitted:
 *
 *  - `methodologyFieldId` is carried on every row (fold 2): it is the id the
 *    backend's MethodologyValue keys off, minted by Extraction Review's Accept.
 *  - `completenessStatus` has a home on every row (fold 1) so the completeness
 *    tracker's per-field status can land here when product decides to surface
 *    it. It stays null until then; Setup does not compute it.
 */

/** Mirrors the backend completeness tracker's statuses (see docs/verificationContracts.ts). */
export type CompletenessStatus =
  | "complete"
  | "missing_required"
  | "not_applicable"
  | "provisional_condition_unknown"
  | "not_requestable_value_origin";

export type ScopeLayer = "general" | "scope1" | "scope2";

export interface InScopeField {
  /** The S1->S2 handoff id. Placeholder until the real field list arrives. */
  methodologyFieldId: string;
  /** Plain-words label (placeholder). */
  label: string;
  layer: ScopeLayer;
  /** e.g. "Core" | "Conditional"; null while unknown. */
  requirementLevel: string | null;
  valueOrigin: string | null;
  /** Whether this data point is in scope for the engagement. */
  inScope: boolean;
  /** Reserved for the completeness tracker's status; not populated in Setup. */
  completenessStatus: CompletenessStatus | null;
}
