/**
 * Demo backend: GET /engagements/{id}/recalculation/lines/{line_key}/trace. The demo's stationary, mobile
 * and electricity lines are traced from the same recalculation the lines table shows (see fromLine.ts),
 * so the totals on screen agree. A line the recalculation does not have has no trace (`trace: null`).
 */
import { buildRecalculation } from "../recalcDataRollup";
import type { DemoRoute } from "../types";
import { traceFromLine } from "./fromLine";

export const calcTraceRoutes: DemoRoute[] = [
  {
    method: "GET",
    path: /^\/engagements\/(?<id>[^/]+)\/recalculation\/lines\/(?<key>[^/]+)\/trace$/,
    handle: ({ params }) => {
      const line = buildRecalculation(params.id).calculation_lines?.find((l) => l.key === params.key);
      return { line_key: params.key, trace: line ? traceFromLine(line) : null };
    },
  },
];
