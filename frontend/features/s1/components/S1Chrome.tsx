"use client";

import { useState, type ReactNode } from "react";

import type { EngagementConfig } from "../types";

export type NavKey =
  | "dashboard"
  | "setup"
  | "upload"
  | "evidence"
  | "requests"
  | "coverage"
  | "results"
  | "output";

interface S1ChromeProps {
  engagement: EngagementConfig;
  children: ReactNode;
  current?: NavKey;
  onNavigate?: (key: NavKey) => void;
  onOpenGlossary?: () => void;
  onReset?: () => void;
}

export function PersistentRail({
  engagement,
  onOpenGlossary,
  onReset,
  collapsed = false,
  onToggle,
}: {
  engagement: EngagementConfig;
  onOpenGlossary?: () => void;
  onReset?: () => void;
  collapsed?: boolean;
  onToggle?: () => void;
}) {
  return (
    <aside className={`s1-rail${collapsed ? " s1-rail--collapsed" : ""}`}>
      <button
        className="s1-rail__toggle"
        type="button"
        onClick={onToggle}
        aria-label={collapsed ? "Expand engagement panel" : "Collapse engagement panel"}
        title={collapsed ? "Expand" : "Collapse"}
      >
        <ChevronsIcon collapsed={collapsed} />
      </button>
      <h1 className="s1-rail__brand">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img className="s1-rail__logo" src="/sustentra-logo.png" alt="Sustentra" />
      </h1>
      <RailItem label="Client" value={engagement.clientName} />
      <RailItem label="Engagement ID" value={engagement.engagementId} mono />
      <RailItem
        label="Reporting period"
        value={`${engagement.reportingPeriod.start} to ${engagement.reportingPeriod.end}`}
      />
      <RailItem label="Regulation" value={engagement.regulation} />
      <RailItem label="Assurance level" value={engagement.assuranceLevel} />
      <RailItem label="Boundary approach" value={engagement.boundaryApproach} />
      <div className="s1-rail__section">
        <button className="s1-linklike" type="button" onClick={onOpenGlossary}>
          Glossary
        </button>
      </div>
      {onReset ? (
        <div className="s1-rail__reset">
          <button
            className="s1-rail__reset-btn"
            type="button"
            onClick={() => {
              if (window.confirm("Reset the workspace to the start? This clears the current session.")) onReset();
            }}
          >
            <ResetIcon />
            Reset workspace
          </button>
        </div>
      ) : null}
    </aside>
  );
}

function ChevronsIcon({ collapsed }: { collapsed: boolean }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      {collapsed ? <path d="m9 6 6 6-6 6M4 6l6 6-6 6" /> : <path d="m15 6-6 6 6 6M20 6l-6 6 6 6" />}
    </svg>
  );
}

function ResetIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M3 12a9 9 0 1 0 3-6.7L3 8" />
      <path d="M3 3v5h5" />
    </svg>
  );
}

function RailItem({ label, value, mono = false }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="s1-rail__section">
      <div className="s1-label">{label}</div>
      <div className={`s1-value ${mono ? "s1-mono" : ""}`}>{value}</div>
    </div>
  );
}

const DESTINATIONS: Array<{ key: NavKey; label: string; built: boolean }> = [
  { key: "dashboard", label: "Dashboard", built: true },
  { key: "setup", label: "Setup", built: true },
  { key: "upload", label: "Upload", built: true },
  { key: "evidence", label: "Evidence", built: true },
  { key: "requests", label: "Requests", built: true },
  { key: "coverage", label: "Check coverage", built: true },
  { key: "results", label: "Verification results", built: true },
  { key: "output", label: "Output", built: true },
];

export function PrimaryNav({
  current = "evidence",
  onNavigate,
}: {
  current?: NavKey;
  onNavigate?: (key: NavKey) => void;
}) {
  return (
    <nav className="s1-nav" aria-label="Primary">
      {DESTINATIONS.map((dest) => (
        <button
          key={dest.key}
          className="s1-tab"
          type="button"
          aria-current={current === dest.key ? "page" : undefined}
          onClick={() => onNavigate?.(dest.key)}
        >
          <span className="s1-tab__icon"><NavIcon nav={dest.key} /></span>
          {dest.label}
        </button>
      ))}
    </nav>
  );
}

function NavIcon({ nav }: { nav: NavKey }) {
  const p = { fill: "none", stroke: "currentColor", strokeWidth: 1.7, strokeLinecap: "round" as const, strokeLinejoin: "round" as const };
  switch (nav) {
    case "dashboard":
      return <svg viewBox="0 0 24 24" {...p} aria-hidden="true"><rect x="3" y="3" width="7" height="9" rx="1" /><rect x="14" y="3" width="7" height="5" rx="1" /><rect x="14" y="12" width="7" height="9" rx="1" /><rect x="3" y="16" width="7" height="5" rx="1" /></svg>;
    case "setup":
      return <svg viewBox="0 0 24 24" {...p} aria-hidden="true"><circle cx="12" cy="12" r="3" /><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" /></svg>;
    case "upload":
      return <svg viewBox="0 0 24 24" {...p} aria-hidden="true"><path d="M12 15V4m0 0 4 4m-4-4-4 4" /><path d="M4 17v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2" /></svg>;
    case "evidence":
      return <svg viewBox="0 0 24 24" {...p} aria-hidden="true"><path d="M4 4h6l2 2h8v12a2 2 0 0 1-2 2H4z" /><path d="M8 13h8M8 17h5" /></svg>;
    case "requests":
      return <svg viewBox="0 0 24 24" {...p} aria-hidden="true"><rect x="3" y="5" width="18" height="14" rx="2" /><path d="m3.5 7 8.5 6 8.5-6" /></svg>;
    case "coverage":
      return <svg viewBox="0 0 24 24" {...p} aria-hidden="true"><path d="M12 3.2 5 6v5.2c0 4.3 2.9 7.2 7 8.6 4.1-1.4 7-4.3 7-8.6V6z" /><path d="m9 12 2.1 2.1L15.2 10" /></svg>;
    case "results":
      return <svg viewBox="0 0 24 24" {...p} aria-hidden="true"><path d="M4 20V4M4 20h16" /><path d="M8 16v-4M12 16V8M16 16v-6" /></svg>;
    case "output":
      return <svg viewBox="0 0 24 24" {...p} aria-hidden="true"><path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z" /><path d="M14 3v5h5M9 13h6M9 17h6" /></svg>;
  }
}

export function S1Chrome({ engagement, children, current, onNavigate, onOpenGlossary, onReset }: S1ChromeProps) {
  const [railCollapsed, setRailCollapsed] = useState(false);
  return (
    <div className={`s1-screen${railCollapsed ? " is-railcollapsed" : ""}`}>
      <PersistentRail
        engagement={engagement}
        onOpenGlossary={onOpenGlossary}
        onReset={onReset}
        collapsed={railCollapsed}
        onToggle={() => setRailCollapsed((v) => !v)}
      />
      <section className="s1-main">
        <PrimaryNav current={current} onNavigate={onNavigate} />
        {children}
      </section>
    </div>
  );
}
