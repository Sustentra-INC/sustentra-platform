/**
 * Demo backend: the emissions recalculation (GET /engagements/{id}/recalculation), the reference
 * data behind its inputs (GET /reference/recalculation) and the eGRID ZIP lookup. Numbers come
 * from the demo line model, so they agree with the Evidence tree and the supporting schedules.
 */
import type { DataPointOption, RecalculationReference } from "../api/recalculation";
import { demoError } from "./index";
import { ZIP_SUBREGION, EGRID } from "./recalcDataCalc";
import { LAYOUT_NODES, LAYOUT_OUTPUTS, LAYOUT_CATEGORIES, LAYOUT_STEPS } from "./recalcDataLayout";
import { buildRecalculation } from "./recalcDataRollup";
import type { DemoRoute } from "./types";

const SUBREGIONS = [
  ...Object.entries(EGRID).map(([egrid_subregion, v]) => ({ egrid_subregion, name: v.name })),
  { egrid_subregion: "NYUP", name: "NPCC Upstate NY" },
  { egrid_subregion: "RFCE", name: "RFC East" },
  { egrid_subregion: "SRSO", name: "SERC South" },
].sort((a, b) => a.egrid_subregion.localeCompare(b.egrid_subregion));

function reference(): RecalculationReference {
  const unbuilt = new Set(LAYOUT_CATEGORIES.filter((c) => !c.built).map((c) => c.key));
  const nodeScope = (key: string) => LAYOUT_NODES.find((n) => n.key === key)?.scope ?? "scope1";
  const dataPoints: DataPointOption[] = LAYOUT_OUTPUTS.map((o) => ({
    key: o.key, label: o.label, workbook_row: o.workbook_row, unit: o.unit ?? "t", layer: nodeScope(o.node).startsWith("scope2") ? "scope2" : "scope1", requirement: o.requirement,
    check: /process|agricultural|cooling|hfcs|pfcs|sf6|nf3/.test(o.key) || unbuilt.has(o.key as never) ? "not_recalculated" : "recalculated",
  }));
  return {
    dataset: "EPA GHG Emission Factors Hub 2025", gwp_sets: ["AR4", "AR5", "AR6"], default_gwp_set: "AR5", egrid_subregions: SUBREGIONS,
    stationary_fuels: ["Natural Gas", "Propane", "Distillate Fuel Oil No. 2", "Wood and Wood Residuals"],
    mobile_fuels: ["Diesel Fuel", "Motor Gasoline", "Liquefied Petroleum Gases (LPG)"],
    vehicle_types: [
      { vehicle_type: "Medium- and Heavy-Duty Vehicles", fuel_type: "Diesel", on_road: true, by_model_year: true, first_model_year: 2007, last_model_year: 2022 },
      { vehicle_type: "Gasoline Light-Duty Trucks", fuel_type: "Gasoline", on_road: true, by_model_year: true, first_model_year: 1990, last_model_year: 2022 },
      { vehicle_type: "Industrial/Commercial Equipment", fuel_type: "LPG", on_road: false, by_model_year: false, first_model_year: null, last_model_year: null },
    ],
    reported_data_points: dataPoints.map((p) => ({ key: p.key, label: p.label, workbook_row: p.workbook_row, unit: p.unit })),
    data_points: dataPoints,
    rollup_layout: {
      version: 2, steps: LAYOUT_STEPS,
      sources: LAYOUT_CATEGORIES.map((c) => ({ key: c.key, label: c.label, scope: c.scope, workbook_row: c.workbook_row, built: c.built, gases: c.gases })),
      nodes: LAYOUT_NODES.map((n) => ({ key: n.key, step: n.step, label: n.label, unit: n.unit, kind: n.kind, scope: n.scope, gas: n.gas, formula: n.formula, terms: n.terms, structural_zero: n.basis === "structural_zero" })),
      final_outputs: LAYOUT_OUTPUTS.map((o) => ({ key: o.key, label: o.label, workbook_row: o.workbook_row, requirement: o.requirement, node: o.node, default_measure: o.measure, unit: o.unit, unit_settable: o.measure === null })),
    },
  };
}

export const recalculationRoutes: DemoRoute[] = [
  { method: "GET", path: /^\/engagements\/(?<id>[^/]+)\/recalculation$/, handle: ({ params }) => buildRecalculation(params.id) },
  { method: "GET", path: /^\/reference\/recalculation$/, handle: () => reference() },
  {
    method: "GET",
    path: /^\/reference\/egrid-zip\/(?<zip>[^/]+)$/,
    handle: ({ params }) => {
      const subregions = ZIP_SUBREGION[params.zip];
      if (!subregions) return demoError(404, "EPA does not list this ZIP code.");
      return { zip: params.zip, subregions: [...subregions] };
    },
  },
];
