/**
 * Demo backend: GET /engagements/{id}/recalculation/lines/{line_key}/trace. The demo's stationary, mobile
 * and electricity lines are traced from the same recalculation the lines table shows (see fromLine.ts),
 * so the totals on screen agree. Reviewer decisions (decisions.ts) are kept in memory and shown on it. A line the recalculation does not have has no trace (`trace: null`).
 */
import { buildRecalculation } from "../recalcDataRollup";
import type { DemoRoute } from "../types";
import { applyDecisions, decisionRoutes } from "./decisions";
import { ZIP_SUBREGION, calculate, regionOf } from "../recalcDataCalc";
import { demoCompanyRegion } from "./companyRegion";
import { traceFromLine, type DemoElectricity } from "./fromLine";
import { fugitiveTrace } from "./fugitive";
import { withFuelEconomy } from "./mobile";

/** The grid region of an electricity line as the demo's calculation resolved it, with its facility's ZIP. */
function electricityOf(engagementId: string, lineKey: string): DemoElectricity | null {
  const c = calculate();
  const built = c.lines.find((l) => l.line.key === lineKey);
  const facility = built ? c.model.facilities.find((f) => f.facilityId === built.line.facility_id) : undefined;
  if (!built || !facility) return null;
  const { region, source } = regionOf(facility.name, facility.address, c.inputs);
  const zip = /(\d{5})(?:-\d{4})?\s*$/.exec(facility.address ?? "")?.[1] ?? null;
  return { region, source, zip, candidates: zip ? [...(ZIP_SUBREGION[zip] ?? [])] : [], companyRegionText: demoCompanyRegion(engagementId, lineKey) };
}

function traceOf(engagementId: string, lineKey: string) {
  const line = buildRecalculation(engagementId).calculation_lines?.find((l) => l.key === lineKey);
  if (line?.counts_toward === "fugitive") return fugitiveTrace(line);
  return line ? withFuelEconomy(traceFromLine(line, line.category === "purchased_energy" ? electricityOf(engagementId, line.key) : null), line) : null;
}

export const calcTraceRoutes: DemoRoute[] = [
  {
    method: "GET",
    path: /^\/engagements\/(?<id>[^/]+)\/recalculation\/lines\/(?<key>[^/]+)\/trace$/,
    handle: ({ params }) => {
      const trace = traceOf(params.id, params.key);
      return { line_key: params.key, trace: trace ? applyDecisions(params.id, trace) : null };
    },
  },
  ...decisionRoutes(traceOf),
];
