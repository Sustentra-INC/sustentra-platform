"use client";

import type { ReactNode } from "react";

import type { EngagementConfig } from "../types";
import type { NavKey } from "./S1Chrome";

export interface DashboardMetrics {
  documents: number;
  openRequests: number;
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
            {hasEngagement && engagement.regulation
              ? `${engagement.regulation}${engagement.reportingPeriod.start ? ` · ${engagement.reportingPeriod.start} to ${engagement.reportingPeriod.end}` : ""}`
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
        <Kpi icon={<CheckIcon />} label="Values reviewed" value="—" sub="awaiting extraction" tone="accent" onClick={go("evidence")} />
        <Kpi icon={<MailIcon />} label="Open requests" value={String(metrics.openRequests)} sub={metrics.openRequests === 0 ? "none open" : "awaiting client"} tone="open" onClick={go("requests")} />
        <Kpi icon={<ShieldIcon />} label="Coverage ready" value="—" sub="awaiting coverage run" onClick={go("coverage")} />
      </div>

      {/* Visualizations — populate from backend verification/coverage; empty until then */}
      <div className="s1-dash-grid">
        <div className="s1-dash-card">
          <div className="s1-dash-card__head">
            <h2>Verified emissions by category</h2>
            <span className="s1-muted">tCO2e · reporting year</span>
          </div>
          <EmptyViz label="Verified emissions appear here once verification results are computed." />
        </div>

        <div className="s1-dash-card">
          <div className="s1-dash-card__head">
            <h2>Assurance coverage</h2>
            <button className="s1-linklike" type="button" onClick={go("coverage")}>
              Open
            </button>
          </div>
          <EmptyViz label="Coverage appears here once the evidence is checked." />
        </div>
      </div>

      {/* Phases + activity */}
      <div className="s1-dash-grid">
        <div className="s1-dash-card">
          <div className="s1-dash-card__head">
            <h2>Verification phases</h2>
          </div>
          <PhaseTracker hasEngagement={hasEngagement} hasEvidence={hasEvidence} onNavigate={onNavigate} />
        </div>

        <div className="s1-dash-card">
          <div className="s1-dash-card__head">
            <h2>Recent activity</h2>
          </div>
          <p className="s1-muted s1-dash-emptyline">No activity yet.</p>
        </div>
      </div>
    </section>
  );
}

function EmptyViz({ label }: { label: string }) {
  return <p className="s1-muted s1-dash-emptyline">{label}</p>;
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
// all "Not started"; Setup completes once an engagement exists; intake/review
// becomes active once evidence is present.
function buildPhases(hasEngagement: boolean, hasEvidence: boolean): Phase[] {
  const setup: Phase["status"] = hasEngagement ? "completed" : "active";
  const intake: Phase["status"] = hasEvidence ? "active" : "pending";
  const stepState = (s: Phase["status"]): "Completed" | "Active" | "Pending" =>
    s === "completed" ? "Completed" : s === "active" ? "Active" : "Pending";
  return [
    { key: "setup", label: "Setup", status: setup, icon: <GearIcon />, steps: [{ label: "Engagement configured", state: stepState(setup), nav: "setup" }] },
    {
      key: "intake",
      label: "Evidence intake",
      status: intake,
      icon: <InboxIcon />,
      steps: [
        { label: "Documents uploaded", state: stepState(intake), nav: "upload" },
        { label: "Evidence workspace", state: stepState(intake), nav: "evidence" },
      ],
    },
    {
      key: "review",
      label: "Review",
      status: "pending",
      icon: <BoltIcon />,
      steps: [
        { label: "Extraction review", state: "Pending", nav: "evidence" },
        { label: "Evidence requests", state: "Pending", nav: "requests" },
      ],
    },
    {
      key: "assessment",
      label: "Assessment",
      status: "pending",
      icon: <ShieldIcon />,
      steps: [
        { label: "Check coverage", state: "Pending", nav: "coverage" },
        { label: "Verification results", state: "Pending", nav: "results" },
      ],
    },
    { key: "opinion", label: "Opinion", status: "pending", icon: <DocIcon />, steps: [{ label: "Assurance statement", state: "Pending", nav: "output" }] },
  ];
}

function PhaseTracker({ hasEngagement, hasEvidence, onNavigate }: { hasEngagement: boolean; hasEvidence: boolean; onNavigate?: (k: NavKey) => void }) {
  return (
    <ol className="s1-phases">
      {buildPhases(hasEngagement, hasEvidence).map((p) => (
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
