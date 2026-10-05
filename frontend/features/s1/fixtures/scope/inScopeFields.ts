import type { InScopeField } from "../../types/scope";

/**
 * PLACEHOLDER in-scope data points. The real field list is still being defined
 * by product · these rows exist only to fix the shape (methodologyFieldId +
 * completenessStatus slot) and to let the flow be walked. Every row is marked
 * placeholder in the UI; none of these ids are canonical.
 */
export const inScopeFieldPlaceholders: InScopeField[] = [
  { methodologyFieldId: "MF-PLH-electricity-consumed-scope2_location", label: "Electricity consumed (location-based)", layer: "scope2", requirementLevel: "Core", valueOrigin: "extracted", inScope: true, completenessStatus: null },
  { methodologyFieldId: "MF-PLH-electricity-consumed-scope2_market", label: "Electricity consumed (market-based)", layer: "scope2", requirementLevel: "Core", valueOrigin: "extracted", inScope: true, completenessStatus: null },
  { methodologyFieldId: "MF-PLH-natural-gas-consumed", label: "Natural gas consumed", layer: "scope1", requirementLevel: "Core", valueOrigin: "extracted", inScope: true, completenessStatus: null },
  { methodologyFieldId: "MF-PLH-diesel-purchased-fleet", label: "Diesel purchased · plant fleet", layer: "scope1", requirementLevel: "Core", valueOrigin: "extracted", inScope: true, completenessStatus: null },
  { methodologyFieldId: "MF-PLH-refrigerant-added", label: "Refrigerant added on service", layer: "scope1", requirementLevel: "Conditional", valueOrigin: "extracted", inScope: true, completenessStatus: null },
  { methodologyFieldId: "MF-PLH-organizational-boundary-approach", label: "Organizational boundary approach", layer: "general", requirementLevel: "Core", valueOrigin: "verifier_determined", inScope: true, completenessStatus: null },
  { methodologyFieldId: "MF-PLH-grid-emission-factor", label: "Grid emission factor cited", layer: "general", requirementLevel: "Core", valueOrigin: "assigned", inScope: true, completenessStatus: null },
  { methodologyFieldId: "MF-PLH-mobile-combustion-gasoline", label: "Gasoline purchased · mobile combustion", layer: "scope1", requirementLevel: "Conditional", valueOrigin: "extracted", inScope: false, completenessStatus: null },
];
