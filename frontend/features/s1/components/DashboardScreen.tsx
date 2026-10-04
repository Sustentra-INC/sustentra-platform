"use client";

import type { ReactNode } from "react";

import type { EngagementConfig } from "../types";
import type { NavKey } from "./S1Chrome";

/**
 * Dashboard (landing). A one-glance view of the engagement: key figures, the
 * verified-emissions and coverage visualizations, the verification phase tracker
 * and recent activity. Figures are an illustrative assembly of the workpaper.
 */
export function DashboardScreen({
  engagement,
  onNavigate,
}: {
  engagement: EngagementConfig;
  onNavigate?: (key: NavKey) => void;
}) {
  const go = (k: NavKey) => () => onNavigate?.(k);

  return (
    <section className="s1-content s1-dash">
      <header className="s1-ws-header">
        <div className="s1-ws-header__id">
          <h1>{engagement.clientName}</h1>
          <span className="s1-muted">
            {engagement.regulation} · {engagement.reportingPeriod.start} to {engagement.reportingPeriod.end}
          </span>
        </div>
        <span className="s1-state s1-state--active s1-dash-phasebadge">Execution · in progress</span>
      </header>

      {/* KPIs */}
      <div className="s1-dash-kpis">
        <Kpi icon={<DocIcon />} label="Documents held" value="148" sub="across 3 facilities" onClick={go("evidence")} />
        <Kpi icon={<CheckIcon />} label="Values reviewed" value="34 / 46" sub="74% accepted" tone="accent" onClick={go("evidence")} />
        <Kpi icon={<MailIcon />} label="Open requests" value="3" sub="1 sent · 2 raised" tone="open" onClick={go("requests")} />
        <Kpi icon={<ShieldIcon />} label="Coverage ready" value="58%" sub="34 of 59 checks" onClick={go("coverage")} />
      </div>

      {/* Visualizations */}
      <div className="s1-dash-grid">
        <div className="s1-dash-card">
          <div className="s1-dash-card__head">
            <h2>Verified emissions by category</h2>
            <span className="s1-muted">tCO2e · reporting year</span>
          </div>
          <EmissionsBars />
        </div>

        <div className="s1-dash-card">
          <div className="s1-dash-card__head">
            <h2>Assurance coverage</h2>
            <button className="s1-linklike" type="button" onClick={go("coverage")}>
              Open
            </button>
          </div>
          <CoverageDonut />
        </div>
      </div>

      {/* Phases + activity */}
      <div className="s1-dash-grid">
        <div className="s1-dash-card">
          <div className="s1-dash-card__head">
            <h2>Verification phases</h2>
          </div>
          <PhaseTracker onNavigate={onNavigate} />
        </div>

        <div className="s1-dash-card">
          <div className="s1-dash-card__head">
            <h2>Recent activity</h2>
          </div>
          <ActivityFeed onNavigate={onNavigate} />
        </div>
      </div>
    </section>
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

/* =========================== emissions bars =========================== */

const EMISSIONS = [
  { label: "Scope 1 stationary", value: 2140.3, varName: "--chart-1" },
  { label: "Scope 1 mobile", value: 486.9, varName: "--chart-5" },
  { label: "Scope 2 location", value: 3910.4, varName: "--chart-4" },
  { label: "Scope 2 market", value: 4205.1, varName: "--chart-2" },
];

function EmissionsBars() {
  const max = Math.max(...EMISSIONS.map((e) => e.value));
  return (
    <div className="s1-bars" role="img" aria-label="Verified emissions by category, tonnes CO2e">
      {EMISSIONS.map((e) => (
        <div className="s1-bars__col" key={e.label}>
          <div className="s1-bars__track">
            <div
              className="s1-bars__fill"
              style={{ height: `${(e.value / max) * 100}%`, background: `var(${e.varName})` }}
            >
              <span className="s1-bars__val">{e.value.toLocaleString()}</span>
            </div>
          </div>
          <div className="s1-bars__label">{e.label}</div>
        </div>
      ))}
    </div>
  );
}

/* =========================== coverage donut =========================== */

const COVERAGE = [
  { label: "Inputs present", value: 34, varName: "--state-resolved-fg" },
  { label: "Inputs missing", value: 12, varName: "--state-open-fg" },
  { label: "Not applicable", value: 8, varName: "--state-na-fg" },
  { label: "Out of scope", value: 5, varName: "--state-unverifiable-fg" },
];

function CoverageDonut() {
  const total = COVERAGE.reduce((s, c) => s + c.value, 0);
  const R = 54;
  const C = 2 * Math.PI * R;
  let offset = 0;
  const segments = COVERAGE.map((c) => {
    const len = (c.value / total) * C;
    const seg = { ...c, dash: len, gap: C - len, off: offset };
    offset -= len;
    return seg;
  });
  return (
    <div className="s1-donut">
      <svg viewBox="0 0 140 140" className="s1-donut__svg" role="img" aria-label="Assurance coverage breakdown">
        <circle cx="70" cy="70" r={R} fill="none" stroke="var(--sf-inset)" strokeWidth="16" />
        {segments.map((s) => (
          <circle
            key={s.label}
            cx="70"
            cy="70"
            r={R}
            fill="none"
            stroke={`var(${s.varName})`}
            strokeWidth="16"
            strokeDasharray={`${s.dash} ${s.gap}`}
            strokeDashoffset={s.off}
            transform="rotate(-90 70 70)"
            strokeLinecap="butt"
          />
        ))}
        <text x="70" y="68" textAnchor="middle" fontSize="26" fontWeight="700" className="s1-donut__num">
          {total}
        </text>
        <text x="70" y="86" textAnchor="middle" fontSize="9" letterSpacing="1" className="s1-donut__cap">
          CHECKS
        </text>
      </svg>
      <ul className="s1-donut__legend">
        {COVERAGE.map((c) => (
          <li key={c.label}>
            <span className="s1-donut__dot" style={{ background: `var(${c.varName})` }} />
            <span className="s1-donut__lbl">{c.label}</span>
            <span className="s1-donut__n">{c.value}</span>
          </li>
        ))}
      </ul>
    </div>
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

const PHASES: Phase[] = [
  {
    key: "setup",
    label: "Setup",
    status: "completed",
    icon: <GearIcon />,
    steps: [{ label: "Engagement configured", state: "Completed", nav: "setup" }],
  },
  {
    key: "intake",
    label: "Evidence intake",
    status: "completed",
    icon: <InboxIcon />,
    steps: [
      { label: "Documents uploaded", state: "Completed", nav: "upload" },
      { label: "Evidence workspace", state: "Completed", nav: "evidence" },
    ],
  },
  {
    key: "review",
    label: "Review",
    status: "active",
    icon: <BoltIcon />,
    steps: [
      { label: "Extraction review", state: "Active", nav: "evidence" },
      { label: "Evidence requests", state: "Open", nav: "requests" },
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
  {
    key: "opinion",
    label: "Opinion",
    status: "pending",
    icon: <DocIcon />,
    steps: [{ label: "Assurance statement", state: "Pending", nav: "output" }],
  },
];

function PhaseTracker({ onNavigate }: { onNavigate?: (k: NavKey) => void }) {
  return (
    <ol className="s1-phases">
      {PHASES.map((p) => (
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

/* =========================== activity feed =========================== */

const ACTIVITY: Array<{ tone: string; text: string; when: string; nav?: NavKey }> = [
  { tone: "resolved", text: "kent_electricity_feb_2025.pdf extracted · 6 values found", when: "just now", nav: "evidence" },
  { tone: "active", text: "Kent Cannery electricity accepted as read", when: "2m ago", nav: "evidence" },
  { tone: "open", text: "Request 1 sent to Cascade Provisions · 2 items", when: "1h ago", nav: "requests" },
  { tone: "blocking", text: "scan_0417.pdf blocked · scan is unreadable", when: "3h ago", nav: "evidence" },
  { tone: "resolved", text: "Modesto Bottling diesel correction posted", when: "yesterday", nav: "results" },
];

function ActivityFeed({ onNavigate }: { onNavigate?: (k: NavKey) => void }) {
  return (
    <ul className="s1-feed">
      {ACTIVITY.map((a, i) => (
        <li key={i} className="s1-feed__row">
          <span className={`s1-feed__dot s1-feed__dot--${a.tone}`} aria-hidden />
          <button className="s1-feed__text" type="button" onClick={() => a.nav && onNavigate?.(a.nav)}>
            {a.text}
          </button>
          <span className="s1-feed__when">{a.when}</span>
        </li>
      ))}
    </ul>
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
