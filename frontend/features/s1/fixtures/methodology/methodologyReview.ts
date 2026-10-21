import type { MethodologyStated, MethodologyState } from "../../types/methodology";

/**
 * Cascade Provisions' methodology as its 2025 GHG report states it (demo). Values
 * from the Methodology review mockup (product, 2026-10-19).
 */
export const methodologyStated: MethodologyStated = {
  reportingPeriod: { id: "period", label: "Reporting period", value: "2025-01-01 to 2025-12-31" },
  approach: "Operational Control",
  entities: [
    {
      id: "cp",
      name: "Cascade Provisions Co.",
      facilities: ["Kent Cannery", "Modesto Bottling"],
      equityShare: 100,
      financialControl: 100,
      operationalControl: "Yes",
    },
    {
      id: "td",
      name: "Cascade Provisions Oregon LLC",
      facilities: ["Tualatin Plant"],
      equityShare: 100,
      financialControl: 100,
      operationalControl: "Yes",
    },
    {
      id: "sc",
      name: "Stockton Cold Storage JV",
      facilities: ["Stockton cold storage"],
      equityShare: 50,
      financialControl: 50,
      operationalControl: "No",
      notes: {
        "Financial Control": "Joint financial control: equity share applies",
        "Operational Control": "Not operated by Cascade Provisions",
      },
    },
  ],
  categories: {
    scope1: [
      { id: "s1sc", name: "Stationary Combustion", value: "Yes" },
      { id: "s1mc", name: "Mobile Combustion", value: "Yes" },
      { id: "s1pe", name: "Process Emissions", value: "Not detected" },
      { id: "s1fe", name: "Fugitive Emissions", value: "Yes" },
    ],
    location: [
      { id: "lbe", name: "Purchased Electricity", value: "Yes" },
      { id: "lbh", name: "Purchased Heating", value: "Yes" },
      { id: "lbs", name: "Purchased Steam", value: "Yes" },
      { id: "lbc", name: "Purchased Cooling", value: "Not detected" },
    ],
    market: [
      { id: "mbe", name: "Purchased Electricity", value: "Yes" },
      { id: "mbh", name: "Purchased Heating", value: "Yes" },
      { id: "mbs", name: "Purchased Steam", value: "Yes" },
      { id: "mbc", name: "Purchased Cooling", value: "Not detected" },
    ],
    biogenic: [
      { id: "bd", name: "Direct Biogenic", value: "No" },
      { id: "bi", name: "Indirect Biogenic", value: "Not detected" },
    ],
  },
  exclusions: [
    {
      id: "exc1",
      label: "Excluded from organizational boundary",
      value: "Stockton cold storage joint venture, not operated by Cascade Provisions.",
      source: "GHG Report p. 4",
    },
    {
      id: "exc2",
      label: "Excluded from this inventory",
      value: "Backup diesel generators at Tualatin Plant; no fuel records for 2025.",
      source: "GHG Report p. 5",
    },
    { id: "exc3", label: "Excluded under the materiality threshold", value: "" },
  ],
  calculation: [
    {
      id: "calc1",
      label: "Calculation approach",
      value:
        "Activity data × emission factor. Stationary fuel from utility bills; mobile fuel from fleet fuel cards, with fleet mileage for CH₄ and N₂O; refrigerant from service records (quantity recharged × GWP); electricity, heat and steam from utility and supplier bills. Tualatin Plant PPA applied to market-based electricity; other sites use the eGRID subregion rate.",
      source: "CARB template, Methods",
    },
    { id: "calc2", label: "Process-specific calculations", value: "" },
  ],
  factors: {
    scope1: [
      { id: "s1a", database: "EPA GHG Emission Factors Hub", edition: "2025", identifiedBy: "Stated by company, confirmed by system match" },
    ],
    scope2: [
      { id: "s2a", database: "EPA eGRID", edition: "eGRID2023", identifiedBy: "Stated by company", flag: "Mismatch", pair: "egrid" },
      { id: "s2b", database: "EPA eGRID", edition: "eGRID2021", identifiedBy: "Matched by system", flag: "Mismatch", pair: "egrid" },
      { id: "s2c", database: "EPA GHG Emission Factors Hub", edition: "2025", identifiedBy: "Stated by company, confirmed by system match" },
      { id: "s2d", database: "Heat supplier emission factor statement (Tualatin Plant)", edition: "2023", identifiedBy: "Provided by company" },
    ],
  },
  gwp: { set: "IPCC Fifth Assessment Report (AR5)", horizon: "100-year", identifiedBy: "Matched by system" },
};

export function emptyMethodologyReview(): MethodologyState {
  return { approach: null, entityValues: {}, entityReviews: {}, texts: {}, categories: {}, factors: null, gwp: null, log: [] };
}
