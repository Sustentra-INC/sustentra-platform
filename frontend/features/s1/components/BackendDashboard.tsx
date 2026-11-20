"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import { liveResultsFromRecalculation } from "../adapters/recalculationResultsAdapter";
import {
  coverageFromRecalculation,
  getRecalculation,
  missingReportedTotals,
  type Recalculation,
} from "../api/recalculation";
import type { EngagementConfig, EvidenceItem, ReviewValue } from "../types";
import type { Ask } from "../types/requests";
import type { Examination, Finding } from "../types/verification";
import { dashboardFigures } from "../utils/engagementActivity";
import { testedExaminationKeys } from "../utils/verificationTable";
import { ContainerStateSurface } from "./ContainerStateSurface";
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
  onOpenReview,
  onError,
}: {
  engagement: EngagementConfig;
  evidence: EvidenceItem[];
  values: ReviewValue[];
  asks: Ask[];
  findings: Finding[];
  examinations: Record<string, Examination>;
  onNavigate?: (key: NavKey) => void;
  onOpenReview?: () => void;
  onError: (error: unknown) => boolean;
}) {
  const [result, setResult] = useState<Recalculation | null>(null);
  // The engagement whose recalculation failed to load: then the dashboard shows what it has.
  const [failedFor, setFailedFor] = useState<string | null>(null);
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
        if (live) setFailedFor(engagement.engagementId);
        onErrorRef.current(error); // the dashboard keeps its empty states
      });
    return () => {
      live = false;
    };
  }, [engagement.engagementId, reviewedCount, evidence.length]);

  const { start, end } = engagement.reportingPeriod;
  const figures = useMemo(() => {
    const current = result && result.engagement_id === engagement.engagementId ? result : null;
    // The facility rows of Verification results, as its Examined counts key them.
    const calculatedIds = current ? testedExaminationKeys(liveResultsFromRecalculation(current).lines) : [];
    return {
      ...dashboardFigures({
        evidence,
        values,
        asks,
        findings,
        examinations,
        // An engagement with no documents at all keeps the empty state ("Upload documents to
        // begin"), not a list of data points with nothing yet.
        coverage: current && evidence.some((e) => e.disposition !== "withdrawn") ? coverageFromRecalculation(current) : null,
        calculatedIds,
      }),
      // From the engagement, not the recalculation: that may be fetched before a Setup
      // save lands, and the row should clear as soon as the period has both dates.
      reportingPeriodIncomplete: Boolean(engagement.engagementId) && (!start || !end),
      reportedTotalsMissing: current ? missingReportedTotals(current).length : 0,
    };
  }, [result, engagement.engagementId, start, end, values, evidence, asks, findings, examinations]);

  // Until the first recalculation lands the figures are only half known, so say it is loading
  // rather than show "Nothing needs you" or a document count that then jumps.
  const pending =
    Boolean(engagement.engagementId) &&
    failedFor !== engagement.engagementId &&
    !(result && result.engagement_id === engagement.engagementId);
  if (pending) {
    return (
      <section className="s1-content">
        <ContainerStateSurface state="loading" />
      </section>
    );
  }

  return (
    <DashboardScreen engagement={engagement} figures={figures} onNavigate={onNavigate} onOpenReview={onOpenReview} />
  );
}
