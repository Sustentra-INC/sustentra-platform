"use client";

import { useEffect, useRef, useState } from "react";

import { coverageFromRecalculation, getRecalculation, type Recalculation } from "../api/recalculation";
import { userFacingApiError } from "../api/s1Backend";
import type { CoverageState } from "./CoveragePanel";

/** Coverage in backend mode: built from the engagement's live recalculation. */
export function useBackendCoverage(
  engagementId: string,
  enabled: boolean,
  /** True when the error was handled (e.g. the session ended). */
  onError: (error: unknown) => boolean
): CoverageState {
  const [result, setResult] = useState<Recalculation | null>(null);
  const [error, setError] = useState<string | null>(null);
  const onErrorRef = useRef(onError);
  useEffect(() => {
    onErrorRef.current = onError;
  });

  useEffect(() => {
    if (!enabled || !engagementId) return;
    let live = true;
    getRecalculation(engagementId)
      .then((next) => {
        if (!live) return;
        setResult(next);
        setError(null);
      })
      .catch((caught: unknown) => {
        if (!live || onErrorRef.current(caught)) return;
        setError(userFacingApiError(caught));
      });
    return () => {
      live = false;
    };
  }, [engagementId, enabled]);

  if (!engagementId) return { rules: null, message: "Pick or create an engagement in Setup to see what can be checked." };
  if (error) return { rules: null, message: `Could not load coverage. ${error}` };
  if (!result || result.engagement_id !== engagementId) return { rules: null };
  return { rules: coverageFromRecalculation(result) };
}
