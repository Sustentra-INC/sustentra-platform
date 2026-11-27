/**
 * Demo backend: GET /engagements/{id}/recalculation/lines/{line_key}/trace. The demo's stationary, mobile
 * and electricity lines are traced from the same recalculation the lines table shows (see fromLine.ts),
 * so the totals on screen agree. Reviewer decisions (decisions.ts) are kept in memory and shown on it. A line the recalculation does not have has no trace (`trace: null`).
 */
import { buildRecalculation } from "../recalcDataRollup";
import type { DemoRoute } from "../types";
import { applyDecisions, decisionRoutes } from "./decisions";
import { traceFromLine } from "./fromLine";

function traceOf(engagementId: string, lineKey: string) {
  const line = buildRecalculation(engagementId).calculation_lines?.find((l) => l.key === lineKey);
  return line ? traceFromLine(line) : null;
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
