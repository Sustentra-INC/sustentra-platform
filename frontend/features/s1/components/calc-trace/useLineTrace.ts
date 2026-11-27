"use client";

import { useEffect, useState } from "react";

import { getLineTrace, type LineTrace } from "../../api/calcTrace";

export type LineTraceState =
  | { status: "idle" | "loading" | "none" | "error" }
  | { status: "ready"; trace: LineTrace };

/**
 * Fetches one line's trace when the line opens, and again when `version` changes (the line's figures
 * changed). A response for an earlier request is dropped. No engagement id means no fetch. A response
 * with no trace, or one that is not a trace, is "none"; a failed request is "error".
 */
export function useLineTrace(engagementId: string | undefined, lineKey: string, version: string): LineTraceState {
  const key = `${engagementId ?? ""}|${lineKey}|${version}`;
  const [done, setDone] = useState<{ key: string; state: LineTraceState } | null>(null);

  useEffect(() => {
    if (!engagementId) return;
    let cancelled = false;
    getLineTrace(engagementId, lineKey)
      .then((res) => {
        const trace = res?.trace;
        if (cancelled) return;
        setDone({ key, state: trace && typeof trace === "object" && Array.isArray(trace.steps) ? { status: "ready", trace } : { status: "none" } });
      })
      .catch(() => {
        if (!cancelled) setDone({ key, state: { status: "error" } });
      });
    return () => {
      cancelled = true;
    };
  }, [engagementId, lineKey, key]);

  if (!engagementId) return { status: "idle" };
  return done?.key === key ? done.state : { status: "loading" };
}
