/**
 * Methodology review: what the client's GHG report states about its inventory boundary
 * and methods, and the verifier's review of it. The stated values are fixed; the
 * verifier's acceptances and changes are kept beside them, so each change can be
 * shown with who made it, when, and reverted to what was stated.
 */

export const BOUNDARY_APPROACHES = ["Equity Share", "Financial Control", "Operational Control"] as const;
export type BoundaryApproach = (typeof BOUNDARY_APPROACHES)[number];

export const INCLUSIONS = ["Yes", "No", "Not detected"] as const;
export type Inclusion = (typeof INCLUSIONS)[number];

/** One legal entity of the organizational boundary and its facilities. */
export interface StatedEntity {
  id: string;
  name: string;
  facilities: string[];
  /** Percent, 0 to 100. */
  equityShare: number;
  /** Percent consolidated under financial control. */
  financialControl: number;
  operationalControl: "Yes" | "No";
  /** A line under the entity's name, per approach. */
  notes?: Partial<Record<BoundaryApproach, string>>;
}

/** A free-text item read from the report, with where it was read. */
export interface StatedText {
  id: string;
  label: string;
  /** "" when the report does not state it ("Not detected"). */
  value: string;
  source?: string;
}

export interface StatedCategory {
  id: string;
  name: string;
  value: Inclusion;
}

/** A database the emission factors were taken from. */
export interface FactorSource {
  id: string;
  database: string;
  edition: string;
  identifiedBy: string;
  /** "Mismatch" when the report and the workbook name different editions. */
  flag?: string;
  /** Rows of one mismatch share a pair: resolving either one resolves it. */
  pair?: string;
}

export interface GwpSource {
  set: string;
  horizon: string;
  identifiedBy: string;
}

export interface MethodologyStated {
  reportingPeriod: StatedText;
  approach: BoundaryApproach;
  entities: StatedEntity[];
  categories: { scope1: StatedCategory[]; location: StatedCategory[]; market: StatedCategory[]; biogenic: StatedCategory[] };
  exclusions: StatedText[];
  calculation: StatedText[];
  factors: { scope1: FactorSource[]; scope2: FactorSource[] };
  gwp: GwpSource;
}

/** A value the verifier changed: the value, when and by whom. */
export interface VerifierEdit<T> {
  value: T;
  at: string;
  by: string;
}

/** A factor source as it stands after review. */
export interface FactorRow extends FactorSource {
  /** The other row of a mismatch the verifier resolved. */
  hidden?: boolean;
  /** Added by the verifier, not stated. */
  added?: boolean;
  /** What was stated, once the verifier set the row; Revert restores it. */
  original?: FactorSource;
  at?: string;
  by?: string;
}

export type FactorScope = "scope1" | "scope2";

export interface MethodologyState {
  approach: VerifierEdit<BoundaryApproach> | null;
  /** Keyed `${approach}:${entityId}`: "Yes"/"No", or a percent as typed. */
  entityValues: Record<string, string>;
  entityReviews: Record<string, true>;
  texts: Record<string, VerifierEdit<string>>;
  categories: Record<string, VerifierEdit<Inclusion>>;
  /** null until the verifier changes a factor source. */
  factors: Record<FactorScope, FactorRow[]> | null;
  gwp: VerifierEdit<{ set: string; horizon: string }> | null;
  /** Each change, for the activity log. */
  log: { at: string; who: string; what: string }[];
}
