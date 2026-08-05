import type { StateDimension } from "../types";

export type StateRole =
  | "blocking"
  | "open"
  | "resolved"
  | "active"
  | "unverifiable"
  | "na";

export const STATE_ROLE_BY_PAIR: Partial<Record<StateDimension, Record<string, StateRole>>> = {
  processing: {
    not_ingested: "active",
    ingested: "active",
    typed: "active",
    extracted: "active",
    blocked: "blocking",
  },
  facilityResolution: {
    resolved: "resolved",
    unresolved: "open",
    multiple: "unverifiable",
    not_facility_scoped: "na",
  },
  periodResolution: {
    resolved: "resolved",
    unresolved: "open",
    spans_multiple: "unverifiable",
  },
  field: {
    populated: "resolved",
    missing_requestable: "open",
  },
  valueProperty: {
    estimated_read: "open",
    unit_missing: "open",
    unit_ambiguous: "open",
    format_mismatch: "open",
  },
  review: {
    unreviewed: "open",
    accepted: "resolved",
    corrected: "resolved",
    keyed_by_reviewer: "resolved",
  },
  readiness: {
    "non-blocking": "open",
    blocking: "blocking",
  },
  check: {
    not_system_verified: "unverifiable",
    not_applicable: "na",
  },
};
