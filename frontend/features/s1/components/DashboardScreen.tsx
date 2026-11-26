"use client";

import {
  CalendarRange,
  Check,
  ChevronRight,
  CircleAlert,
  FileQuestion,
  Hourglass,
  ListChecks,
  PencilLine,
  Scale,
  Send,
  ShieldAlert,
} from "lucide-react";
import { useState, type ReactNode } from "react";

import type { EngagementConfig } from "../types";
import type { DashboardFigures } from "../utils/engagementActivity";
import { formatReportingPeriod } from "../utils/formatPeriod";
import type { NavKey } from "./S1Chrome";
import { IconArrowRight, IconCheckCircle, IconChevronDown } from "./icons";

/**
 * Dashboard: progress only, at a glance. The engagement timeline, how much of the
 * evidence is in and reviewed, and what needs someone now, most urgent first. Every
 * figure comes from the engagement's own state; each line opens the screen to act on.
 */
export function DashboardScreen({
  engagement,
  figures,
  onNavigate,
}: {
  engagement: EngagementConfig;
  figures: DashboardFigures;
  onNavigate?: (key: NavKey) => void;
}) {
  const go = (key: NavKey) => () => onNavigate?.(key);
  const hasEngagement = Boolean(engagement.clientName);
  const [detailsOpen, setDetailsOpen] = useState(false);
  const attention = attentionItems(figures);
  const phases = buildPhases(hasEngagement, figures);
  const intakeStage = phases[1].status;
  const reviewStage = phases[2].status;
  const assessStage = phases[3].status;
  const opinionStage = phases[4].status;

  // Evidence intake card
  const coverage = figures.coverage;
  const covered = coverage ? coverage.present + coverage.missing : 0;
  const byDataPoint = coverage !== null && covered > 0;
  const evidenceDone = byDataPoint ? (coverage?.present ?? 0) : figures.documentsReadable;
  const evidenceTotal = byDataPoint ? covered : figures.documents;
  const evidencePct = evidenceTotal > 0 ? Math.round((evidenceDone / evidenceTotal) * 100) : 0;
  const evidenceMissing = byDataPoint ? (coverage?.missing ?? 0) : 0;

  // Review card
  const reviewTotal = figures.valuesReviewed + figures.valuesToReview;
  const reviewPct = reviewTotal > 0 ? Math.round((figures.valuesReviewed / reviewTotal) * 100) : 0;
  const RING_C = 182.21; // 2π × r=29
  const ringDash = reviewTotal > 0 ? (figures.valuesReviewed / reviewTotal) * RING_C : 0;

  // Assessment card
  const assessTotal = figures.dataPointsCalculated;
  const assessDone = figures.dataPointsExamined;
  const assessPct = assessTotal > 0 ? Math.round((assessDone / assessTotal) * 100) : 0;
  const useSegments = assessTotal > 0 && assessTotal <= 20;
  const assessStatus =
    assessTotal === 0 || assessDone === 0 ? "not started" :
    assessDone === assessTotal ? "all examined" :
    `${assessTotal - assessDone} remaining`;

  const statusText = hasEngagement
    ? [
        engagement.regulation ? shortRegulation(engagement.regulation) : null,
        formatReportingPeriod(engagement.reportingPeriod.start, engagement.reportingPeriod.end),
      ]
        .filter(Boolean)
        .join(" · ")
    : null;

  return (
    <section className="s1-content s1-dash">
      <header className="s1-dash__head">
        <h1 className="s1-dash__title">
          {hasEngagement ? engagement.clientName : "New engagement"}
        </h1>
        <div className="s1-dash__status-line">
          {statusText ? <span className="s1-dash__status-text">{statusText}</span> : null}
          <button
            type="button"
            className={`s1-state ${hasEngagement ? "s1-state--resolved" : "s1-state--open"}`}
            onClick={go("setup")}
          >
            {hasEngagement ? <IconCheckCircle size={13} aria-hidden /> : null}
            {hasEngagement ? "Setup complete" : "Setup incomplete"}
          </button>
          {hasEngagement && (
            <button
              type="button"
              className="s1-dash__details-btn"
              aria-expanded={detailsOpen}
              onClick={() => setDetailsOpen((v) => !v)}
            >
              {detailsOpen ? "Hide details" : "Details"}
              <IconChevronDown size={14} aria-hidden />
            </button>
          )}
        </div>
      </header>

      {detailsOpen && hasEngagement && (
        <section aria-label="Engagement details" className="s1-dash__details-card">
          <div className="s1-dash__detail-item">
            <span className="s1-dash__detail-label">Engagement ID</span>
            <span className="s1-dash__detail-value">{engagement.engagementId}</span>
          </div>
          <div className="s1-dash__detail-item">
            <span className="s1-dash__detail-label">Reporting period</span>
            <span className="s1-dash__detail-value">
              {formatReportingPeriod(engagement.reportingPeriod.start, engagement.reportingPeriod.end)}
            </span>
          </div>
          <div className="s1-dash__detail-item">
            <span className="s1-dash__detail-label">Regulation</span>
            <span className="s1-dash__detail-value">{engagement.regulation}</span>
          </div>
          <div className="s1-dash__detail-item">
            <span className="s1-dash__detail-label">Assurance level</span>
            <span className="s1-dash__detail-value">{engagement.assuranceLevel}</span>
          </div>
          <div className="s1-dash__detail-item">
            <span className="s1-dash__detail-label">Boundary approach</span>
            <span className="s1-dash__detail-value">{engagement.boundaryApproach}</span>
          </div>
        </section>
      )}

      <section aria-label="Engagement progress" className="s1-stage-cards">
        {/* A: Evidence intake */}
        <button type="button" className={`s1-stage-card${intakeStage === "active" ? " s1-stage-card--current" : ""}`} onClick={go("evidence")}>
          <span className="s1-stage-card__top">
            <span className="s1-stage-card__name">Evidence intake</span>
            {intakeStage === "done"
              ? <span className="s1-state s1-state--resolved">Done</span>
              : intakeStage === "active"
                ? <span className="s1-state s1-state--active">In progress</span>
                : <span className="s1-stage-card__icon-slot" aria-hidden><IconArrowRight size={16} /></span>}
          </span>
          <span className="s1-stage-card__big">{evidencePct}%</span>
          <span className="s1-stage-card__bar-track" aria-hidden>
            <span className="s1-stage-card__bar-fill" style={{ width: `${evidencePct}%` }} />
          </span>
          <span className="s1-stage-card__caption">
            {evidenceTotal > 0 ? (
              <>
                {byDataPoint
                  ? `${evidenceDone} of ${evidenceTotal} data points`
                  : `${evidenceDone} of ${evidenceTotal} documents`}
                {evidenceMissing > 0 && (
                  <> · <span
                    className="s1-stage-card__missing s1-stage-card__missing--nav"
                    onClick={(e) => { e.stopPropagation(); onNavigate?.("requests"); }}
                    onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.stopPropagation(); onNavigate?.("requests"); } }}
                  >{evidenceMissing} missing</span></>
                )}
              </>
            ) : "No evidence yet"}
          </span>
        </button>

        {/* B: Review */}
        <button type="button" className={`s1-stage-card${reviewStage === "active" ? " s1-stage-card--current" : ""}`} onClick={go("evidence")}>
          <span className="s1-stage-card__top">
            <span className="s1-stage-card__name">Review</span>
            {reviewStage === "done"
              ? <span className="s1-state s1-state--resolved">Done</span>
              : reviewStage === "active"
                ? <span className="s1-state s1-state--active">In progress</span>
                : <span className="s1-stage-card__icon-slot" aria-hidden><IconArrowRight size={16} /></span>}
          </span>
          <span className="s1-stage-card__ring-wrap">
            <span className="s1-stage-card__ring">
              <svg width="64" height="64" viewBox="0 0 72 72" aria-hidden>
                <circle cx="36" cy="36" r="29" className="s1-stage-card__ring-track" />
                <circle
                  cx="36" cy="36" r="29"
                  className="s1-stage-card__ring-progress"
                  strokeDasharray={`${ringDash.toFixed(1)} ${RING_C}`}
                />
              </svg>
              <span className="s1-stage-card__ring-pct">{reviewPct}%</span>
            </span>
            <span className="s1-stage-card__fraction">
              {figures.valuesReviewed}
              <span className="s1-stage-card__fraction-of"> / {reviewTotal}</span>
            </span>
          </span>
          <span className="s1-stage-card__caption">
            {reviewTotal > 0
              ? `values accepted or corrected · ${figures.valuesToReview} left`
              : "No values to review yet"}
          </span>
        </button>

        {/* C: Assessment */}
        <button type="button" className={`s1-stage-card${assessStage === "active" ? " s1-stage-card--current" : ""}`} onClick={go("results")}>
          <span className="s1-stage-card__top">
            <span className="s1-stage-card__name">Assessment</span>
            {assessStage === "done"
              ? <span className="s1-state s1-state--resolved">Done</span>
              : assessStage === "active"
                ? <span className="s1-state s1-state--active">In progress</span>
                : <span className="s1-stage-card__icon-slot" aria-hidden><IconArrowRight size={16} /></span>}
          </span>
          <span className="s1-stage-card__big">
            {assessDone}
            <span className="s1-stage-card__big-sub"> / {assessTotal}</span>
          </span>
          {useSegments ? (
            <span
              className="s1-stage-card__segments"
              aria-hidden
              style={{ gridTemplateColumns: `repeat(${assessTotal}, minmax(0, 1fr))` }}
            >
              {Array.from({ length: assessTotal }, (_, i) => (
                <span
                  key={i}
                  className={`s1-stage-card__seg${i < assessDone ? " s1-stage-card__seg--done" : ""}`}
                />
              ))}
            </span>
          ) : (
            <span className="s1-stage-card__bar-track" aria-hidden>
              <span className="s1-stage-card__bar-fill" style={{ width: `${assessPct}%` }} />
            </span>
          )}
          <span className="s1-stage-card__caption">results examined · {assessStatus}</span>
        </button>

        {/* D: Opinion — always pending */}
        <button type="button" className="s1-stage-card" onClick={go("output")}>
          <span className="s1-stage-card__top">
            <span className="s1-stage-card__name">Opinion</span>
            {opinionStage === "done"
              ? <span className="s1-state s1-state--resolved">Done</span>
              : opinionStage === "active"
                ? <span className="s1-state s1-state--active">In progress</span>
                : <span className="s1-stage-card__icon-slot" aria-hidden><IconArrowRight size={16} /></span>}
          </span>
          <span className="s1-stage-card__state">Not issued</span>
          <span className="s1-stage-card__bar-striped" aria-hidden />
          <span className="s1-stage-card__caption">Issued after assessment</span>
        </button>
      </section>

      <section className="s1-attention" aria-labelledby="s1-attention-title">
        <h2 id="s1-attention-title">Needs attention</h2>
        {attention.length ? (
          <ul className="s1-attention__list">
            {attention.map((item) => (
              <li key={item.key}>
                <button className={`s1-attention__item s1-attention__item--${item.tone}`} type="button" onClick={go(item.nav)}>
                  <span className="s1-attention__icon" aria-hidden>
                    {item.icon}
                  </span>
                  <span className="s1-attention__n">{item.uncounted ? null : item.n}</span>
                  <span className="s1-attention__what">{item.text}</span>
                  <span className="s1-attention__go">
                    {item.action}
                    <ChevronRight aria-hidden />
                  </span>
                </button>
              </li>
            ))}
          </ul>
        ) : (
          <p className="s1-attention__none">
            <Check aria-hidden /> Nothing needs you right now.
          </p>
        )}
      </section>
    </section>
  );
}

/* ============================ needs attention ============================ */

interface Attention {
  key: string;
  tone: "blocking" | "open" | "waiting";
  icon: ReactNode;
  /** How many; the row shows while this is above zero. */
  n: number;
  /** A row whose text says it all, such as the reporting period or the reported totals, shows no count. */
  uncounted?: boolean;
  text: string;
  action: string;
  nav: NavKey;
}

function attentionItems(f: DashboardFigures): Attention[] {
  const plural = (n: number, one: string, many: string) => (n === 1 ? one : many);
  const items: Attention[] = [
    {
      key: "blocked",
      tone: "blocking",
      icon: <CircleAlert />,
      n: f.blockedDocuments,
      text: plural(f.blockedDocuments, "document can't be read", "documents can't be read"),
      action: "Evidence",
      nav: "evidence",
    },
    {
      key: "period",
      tone: "open",
      icon: <CalendarRange />,
      n: f.reportingPeriodIncomplete ? 1 : 0,
      uncounted: true,
      text: "Reporting period needs a start and an end date",
      action: "Setup",
      nav: "setup",
    },
    {
      key: "unresolved",
      tone: "open",
      icon: <FileQuestion />,
      n: f.documentsNeedingYou,
      text: plural(f.documentsNeedingYou, "document needs a type or facility", "documents need a type or facility"),
      action: "Evidence",
      nav: "evidence",
    },
    {
      key: "review",
      tone: "open",
      icon: <ListChecks />,
      n: f.valuesToReview,
      text: plural(f.valuesToReview, "value waiting for review", "values waiting for review"),
      action: "Review",
      nav: "evidence",
    },
    {
      key: "missing",
      tone: "open",
      icon: <ShieldAlert />,
      n: f.coverage?.missing ?? 0,
      text: plural(f.coverage?.missing ?? 0, "data point missing evidence", "data points missing evidence"),
      action: "Coverage",
      nav: "requests",
    },
    {
      key: "unsent",
      tone: "open",
      icon: <Send />,
      n: f.requestsNotSent,
      text: plural(f.requestsNotSent, "request not sent yet", "requests not sent yet"),
      action: "Requests",
      nav: "requests",
    },
    {
      key: "reported",
      tone: "open",
      icon: <PencilLine />,
      n: f.reportedTotalsMissing ?? 0,
      uncounted: true,
      text: plural(f.reportedTotalsMissing ?? 0, "Reported total not entered", "Reported totals not entered"),
      action: "Results",
      nav: "results",
    },
    {
      key: "examine",
      tone: "open",
      icon: <Scale />,
      n: Math.max(f.dataPointsCalculated - f.dataPointsExamined, 0),
      text: plural(f.dataPointsCalculated - f.dataPointsExamined, "result not examined yet", "results not examined yet"),
      action: "Results",
      nav: "results",
    },
    {
      key: "awaiting",
      tone: "waiting",
      icon: <Hourglass />,
      n: f.requestsAwaitingClient,
      text: plural(f.requestsAwaitingClient, "request waiting on the client", "requests waiting on the client"),
      action: "Requests",
      nav: "requests",
    },
  ];
  return items.filter((item) => item.n > 0);
}

/* =============================== timeline =============================== */

type PhaseStatus = "done" | "active" | "pending";
interface Phase {
  key: string;
  status: PhaseStatus;
  nav: NavKey;
}

function buildPhases(hasEngagement: boolean, f: DashboardFigures): Phase[] {
  const hasEvidence = f.documents > 0;
  const reviewable = f.valuesReviewed + f.valuesToReview;
  const missing = f.coverage?.missing ?? 0;

  const intake: PhaseStatus = !hasEvidence
    ? hasEngagement ? "active" : "pending"
    : f.blockedDocuments || f.documentsNeedingYou || missing || f.requestsAwaitingClient || f.requestsNotSent
      ? "active"
      : "done";
  const review: PhaseStatus = !reviewable ? "pending" : f.valuesToReview ? "active" : "done";
  const assessment: PhaseStatus =
    f.dataPointsCalculated === 0 && !f.coverage?.present
      ? "pending"
      : f.dataPointsCalculated > 0 &&
          f.dataPointsExamined >= f.dataPointsCalculated &&
          missing === 0 &&
          !f.reportedTotalsMissing
        ? "done"
        : review === "pending"
          ? "pending"
          : "active";

  const phases: Phase[] = [
    { key: "setup",      status: hasEngagement ? "done" : "active", nav: "setup" },
    { key: "intake",     status: intake,                             nav: "evidence" },
    { key: "review",     status: review,                             nav: "evidence" },
    { key: "assessment", status: assessment,                         nav: "results" },
    { key: "opinion",    status: "pending",                          nav: "output" },
  ];
  // Only the first unfinished phase is current; later ones keep their computed status.
  let seenOpen = false;
  return phases.map((phase) => {
    if (phase.status === "done") return phase;
    if (seenOpen) return phase;
    seenOpen = true;
    return { ...phase, status: "active" };
  });
}

/* =============================== helpers =============================== */

function shortRegulation(regulation: string): string {
  return regulation.split(":")[0];
}

