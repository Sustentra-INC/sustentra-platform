"use client";

import type { ReactNode } from "react";

import type { EngagementConfig } from "../types";
import type { NavKey } from "./S1Chrome";

export interface DashboardMetrics {
  documents: number;
  openRequests: number;
  /** Backend mode: the live state behind the figures below (absent: they show "—"). */
  live?: LiveDashboard;
}

export interface LiveDashboard {
  valuesReviewed: number;
  valuesToReview: number;
  blockedDocuments: number;
  requestsRaised: number;
  requestsResolved: number;
  /** Recalculated t CO2e per category, null when nothing is calculated yet. */
  emissions: { label: string; value: number }[] | null;
  coverage: { present: number; missing: number; notApplicable: number; outOfScope: number } | null;
  dataPointsExamined: number;
  dataPointsCalculated: number;
  findings: number;
  /** Newest first. */
  activity: { at: string; who: string; what: string }[];
}

/**
 * Dashboard (landing). A one-glance view of the engagement. Figures are derived
 * from live workpaper state — no templated data. Before any engagement is set up
 * or evidence is uploaded, it shows empty states and points the user to Setup /
 * Upload. The emissions and coverage visualizations populate once the backend
 * returns verification results and coverage (not available until then).
 */
export function DashboardScreen({
  engagement,
  metrics,
  onNavigate,
}: {
  engagement: EngagementConfig;
  metrics: DashboardMetrics;
  onNavigate?: (key: NavKey) => void;
}) {
  const go = (k: NavKey) => () => onNavigate?.(k);
  const hasEngagement = Boolean(engagement.clientName);
  const hasEvidence = metrics.documents > 0;

  return (
    <section className="s1-content s1-dash">
      <header className="s1-ws-header">
        <div className="s1-ws-header__id">
          <h1>{hasEngagement ? engagement.clientName : "New engagement"}</h1>
          <span className="s1-muted">
            {hasEngagement
              ? [
                  engagement.regulation || "Regulation not set",
                  engagement.reportingPeriod.start
                    ? `${engagement.reportingPeriod.start} to ${engagement.reportingPeriod.end}`
                    : "Reporting period not set",
                ].join(" · ")
              : "Set up the engagement to begin"}
          </span>
        </div>
        <span className={`s1-state ${hasEvidence ? "s1-state--active" : "s1-state--na"} s1-dash-phasebadge`}>
          {hasEvidence ? "Execution · in progress" : "Not started"}
        </span>
      </header>

      {!hasEngagement || !hasEvidence ? (
        <div className="s1-dash-empty" role="note">
          <ShieldIcon />
          <div>
            <strong>{hasEngagement ? "No evidence yet." : "Nothing here yet."}</strong>{" "}
            {hasEngagement
              ? "Upload documents to begin extraction — figures appear here as evidence is processed."
              : "Configure the engagement in Setup, then upload documents to start extraction."}
          </div>
          <div className="s1-dash-empty__actions">
            <button className="s1-button" type="button" onClick={go(hasEngagement ? "upload" : "setup")}>
              {hasEngagement ? "Upload documents" : "Go to Setup"}
            </button>
          </div>
        </div>
      ) : null}

      {/* KPIs — derived from live state; "—" where the backend has not supplied a figure yet */}
      <div className="s1-dash-kpis">
        <Kpi icon={<DocIcon />} label="Documents held" value={String(metrics.documents)} sub={metrics.documents === 1 ? "document" : "documents"} onClick={go("evidence")} />
        <Kpi
          icon={<CheckIcon />}
          label="Values reviewed"
          value={metrics.live ? String(metrics.live.valuesReviewed) : "—"}
          sub={
            metrics.live
              ? metrics.live.valuesToReview
                ? `${metrics.live.valuesToReview} still to review`
                : metrics.live.valuesReviewed
                  ? "all reviewed"
                  : "nothing extracted yet"
              : "awaiting extraction"
          }
          tone="accent"
          onClick={go("evidence")}
        />
        <Kpi icon={<MailIcon />} label="Open requests" value={String(metrics.openRequests)} sub={metrics.openRequests === 0 ? "none open" : "awaiting client"} tone="open" onClick={go("requests")} />
        <Kpi
          icon={<ShieldIcon />}
          label="Checks ready"
          value={metrics.live?.coverage ? String(metrics.live.coverage.present) : "—"}
          sub={
            metrics.live?.coverage
              ? `${metrics.live.coverage.missing} missing an input`
              : "awaiting coverage run"
          }
          onClick={go("coverage")}
        />
      </div>

      {/* Visualizations — populate from backend verification/coverage; empty until then */}
      <div className="s1-dash-grid">
        <div className="s1-dash-card">
          <div className="s1-dash-card__head">
            <h2>Recalculated emissions by category</h2>
            <span className="s1-muted">tCO2e · reporting year</span>
          </div>
          {metrics.live?.emissions?.length ? (
            <EmissionsBars rows={metrics.live.emissions} />
          ) : (
            <EmptyViz label="Recalculated emissions appear here once values are reviewed." />
          )}
        </div>

        <div className="s1-dash-card">
          <div className="s1-dash-card__head">
            <h2>Assurance coverage</h2>
            <button className="s1-linklike" type="button" onClick={go("coverage")}>
              Open
            </button>
          </div>
          {metrics.live?.coverage ? (
            <CoverageBar coverage={metrics.live.coverage} />
          ) : (
            <EmptyViz label="Coverage appears here once the evidence is checked." />
          )}
        </div>
      </div>

      {/* Phases + activity */}
      <div className="s1-dash-grid">
        <div className="s1-dash-card">
          <div className="s1-dash-card__head">
            <h2>Verification phases</h2>
          </div>
          <PhaseTracker hasEngagement={hasEngagement} hasEvidence={hasEvidence} live={metrics.live} onNavigate={onNavigate} />
        </div>

        <div className="s1-dash-card">
          <div className="s1-dash-card__head">
            <h2>Recent activity</h2>
          </div>
          {metrics.live?.activity.length ? (
            <ul className="s1-dash-activity">
              {metrics.live.activity.map((a, i) => (
                <li key={`${a.at}|${i}`}>
                  <span className="s1-dash-activity__what">
                    <strong>{a.who}</strong> {a.what}
                  </span>
                  <span className="s1-mono s1-muted">{when(a.at)}</span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="s1-muted s1-dash-emptyline">No activity yet.</p>
          )}
        </div>
      </div>
    </section>
  );
}

function EmptyViz({ label }: { label: string }) {
  return <p className="s1-muted s1-dash-emptyline">{label}</p>;
}

function when(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
}

/** One bar per category on a shared scale (the largest category fills the track). */
function EmissionsBars({ rows }: { rows: { label: string; value: number }[] }) {
  const max = Math.max(...rows.map((r) => r.value), 0) || 1;
  return (
    <ul className="s1-dash-bars">
      {rows.map((r) => (
        <li key={r.label}>
          <span className="s1-dash-bars__label">{r.label}</span>
          <span className="s1-dash-bars__track" aria-hidden>
            <span className="s1-dash-bars__fill" style={{ width: `${Math.max((r.value / max) * 100, r.value > 0 ? 1 : 0)}%` }} />
          </span>
          <span className="s1-dash-bars__value s1-mono">
            {r.value.toLocaleString(undefined, { maximumFractionDigits: 2 })} t
          </span>
        </li>
      ))}
    </ul>
  );
}

function CoverageBar({ coverage }: { coverage: NonNullable<LiveDashboard["coverage"]> }) {
  const parts = [
    { key: "present", label: "Inputs present", n: coverage.present },
    { key: "missing", label: "Inputs missing", n: coverage.missing },
    { key: "na", label: "Not applicable", n: coverage.notApplicable },
    { key: "oos", label: "Out of scope", n: coverage.outOfScope },
  ];
  const total = parts.reduce((sum, p) => sum + p.n, 0) || 1;
  return (
    <div className="s1-dash-cov">
      <div className="s1-dash-cov__bar" aria-hidden>
        {parts.map((p) =>
          p.n ? <span key={p.key} className={`s1-dash-cov__seg s1-dash-cov__seg--${p.key}`} style={{ width: `${(p.n / total) * 100}%` }} /> : null
        )}
      </div>
      <ul className="s1-dash-cov__legend">
        {parts.map((p) => (
          <li key={p.key}>
            <span className={`s1-dash-cov__dot s1-dash-cov__seg--${p.key}`} aria-hidden />
            {p.label} <strong>{p.n}</strong>
          </li>
        ))}
      </ul>
    </div>
  );
}

/* =============================== KPIs =============================== */

function Kpi({
  icon,
  label,
  value,
  sub,
  tone,
  onClick,
}: {
  icon: ReactNode;
  label: string;
  value: string;
  sub: string;
  tone?: "accent" | "open";
  onClick?: () => void;
}) {
  return (
    <button className={`s1-dash-kpi${tone ? ` s1-dash-kpi--${tone}` : ""}`} type="button" onClick={onClick}>
      <span className="s1-dash-kpi__icon">{icon}</span>
      <span className="s1-dash-kpi__body">
        <span className="s1-dash-kpi__label">{label}</span>
        <span className="s1-dash-kpi__value">{value}</span>
        <span className="s1-dash-kpi__sub">{sub}</span>
      </span>
    </button>
  );
}

/* =========================== phase tracker =========================== */

type Phase = {
  key: string;
  label: string;
  status: "completed" | "active" | "pending";
  icon: ReactNode;
  steps: Array<{ label: string; state: "Completed" | "Active" | "Open" | "Pending"; nav?: NavKey }>;
};

// Phase status is derived from live progress, not hardcoded. Before Setup it is
// all "Not started"; with live state (backend mode) each step reads what was done.
function buildPhases(hasEngagement: boolean, hasEvidence: boolean, live?: LiveDashboard): Phase[] {
  const setup: Phase["status"] = hasEngagement ? "completed" : "active";
  const stepState = (s: Phase["status"]): "Completed" | "Active" | "Pending" =>
    s === "completed" ? "Completed" : s === "active" ? "Active" : "Pending";
  const phase = (states: ("Completed" | "Active" | "Open" | "Pending")[]): Phase["status"] =>
    states.every((x) => x === "Completed") ? "completed" : states.some((x) => x !== "Pending") ? "active" : "pending";

  const uploaded = hasEvidence ? "Completed" : "Pending";
  const workspace = !hasEvidence ? "Pending" : live && live.blockedDocuments === 0 ? "Completed" : "Active";
  const review = !live
    ? "Pending"
    : live.valuesReviewed > 0 && live.valuesToReview === 0
      ? "Completed"
      : live.valuesReviewed > 0
        ? "Active"
        : "Pending";
  const requests = !live || live.requestsRaised === 0
    ? "Pending"
    : live.requestsResolved === live.requestsRaised
      ? "Completed"
      : "Open";
  const coverage = !live?.coverage
    ? "Pending"
    : live.coverage.missing === 0 && live.coverage.present > 0
      ? "Completed"
      : "Active";
  const results = !live || live.dataPointsCalculated === 0
    ? "Pending"
    : live.dataPointsExamined >= live.dataPointsCalculated
      ? "Completed"
      : "Active";
  const intakeStates: ("Completed" | "Active" | "Open" | "Pending")[] = [uploaded, workspace];
  const reviewStates: ("Completed" | "Active" | "Open" | "Pending")[] = [review, requests === "Pending" ? review : requests];
  return [
    { key: "setup", label: "Setup", status: setup, icon: <GearIcon />, steps: [{ label: "Engagement configured", state: stepState(setup), nav: "setup" }] },
    {
      key: "intake",
      label: "Evidence intake",
      status: live ? phase(intakeStates) : hasEvidence ? "active" : "pending",
      icon: <InboxIcon />,
      steps: [
        { label: "Documents uploaded", state: live ? uploaded : stepState(hasEvidence ? "active" : "pending"), nav: "upload" },
        { label: "Evidence workspace", state: live ? workspace : stepState(hasEvidence ? "active" : "pending"), nav: "evidence" },
      ],
    },
    {
      key: "review",
      label: "Review",
      status: live ? phase(reviewStates) : "pending",
      icon: <BoltIcon />,
      steps: [
        { label: "Extraction review", state: review, nav: "evidence" },
        { label: "Evidence requests", state: requests, nav: "requests" },
      ],
    },
    {
      key: "assessment",
      label: "Assessment",
      status: live ? phase([coverage, results]) : "pending",
      icon: <ShieldIcon />,
      steps: [
        { label: "Check coverage", state: coverage, nav: "coverage" },
        { label: "Verification results", state: results, nav: "results" },
      ],
    },
    { key: "opinion", label: "Opinion", status: "pending", icon: <DocIcon />, steps: [{ label: "Assurance statement", state: "Pending", nav: "output" }] },
  ];
}

function PhaseTracker({
  hasEngagement,
  hasEvidence,
  live,
  onNavigate,
}: {
  hasEngagement: boolean;
  hasEvidence: boolean;
  live?: LiveDashboard;
  onNavigate?: (k: NavKey) => void;
}) {
  return (
    <ol className="s1-phases">
      {buildPhases(hasEngagement, hasEvidence, live).map((p) => (
        <li key={p.key} className={`s1-phase s1-phase--${p.status}`}>
          <div className="s1-phase__head">
            <span className="s1-phase__icon">{p.icon}</span>
            <span className="s1-phase__label">{p.label}</span>
            <span className={`s1-phase__badge s1-phase__badge--${p.status}`}>
              {p.status === "completed" ? "Completed" : p.status === "active" ? "In progress" : "Not started"}
            </span>
          </div>
          <ul className="s1-phase__steps">
            {p.steps.map((s) => (
              <li key={s.label} className="s1-phase__step">
                {s.nav ? (
                  <button className="s1-phase__steplink" type="button" onClick={() => onNavigate?.(s.nav!)}>
                    {s.label}
                  </button>
                ) : (
                  <span>{s.label}</span>
                )}
                <span className={`s1-phase__state s1-phase__state--${s.state.toLowerCase()}`}>{s.state}</span>
              </li>
            ))}
          </ul>
        </li>
      ))}
    </ol>
  );
}

/* =============================== icons =============================== */

const SVG = { fill: "none", stroke: "currentColor", strokeWidth: 1.7, strokeLinecap: "round" as const, strokeLinejoin: "round" as const };

function DocIcon() {
  return (
    <svg viewBox="0 0 24 24" {...SVG} aria-hidden="true">
      <path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z" />
      <path d="M14 3v5h5M9 13h6M9 17h6" />
    </svg>
  );
}
function CheckIcon() {
  return (
    <svg viewBox="0 0 24 24" {...SVG} aria-hidden="true">
      <path d="M20 6 9 17l-5-5" />
    </svg>
  );
}
function MailIcon() {
  return (
    <svg viewBox="0 0 24 24" {...SVG} aria-hidden="true">
      <rect x="3" y="5" width="18" height="14" rx="2" />
      <path d="m3.5 7 8.5 6 8.5-6" />
    </svg>
  );
}
function ShieldIcon() {
  return (
    <svg viewBox="0 0 24 24" {...SVG} aria-hidden="true">
      <path d="M12 3.2 5 6v5.2c0 4.3 2.9 7.2 7 8.6 4.1-1.4 7-4.3 7-8.6V6z" />
      <path d="m9 12 2.1 2.1L15.2 10" />
    </svg>
  );
}
function GearIcon() {
  return (
    <svg viewBox="0 0 24 24" {...SVG} aria-hidden="true">
      <circle cx="12" cy="12" r="3" />
      <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
    </svg>
  );
}
function InboxIcon() {
  return (
    <svg viewBox="0 0 24 24" {...SVG} aria-hidden="true">
      <path d="M4 13h4l2 3h4l2-3h4" />
      <path d="M5 5h14l2 8v5a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-5z" />
    </svg>
  );
}
function BoltIcon() {
  return (
    <svg viewBox="0 0 24 24" {...SVG} aria-hidden="true">
      <path d="M13 2 4 14h7l-1 8 9-12h-7z" />
    </svg>
  );
}
