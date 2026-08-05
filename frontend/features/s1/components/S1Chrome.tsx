import type { ReactNode } from "react";

import { EXACT_COPY } from "../constants/copy";
import type { EngagementConfig } from "../types";

interface S1ChromeProps {
  engagement: EngagementConfig;
  children: ReactNode;
  currentTab?: "evidence" | "extraction";
}

export function PersistentRail({ engagement }: { engagement: EngagementConfig }) {
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
        <button className="s1-linklike" type="button">
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

export function PrimaryNav({ currentTab = "evidence" }: { currentTab?: "evidence" | "extraction" }) {
  return (
    <nav className="s1-nav" aria-label="Primary">
      <button className="s1-tab" aria-current={currentTab === "evidence" ? "page" : undefined}>
        Evidence
      </button>
      <button className="s1-tab" disabled>
        Register <span className="s1-next">— next release</span>
      </button>
      <button className="s1-tab" disabled>
        Requests <span className="s1-next">— next release</span>
      </button>
      <button className="s1-tab" disabled>
        Conclusion <span className="s1-next">— next release</span>
      </button>
    </nav>
  );
}

export function S1Chrome({ engagement, children, currentTab }: S1ChromeProps) {
  return (
    <div className="s1-screen">
      <PersistentRail engagement={engagement} />
      <section className="s1-main">
        <PrimaryNav currentTab={currentTab} />
        {children}
      </section>
    </div>
  );
}
