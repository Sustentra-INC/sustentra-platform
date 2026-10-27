"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import { apiPath } from "../../../lib/api";
import { liveResultsFromRecalculation } from "../adapters/recalculationResultsAdapter";
import {
  coverageFromRecalculation,
  documentsBasis,
  getRecalculation,
  type Recalculation,
} from "../api/recalculation";
import { userFacingApiError } from "../api/s1Backend";
import type { EngagementConfig, EvidenceItem, ReviewValue } from "../types";
import type { Ask } from "../types/requests";
import type { Finding } from "../types/verification";
import { dashboardFigures } from "../utils/engagementActivity";
import { liveStatementFigures } from "../utils/outputStatement";
import { OutputScreen, type LiveOutput } from "./OutputScreen";

/**
 * Output in backend mode: the demo's statement (OutputScreen) on the engagement's real
 * results, from the same live results as Verification results, with the whole workpaper as
 * an Excel download. Every figure is the recalculation's; nothing is illustrative. It is a
 * draft working paper, not an assurance opinion, and says so.
 */
export function BackendOutputScreen({
  engagement,
  evidence,
  values,
  asks,
  findings,
  onError,
}: {
  engagement: EngagementConfig;
  evidence: EvidenceItem[];
  values: ReviewValue[];
  asks: Ask[];
  findings: Finding[];
  onError: (error: unknown) => boolean;
}) {
  const [result, setResult] = useState<Recalculation | null>(null);
  const [error, setError] = useState<string | null>(null);
  const onErrorRef = useRef(onError);
  useEffect(() => {
    onErrorRef.current = onError;
  });
  useEffect(() => {
    if (!engagement.engagementId) return;
    let live = true;
    getRecalculation(engagement.engagementId)
      .then((next) => {
        if (live) setResult(next);
      })
      .catch((caught: unknown) => {
        if (live && !onErrorRef.current(caught)) setError(userFacingApiError(caught));
      });
    return () => {
      live = false;
    };
  }, [engagement.engagementId]);

  const current = result && result.engagement_id === engagement.engagementId ? result : null;
  const output = useMemo(
    () => (current ? liveOutputFrom(current, engagement, values, findings) : null),
    [current, engagement, values, findings]
  );

  if (!engagement.engagementId) {
    return (
      <section className="s1-content s1-output">
        <div className="s1-ws-empty">
          <p>Pick or create an engagement in Setup to see its output.</p>
        </div>
      </section>
    );
  }
  if (error) {
    return (
      <section className="s1-content s1-output">
        <div className="s1-ws-empty">
          <p>Could not load the results. {error}</p>
        </div>
      </section>
    );
  }
  if (!current || !output) {
    return (
      <section className="s1-content s1-output">
        <p className="s1-muted">Assembling the results…</p>
      </section>
    );
  }

  return (
    <OutputScreen
      engagement={engagement}
      lines={output.lines}
      figures={dashboardFigures({ evidence, values, asks, findings, coverage: coverageFromRecalculation(current) })}
      live={output.live}
    />
  );
}

/** The live statement and the lines it is built from (the same as Verification results). */
export function liveOutputFrom(
  result: Recalculation,
  engagement: EngagementConfig,
  values: ReviewValue[],
  findings: Finding[]
): { lines: ReturnType<typeof liveResultsFromRecalculation>["lines"]; live: LiveOutput } {
  const results = liveResultsFromRecalculation(result);
  const corrected = values.filter((v) => v.reviewState === "corrected").length;
  const leftOut = result.excluded ?? [];
  const reviewed = documentsBasis(result);
  return {
    lines: results.lines,
    live: {
      statement: liveStatementFigures(results.lines, results.boxTotals, results.inventory, result.tolerance_pct),
      exportHref: apiPath(`/engagements/${encodeURIComponent(result.engagement_id)}/export`),
      gwpBasis: `${result.gwp_set}${result.gwp_set === "AR5" ? " (EPA Hub Table 11)" : ""}`,
      findings,
      basisLines: [
        `${reviewed[0].toUpperCase()}${reviewed.slice(1)}`,
        ...(corrected ? [`${corrected} ${corrected === 1 ? "value" : "values"} corrected or entered by the reviewer`] : []),
        ...(leftOut.length
          ? [`${leftOut.length} ${leftOut.length === 1 ? "document or record" : "documents or records"} left out (withdrawn, duplicate, superseded or outside the period)`]
          : []),
        ...(result.not_recalculated.length ? [`Not calculated yet: ${result.not_recalculated.join(", ")}`] : []),
      ],
      preparedBy: engagement.signedInName ?? engagement.signedInLogin ?? null,
    },
  };
}
