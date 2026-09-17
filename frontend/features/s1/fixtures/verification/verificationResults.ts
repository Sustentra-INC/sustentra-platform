import type { VerificationRow } from "../../types/verification";

/**
 * Verification results rows (fixture). Only the Scope 1 stationary-combustion
 * fuel-based path is recomputed (the one real backend path); everything else
 * reads "not recomputed" with a reason, never a blank. Check outcomes are honest:
 * where nothing was evaluated, they say "could not check".
 */
export const verificationRows: VerificationRow[] = [
  // General
  {
    dataPointId: "DP-BOUNDARY",
    methodologyFieldId: "MF-PLH-organizational-boundary-approach",
    label: "Organizational boundary approach",
    layer: "general",
    reportedValue: "Operational control",
    unit: "",
    recomputed: null,
    recomputeReason: "narrative field — not recomputable",
    delta: null,
    checkOutcome: "could_not_check",
    checkReason: "Rule evaluation not implemented.",
  },

  // Scope 1 — the recomputed path
  {
    dataPointId: "DP-GAS-TUALATIN",
    methodologyFieldId: "MF-PLH-natural-gas-consumed",
    label: "Stationary combustion — natural gas · Tualatin Plant",
    layer: "scope1",
    facilityName: "Tualatin Plant",
    reportedValue: "1,812",
    unit: "tCO₂e",
    recomputed: "1,798",
    delta: "+0.8%",
    checkOutcome: "held",
    checkReason: "Fuel-based recompute within tolerance.",
  },
  {
    dataPointId: "DP-GAS-KENT",
    methodologyFieldId: "MF-PLH-natural-gas-consumed",
    label: "Stationary combustion — natural gas · Kent Cannery",
    layer: "scope1",
    facilityName: "Kent Cannery",
    reportedValue: "1,540",
    unit: "tCO₂e",
    recomputed: "1,705",
    delta: "+10.7%",
    checkOutcome: "exception",
    checkReason: "Fuel-based recompute exceeds tolerance.",
  },
  {
    dataPointId: "DP-DIESEL-FLEET",
    methodologyFieldId: "MF-PLH-diesel-purchased-fleet",
    label: "Mobile combustion — diesel · plant fleet",
    layer: "scope1",
    reportedValue: "260",
    unit: "tCO₂e",
    recomputed: null,
    recomputeReason: "recompute path not implemented for mobile combustion",
    delta: null,
    checkOutcome: "could_not_check",
    checkReason: "No recompute path; rule evaluation not implemented.",
  },
  {
    dataPointId: "DP-REFRIGERANT",
    methodologyFieldId: "MF-PLH-refrigerant-added",
    label: "Fugitive — refrigerant R-404A",
    layer: "scope1",
    reportedValue: "48",
    unit: "tCO₂e",
    recomputed: null,
    recomputeReason: "recompute path not implemented for fugitive emissions",
    delta: null,
    checkOutcome: "could_not_check",
    checkReason: "No recompute path.",
  },

  // Scope 2 — always two rows
  {
    dataPointId: "DP-ELEC-LOC",
    methodologyFieldId: "MF-PLH-electricity-consumed-scope2_location",
    label: "Purchased electricity",
    layer: "scope2",
    scopeBasis: "location",
    reportedValue: "9,880",
    unit: "tCO₂e",
    recomputed: null,
    recomputeReason: "recompute path not implemented for Scope 2",
    delta: null,
    checkOutcome: "could_not_check",
    checkReason: "No recompute path; rule evaluation not implemented.",
  },
  {
    dataPointId: "DP-ELEC-MKT",
    methodologyFieldId: "MF-PLH-electricity-consumed-scope2_market",
    label: "Purchased electricity",
    layer: "scope2",
    scopeBasis: "market",
    reportedValue: "7,410",
    unit: "tCO₂e",
    recomputed: null,
    recomputeReason: "recompute path not implemented for Scope 2",
    delta: null,
    checkOutcome: "could_not_check",
    checkReason: "Market-based factor documentation missing for Modesto Bottling.",
  },
];
