"use client";

import { ProvenanceLabel } from "./ProvenanceLabel";
import { Ban, CircleCheck, CircleMinus, CircleAlert, ListChecks, Send } from "lucide-react";
import { useState, type ReactNode } from "react";

import type { CoverageRule } from "../types/verification";
import { coverageView, type CoverageView } from "../utils/engagementActivity";

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

/** Each count reads as a plain phrase after its number: "4 awaiting review", "0 missing". */
const VIEWS: Record<CoverageView, { label: string; role: string; icon: ReactNode }> = {
  awaiting_review: { label: "awaiting review", role: "open", icon: <CircleAlert /> },
  needs_choice: { label: "need a choice", role: "open", icon: <CircleAlert /> },
  missing: { label: "missing", role: "open", icon: <CircleAlert /> },
  present: { label: "present", role: "resolved", icon: <CircleCheck /> },
  not_applicable: { label: "not applicable", role: "na", icon: <CircleMinus /> },
  out_of_scope: { label: "out of scope", role: "unverifiable", icon: <Ban /> },
  method_open: { label: "method checks to do", role: "open", icon: <CircleAlert /> },
  method_done: { label: "method checks done", role: "resolved", icon: <CircleCheck /> },
};
/** The counts shown, in order. Method checks show only when one is still to do. */
const ORDER: CoverageView[] = ["awaiting_review", "needs_choice", "missing", "present", "not_applicable", "out_of_scope", "method_open"];
/** What the list is sorted by: what needs someone first. */
const SORT: CoverageView[] = [...ORDER, "method_done"];

export function CoveragePanel({
  coverage,
  isRequested,
  requestOf,
  onRequest,
  onReview,
}: {
  coverage: CoverageState;
  isRequested: (rule: CoverageRule) => boolean;
  /** Who raised the request for a check, and when, for its provenance label. */
  requestOf?: (rule: CoverageRule) => { by?: string; at?: string } | null;
  onRequest: (rule: CoverageRule) => void;
  /** Opens the first value waiting on a check that awaits review. Without it such a check offers Request, as before. */
  onReview?: (rule: CoverageRule) => void;
}) {
  const rules = coverage.rules ?? [];
  const viewOf = new Map(rules.map((r) => [r, coverageView(r)]));
  const countOf = (view: CoverageView) => rules.filter((r) => viewOf.get(r) === view).length;
  const [filter, setFilter] = useState<CoverageView | "all">(() => {
    const open = (["awaiting_review", "needs_choice", "missing", "method_open"] as CoverageView[]).find((v) =>
      (coverage.rules ?? []).some((r) => coverageView(r) === v)
    );
    return open ?? "all";
  });
  const shown = rules
    .filter((r) => filter === "all" || viewOf.get(r) === filter)
    .sort((a, b) => SORT.indexOf(viewOf.get(a)!) - SORT.indexOf(viewOf.get(b)!));

  return (
    <section className="s1-cr-cov" aria-labelledby="s1-cr-cov-title">
      <div className="s1-cr-sectionhead">
        <h2 id="s1-cr-cov-title">What can be checked</h2>
        {coverage.rules ? (
          <div className="s1-cr-filters" role="group" aria-label="Show checks">
            {ORDER.filter((view) => view !== "method_open" || countOf(view) > 0).map((view) => {
              const n = countOf(view);
              const on = filter === view;
              return (
                <button
                  key={view}
                  className={`s1-cr-filter s1-cr-filter--${VIEWS[view].role}${on ? " is-on" : ""}`}
                  type="button"
                  aria-pressed={on}
                  onClick={() => setFilter(on ? "all" : view)}
                >
                  <span className="s1-cr-filter__icon" aria-hidden>
                    {VIEWS[view].icon}
                  </span>
                  <span className="s1-cr-filter__n">{n}</span> {VIEWS[view].label}
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
            const view = viewOf.get(rule) ?? "present";
            const status = VIEWS[view];
            const requested = rule.status === "inputs_missing" && isRequested(rule);
            return (
              <li
                key={rule.ruleId}
                className={`s1-cr-rule s1-cr-rule--${status.role}`}
                style={{ transitionDelay: `${Math.min(index, 8) * 24}ms` }}
              >
                <span className="s1-cr-rule__icon" aria-hidden title={sentenceCase(status.label)}>
                  {status.icon}
                </span>
                <div className="s1-cr-rule__main">
                  <div className="s1-cr-rule__what">{rule.assertion}</div>
                  <div className="s1-cr-rule__prov">
                    {requested ? (
                      <ProvenanceLabel source="human" action="requested" by={requestOf?.(rule)?.by} at={requestOf?.(rule)?.at} />
                    ) : (
                      <ProvenanceLabel source="system" />
                    )}
                  </div>
                  <div className="s1-cr-rule__points">
                    {rule.appliesTo.map((point) => (
                      <span key={point}>{point}</span>
                    ))}
                  </div>
                </div>
                <div className="s1-cr-rule__why">{rule.reason}</div>
                <div className="s1-cr-rule__act">
                  {rule.status !== "inputs_missing" ? (
                    <span className={`s1-state s1-state--${status.role}`}>{sentenceCase(status.label)}</span>
                  ) : view === "awaiting_review" && onReview ? (
                    // The values are in: the reviewer's job, not the client's.
                    <button className="s1-button s1-button--compact s1-cr-request" type="button" onClick={() => onReview(rule)}>
                      <ListChecks aria-hidden /> Review
                    </button>
                  ) : requested ? (
                    <span className="s1-state s1-state--active">In requests</span>
                  ) : (
                    <button className="s1-button s1-button--compact s1-cr-request" type="button" onClick={() => onRequest(rule)}>
                      <Send aria-hidden /> Request
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

const sentenceCase = (text: string) => text.charAt(0).toUpperCase() + text.slice(1);
