"use client";

import { ChevronDown, History } from "lucide-react";
import { IconTrash } from "./icons";
import Link from "next/link";
import { useState, type ReactNode } from "react";

import type { EngagementConfig } from "../types";
import { formatReportingPeriod } from "../utils/formatPeriod";
import { ActionMenu, type ActionMenuEntry } from "./ActionMenu";
import { AssistantWidget, type AssistantConnection } from "./AssistantWidget";

export type NavKey =
  | "dashboard"
  | "setup"
  | "upload"
  | "evidence"
  | "requests"
  | "coverage"
  | "methodology"
  | "results"
  | "output";

/** The signed-in user shown in the workpaper header (FE-006). */
export interface WorkpaperUser {
  email: string;
  firstName: string | null;
  role: "provider_admin" | "org_admin" | "org_member";
  orgSlug: string | null;
}

const ROLE_LABEL: Record<WorkpaperUser["role"], string> = {
  provider_admin: "Provider admin",
  org_admin: "Org admin",
  org_member: "Member",
};

interface S1ChromeProps {
  engagement: EngagementConfig;
  /** Backend mode: who is signed in, with sign-out (FE-006). */
  user?: WorkpaperUser;
  onSignOut?: () => void;
  children: ReactNode;
  current?: NavKey;
  onNavigate?: (key: NavKey) => void;
  onOpenGlossary?: () => void;
  /** The Glossary page is showing: its footer link is the current item and no main nav item is. */
  glossaryOpen?: boolean;
  onOpenActivity?: () => void;
  onReset?: () => void;
  /** The live assistant's data and links; without it the assistant gives built-in help. */
  assistant?: AssistantConnection;
  /** Destinations this data mode does not have yet. */
  hiddenNav?: NavKey[];
  /** Live counts shown as badges on nav items. */
  navCounts?: Partial<Record<"evidence" | "requests" | "results", number>>;
}

const DESTINATIONS: Array<{ key: NavKey; label: string }> = [
  { key: "dashboard", label: "Dashboard" },
  { key: "setup", label: "Setup" },
  { key: "upload", label: "Upload" },
  { key: "evidence", label: "Evidence" },
  { key: "requests", label: "Coverage & requests" },
  { key: "methodology", label: "Methodology review" },
  { key: "results", label: "Verification results" },
  { key: "output", label: "Output" },
];

const WORKFLOW_KEYS: NavKey[] = ["dashboard", "setup", "upload", "evidence", "requests"];
const ASSURANCE_KEYS: NavKey[] = ["methodology", "results", "output"];

export function S1Chrome({
  engagement,
  user,
  onSignOut,
  children,
  current,
  onNavigate,
  onOpenGlossary,
  glossaryOpen = false,
  onOpenActivity,
  onReset,
  assistant,
  hiddenNav,
  navCounts,
}: S1ChromeProps) {
  const [navExpanded, setNavExpanded] = useState(true);
  const [ctxExpanded, setCtxExpanded] = useState(false);
  return (
    <div className="s1-shell">
      <Sidebar
        current={glossaryOpen ? undefined : current}
        glossaryOpen={glossaryOpen}
        onNavigate={onNavigate}
        hidden={hiddenNav}
        expanded={navExpanded}
        onToggle={() => setNavExpanded((v) => !v)}
        engagement={engagement}
        user={user}
        onOpenActivity={onOpenActivity}
        onOpenGlossary={onOpenGlossary}
        navCounts={navCounts}
      />
      <section className="s1-main">
        <TopRow onReset={onReset} />
        <ContextBar
          engagement={engagement}
          expanded={ctxExpanded}
          onToggle={() => setCtxExpanded((v) => !v)}
          onOpenGlossary={onOpenGlossary}
          onOpenActivity={onOpenActivity}
          user={user}
          onSignOut={onSignOut}
        />
        {children}
      </section>
      {/* A signed-in user means live data: the assistant explains methods, not demo figures. */}
      <AssistantWidget page={current} live={Boolean(user)} assistant={assistant} />
    </div>
  );
}

/* =============================== sidebar =============================== */

function Sidebar({
  current,
  onNavigate,
  hidden,
  expanded,
  onToggle,
  engagement,
  user,
  onOpenActivity,
  onOpenGlossary,
  glossaryOpen,
  navCounts,
}: {
  current?: NavKey;
  glossaryOpen?: boolean;
  onNavigate?: (key: NavKey) => void;
  hidden?: NavKey[];
  expanded: boolean;
  onToggle: () => void;
  engagement: EngagementConfig;
  user?: WorkpaperUser;
  onOpenActivity?: () => void;
  onOpenGlossary?: () => void;
  navCounts?: Partial<Record<"evidence" | "requests" | "results", number>>;
}) {
  const initials = engagement.clientName
    .split(/\s+/)
    .slice(0, 2)
    .map((w) => w[0] ?? "")
    .join("")
    .toUpperCase() || "?";

  const workflowDests = DESTINATIONS.filter(
    (d) => WORKFLOW_KEYS.includes(d.key) && !hidden?.includes(d.key),
  );
  const assuranceDests = DESTINATIONS.filter(
    (d) => ASSURANCE_KEYS.includes(d.key) && !hidden?.includes(d.key),
  );

  return (
    <aside className={`s1-side${expanded ? "" : " s1-side--min"}`}>
      {/* Logo */}
      <div className="s1-side__top">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          className="s1-side__logo"
          src={expanded ? "/sustentra-logo.png" : "/sustentra-mark.png"}
          alt="Sustentra"
        />
      </div>

      {/* Engagement switcher */}
      <button className="s1-side__switcher" type="button" aria-label="Switch engagement">
        <span className="s1-side__switcher-av" aria-hidden="true">{initials}</span>
        <span className="s1-side__switcher-body">
          <span className="s1-side__switcher-name">{engagement.clientName}</span>
          <span className="s1-side__switcher-sub">
            {engagement.reportingPeriod.start
              ? `FY ${engagement.reportingPeriod.start.slice(0, 4)}`
              : engagement.assuranceLevel || engagement.regulation}
          </span>
        </span>
        <span className="s1-side__switcher-arr" aria-hidden="true">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <path d="M8 9l4-4 4 4M8 15l4 4 4-4" />
          </svg>
        </span>
      </button>

      {/* Main nav */}
      <nav className="s1-side__nav" aria-label="Primary">
        {workflowDests.length > 0 && (
          <span className="s1-side__group" aria-hidden="true">WORKFLOW</span>
        )}
        {workflowDests.map((dest) => {
          const count =
            dest.key === "evidence" || dest.key === "requests"
              ? navCounts?.[dest.key]
              : undefined;
          return (
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
              {count != null && count > 0 && (
                <span className="s1-side__badge" aria-label={`${count} items`}>{count}</span>
              )}
            </button>
          );
        })}
        {assuranceDests.length > 0 && (
          <span className="s1-side__group s1-side__group--mt" aria-hidden="true">ASSURANCE</span>
        )}
        {assuranceDests.map((dest) => {
          const count = dest.key === "results" ? navCounts?.results : undefined;
          return (
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
              {count != null && count > 0 && (
                <span className="s1-side__badge" aria-label={`${count} items`}>{count}</span>
              )}
            </button>
          );
        })}
      </nav>

      {/* Spacer */}
      <div className="s1-side__spacer" aria-hidden="true" />

      {/* Footer links — Activity log and Glossary */}
      {(onOpenActivity || onOpenGlossary) && (
        <div className="s1-side__footer">
          {onOpenActivity && (
            <button className="s1-side__item" type="button" onClick={onOpenActivity}>
              <span className="s1-side__icon"><ActivityIcon /></span>
              <span className="s1-side__label">Activity log</span>
            </button>
          )}
          {onOpenGlossary && (
            <button
              className={`s1-side__item${glossaryOpen ? " is-on" : ""}`}
              type="button"
              aria-current={glossaryOpen ? "page" : undefined}
              onClick={onOpenGlossary}
            >
              <span className="s1-side__icon"><GlossaryIcon /></span>
              <span className="s1-side__label">Glossary</span>
            </button>
          )}
        </div>
      )}

      {/* Account card */}
      {user && (
        <button className="s1-side__account" type="button" aria-label="Account menu">
          <span className="s1-side__account-av" aria-hidden="true">
            {(user.firstName || user.email)[0]?.toUpperCase() ?? "?"}
          </span>
          <span className="s1-side__account-body">
            <span className="s1-side__account-name">
              {user.firstName || ROLE_LABEL[user.role]}
            </span>
            {user.firstName && (
              <span className="s1-side__account-email">{user.email}</span>
            )}
          </span>
          <span className="s1-side__account-arr" aria-hidden="true">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <path d="M6 9l6 6 6-6" />
            </svg>
          </span>
        </button>
      )}

      {/* Collapse toggle */}
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

/* ========================= top row: ⋯ More actions ========================= */

function TopRow({ onReset }: { onReset?: () => void }) {
  const [moreOpen, setMoreOpen] = useState(false);
  const entries: ActionMenuEntry[] = [];
  if (onReset) {
    entries.push({
      label: "Reset",
      danger: true,
      icon: <IconTrash size={16} />,
      action: () => {
        if (window.confirm("Reset the workspace to the start? This clears the current session.")) {
          onReset();
        }
      },
    });
  }
  if (!entries.length) return null;
  return (
    <div className="s1-toprow">
      <ActionMenu label="More actions" entries={entries} isOpen={moreOpen} onOpenChange={setMoreOpen} />
    </div>
  );
}

/* ===================== engagement context bar (relocated, collapsed) ===================== */

function ContextBar({
  engagement,
  expanded,
  onToggle,
  onOpenGlossary,
  onOpenActivity,
  user,
  onSignOut,
}: {
  engagement: EngagementConfig;
  expanded: boolean;
  onToggle: () => void;
  onOpenGlossary?: () => void;
  onOpenActivity?: () => void;
  user?: WorkpaperUser;
  onSignOut?: () => void;
}) {
  return (
    <div className={`s1-ctx${expanded ? " s1-ctx--open" : ""}`}>
      <div className="s1-ctx__bar">
        {/* Two looks only: the client, then everything else in the small secondary style. */}
        <button className="s1-ctx__summary" type="button" onClick={onToggle} aria-expanded={expanded}>
          <span className="s1-ctx__client">{engagement.clientName}</span>
          <span className="s1-ctx__meta">
            <span className="s1-ctx__id">{engagement.engagementName || engagement.engagementId}</span>
            <span className="s1-ctx__hint">
              {expanded ? "Hide details" : "Details"}
              <ChevronDown className={`s1-ctx__chev${expanded ? " is-open" : ""}`} aria-hidden />
            </span>
          </span>
        </button>
        <div className="s1-ctx__actions">
          {onOpenActivity ? (
            <button className="s1-ctx__activity" type="button" onClick={onOpenActivity}>
              <History aria-hidden /> Activity log
            </button>
          ) : null}
          <button className="s1-linklike" type="button" onClick={onOpenGlossary}>
            Glossary
          </button>
          {user ? (
            <div className="s1-ctx__user" aria-label="Signed in">
              <span className="s1-ctx__user-name" title={user.email}>
                {user.firstName || user.email}
              </span>
              <span className="s1-muted s1-ctx__user-role">{ROLE_LABEL[user.role]}</span>
              {user.role === "org_admin" && user.orgSlug ? (
                <Link className="s1-linklike" href={`/org/${user.orgSlug}`}>
                  Admin
                </Link>
              ) : null}
              {user.role === "provider_admin" ? (
                <Link className="s1-linklike" href="/provider-admin/orgs">
                  Organizations
                </Link>
              ) : null}
              {onSignOut ? (
                <button className="s1-linklike" type="button" onClick={onSignOut}>
                  Sign out
                </button>
              ) : null}
            </div>
          ) : null}
        </div>
      </div>
      {expanded ? (
        <div className="s1-ctx__details">
          <CtxItem label="Engagement ID" value={engagement.engagementId} />
          <CtxItem
            label="Reporting period"
            value={formatReportingPeriod(engagement.reportingPeriod.start, engagement.reportingPeriod.end)}
          />
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


function ActivityIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <defs>
        <mask id="s1-nav-clock" maskUnits="userSpaceOnUse" x="0" y="0" width="24" height="24">
          <rect width="24" height="24" fill="#fff" />
          <path d="M12 7.5V12l3 2" stroke="#000" strokeWidth="2.3" strokeLinecap="round" strokeLinejoin="round" fill="none" />
        </mask>
      </defs>
      <g mask="url(#s1-nav-clock)">
        <circle cx="12" cy="12" r="9.5" fill="currentColor" />
      </g>
    </svg>
  );
}

function GlossaryIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <defs>
        <mask id="s1-nav-book" maskUnits="userSpaceOnUse" x="0" y="0" width="24" height="24">
          <rect width="24" height="24" fill="#fff" />
          <path d="M9 7.5h6" stroke="#000" strokeWidth="2.3" strokeLinecap="round" strokeLinejoin="round" fill="none" />
        </mask>
      </defs>
      <g mask="url(#s1-nav-book)">
        <path d="M6.5 2.5H19a1 1 0 0 1 1 1V18H6.5a1.5 1.5 0 0 0 0 3H20v.5a1 1 0 0 1-1 1H6.5A2.5 2.5 0 0 1 4 20V5a2.5 2.5 0 0 1 2.5-2.5z" fill="currentColor" />
        <rect x="5" y="18" width="15" height="3" rx="1.5" fill="currentColor" fillOpacity=".38" />
      </g>
    </svg>
  );
}

function NavIcon({ nav }: { nav: NavKey }) {
  switch (nav) {
    case "dashboard":
      return (
        <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
          <rect x="3" y="3" width="8" height="8" rx="2.6" fill="currentColor" />
          <rect x="13" y="3" width="8" height="8" rx="2.6" fill="currentColor" fillOpacity=".38" />
          <rect x="3" y="13" width="8" height="8" rx="2.6" fill="currentColor" fillOpacity=".38" />
          <rect x="13" y="13" width="8" height="8" rx="2.6" fill="currentColor" />
        </svg>
      );
    case "setup":
      return (
        <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
          <rect x="3" y="6" width="18" height="2.6" rx="1.3" fill="currentColor" fillOpacity=".38" />
          <rect x="3" y="15.4" width="18" height="2.6" rx="1.3" fill="currentColor" fillOpacity=".38" />
          <circle cx="15.5" cy="7.3" r="3.4" fill="currentColor" />
          <circle cx="8.5" cy="16.7" r="3.4" fill="currentColor" />
        </svg>
      );
    case "upload":
      return (
        <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
          <path d="M3 13.5a1.5 1.5 0 0 1 3 0V18h12v-4.5a1.5 1.5 0 0 1 3 0v5A2.5 2.5 0 0 1 18.5 21h-13A2.5 2.5 0 0 1 3 18.5z" fill="currentColor" fillOpacity=".38" />
          <path d="M11 3.6a1.4 1.4 0 0 1 2 0l4.2 4.2c.9.9.3 2.2-.9 2.2H14v4.5a2 2 0 0 1-4 0V10H7.7c-1.2 0-1.8-1.3-.9-2.2z" fill="currentColor" />
        </svg>
      );
    case "evidence":
      return (
        <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
          <defs>
            <mask id="s1-nav-doc" maskUnits="userSpaceOnUse" x="0" y="0" width="24" height="24">
              <rect width="24" height="24" fill="#fff" />
              <path d="M8.5 13h7M8.5 17h4.5" stroke="#000" strokeWidth="2.3" strokeLinecap="round" strokeLinejoin="round" fill="none" />
            </mask>
          </defs>
          <g mask="url(#s1-nav-doc)">
            <path d="M6.5 2H14v4a2.5 2.5 0 0 0 2.5 2.5H20v11A2.5 2.5 0 0 1 17.5 22h-11A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z" fill="currentColor" />
            <path d="M15.5 2.4L19.6 6.5H16.5a1 1 0 0 1-1-1z" fill="currentColor" fillOpacity=".38" />
          </g>
        </svg>
      );
    case "requests":
      return (
        <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
          <path d="M6.3 3.5h11.4a2 2 0 0 1 1.9 1.4L21 9.5H3l1.4-4.6a2 2 0 0 1 1.9-1.4z" fill="currentColor" fillOpacity=".38" />
          <path d="M2.5 11h5.2a1 1 0 0 1 .9.6l.7 1.4a1 1 0 0 0 .9.6h3.6a1 1 0 0 0 .9-.6l.7-1.4a1 1 0 0 1 .9-.6h5.2v7.5A2.5 2.5 0 0 1 19 21H5a2.5 2.5 0 0 1-2.5-2.5z" fill="currentColor" />
        </svg>
      );
    case "coverage":
      return (
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="M12 3.2 5 6v5.2c0 4.3 2.9 7.2 7 8.6 4.1-1.4 7-4.3 7-8.6V6z" />
          <path d="m9 12 2.1 2.1L15.2 10" />
        </svg>
      );
    case "methodology":
      return (
        <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
          <defs>
            <mask id="s1-nav-clip" maskUnits="userSpaceOnUse" x="0" y="0" width="24" height="24">
              <rect width="24" height="24" fill="#fff" />
              <path d="M8.5 13.5l2.5 2.5 4.5-5" stroke="#000" strokeWidth="2.3" strokeLinecap="round" strokeLinejoin="round" fill="none" />
            </mask>
          </defs>
          <g mask="url(#s1-nav-clip)">
            <rect x="4" y="4" width="16" height="18" rx="3" fill="currentColor" />
            <rect x="8" y="2" width="8" height="4.5" rx="1.8" fill="currentColor" fillOpacity=".38" />
          </g>
        </svg>
      );
    case "results":
      return (
        <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
          <rect x="3.5" y="12" width="4.6" height="9" rx="1.8" fill="currentColor" fillOpacity=".38" />
          <rect x="9.7" y="4" width="4.6" height="17" rx="1.8" fill="currentColor" />
          <rect x="15.9" y="8.5" width="4.6" height="12.5" rx="1.8" fill="currentColor" fillOpacity=".38" />
        </svg>
      );
    case "output":
      return (
        <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
          <defs>
            <mask id="s1-nav-out" maskUnits="userSpaceOnUse" x="0" y="0" width="24" height="24">
              <rect width="24" height="24" fill="#fff" />
              <path d="M12 11v6M9.5 14.5L12 17l2.5-2.5" stroke="#000" strokeWidth="2.3" strokeLinecap="round" strokeLinejoin="round" fill="none" />
            </mask>
          </defs>
          <g mask="url(#s1-nav-out)">
            <path d="M6.5 2H14v4a2.5 2.5 0 0 0 2.5 2.5H20v11A2.5 2.5 0 0 1 17.5 22h-11A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z" fill="currentColor" />
            <path d="M15.5 2.4L19.6 6.5H16.5a1 1 0 0 1-1-1z" fill="currentColor" fillOpacity=".38" />
          </g>
        </svg>
      );
  }
}
