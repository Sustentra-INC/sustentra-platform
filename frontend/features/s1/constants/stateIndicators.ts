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
    populated: "active",
    missing_requestable: "open",
    missing_not_requestable: "unverifiable",
    system_key: "na",
    not_applicable: "na",
  },
  valueProperty: {
    estimated_read: "open",
    unit_missing: "open",
    unit_ambiguous: "open",
    format_mismatch: "open",
  },
  review: {
    unreviewed: "na",
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
    passed: "resolved",
    failed: "blocking",
    not_evaluable: "unverifiable",
  },
  disposition: {
    active: "na",
    withdrawn: "na",
  },
  request: {
    requested: "active",
    fulfilled: "resolved",
    cancelled: "na",
    waived_below_threshold: "unverifiable",
  },
};
