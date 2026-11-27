"use client";

import { Ban, CircleMinus } from "lucide-react";
import { useState, type ReactNode } from "react";

import type { CoverageRule, CoverageStatus } from "../types/verification";
import { IconCheckCircle, IconSend, IconWarning } from "./icons";
import { InfoTip } from "./InfoTip";

/**
 * What can and cannot be checked with the evidence held. The status states input
 * readiness only, never that a rule ran: the engine does not evaluate rule
 * expressions yet. A check missing its inputs can become a request in one click.
 */

export interface CoverageState {
  rules: CoverageRule[] | null;
  /** Why there are no rules: still loading, failed, or no engagement picked. */
  message?: string;
}

/** Only missing and present get a dot in the filter (MVP-228); the other two are plain labels. */
const STATUS: Record<CoverageStatus, { label: string; role: string; icon: ReactNode; dot?: "warning" | "success" }> = {
  inputs_missing: { label: "Missing", role: "open", icon: <IconWarning size={18} />, dot: "warning" },
  inputs_present: { label: "Present", role: "resolved", icon: <IconCheckCircle size={18} />, dot: "success" },
  not_applicable: { label: "Not applicable", role: "na", icon: <CircleMinus /> },
  out_of_scope: { label: "Out of scope", role: "unverifiable", icon: <Ban /> },
};
const ORDER: CoverageStatus[] = ["inputs_missing", "inputs_present", "not_applicable", "out_of_scope"];

export function CoveragePanel({
  coverage,
  isRequested,
  onRequest,
}: {
  coverage: CoverageState;
  isRequested: (rule: CoverageRule) => boolean;
  onRequest: (rule: CoverageRule) => void;
}) {
  const rules = coverage.rules ?? [];
  const missing = rules.filter((r) => r.status === "inputs_missing").length;
  const [filter, setFilter] = useState<CoverageStatus | "all">(missing ? "inputs_missing" : "all");
  const shown = rules
    .filter((r) => filter === "all" || r.status === filter)
    .sort((a, b) => ORDER.indexOf(a.status) - ORDER.indexOf(b.status));

  return (
    <section className="s1-cr-cov" aria-labelledby="s1-cr-cov-title">
      <div className="s1-cr-sectionhead">
        <span className="s1-cr-sectionhead__title">
          <h2 id="s1-cr-cov-title">What can be checked</h2>
          <InfoTip label="What can be checked">Checks count a value once it is accepted or corrected.</InfoTip>
        </span>
        {coverage.rules ? (
          <div className="s1-ws-factabs s1-ws-factabs--seg s1-cr-checkfilter" role="group" aria-label="Show checks">
            {ORDER.map((status) => {
              const n = rules.filter((r) => r.status === status).length;
              const on = filter === status;
              const dot = STATUS[status].dot;
              return (
                <button
                  key={status}
                  className={`s1-ws-factab${on ? " is-on" : ""}`}
                  type="button"
                  aria-pressed={on}
                  onClick={() => setFilter(on ? "all" : status)}
                >
                  {dot ? <span className={`s1-cr-checkfilter__dot s1-cr-checkfilter__dot--${dot}`} aria-hidden /> : null}
                  <span className="s1-cr-checkfilter__n">{n}</span>
                  {STATUS[status].label}
                </button>
              );
            })}
          </div>
        ) : null}
      </div>

      {!coverage.rules ? (
        <p className="s1-cr-note">{coverage.message ?? "Checking what the evidence covers…"}</p>
      ) : shown.length === 0 ? (
        <p className="s1-cr-note">No checks in this state.</p>
      ) : (
        <ul className="s1-cr-rules" key={filter}>
          {shown.map((rule, index) => {
            const status = STATUS[rule.status];
            const requested = rule.status === "inputs_missing" && isRequested(rule);
            return (
              <li
                key={rule.ruleId}
                className={`s1-cr-rule s1-cr-rule--${status.role}`}
                style={{ transitionDelay: `${Math.min(index, 8) * 24}ms` }}
              >
                <span className="s1-cr-rule__icon" role="img" aria-label={status.label} title={status.label}>
                  {status.icon}
                </span>
                {/* The finding leads; the check it belongs to follows, quieter (MVP-228). */}
                <div className="s1-cr-rule__main">
                  <div className="s1-cr-rule__why">{rule.reason}</div>
                  <div className="s1-cr-rule__what">{[rule.assertion, ...rule.appliesTo].join(" · ")}</div>
                </div>
                <div className="s1-cr-rule__act">
                  {rule.status !== "inputs_missing" ? null : requested ? (
                    <span className="s1-state s1-state--active">In requests</span>
                  ) : (
                    <button className="s1-button s1-button--soft s1-cr-request" type="button" onClick={() => onRequest(rule)}>
                      <IconSend size={14} aria-hidden /> Request
                    </button>
                  )}
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
