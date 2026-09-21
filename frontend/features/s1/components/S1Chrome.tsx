"use client";

import { useState, type ReactNode } from "react";

import type { EngagementConfig } from "../types";
import { AssistantWidget } from "./AssistantWidget";

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

const DESTINATIONS: Array<{ key: NavKey; label: string }> = [
  { key: "dashboard", label: "Dashboard" },
  { key: "setup", label: "Setup" },
  { key: "upload", label: "Upload" },
  { key: "evidence", label: "Evidence" },
  { key: "requests", label: "Requests" },
  { key: "coverage", label: "Check coverage" },
  { key: "results", label: "Verification results" },
  { key: "output", label: "Output" },
];

export function S1Chrome({ engagement, children, current, onNavigate, onOpenGlossary, onReset }: S1ChromeProps) {
  const [navExpanded, setNavExpanded] = useState(true);
  const [ctxExpanded, setCtxExpanded] = useState(false);
  return (
    <div className="s1-shell">
      <Sidebar
        current={current}
        onNavigate={onNavigate}
        expanded={navExpanded}
        onToggle={() => setNavExpanded((v) => !v)}
      />
      <section className="s1-main">
        <ContextBar
          engagement={engagement}
          expanded={ctxExpanded}
          onToggle={() => setCtxExpanded((v) => !v)}
          onOpenGlossary={onOpenGlossary}
          onReset={onReset}
        />
        {children}
      </section>
      <AssistantWidget page={current} />
    </div>
  );
}

/* =============================== sidebar =============================== */

function Sidebar({
  current,
  onNavigate,
  expanded,
  onToggle,
}: {
  current?: NavKey;
  onNavigate?: (key: NavKey) => void;
  expanded: boolean;
  onToggle: () => void;
}) {
  return (
    <aside className={`s1-side${expanded ? "" : " s1-side--min"}`}>
      <div className="s1-side__top">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img className="s1-side__logo" src={expanded ? "/sustentra-logo.png" : "/sustentra-mark.png"} alt="Sustentra" />
      </div>
      <nav className="s1-side__nav" aria-label="Primary">
        {DESTINATIONS.map((dest) => (
          <button
            key={dest.key}
            className={`s1-side__item${current === dest.key ? " is-on" : ""}`}
            type="button"
            title={dest.label}
            aria-current={current === dest.key ? "page" : undefined}
            onClick={() => onNavigate?.(dest.key)}
          >
            <span className="s1-side__icon"><NavIcon nav={dest.key} /></span>
            <span className="s1-side__label">{dest.label}</span>
          </button>
        ))}
      </nav>
      <button
        className="s1-side__toggle"
        type="button"
        onClick={onToggle}
        aria-label={expanded ? "Minimize sidebar" : "Expand sidebar"}
        title={expanded ? "Minimize" : "Expand"}
      >
        <span className="s1-side__icon"><ChevronsIcon collapsed={!expanded} /></span>
        <span className="s1-side__label">Collapse</span>
      </button>
    </aside>
  );
}

/* ===================== engagement context bar (relocated, collapsed) ===================== */

function ContextBar({
  engagement,
  expanded,
  onToggle,
  onOpenGlossary,
  onReset,
}: {
  engagement: EngagementConfig;
  expanded: boolean;
  onToggle: () => void;
  onOpenGlossary?: () => void;
  onReset?: () => void;
}) {
  return (
    <div className={`s1-ctx${expanded ? " s1-ctx--open" : ""}`}>
      <div className="s1-ctx__bar">
        <button className="s1-ctx__summary" type="button" onClick={onToggle} aria-expanded={expanded}>
          <span className="s1-ctx__client">{engagement.clientName}</span>
          <span className="s1-ctx__id s1-mono">{engagement.engagementId}</span>
          <span className="s1-ctx__caret" aria-hidden>{expanded ? "▴" : "▾"}</span>
          <span className="s1-muted s1-ctx__hint">{expanded ? "Hide engagement" : "Engagement details"}</span>
        </button>
        <div className="s1-ctx__actions">
          <button className="s1-linklike" type="button" onClick={onOpenGlossary}>
            Glossary
          </button>
          {onReset ? (
            <button
              className="s1-ctx__reset"
              type="button"
              onClick={() => {
                if (window.confirm("Reset the workspace to the start? This clears the current session.")) onReset();
              }}
            >
              <ResetIcon /> Reset
            </button>
          ) : null}
        </div>
      </div>
      {expanded ? (
        <div className="s1-ctx__details">
          <CtxItem label="Reporting period" value={`${engagement.reportingPeriod.start} to ${engagement.reportingPeriod.end}`} />
          <CtxItem label="Regulation" value={engagement.regulation} />
          <CtxItem label="Assurance level" value={engagement.assuranceLevel} />
          <CtxItem label="Boundary approach" value={engagement.boundaryApproach} />
        </div>
      ) : null}
    </div>
  );
}

function CtxItem({ label, value }: { label: string; value: string }) {
  return (
    <div className="s1-ctx__item">
      <div className="s1-label">{label}</div>
      <div className="s1-value">{value}</div>
    </div>
  );
}

/* =============================== icons =============================== */

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
