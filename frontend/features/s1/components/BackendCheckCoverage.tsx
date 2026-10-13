"use client";

import { useEffect, useRef, useState } from "react";

import { coverageFromRecalculation, getRecalculation, type Recalculation } from "../api/recalculation";
import { userFacingApiError } from "../api/s1Backend";
import { CheckCoverage } from "./CheckCoverage";

/** Check coverage in backend mode: built from the engagement's live recalculation. */
export function BackendCheckCoverage({
  engagementId,
  onError,
}: {
  engagementId: string;
  /** True when the error was handled (e.g. the session ended). */
  onError: (error: unknown) => boolean;
}) {
  const [result, setResult] = useState<Recalculation | null>(null);
  const [error, setError] = useState<string | null>(null);
  const onErrorRef = useRef(onError);
  useEffect(() => {
    onErrorRef.current = onError;
  });

  useEffect(() => {
    if (!engagementId) return;
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
  }, [engagementId]);

  if (!engagementId) {
    return (
      <section className="s1-content s1-cov">
        <div className="s1-ws-empty">
          <p>Pick or create an engagement in Setup to see what can be checked.</p>
        </div>
      </section>
    );
  }
  if (error) {
    return (
      <section className="s1-content s1-cov">
        <div className="s1-ws-empty">
          <p>Could not load coverage. {error}</p>
        </div>
      </section>
    );
  }
  if (!result || result.engagement_id !== engagementId) {
    return (
      <section className="s1-content s1-cov">
        <p className="s1-muted">Checking what the evidence covers…</p>
      </section>
    );
  }
  return <CheckCoverage rules={coverageFromRecalculation(result)} />;
}
