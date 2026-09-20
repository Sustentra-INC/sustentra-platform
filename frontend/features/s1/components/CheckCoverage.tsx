"use client";

import { Fragment } from "react";

import type { CoverageRule, CoverageStatus } from "../types/verification";

/**
 * Check Coverage (screen 5). What the system can and cannot check with the
 * evidence held. HONEST STATUS: the engine does not evaluate rule expressions
 * yet, so the status states input readiness only, never that a rule "ran".
 * The banner says so in plain terms.
 */

// Proposed wording; flagged to product; naming is theirs to settle.
const STATUS_LABEL: Record<CoverageStatus, string> = {
  inputs_present: "Inputs present",
  inputs_missing: "Inputs missing",
  not_applicable: "Not applicable",
  out_of_scope: "Out of scope",
};
const STATUS_ROLE: Record<CoverageStatus, string> = {
  inputs_present: "resolved",
  inputs_missing: "open",
  not_applicable: "na",
  out_of_scope: "unverifiable",
};
// Grouped by the reason it cannot run: missing first, then not-applicable,
// out-of-scope, and finally the rules whose inputs are present.
const GROUP_ORDER: CoverageStatus[] = ["inputs_missing", "not_applicable", "out_of_scope", "inputs_present"];

export function CheckCoverage({ rules }: { rules: CoverageRule[] }) {
  const groups = GROUP_ORDER.map((status) => ({
    status,
    rules: rules.filter((r) => r.status === status),
  })).filter((g) => g.rules.length > 0);

  return (
    <section className="s1-content s1-cov">
      <header className="s1-ws-header">
        <div className="s1-ws-header__id s1-cov-header">
          <ShieldIcon className="s1-cov-title-icon" />
          <div>
            <h1>Check coverage</h1>
            <span className="s1-muted">What can and cannot be checked with the evidence held.</span>
          </div>
        </div>
      </header>

      <div className="s1-cov-summary">
        {GROUP_ORDER.map((status) => (
          <div key={status} className={`s1-cov-tile s1-cov-tile--${STATUS_ROLE[status]}`}>
            <span className="s1-cov-tile__icon">
              <StatusIcon status={status} />
            </span>
            <div>
              <div className="s1-cov-tile__n">{rules.filter((r) => r.status === status).length}</div>
              <div className="s1-cov-tile__label">{STATUS_LABEL[status]}</div>
            </div>
          </div>
        ))}
      </div>

      <div className="s1-cov-banner" role="note">
        <InfoIcon className="s1-cov-banner__icon" />
        <div>
          <strong>Rule evaluation is not yet implemented.</strong> This shows <em>input readiness</em> only: whether a
          rule&rsquo;s data points have accepted values, not whether the rule&rsquo;s assertion held. A rule with inputs
          present has not been run.
        </div>
      </div>

      <div className="s1-table-wrap">
        <table className="s1-table s1-cov-table">
          <colgroup>
            <col style={{ width: "14%" }} /> {/* Rule */}
            <col style={{ width: "26%" }} /> {/* What it checks */}
            <col style={{ width: "23%" }} /> {/* Data points */}
            <col style={{ width: "15%" }} /> {/* Status */}
            <col style={{ width: "22%" }} /> {/* Reason */}
          </colgroup>
          <thead>
            <tr>
              <th>Rule</th>
              <th>What it checks</th>
              <th>Data points it applies to</th>
              <th>Status</th>
              <th>Reason</th>
            </tr>
          </thead>
          <tbody>
            {groups.map((group) => (
              <Fragment key={group.status}>
                <tr className="s1-ws-group">
                  <td colSpan={5}>
                    <span className="s1-cov-grouphead">
                      <StatusIcon status={group.status} />
                      {STATUS_LABEL[group.status]} <span className="s1-muted">({group.rules.length})</span>
                    </span>
                  </td>
                </tr>
                {group.rules.map((rule) => (
                  <tr key={rule.ruleId}>
                    <td className="s1-mono s1-muted">{rule.ruleId}</td>
                    <td>{rule.assertion}</td>
                    <td>
                      {rule.appliesTo.map((d) => (
                        <div key={d}>{d}</div>
                      ))}
                    </td>
                    <td>
                      <span className={`s1-state s1-state--${STATUS_ROLE[rule.status]}`}>
                        <StatusIcon status={rule.status} />
                        {STATUS_LABEL[rule.status]}
                      </span>
                    </td>
                    <td className="s1-muted">{rule.reason}</td>
                  </tr>
                ))}
              </Fragment>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

/* ---- Professional line icons (stroked, currentColor) ---- */

const SVG = {
  fill: "none" as const,
  stroke: "currentColor",
  strokeWidth: 1.7,
  strokeLinecap: "round" as const,
  strokeLinejoin: "round" as const,
};

function StatusIcon({ status }: { status: CoverageStatus }) {
  switch (status) {
    case "inputs_present":
      return (
        <svg viewBox="0 0 24 24" {...SVG} aria-hidden="true">
          <circle cx="12" cy="12" r="9" />
          <path d="m8.4 12.2 2.3 2.3 4.9-5" />
        </svg>
      );
    case "inputs_missing":
      return (
        <svg viewBox="0 0 24 24" {...SVG} aria-hidden="true">
          <circle cx="12" cy="12" r="9" />
          <path d="M12 8v4.5" />
          <path d="M12 15.8h.01" />
        </svg>
      );
    case "not_applicable":
      return (
        <svg viewBox="0 0 24 24" {...SVG} aria-hidden="true">
          <circle cx="12" cy="12" r="9" />
          <path d="M8.5 12h7" />
        </svg>
      );
    case "out_of_scope":
      return (
        <svg viewBox="0 0 24 24" {...SVG} aria-hidden="true">
          <circle cx="12" cy="12" r="9" />
          <path d="m5.7 5.7 12.6 12.6" />
        </svg>
      );
  }
}

function ShieldIcon({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" {...SVG} aria-hidden="true">
      <path d="M12 3.2 5 6v5.2c0 4.3 2.9 7.2 7 8.6 4.1-1.4 7-4.3 7-8.6V6z" />
      <path d="m9 12 2.1 2.1L15.2 10" />
    </svg>
  );
}

function InfoIcon({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" {...SVG} aria-hidden="true">
      <circle cx="12" cy="12" r="9" />
      <path d="M12 11v5" />
      <path d="M12 8h.01" />
    </svg>
  );
}
