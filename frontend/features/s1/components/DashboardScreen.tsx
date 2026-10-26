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
import type { ReactNode } from "react";

import type { EngagementConfig } from "../types";
import type { DashboardFigures } from "../utils/engagementActivity";
import { formatReportingPeriod } from "../utils/formatPeriod";
import type { NavKey } from "./S1Chrome";

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
  const phases = buildPhases(hasEngagement, figures);
  const coverage = figures.coverage;
  const covered = coverage ? coverage.present + coverage.missing : 0;
  // Data points once an evidence check is in play; until then, the documents read.
  const byDataPoint = coverage !== null && covered > 0;
  const reviewable = figures.valuesReviewed + figures.valuesToReview;
  const attention = attentionItems(figures);

  return (
    <section className="s1-content s1-dash">
      <header className="s1-dash__head">
        <div className="s1-dash__id">
          <h1>{hasEngagement ? engagement.clientName : "New engagement"}</h1>
          <p className="s1-dash__meta">
            {hasEngagement
              ? [
                  engagement.regulation ? shortRegulation(engagement.regulation) : null,
                  formatReportingPeriod(engagement.reportingPeriod.start, engagement.reportingPeriod.end),
                ]
                  .filter(Boolean)
                  .join(" · ")
              : "Set up the engagement to begin"}
          </p>
        </div>
      </header>

      <ol className="s1-timeline" aria-label="Engagement timeline">
        {phases.map((phase, index) => (
          <li key={phase.key} className={`s1-timeline__step s1-timeline__step--${phase.status}`}>
            <button className="s1-timeline__btn" type="button" onClick={go(phase.nav)}>
              <span className="s1-timeline__dot" aria-hidden>
                {phase.status === "done" ? <Check /> : <span>{index + 1}</span>}
              </span>
              <span className="s1-timeline__text">
                <span className="s1-timeline__label">{phase.label}</span>
                <span className="s1-timeline__caption">{phase.caption}</span>
              </span>
            </button>
          </li>
        ))}
      </ol>

      <div className="s1-dash__meters">
        <Meter
          label="Evidence obtained"
          done={byDataPoint ? coverage.present : figures.documentsReadable}
          total={byDataPoint ? covered : figures.documents}
          detail={
            byDataPoint
              ? `${coverage.present} of ${covered} in-scope data points have their evidence`
              : figures.documents
                ? `${figures.documentsReadable} of ${figures.documents} documents read`
                : "Nothing uploaded yet"
          }
          onClick={go("requests")}
        />
        <Meter
          label="Values reviewed"
          done={figures.valuesReviewed}
          total={reviewable}
          detail={
            reviewable
              ? `${figures.valuesReviewed} of ${reviewable} values accepted or corrected`
              : "No values read yet"
          }
          onClick={go("evidence")}
        />
      </div>

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

/* =============================== meters =============================== */

function Meter({
  label,
  done,
  total,
  detail,
  onClick,
}: {
  label: string;
  done: number;
  total: number;
  detail: string;
  onClick: () => void;
}) {
  const share = total > 0 ? done / total : 0;
  return (
    <button className="s1-meter" type="button" onClick={onClick}>
      <span className="s1-meter__label">{label}</span>
      <span className="s1-meter__figure">
        {done > 0 && share < 0.01 ? "<1" : Math.round(share * 100)}
        <span className="s1-meter__unit">%</span>
      </span>
      <span className="s1-meter__track" aria-hidden>
        <span className="s1-meter__fill" style={{ transform: `scaleX(${share})` }} />
      </span>
      <span className="s1-meter__detail">{detail}</span>
    </button>
  );
}

/* =============================== timeline =============================== */

type PhaseStatus = "done" | "active" | "pending";
interface Phase {
  key: string;
  label: string;
  status: PhaseStatus;
  caption: string;
  nav: NavKey;
}

function buildPhases(hasEngagement: boolean, f: DashboardFigures): Phase[] {
  const hasEvidence = f.documents > 0;
  const reviewable = f.valuesReviewed + f.valuesToReview;
  const missing = f.coverage?.missing ?? 0;

  const intake: PhaseStatus = !hasEvidence
    ? hasEngagement
      ? "active"
      : "pending"
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
    { key: "setup", label: "Setup", status: hasEngagement ? "done" : "active", caption: hasEngagement ? "Done" : "To do", nav: "setup" },
    {
      key: "intake",
      label: "Evidence intake",
      status: intake,
      caption: hasEvidence ? `${f.documents} documents in` : "Nothing uploaded yet",
      nav: "evidence",
    },
    {
      key: "review",
      label: "Review",
      status: review,
      caption: !reviewable ? "Waiting for evidence" : f.valuesToReview ? `${f.valuesToReview} values to review` : "All values reviewed",
      nav: "evidence",
    },
    {
      key: "assessment",
      label: "Assessment",
      status: assessment,
      caption: f.dataPointsCalculated
        ? `${f.dataPointsExamined} of ${f.dataPointsCalculated} results examined`
        : missing
          ? `${missing} data points missing evidence`
          : "Not started",
      nav: "results",
    },
    { key: "opinion", label: "Opinion", status: "pending", caption: "Statement not issued", nav: "output" },
  ];
  // Only the first unfinished phase is current; later ones wait their turn.
  let seenOpen = false;
  return phases.map((phase) => {
    if (phase.status === "done") return phase;
    if (seenOpen) return { ...phase, status: phase.status === "active" ? "active" : "pending" };
    seenOpen = true;
    return { ...phase, status: "active" };
  });
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

/* =============================== helpers =============================== */

function shortRegulation(regulation: string): string {
  return regulation.split(":")[0];
}

