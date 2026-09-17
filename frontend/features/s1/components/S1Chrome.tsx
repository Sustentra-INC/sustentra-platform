import type { ReactNode } from "react";

import { EXACT_COPY } from "../constants/copy";
import type { EngagementConfig } from "../types";

export type NavKey =
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
}

export function PersistentRail({
  engagement,
  onOpenGlossary,
}: {
  engagement: EngagementConfig;
  onOpenGlossary?: () => void;
}) {
  return (
    <aside className="s1-rail">
      <h1 className="s1-rail__brand">Sustentra</h1>
      <RailItem label="Client" value={engagement.clientName} />
      <RailItem label="Engagement ID" value={engagement.engagementId} mono />
      <RailItem
        label="Reporting period"
        value={`${engagement.reportingPeriod.start} to ${engagement.reportingPeriod.end}`}
      />
      <RailItem label="Regulation" value={engagement.regulation} />
      <RailItem label="Assurance level" value={engagement.assuranceLevel} />
      <RailItem label="Boundary approach" value={engagement.boundaryApproach} />
      <RailItem label="Scope boundary" value={engagement.scopeBoundaryStatement} />
      <RailItem label="Aggregate uncorrected magnitude" value={EXACT_COPY.railMagnitude} />
      <div className="s1-rail__section">
        <button className="s1-linklike" type="button" onClick={onOpenGlossary}>
          Glossary
        </button>
      </div>
    </aside>
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
  { key: "setup", label: "Setup", built: false },
  { key: "upload", label: "Upload", built: true },
  { key: "evidence", label: "Evidence", built: true },
  { key: "requests", label: "Requests", built: false },
  { key: "coverage", label: "Check coverage", built: false },
  { key: "results", label: "Verification results", built: false },
  { key: "output", label: "Output", built: false },
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
      {DESTINATIONS.map((dest) =>
        dest.built ? (
          <button
            key={dest.key}
            className="s1-tab"
            type="button"
            aria-current={current === dest.key ? "page" : undefined}
            onClick={() => onNavigate?.(dest.key)}
          >
            {dest.label}
          </button>
        ) : (
          <button key={dest.key} className="s1-tab" type="button" disabled>
            {dest.label} <span className="s1-next">— not built</span>
          </button>
        )
      )}
    </nav>
  );
}

export function S1Chrome({ engagement, children, current, onNavigate, onOpenGlossary }: S1ChromeProps) {
  return (
    <div className="s1-screen">
      <PersistentRail engagement={engagement} onOpenGlossary={onOpenGlossary} />
      <section className="s1-main">
        <PrimaryNav current={current} onNavigate={onNavigate} />
        {children}
      </section>
    </div>
  );
}
