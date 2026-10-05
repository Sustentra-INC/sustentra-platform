/**
 * Screens 5 (Check Coverage) and 6 (Verification results). Built to the spec's
 * paragraph-level detail, on fixtures. Two honesty constraints baked into the
 * types (from the backend study):
 *  - Coverage status states input readiness, NOT whether a rule ran — the engine
 *    does not evaluate rule expressions yet.
 *  - Examination state and next action are HUMAN dispositions, not backend
 *    fields; they live in a frontend store (verification/verificationStore).
 */

/* ---- Screen 5: Check Coverage ---- */
export type CoverageStatus = "inputs_present" | "inputs_missing" | "not_applicable" | "out_of_scope";

export interface CoverageRule {
  ruleId: string;
  /** What it checks, in plain words. */
  assertion: string;
  /** Data points it applies to, as labels. */
  appliesTo: string[];
  status: CoverageStatus;
  reason: string;
}

/* ---- Screen 6: Verification results ---- */
export type ResultLayer = "general" | "scope1" | "scope2";
export type CheckOutcome = "held" | "exception" | "could_not_check" | "out_of_scope";

export interface VerificationRow {
  dataPointId: string;
  methodologyFieldId: string;
  label: string;
  layer: ResultLayer;
  /** Scope 2 is always two rows. */
  scopeBasis?: "location" | "market";
  facilityName?: string | null;
  reportedValue: string;
  unit: string;
  /** null → not recomputed; recomputeReason says why. */
  recomputed: string | null;
  recomputeReason?: string;
  delta: string | null;
  checkOutcome: CheckOutcome;
  checkReason: string;
}

/* ---- Frontend-owned dispositions ---- */
export type ExaminationState = "not_examined" | "examined_no_exceptions" | "finding_raised";
export type NextActionWith = "me" | "client" | "none";

export interface Examination {
  examinationState: ExaminationState;
  nextActionWith: NextActionWith;
}

export interface Finding {
  id: string;
  dataPointId: string;
  dataPointLabel: string;
  /** Frontend-authored: the verifier writes the sentence. */
  sentence: string;
  cause: string;
  /** Frontend-authored / from delta — not in the backend gap record. */
  magnitude: string;
  status: string;
  /** Request-linked (the sent date of the linked ask); null until linked. */
  withClientSince: string | null;
}
