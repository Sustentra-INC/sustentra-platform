"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import { coverageFromRecalculation, getRecalculation, type Recalculation } from "../api/recalculation";
import type { EngagementConfig, EvidenceItem, ReviewValue } from "../types";
import type { Ask } from "../types/requests";
import type { Examination, Finding } from "../types/verification";
import { DashboardScreen, type LiveDashboard } from "./DashboardScreen";
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

  const live = useMemo((): LiveDashboard => {
    const current = result && result.engagement_id === engagement.engagementId ? result : null;
    const active = values.filter((v) => !v.withdrawn);
    const category = (key: keyof Recalculation["categories"], label: string) => {
      const part = current?.categories[key];
      return part ? { label, value: part.total_co2e } : null;
    };
    const emissions = current
      ? [
          category("stationary_combustion", "Scope 1 · fuel burned on site"),
          category("mobile_combustion", "Scope 1 · vehicle fuel"),
          category("fugitive_refrigerants", "Scope 1 · refrigerants"),
          category("purchased_electricity_location_based", "Scope 2 · location-based"),
          category("purchased_electricity_market_based", "Scope 2 · market-based"),
        ].filter((row): row is { label: string; value: number } => row !== null)
      : null;
    const rules = current ? coverageFromRecalculation(current) : null;
    const calculated = current
      ? current.comparisons
          .filter((c) => c.recalculated !== null && c.status !== "not_in_scope")
          .map((c) => `RECALC-${c.key}`)
      : [];

    const activity: LiveDashboard["activity"] = [];
    for (const item of evidence) {
      activity.push({ at: item.uploadedAt, who: item.uploadedBy.name, what: `uploaded ${item.filename}` });
    }
    for (const value of values) {
      for (const entry of value.record) {
        if (entry.kind === "human" && entry.at) {
          activity.push({ at: entry.at, who: entry.actor, what: `${entry.action}: ${value.whatItIs} (${value.filename})` });
        }
      }
    }
    for (const ask of asks) {
      for (const event of ask.history) {
        activity.push({ at: event.at, who: event.actorName, what: `${event.kind} a request: ${ask.source.itemLabel}` });
      }
    }
    for (const finding of findings) {
      if (finding.registeredAt) {
        activity.push({
          at: finding.registeredAt,
          who: finding.registeredBy ?? "Reviewer",
          what: `registered a finding on ${finding.dataPointLabel}`,
        });
      }
    }
    activity.sort((a, b) => b.at.localeCompare(a.at));

    return {
      valuesReviewed: active.filter((v) => v.reviewState === "accepted" || v.reviewState === "corrected").length,
      valuesToReview: active.filter((v) => v.reviewState === "to_review").length,
      blockedDocuments: evidence.filter((e) => e.processingState === "blocked" && e.disposition !== "withdrawn").length,
      requestsRaised: asks.filter((a) => a.state !== "withdrawn").length,
      requestsResolved: asks.filter((a) => a.state === "resolved").length,
      emissions,
      coverage: rules
        ? {
            present: rules.filter((r) => r.status === "inputs_present").length,
            missing: rules.filter((r) => r.status === "inputs_missing").length,
            notApplicable: rules.filter((r) => r.status === "not_applicable").length,
            outOfScope: rules.filter((r) => r.status === "out_of_scope").length,
          }
        : null,
      dataPointsCalculated: calculated.length,
      dataPointsExamined: calculated.filter(
        (id) => examinations[id] && examinations[id].examinationState !== "not_examined"
      ).length,
      findings: findings.length,
      activity: activity.slice(0, 8),
    };
  }, [result, engagement.engagementId, values, evidence, asks, findings, examinations]);

  return (
    <DashboardScreen
      engagement={engagement}
      metrics={{
        documents: evidence.length,
        openRequests: asks.filter((a) => a.state === "not_yet_sent" || a.state === "requested").length,
        live,
      }}
      onNavigate={onNavigate}
    />
  );
}
