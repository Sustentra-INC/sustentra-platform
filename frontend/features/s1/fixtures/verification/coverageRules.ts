import type { CoverageRule } from "../../types/verification";

/**
 * Check Coverage rules (fixture). Status reflects INPUT READINESS only · the
 * engine does not evaluate rule expressions yet, so no status claims a rule
 * "ran" or "passed". The screen states this in a banner.
 */
export const coverageRules: CoverageRule[] = [
  {
    ruleId: "COV-GAS-COMPLETE",
    assertion: "Natural gas consumption is present for every reporting month",
    appliesTo: ["Natural gas consumed"],
    status: "inputs_missing",
    reason: "September service-period end date not found for Kent Cannery.",
  },
  {
    ruleId: "COV-S2-BOTH-BASES",
    assertion: "Scope 2 electricity is present on both a location and a market basis",
    appliesTo: ["Electricity consumed (location-based)", "Electricity consumed (market-based)"],
    status: "inputs_missing",
    reason: "Market-based factor documentation missing for Modesto Bottling.",
  },
  {
    ruleId: "COV-MOBILE-FUEL",
    assertion: "Mobile combustion fuel is present for the fleet",
    appliesTo: ["Gasoline purchased · mobile combustion"],
    status: "inputs_missing",
    reason: "No mobile-combustion fuel records have been accepted.",
  },
  {
    ruleId: "COV-REFRIGERANT-TOL",
    assertion: "Refrigerant leakage is within service tolerance",
    appliesTo: ["Refrigerant added on service"],
    status: "not_applicable",
    reason: "Condition not met · two facilities have no refrigerant systems in scope.",
  },
  {
    ruleId: "COV-SCOPE3-CAT1",
    assertion: "Purchased-goods completeness (Scope 3, category 1)",
    appliesTo: ["Supplier annual spend"],
    status: "out_of_scope",
    reason: "Scope 3 is outside this engagement's boundary.",
  },
  {
    ruleId: "COV-ELEC-COMPLETE",
    assertion: "Electricity consumption is present for every reporting month",
    appliesTo: ["Electricity consumed (location-based)"],
    status: "inputs_present",
    reason: "All accepted; Tualatin's missing Feb–Mar were answered by request.",
  },
  {
    ruleId: "COV-GRID-FACTOR",
    assertion: "A grid emission factor source is recorded",
    appliesTo: ["Grid emission factor cited"],
    status: "inputs_present",
    reason: "Factor source accepted.",
  },
  {
    ruleId: "COV-BOUNDARY",
    assertion: "The organizational boundary approach is stated",
    appliesTo: ["Organizational boundary approach"],
    status: "inputs_present",
    reason: "Boundary statement accepted.",
  },
];
