"use client";

import { useEffect, useState } from "react";

import { getLineTrace, type LineDecisions, type LineTrace } from "../../api/calcTrace";

export type LineTraceState =
  | { status: "idle" | "loading" | "none" | "error" }
  | { status: "ready"; trace: LineTrace; decisions?: LineDecisions };

/**
 * Fetches one line's trace when the line opens, and again when `version` changes (the line's figures
 * changed) or `reload` is bumped (a decision was saved). A response for an earlier request is dropped. No engagement id means no fetch. A response
 * with no trace, or one that is not a trace, is "none"; a failed request is "error".
 */
export function useLineTrace(engagementId: string | undefined, lineKey: string, version: string, reload = 0): LineTraceState {
  const line = `${engagementId ?? ""}|${lineKey}`;
  const key = `${line}|${version}|${reload}`;
  const [done, setDone] = useState<{ key: string; line: string; state: LineTraceState } | null>(null);

  useEffect(() => {
    if (!engagementId) return;
    let cancelled = false;
    getLineTrace(engagementId, lineKey)
      .then((res) => {
        const trace = res?.trace;
        if (cancelled) return;
        setDone({ key, line, state: trace && typeof trace === "object" && Array.isArray(trace.steps) ? { status: "ready", trace, decisions: res.decisions } : { status: "none" } });
      })
      .catch(() => {
        if (!cancelled) setDone({ key, line, state: { status: "error" } });
      });
    return () => {
      cancelled = true;
    };
  }, [engagementId, lineKey, key, line]);

  if (!engagementId) return { status: "idle" };
  if (done?.key === key) return done.state;
  // Fetching again after a decision: the trace on screen stays until the new one arrives, so the panel never blinks away.
  if (done?.line === line && done.state.status === "ready") return done.state;
  return { status: "loading" };
}
