export type RequirementLevel = "Core" | "Core-derived" | "Recommended";

export interface ManualEntryFieldDefinition {
  fieldKey: string;
  fieldLabel: string;
  requirementLevel: RequirementLevel;
  valueOrigin: "extracted";
}

const requirementOrder: Record<RequirementLevel, number> = {
  Core: 0,
  "Core-derived": 1,
  Recommended: 2,
};

export const manualEntryFieldsByType: Record<string, ManualEntryFieldDefinition[]> = {
  "Electric utility bill": [
    {
      fieldKey: "CT-S2-ELECBILL::account_number",
      fieldLabel: "Account number",
      requirementLevel: "Core",
      valueOrigin: "extracted",
    },
    {
      fieldKey: "CT-S2-ELECBILL::service_address",
      fieldLabel: "Service address",
      requirementLevel: "Core",
      valueOrigin: "extracted",
    },
    {
      fieldKey: "CT-S2-ELECBILL::billing_period",
      fieldLabel: "Billing period",
      requirementLevel: "Core",
      valueOrigin: "extracted",
    },
    {
      fieldKey: "CT-S2-ELECBILL::consumption_kwh",
      fieldLabel: "Electricity consumed",
      requirementLevel: "Core",
      valueOrigin: "extracted",
    },
    {
      fieldKey: "CT-S2-ELECBILL::unit",
      fieldLabel: "Consumption unit",
      requirementLevel: "Core-derived",
      valueOrigin: "extracted",
    },
    {
      fieldKey: "CT-S2-ELECBILL::meter_number",
      fieldLabel: "Meter number",
      requirementLevel: "Recommended",
      valueOrigin: "extracted",
    },
    {
      fieldKey: "CT-S2-ELECBILL::supplier_name",
      fieldLabel: "Supplier name",
      requirementLevel: "Recommended",
      valueOrigin: "extracted",
    },
  ],
};

export function manualEntryFieldsForType(typeName: string | null | undefined): ManualEntryFieldDefinition[] {
  return [...(typeName ? manualEntryFieldsByType[typeName] ?? [] : [])].sort(
    (left, right) => requirementOrder[left.requirementLevel] - requirementOrder[right.requirementLevel]
  );
}
