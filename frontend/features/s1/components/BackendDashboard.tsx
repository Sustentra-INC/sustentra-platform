"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import { coverageFromRecalculation, getRecalculation, type Recalculation } from "../api/recalculation";
import type { EngagementConfig, EvidenceItem, ReviewValue } from "../types";
import type { Ask } from "../types/requests";
import type { Examination, Finding } from "../types/verification";
import { dashboardFigures } from "../utils/engagementActivity";
import { DashboardScreen } from "./DashboardScreen";
import type { NavKey } from "./S1Chrome";

/** The dashboard in backend mode: every figure from the engagement's live state. */
export function BackendDashboard({
  engagement,
  evidence,
  values,
  asks,
  findings,
  examinations,
  onNavigate,
  onError,
}: {
  engagement: EngagementConfig;
  evidence: EvidenceItem[];
  values: ReviewValue[];
  asks: Ask[];
  findings: Finding[];
  examinations: Record<string, Examination>;
  onNavigate?: (key: NavKey) => void;
  onError: (error: unknown) => boolean;
}) {
  const [result, setResult] = useState<Recalculation | null>(null);
  const onErrorRef = useRef(onError);
  useEffect(() => {
    onErrorRef.current = onError;
  });
  // Refetch when the reviewed values change, so the figures follow the review.
  const reviewedCount = values.filter((v) => v.reviewState === "accepted" || v.reviewState === "corrected").length;
  useEffect(() => {
    if (!engagement.engagementId) return;
    let live = true;
    getRecalculation(engagement.engagementId)
      .then((next) => {
        if (live) setResult(next);
      })
      .catch((error: unknown) => {
        onErrorRef.current(error); // the dashboard keeps its empty states
      });
    return () => {
      live = false;
    };
  }, [engagement.engagementId, reviewedCount, evidence.length]);

  const figures = useMemo(() => {
    const current = result && result.engagement_id === engagement.engagementId ? result : null;
    const calculatedIds = current
      ? current.comparisons
          .filter((c) => c.recalculated !== null && c.status !== "not_in_scope")
          .map((c) => `RECALC-${c.key}`)
      : [];
    return dashboardFigures({
      evidence,
      values,
      asks,
      findings,
      examinations,
      coverage: current ? coverageFromRecalculation(current) : null,
      calculatedIds,
    });
  }, [result, engagement.engagementId, values, evidence, asks, findings, examinations]);

  return (
    <DashboardScreen engagement={engagement} figures={figures} onNavigate={onNavigate} />
  );
}
