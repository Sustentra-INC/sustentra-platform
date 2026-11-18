// Generated from the real backend roll-up layout (tests/fixtures/recalculationLive.json). Static structure only: no values.
import type { GasGroup, RollupSourceKey, RollupStep } from "../api/recalculation";

export interface LayoutNode { key: string; step: "step_1a" | "step_1b" | "step_2"; label: string; kind: "category" | "gas" | "total" | "memo"; scope: "scope1" | "scope2_location" | "scope2_market" | "inventory_location" | "inventory_market"; unit: string; formula: string; gas: GasGroup | null; terms: string[]; basis: "structural_zero" | null }
export interface LayoutCategory { key: RollupSourceKey; label: string; scope: "scope1" | "scope2"; workbook_row: number; built: boolean; backend_categories: Partial<Record<"location" | "market", string>>; gases: GasGroup[] }
export interface LayoutOutput { key: string; label: string; workbook_row: number; requirement: "Required" | "Optional"; node: string; measure: "co2e_t" | "mass_t" | null; unit: "t CO2e" | "t" | null }
export const LAYOUT_STEPS: RollupStep[] = [
 {
  "key": "step_1a",
  "label": "Step 1a \u00b7 Category results to Scope 1",
  "order": 1,
  "after": [],
  "node_keys": [
   "stationary_combustion_total",
   "mobile_combustion_total",
   "process_total",
   "fugitive_total",
   "agricultural_total",
   "scope1_co2",
   "scope1_ch4",
   "scope1_n2o",
   "scope1_hfcs",
   "scope1_pfcs",
   "scope1_sf6",
   "scope1_nf3",
   "scope1_total",
   "biogenic_co2"
  ]
 },
 {
  "key": "step_1b",
  "label": "Step 1b \u00b7 Category results to Scope 2 (location-based and market-based)",
  "order": 2,
  "after": [],
  "node_keys": [
   "purchased_electricity_total",
   "purchased_steam_total",
   "purchased_heating_total",
   "purchased_cooling_total",
   "scope2_location_total",
   "scope2_co2",
   "scope2_ch4",
   "scope2_n2o",
   "scope2_hfcs",
   "scope2_pfcs",
   "scope2_sf6",
   "scope2_nf3",
   "purchased_electricity_market_total",
   "purchased_steam_market_total",
   "purchased_heating_market_total",
   "purchased_cooling_market_total",
   "scope2_market_total",
   "scope2_market_co2",
   "scope2_market_ch4",
   "scope2_market_n2o",
   "scope2_market_hfcs",
   "scope2_market_pfcs",
   "scope2_market_sf6",
   "scope2_market_nf3"
  ]
 },
 {
  "key": "step_2",
  "label": "Step 2 \u00b7 Inventory totals",
  "order": 3,
  "after": [
   "step_1a",
   "step_1b"
  ],
  "node_keys": [
   "inventory_location_total",
   "inventory_market_total"
  ]
 }
];
export const LAYOUT_NODES: LayoutNode[] = [
 {
  "key": "stationary_combustion_total",
  "step": "step_1a",
  "label": "Direct emissions from stationary combustion",
  "kind": "category",
  "scope": "scope1",
  "unit": "t CO2e",
  "formula": "stationary_combustion",
  "gas": null,
  "terms": [
   "category:stationary_combustion"
  ],
  "basis": null
 },
 {
  "key": "mobile_combustion_total",
  "step": "step_1a",
  "label": "Direct emissions from mobile combustion",
  "kind": "category",
  "scope": "scope1",
  "unit": "t CO2e",
  "formula": "mobile_combustion",
  "gas": null,
  "terms": [
   "category:mobile_combustion"
  ],
  "basis": null
 },
 {
  "key": "process_total",
  "step": "step_1a",
  "label": "Direct emissions from process sources",
  "kind": "category",
  "scope": "scope1",
  "unit": "t CO2e",
  "formula": "process_sources",
  "gas": null,
  "terms": [
   "category:process_sources"
  ],
  "basis": null
 },
 {
  "key": "fugitive_total",
  "step": "step_1a",
  "label": "Direct emissions from fugitive sources",
  "kind": "category",
  "scope": "scope1",
  "unit": "t CO2e",
  "formula": "fugitive_refrigerants + fugitive_purchased_gases",
  "gas": null,
  "terms": [
   "category:fugitive_refrigerants",
   "category:fugitive_purchased_gases"
  ],
  "basis": null
 },
 {
  "key": "agricultural_total",
  "step": "step_1a",
  "label": "Direct emissions from agricultural sources",
  "kind": "category",
  "scope": "scope1",
  "unit": "t CO2e",
  "formula": "agricultural_sources",
  "gas": null,
  "terms": [
   "category:agricultural_sources"
  ],
  "basis": null
 },
 {
  "key": "scope1_co2",
  "step": "step_1a",
  "label": "Scope 1 CO2",
  "kind": "gas",
  "scope": "scope1",
  "unit": "t and t CO2e",
  "formula": "sum of CO2 over Scope 1 sources",
  "gas": "CO2",
  "terms": [
   "category:stationary_combustion",
   "category:mobile_combustion",
   "category:process_sources",
   "category:fugitive_refrigerants",
   "category:fugitive_purchased_gases",
   "category:agricultural_sources"
  ],
  "basis": null
 },
 {
  "key": "scope1_ch4",
  "step": "step_1a",
  "label": "Scope 1 CH4",
  "kind": "gas",
  "scope": "scope1",
  "unit": "t and t CO2e",
  "formula": "sum of CH4 over Scope 1 sources",
  "gas": "CH4",
  "terms": [
   "category:stationary_combustion",
   "category:mobile_combustion",
   "category:process_sources",
   "category:fugitive_purchased_gases",
   "category:agricultural_sources"
  ],
  "basis": null
 },
 {
  "key": "scope1_n2o",
  "step": "step_1a",
  "label": "Scope 1 N2O",
  "kind": "gas",
  "scope": "scope1",
  "unit": "t and t CO2e",
  "formula": "sum of N2O over Scope 1 sources",
  "gas": "N2O",
  "terms": [
   "category:stationary_combustion",
   "category:mobile_combustion",
   "category:process_sources",
   "category:fugitive_purchased_gases",
   "category:agricultural_sources"
  ],
  "basis": null
 },
 {
  "key": "scope1_hfcs",
  "step": "step_1a",
  "label": "Scope 1 HFCs",
  "kind": "gas",
  "scope": "scope1",
  "unit": "t and t CO2e",
  "formula": "sum of HFCs over Scope 1 sources",
  "gas": "HFCs",
  "terms": [
   "category:process_sources",
   "category:fugitive_refrigerants",
   "category:fugitive_purchased_gases"
  ],
  "basis": null
 },
 {
  "key": "scope1_pfcs",
  "step": "step_1a",
  "label": "Scope 1 PFCs",
  "kind": "gas",
  "scope": "scope1",
  "unit": "t and t CO2e",
  "formula": "sum of PFCs over Scope 1 sources",
  "gas": "PFCs",
  "terms": [
   "category:process_sources",
   "category:fugitive_refrigerants",
   "category:fugitive_purchased_gases"
  ],
  "basis": null
 },
 {
  "key": "scope1_sf6",
  "step": "step_1a",
  "label": "Scope 1 SF6",
  "kind": "gas",
  "scope": "scope1",
  "unit": "t and t CO2e",
  "formula": "sum of SF6 over Scope 1 sources",
  "gas": "SF6",
  "terms": [
   "category:process_sources",
   "category:fugitive_refrigerants",
   "category:fugitive_purchased_gases"
  ],
  "basis": null
 },
 {
  "key": "scope1_nf3",
  "step": "step_1a",
  "label": "Scope 1 NF3",
  "kind": "gas",
  "scope": "scope1",
  "unit": "t and t CO2e",
  "formula": "sum of NF3 over Scope 1 sources",
  "gas": "NF3",
  "terms": [
   "category:process_sources",
   "category:fugitive_refrigerants",
   "category:fugitive_purchased_gases"
  ],
  "basis": null
 },
 {
  "key": "scope1_total",
  "step": "step_1a",
  "label": "Scope 1 (Total)",
  "kind": "total",
  "scope": "scope1",
  "unit": "t CO2e",
  "formula": "stationary_combustion_total + mobile_combustion_total + process_total + fugitive_total + agricultural_total",
  "gas": null,
  "terms": [
   "node:stationary_combustion_total",
   "node:mobile_combustion_total",
   "node:process_total",
   "node:fugitive_total",
   "node:agricultural_total"
  ],
  "basis": null
 },
 {
  "key": "biogenic_co2",
  "step": "step_1a",
  "label": "CO2 emissions from biogenic combustion",
  "kind": "memo",
  "scope": "scope1",
  "unit": "t CO2e",
  "formula": "biogenic CO2 of stationary + mobile combustion (reported separately, in no total; a placeholder until its calculation is agreed)",
  "gas": null,
  "terms": [],
  "basis": null
 },
 {
  "key": "purchased_electricity_total",
  "step": "step_1b",
  "label": "Indirect emissions from purchased electricity (location-based)",
  "kind": "category",
  "scope": "scope2_location",
  "unit": "t CO2e",
  "formula": "purchased_electricity",
  "gas": null,
  "terms": [
   "category:purchased_electricity"
  ],
  "basis": null
 },
 {
  "key": "purchased_steam_total",
  "step": "step_1b",
  "label": "Indirect emissions from purchased steam",
  "kind": "category",
  "scope": "scope2_location",
  "unit": "t CO2e",
  "formula": "purchased_steam",
  "gas": null,
  "terms": [
   "category:purchased_steam"
  ],
  "basis": null
 },
 {
  "key": "purchased_heating_total",
  "step": "step_1b",
  "label": "Indirect emissions from purchased heating",
  "kind": "category",
  "scope": "scope2_location",
  "unit": "t CO2e",
  "formula": "purchased_heating",
  "gas": null,
  "terms": [
   "category:purchased_heating"
  ],
  "basis": null
 },
 {
  "key": "purchased_cooling_total",
  "step": "step_1b",
  "label": "Indirect emissions from purchased cooling",
  "kind": "category",
  "scope": "scope2_location",
  "unit": "t CO2e",
  "formula": "purchased_cooling",
  "gas": null,
  "terms": [
   "category:purchased_cooling"
  ],
  "basis": null
 },
 {
  "key": "scope2_location_total",
  "step": "step_1b",
  "label": "Scope 2 (Total), location-based",
  "kind": "total",
  "scope": "scope2_location",
  "unit": "t CO2e",
  "formula": "purchased_electricity_total + purchased_steam_total + purchased_heating_total + purchased_cooling_total",
  "gas": null,
  "terms": [
   "node:purchased_electricity_total",
   "node:purchased_steam_total",
   "node:purchased_heating_total",
   "node:purchased_cooling_total"
  ],
  "basis": null
 },
 {
  "key": "scope2_co2",
  "step": "step_1b",
  "label": "Scope 2 CO2 (location-based)",
  "kind": "gas",
  "scope": "scope2_location",
  "unit": "t and t CO2e",
  "formula": "sum of CO2 over Scope 2 sources",
  "gas": "CO2",
  "terms": [
   "category:purchased_electricity",
   "category:purchased_steam",
   "category:purchased_heating",
   "category:purchased_cooling"
  ],
  "basis": null
 },
 {
  "key": "scope2_ch4",
  "step": "step_1b",
  "label": "Scope 2 CH4 (location-based)",
  "kind": "gas",
  "scope": "scope2_location",
  "unit": "t and t CO2e",
  "formula": "sum of CH4 over Scope 2 sources",
  "gas": "CH4",
  "terms": [
   "category:purchased_electricity",
   "category:purchased_steam",
   "category:purchased_heating",
   "category:purchased_cooling"
  ],
  "basis": null
 },
 {
  "key": "scope2_n2o",
  "step": "step_1b",
  "label": "Scope 2 N2O (location-based)",
  "kind": "gas",
  "scope": "scope2_location",
  "unit": "t and t CO2e",
  "formula": "sum of N2O over Scope 2 sources",
  "gas": "N2O",
  "terms": [
   "category:purchased_electricity",
   "category:purchased_steam",
   "category:purchased_heating",
   "category:purchased_cooling"
  ],
  "basis": null
 },
 {
  "key": "scope2_hfcs",
  "step": "step_1b",
  "label": "Scope 2 HFCs (location-based)",
  "kind": "gas",
  "scope": "scope2_location",
  "unit": "t and t CO2e",
  "formula": "0: no Scope 2 method emits fluorinated gases",
  "gas": "HFCs",
  "terms": [],
  "basis": "structural_zero"
 },
 {
  "key": "scope2_pfcs",
  "step": "step_1b",
  "label": "Scope 2 PFCs (location-based)",
  "kind": "gas",
  "scope": "scope2_location",
  "unit": "t and t CO2e",
  "formula": "0: no Scope 2 method emits fluorinated gases",
  "gas": "PFCs",
  "terms": [],
  "basis": "structural_zero"
 },
 {
  "key": "scope2_sf6",
  "step": "step_1b",
  "label": "Scope 2 SF6 (location-based)",
  "kind": "gas",
  "scope": "scope2_location",
  "unit": "t and t CO2e",
  "formula": "0: no Scope 2 method emits fluorinated gases",
  "gas": "SF6",
  "terms": [],
  "basis": "structural_zero"
 },
 {
  "key": "scope2_nf3",
  "step": "step_1b",
  "label": "Scope 2 NF3 (location-based)",
  "kind": "gas",
  "scope": "scope2_location",
  "unit": "t and t CO2e",
  "formula": "0: no Scope 2 method emits fluorinated gases",
  "gas": "NF3",
  "terms": [],
  "basis": "structural_zero"
 },
 {
  "key": "purchased_electricity_market_total",
  "step": "step_1b",
  "label": "Indirect emissions from purchased electricity (market-based)",
  "kind": "category",
  "scope": "scope2_market",
  "unit": "t CO2e",
  "formula": "purchased_electricity",
  "gas": null,
  "terms": [
   "category:purchased_electricity"
  ],
  "basis": null
 },
 {
  "key": "purchased_steam_market_total",
  "step": "step_1b",
  "label": "Indirect emissions from purchased steam (market-based)",
  "kind": "category",
  "scope": "scope2_market",
  "unit": "t CO2e",
  "formula": "purchased_steam",
  "gas": null,
  "terms": [
   "category:purchased_steam"
  ],
  "basis": null
 },
 {
  "key": "purchased_heating_market_total",
  "step": "step_1b",
  "label": "Indirect emissions from purchased heating (market-based)",
  "kind": "category",
  "scope": "scope2_market",
  "unit": "t CO2e",
  "formula": "purchased_heating",
  "gas": null,
  "terms": [
   "category:purchased_heating"
  ],
  "basis": null
 },
 {
  "key": "purchased_cooling_market_total",
  "step": "step_1b",
  "label": "Indirect emissions from purchased cooling (market-based)",
  "kind": "category",
  "scope": "scope2_market",
  "unit": "t CO2e",
  "formula": "purchased_cooling",
  "gas": null,
  "terms": [
   "category:purchased_cooling"
  ],
  "basis": null
 },
 {
  "key": "scope2_market_total",
  "step": "step_1b",
  "label": "Scope 2 (Total), market-based",
  "kind": "total",
  "scope": "scope2_market",
  "unit": "t CO2e",
  "formula": "purchased_electricity_market_total + purchased_steam_market_total + purchased_heating_market_total + purchased_cooling_market_total",
  "gas": null,
  "terms": [
   "node:purchased_electricity_market_total",
   "node:purchased_steam_market_total",
   "node:purchased_heating_market_total",
   "node:purchased_cooling_market_total"
  ],
  "basis": null
 },
 {
  "key": "scope2_market_co2",
  "step": "step_1b",
  "label": "Scope 2 CO2 (market-based)",
  "kind": "gas",
  "scope": "scope2_market",
  "unit": "t and t CO2e",
  "formula": "sum of CO2 over Scope 2 sources",
  "gas": "CO2",
  "terms": [
   "category:purchased_electricity",
   "category:purchased_steam",
   "category:purchased_heating",
   "category:purchased_cooling"
  ],
  "basis": null
 },
 {
  "key": "scope2_market_ch4",
  "step": "step_1b",
  "label": "Scope 2 CH4 (market-based)",
  "kind": "gas",
  "scope": "scope2_market",
  "unit": "t and t CO2e",
  "formula": "sum of CH4 over Scope 2 sources",
  "gas": "CH4",
  "terms": [
   "category:purchased_electricity",
   "category:purchased_steam",
   "category:purchased_heating",
   "category:purchased_cooling"
  ],
  "basis": null
 },
 {
  "key": "scope2_market_n2o",
  "step": "step_1b",
  "label": "Scope 2 N2O (market-based)",
  "kind": "gas",
  "scope": "scope2_market",
  "unit": "t and t CO2e",
  "formula": "sum of N2O over Scope 2 sources",
  "gas": "N2O",
  "terms": [
   "category:purchased_electricity",
   "category:purchased_steam",
   "category:purchased_heating",
   "category:purchased_cooling"
  ],
  "basis": null
 },
 {
  "key": "scope2_market_hfcs",
  "step": "step_1b",
  "label": "Scope 2 HFCs (market-based)",
  "kind": "gas",
  "scope": "scope2_market",
  "unit": "t and t CO2e",
  "formula": "0: no Scope 2 method emits fluorinated gases",
  "gas": "HFCs",
  "terms": [],
  "basis": "structural_zero"
 },
 {
  "key": "scope2_market_pfcs",
  "step": "step_1b",
  "label": "Scope 2 PFCs (market-based)",
  "kind": "gas",
  "scope": "scope2_market",
  "unit": "t and t CO2e",
  "formula": "0: no Scope 2 method emits fluorinated gases",
  "gas": "PFCs",
  "terms": [],
  "basis": "structural_zero"
 },
 {
  "key": "scope2_market_sf6",
  "step": "step_1b",
  "label": "Scope 2 SF6 (market-based)",
  "kind": "gas",
  "scope": "scope2_market",
  "unit": "t and t CO2e",
  "formula": "0: no Scope 2 method emits fluorinated gases",
  "gas": "SF6",
  "terms": [],
  "basis": "structural_zero"
 },
 {
  "key": "scope2_market_nf3",
  "step": "step_1b",
  "label": "Scope 2 NF3 (market-based)",
  "kind": "gas",
  "scope": "scope2_market",
  "unit": "t and t CO2e",
  "formula": "0: no Scope 2 method emits fluorinated gases",
  "gas": "NF3",
  "terms": [],
  "basis": "structural_zero"
 },
 {
  "key": "inventory_location_total",
  "step": "step_2",
  "label": "Inventory total, location-based (Scope 1 + Scope 2)",
  "kind": "total",
  "scope": "inventory_location",
  "unit": "t CO2e",
  "formula": "scope1_total + scope2_location_total",
  "gas": null,
  "terms": [
   "node:scope1_total",
   "node:scope2_location_total"
  ],
  "basis": null
 },
 {
  "key": "inventory_market_total",
  "step": "step_2",
  "label": "Inventory total, market-based (Scope 1 + Scope 2)",
  "kind": "total",
  "scope": "inventory_market",
  "unit": "t CO2e",
  "formula": "scope1_total + scope2_market_total",
  "gas": null,
  "terms": [
   "node:scope1_total",
   "node:scope2_market_total"
  ],
  "basis": null
 }
] as LayoutNode[];
export const LAYOUT_CATEGORIES: LayoutCategory[] = [
 {
  "key": "stationary_combustion",
  "label": "Stationary combustion",
  "scope": "scope1",
  "workbook_row": 43,
  "built": true,
  "backend_categories": {
   "location": "stationary_combustion"
  },
  "gases": [
   "CO2",
   "CH4",
   "N2O"
  ]
 },
 {
  "key": "mobile_combustion",
  "label": "Mobile combustion",
  "scope": "scope1",
  "workbook_row": 44,
  "built": true,
  "backend_categories": {
   "location": "mobile_combustion"
  },
  "gases": [
   "CO2",
   "CH4",
   "N2O"
  ]
 },
 {
  "key": "process_sources",
  "label": "Process sources",
  "scope": "scope1",
  "workbook_row": 45,
  "built": false,
  "backend_categories": {},
  "gases": [
   "CO2",
   "CH4",
   "N2O",
   "HFCs",
   "PFCs",
   "SF6",
   "NF3"
  ]
 },
 {
  "key": "fugitive_refrigerants",
  "label": "Fugitive: refrigeration, AC and fire suppression",
  "scope": "scope1",
  "workbook_row": 46,
  "built": true,
  "backend_categories": {
   "location": "fugitive_refrigerants"
  },
  "gases": [
   "CO2",
   "HFCs",
   "PFCs",
   "SF6",
   "NF3"
  ]
 },
 {
  "key": "fugitive_purchased_gases",
  "label": "Fugitive: purchased industrial gases",
  "scope": "scope1",
  "workbook_row": 46,
  "built": false,
  "backend_categories": {},
  "gases": [
   "CO2",
   "CH4",
   "N2O",
   "HFCs",
   "PFCs",
   "SF6",
   "NF3"
  ]
 },
 {
  "key": "agricultural_sources",
  "label": "Agricultural sources",
  "scope": "scope1",
  "workbook_row": 47,
  "built": false,
  "backend_categories": {},
  "gases": [
   "CO2",
   "CH4",
   "N2O"
  ]
 },
 {
  "key": "purchased_electricity",
  "label": "Purchased electricity",
  "scope": "scope2",
  "workbook_row": 48,
  "built": true,
  "backend_categories": {
   "location": "purchased_electricity_location_based",
   "market": "purchased_electricity_market_based"
  },
  "gases": [
   "CO2",
   "CH4",
   "N2O"
  ]
 },
 {
  "key": "purchased_steam",
  "label": "Purchased steam",
  "scope": "scope2",
  "workbook_row": 49,
  "built": true,
  "backend_categories": {
   "location": "purchased_steam_location_based",
   "market": "purchased_steam_market_based"
  },
  "gases": [
   "CO2",
   "CH4",
   "N2O"
  ]
 },
 {
  "key": "purchased_heating",
  "label": "Purchased heating",
  "scope": "scope2",
  "workbook_row": 50,
  "built": true,
  "backend_categories": {
   "location": "purchased_heating_location_based",
   "market": "purchased_heating_market_based"
  },
  "gases": [
   "CO2",
   "CH4",
   "N2O"
  ]
 },
 {
  "key": "purchased_cooling",
  "label": "Purchased cooling",
  "scope": "scope2",
  "workbook_row": 51,
  "built": false,
  "backend_categories": {},
  "gases": [
   "CO2",
   "CH4",
   "N2O"
  ]
 }
] as LayoutCategory[];
export const LAYOUT_OUTPUTS: LayoutOutput[] = [
 {
  "key": "scope1_total",
  "label": "Scope 1 (Total)",
  "workbook_row": 22,
  "requirement": "Required",
  "node": "scope1_total",
  "measure": "co2e_t",
  "unit": "t CO2e"
 },
 {
  "key": "scope1_co2",
  "label": "Scope 1 CO2",
  "workbook_row": 23,
  "requirement": "Required",
  "node": "scope1_co2",
  "measure": "mass_t",
  "unit": "t"
 },
 {
  "key": "scope1_ch4",
  "label": "Scope 1 CH4",
  "workbook_row": 24,
  "requirement": "Required",
  "node": "scope1_ch4",
  "measure": "mass_t",
  "unit": "t"
 },
 {
  "key": "scope1_n2o",
  "label": "Scope 1 N2O",
  "workbook_row": 25,
  "requirement": "Required",
  "node": "scope1_n2o",
  "measure": "mass_t",
  "unit": "t"
 },
 {
  "key": "scope1_hfcs",
  "label": "Scope 1 HFCs",
  "workbook_row": 26,
  "requirement": "Required",
  "node": "scope1_hfcs",
  "measure": "mass_t",
  "unit": "t"
 },
 {
  "key": "scope1_pfcs",
  "label": "Scope 1 PFCs",
  "workbook_row": 27,
  "requirement": "Required",
  "node": "scope1_pfcs",
  "measure": "mass_t",
  "unit": "t"
 },
 {
  "key": "scope1_sf6",
  "label": "Scope 1 SF6",
  "workbook_row": 28,
  "requirement": "Required",
  "node": "scope1_sf6",
  "measure": "mass_t",
  "unit": "t"
 },
 {
  "key": "scope1_nf3",
  "label": "Scope 1 NF3",
  "workbook_row": 29,
  "requirement": "Required",
  "node": "scope1_nf3",
  "measure": "mass_t",
  "unit": "t"
 },
 {
  "key": "scope2_location_total",
  "label": "Scope 2 (Total), location-based",
  "workbook_row": 30,
  "requirement": "Required",
  "node": "scope2_location_total",
  "measure": "co2e_t",
  "unit": "t CO2e"
 },
 {
  "key": "scope2_market_total",
  "label": "Scope 2 (Total), market-based",
  "workbook_row": 30,
  "requirement": "Required",
  "node": "scope2_market_total",
  "measure": "co2e_t",
  "unit": "t CO2e"
 },
 {
  "key": "scope2_co2",
  "label": "Scope 2 CO2 (location-based)",
  "workbook_row": 31,
  "requirement": "Required",
  "node": "scope2_co2",
  "measure": "mass_t",
  "unit": "t"
 },
 {
  "key": "scope2_ch4",
  "label": "Scope 2 CH4 (location-based)",
  "workbook_row": 32,
  "requirement": "Required",
  "node": "scope2_ch4",
  "measure": "mass_t",
  "unit": "t"
 },
 {
  "key": "scope2_n2o",
  "label": "Scope 2 N2O (location-based)",
  "workbook_row": 33,
  "requirement": "Required",
  "node": "scope2_n2o",
  "measure": "mass_t",
  "unit": "t"
 },
 {
  "key": "scope2_hfcs",
  "label": "Scope 2 HFCs (location-based)",
  "workbook_row": 34,
  "requirement": "Required",
  "node": "scope2_hfcs",
  "measure": "mass_t",
  "unit": "t"
 },
 {
  "key": "scope2_pfcs",
  "label": "Scope 2 PFCs (location-based)",
  "workbook_row": 35,
  "requirement": "Required",
  "node": "scope2_pfcs",
  "measure": "mass_t",
  "unit": "t"
 },
 {
  "key": "scope2_sf6",
  "label": "Scope 2 SF6 (location-based)",
  "workbook_row": 36,
  "requirement": "Required",
  "node": "scope2_sf6",
  "measure": "mass_t",
  "unit": "t"
 },
 {
  "key": "scope2_nf3",
  "label": "Scope 2 NF3 (location-based)",
  "workbook_row": 37,
  "requirement": "Required",
  "node": "scope2_nf3",
  "measure": "mass_t",
  "unit": "t"
 },
 {
  "key": "scope2_market_co2",
  "label": "Scope 2 CO2 (market-based)",
  "workbook_row": 31,
  "requirement": "Required",
  "node": "scope2_market_co2",
  "measure": "mass_t",
  "unit": "t"
 },
 {
  "key": "scope2_market_ch4",
  "label": "Scope 2 CH4 (market-based)",
  "workbook_row": 32,
  "requirement": "Required",
  "node": "scope2_market_ch4",
  "measure": "mass_t",
  "unit": "t"
 },
 {
  "key": "scope2_market_n2o",
  "label": "Scope 2 N2O (market-based)",
  "workbook_row": 33,
  "requirement": "Required",
  "node": "scope2_market_n2o",
  "measure": "mass_t",
  "unit": "t"
 },
 {
  "key": "scope2_market_hfcs",
  "label": "Scope 2 HFCs (market-based)",
  "workbook_row": 34,
  "requirement": "Required",
  "node": "scope2_market_hfcs",
  "measure": "mass_t",
  "unit": "t"
 },
 {
  "key": "scope2_market_pfcs",
  "label": "Scope 2 PFCs (market-based)",
  "workbook_row": 35,
  "requirement": "Required",
  "node": "scope2_market_pfcs",
  "measure": "mass_t",
  "unit": "t"
 },
 {
  "key": "scope2_market_sf6",
  "label": "Scope 2 SF6 (market-based)",
  "workbook_row": 36,
  "requirement": "Required",
  "node": "scope2_market_sf6",
  "measure": "mass_t",
  "unit": "t"
 },
 {
  "key": "scope2_market_nf3",
  "label": "Scope 2 NF3 (market-based)",
  "workbook_row": 37,
  "requirement": "Required",
  "node": "scope2_market_nf3",
  "measure": "mass_t",
  "unit": "t"
 },
 {
  "key": "biogenic_co2",
  "label": "CO2 emissions from biogenic combustion",
  "workbook_row": 38,
  "requirement": "Required",
  "node": "biogenic_co2",
  "measure": "co2e_t",
  "unit": "t CO2e"
 },
 {
  "key": "stationary_combustion_total",
  "label": "Direct emissions from stationary combustion",
  "workbook_row": 43,
  "requirement": "Optional",
  "node": "stationary_combustion_total",
  "measure": "co2e_t",
  "unit": "t CO2e"
 },
 {
  "key": "mobile_combustion_total",
  "label": "Direct emissions from mobile combustion",
  "workbook_row": 44,
  "requirement": "Optional",
  "node": "mobile_combustion_total",
  "measure": "co2e_t",
  "unit": "t CO2e"
 },
 {
  "key": "process_total",
  "label": "Direct emissions from process sources",
  "workbook_row": 45,
  "requirement": "Optional",
  "node": "process_total",
  "measure": "co2e_t",
  "unit": "t CO2e"
 },
 {
  "key": "fugitive_total",
  "label": "Direct emissions from fugitive sources",
  "workbook_row": 46,
  "requirement": "Optional",
  "node": "fugitive_total",
  "measure": "co2e_t",
  "unit": "t CO2e"
 },
 {
  "key": "agricultural_total",
  "label": "Direct emissions from agricultural sources",
  "workbook_row": 47,
  "requirement": "Optional",
  "node": "agricultural_total",
  "measure": "co2e_t",
  "unit": "t CO2e"
 },
 {
  "key": "purchased_electricity_total",
  "label": "Indirect emissions from purchased electricity (location-based)",
  "workbook_row": 48,
  "requirement": "Optional",
  "node": "purchased_electricity_total",
  "measure": "co2e_t",
  "unit": "t CO2e"
 },
 {
  "key": "purchased_steam_total",
  "label": "Indirect emissions from purchased steam",
  "workbook_row": 49,
  "requirement": "Optional",
  "node": "purchased_steam_total",
  "measure": "co2e_t",
  "unit": "t CO2e"
 },
 {
  "key": "purchased_heating_total",
  "label": "Indirect emissions from purchased heating",
  "workbook_row": 50,
  "requirement": "Optional",
  "node": "purchased_heating_total",
  "measure": "co2e_t",
  "unit": "t CO2e"
 },
 {
  "key": "purchased_cooling_total",
  "label": "Indirect emissions from purchased cooling",
  "workbook_row": 51,
  "requirement": "Optional",
  "node": "purchased_cooling_total",
  "measure": "co2e_t",
  "unit": "t CO2e"
 }
] as LayoutOutput[];
export const COMPARISON_POINTS: { key: string; data_point: string; workbook_row: number; unit: string }[] = [
 {
  "key": "scope1_total",
  "data_point": "Scope 1 (Total)",
  "workbook_row": 22,
  "unit": "t CO2e"
 },
 {
  "key": "scope1_co2",
  "data_point": "Scope 1 CO2",
  "workbook_row": 23,
  "unit": "t"
 },
 {
  "key": "scope1_ch4",
  "data_point": "Scope 1 CH4",
  "workbook_row": 24,
  "unit": "t"
 },
 {
  "key": "scope1_n2o",
  "data_point": "Scope 1 N2O",
  "workbook_row": 25,
  "unit": "t"
 },
 {
  "key": "scope1_hfcs",
  "data_point": "Scope 1 HFCs",
  "workbook_row": 26,
  "unit": "t"
 },
 {
  "key": "scope1_pfcs",
  "data_point": "Scope 1 PFCs",
  "workbook_row": 27,
  "unit": "t"
 },
 {
  "key": "scope1_sf6",
  "data_point": "Scope 1 SF6",
  "workbook_row": 28,
  "unit": "t"
 },
 {
  "key": "scope2_location_total",
  "data_point": "Scope 2 (Total), location-based",
  "workbook_row": 30,
  "unit": "t CO2e"
 },
 {
  "key": "scope2_market_total",
  "data_point": "Scope 2 (Total), market-based",
  "workbook_row": 30,
  "unit": "t CO2e"
 },
 {
  "key": "scope2_co2",
  "data_point": "Scope 2 CO2 (location-based)",
  "workbook_row": 31,
  "unit": "t"
 },
 {
  "key": "scope2_ch4",
  "data_point": "Scope 2 CH4 (location-based)",
  "workbook_row": 32,
  "unit": "t"
 },
 {
  "key": "scope2_n2o",
  "data_point": "Scope 2 N2O (location-based)",
  "workbook_row": 33,
  "unit": "t"
 },
 {
  "key": "biogenic_co2",
  "data_point": "CO2 emissions from biogenic combustion",
  "workbook_row": 38,
  "unit": "t CO2e"
 },
 {
  "key": "stationary_combustion_total",
  "data_point": "Direct emissions from stationary combustion",
  "workbook_row": 43,
  "unit": "t CO2e"
 },
 {
  "key": "mobile_combustion_total",
  "data_point": "Direct emissions from mobile combustion",
  "workbook_row": 44,
  "unit": "t CO2e"
 },
 {
  "key": "fugitive_total",
  "data_point": "Direct emissions from fugitive sources",
  "workbook_row": 46,
  "unit": "t CO2e"
 },
 {
  "key": "purchased_electricity_total",
  "data_point": "Indirect emissions from purchased electricity (location-based)",
  "workbook_row": 48,
  "unit": "t CO2e"
 },
 {
  "key": "purchased_steam_total",
  "data_point": "Indirect emissions from purchased steam",
  "workbook_row": 49,
  "unit": "t CO2e"
 },
 {
  "key": "purchased_heating_total",
  "data_point": "Indirect emissions from purchased heating",
  "workbook_row": 50,
  "unit": "t CO2e"
 }
];
