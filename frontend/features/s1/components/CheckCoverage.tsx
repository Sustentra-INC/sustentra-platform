"use client";

import { Fragment } from "react";

import type { CoverageRule, CoverageStatus } from "../types/verification";

/**
 * Check Coverage (screen 5). What the system can and cannot check with the
 * evidence held. HONEST STATUS: the engine does not evaluate rule expressions
 * yet, so the status states input readiness only — never that a rule "ran".
 * The banner says so in plain terms.
 */

// Proposed wording — flagged to product; naming is theirs to settle.
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
        <div className="s1-ws-header__id">
          <h1>Check coverage</h1>
          <span className="s1-muted">What can and cannot be checked with the evidence held.</span>
        </div>
      </header>

      <div className="s1-cov-banner" role="note">
        <strong>Rule evaluation is not yet implemented.</strong> This shows <em>input readiness</em> only — whether a
        rule&rsquo;s data points have accepted values — not whether the rule&rsquo;s assertion held. A rule with inputs
        present has not been run.
      </div>

      <div className="s1-table-wrap">
        <table className="s1-table s1-cov-table">
          <colgroup>
            <col style={{ minWidth: "12rem" }} />
            <col style={{ minWidth: "18rem" }} />
            <col style={{ minWidth: "16rem" }} />
            <col style={{ width: "10rem" }} />
            <col style={{ minWidth: "18rem" }} />
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
                    {STATUS_LABEL[group.status]} <span className="s1-muted">({group.rules.length})</span>
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
                      <span className={`s1-state s1-state--${STATUS_ROLE[rule.status]}`}>{STATUS_LABEL[rule.status]}</span>
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
