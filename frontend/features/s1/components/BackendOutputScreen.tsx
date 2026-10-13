"use client";

import { useEffect, useRef, useState } from "react";

import { apiPath } from "../../../lib/api";
import {
  formatNumber,
  getRecalculation,
  recalculationMateriality,
  type ComparisonStatus,
  type Recalculation,
} from "../api/recalculation";
import { userFacingApiError } from "../api/s1Backend";
import type { EngagementConfig, EvidenceItem, ReviewValue } from "../types";
import type { Ask } from "../types/requests";
import type { Finding } from "../types/verification";

/**
 * Output in backend mode: the engagement's real results as a draft working paper, with
 * the whole workpaper as an Excel download. Every figure is the recalculation's; nothing
 * is illustrative. It is not an assurance opinion, and says so.
 */
const ROWS: { key: string; label: string }[] = [
  { key: "stationary_combustion_total", label: "Scope 1 · fuel burned on site" },
  { key: "mobile_combustion_total", label: "Scope 1 · vehicle fuel" },
  { key: "fugitive_total", label: "Scope 1 · refrigerants and fire suppression" },
  { key: "scope1_total", label: "Scope 1 · total" },
  { key: "scope2_location_total", label: "Scope 2 · purchased electricity, location-based" },
  { key: "scope2_market_total", label: "Scope 2 · purchased electricity, market-based" },
];

const OUTCOME: Record<ComparisonStatus, { label: string; role: string }> = {
  within_tolerance: { label: "Held", role: "resolved" },
  exceeds_tolerance: { label: "Exception", role: "blocking" },
  not_reported: { label: "Reported value not entered", role: "unverifiable" },
  no_evidence: { label: "No reviewed evidence", role: "unverifiable" },
  not_recalculated: { label: "Not calculated yet", role: "na" },
};

export function BackendOutputScreen({
  engagement,
  evidence,
  values,
  asks,
  findings,
  onError,
}: {
  engagement: EngagementConfig;
  evidence: EvidenceItem[];
  values: ReviewValue[];
  asks: Ask[];
  findings: Finding[];
  onError: (error: unknown) => boolean;
}) {
  const [result, setResult] = useState<Recalculation | null>(null);
  const [error, setError] = useState<string | null>(null);
  const onErrorRef = useRef(onError);
  useEffect(() => {
    onErrorRef.current = onError;
  });
  useEffect(() => {
    if (!engagement.engagementId) return;
    let live = true;
    getRecalculation(engagement.engagementId)
      .then((next) => {
        if (live) setResult(next);
      })
      .catch((caught: unknown) => {
        if (live && !onErrorRef.current(caught)) setError(userFacingApiError(caught));
      });
    return () => {
      live = false;
    };
  }, [engagement.engagementId]);

  if (!engagement.engagementId) {
    return (
      <section className="s1-content s1-output">
        <div className="s1-ws-empty">
          <p>Pick or create an engagement in Setup to see its output.</p>
        </div>
      </section>
    );
  }
  if (error) {
    return (
      <section className="s1-content s1-output">
        <div className="s1-ws-empty">
          <p>Could not load the results. {error}</p>
        </div>
      </section>
    );
  }
  if (!result || result.engagement_id !== engagement.engagementId) {
    return (
      <section className="s1-content s1-output">
        <p className="s1-muted">Assembling the results…</p>
      </section>
    );
  }

  const byKey = new Map(result.comparisons.map((c) => [c.key, c]));
  const materiality = recalculationMateriality(result);
  const scope1 = result.scope_totals.scope1?.total_co2e ?? null;
  const location = result.scope_totals.scope2_location?.total_co2e ?? null;
  const market = result.scope_totals.scope2_market?.total_co2e ?? null;
  const t = (n: number | null) => (n === null ? "Not calculated" : formatNumber(n));
  const reviewed = values.filter((v) => v.reviewState === "accepted" || v.reviewState === "corrected");
  const corrected = values.filter((v) => v.reviewState === "corrected").length;
  const openAsks = asks.filter((a) => a.state === "not_yet_sent" || a.state === "requested").length;
  const resolvedAsks = asks.filter((a) => a.state === "resolved").length;
  const leftOut = result.excluded ?? [];
  const period = `${engagement.reportingPeriod.start || "?"} to ${engagement.reportingPeriod.end || "?"}`;

  return (
    <section className="s1-content s1-output">
      <header className="s1-ws-header">
        <div className="s1-ws-header__id">
          <h1>Output</h1>
          <span className="s1-muted">This engagement&rsquo;s results, from the reviewed evidence.</span>
        </div>
        <div className="s1-out-actions">
          <span className="s1-state s1-state--open s1-out-status">Draft · not issued</span>
          <a
            className="s1-button s1-button--pri"
            href={apiPath(`/engagements/${encodeURIComponent(engagement.engagementId)}/export`)}
            download
          >
            Download workpaper (Excel)
          </a>
        </div>
      </header>

      <article className="s1-out-doc">
        <div className="s1-out-doc__band">
          <div className="s1-out-brand">Sustentra</div>
          <div className="s1-out-eyebrow">Draft working paper · not an assurance opinion</div>
        </div>
        <div className="s1-out-titleblock">
          <h2>{engagement.clientName || engagement.engagementName || "Engagement"}</h2>
          <p className="s1-muted">Greenhouse gas emissions · Scope 1 and Scope 2 · recalculated from reviewed evidence</p>
        </div>
        <dl className="s1-out-meta">
          <Meta label="Reporting period" value={period} />
          <Meta label="Regulation" value={engagement.regulation || "Not set in Setup"} />
          <Meta label="Assurance level" value={engagement.assuranceLevel || "Not set in Setup"} />
          <Meta label="Methodology" value={engagement.methodology || "GHG Protocol Corporate Standard"} />
          <Meta label="Emission factors" value="EPA GHG Emission Factors Hub 2025" />
          <Meta label="GWP basis" value={`${result.gwp_set}${result.gwp_set === "AR5" ? " (EPA Hub Table 11)" : ""}`} />
        </dl>

        <section className="s1-out-section">
          <h3>Recalculated emissions</h3>
          <div className="s1-out-tiles">
            <Tile label="Scope 1" value={t(scope1)} />
            <Tile label="Scope 2 (location-based)" value={t(location)} />
            <Tile label="Scope 2 (market-based)" value={t(market)} />
            <Tile
              label="Materiality threshold"
              value={formatNumber(materiality.total * (materiality.tolerancePct / 100))}
              sub={`${materiality.tolerancePct}% of ${formatNumber(materiality.total)} t`}
            />
          </div>
          <div className="s1-table-wrap s1-out-tablewrap">
            <table className="s1-table s1-out-table">
              <thead>
                <tr>
                  <th>Emissions</th>
                  <th className="s1-out-num">Reported (t CO₂e)</th>
                  <th className="s1-out-num">Recalculated (t CO₂e)</th>
                  <th>Outcome</th>
                </tr>
              </thead>
              <tbody>
                {ROWS.map(({ key, label }) => {
                  const c = byKey.get(key);
                  if (!c) return null;
                  const outcome = c.inputs_incomplete && c.status !== "not_recalculated"
                    ? { label: "Inputs incomplete", role: "unverifiable" }
                    : OUTCOME[c.status];
                  return (
                    <tr key={key}>
                      <td>{label}</td>
                      <td className="s1-out-num">{c.reported === null ? "Not entered" : formatNumber(c.reported)}</td>
                      <td className="s1-out-num">{c.recalculated === null ? "None" : formatNumber(c.recalculated)}</td>
                      <td>
                        <span className={`s1-state s1-state--${outcome.role}`}>{outcome.label}</span>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </section>

        <section className="s1-out-section s1-out-split">
          <div>
            <h3>Findings</h3>
            {findings.length === 0 ? (
              <p className="s1-muted">No findings registered.</p>
            ) : (
              <ul className="s1-out-list">
                {findings.map((f) => (
                  <li key={f.id}>
                    <span className="s1-state s1-state--open">{f.status}</span> {f.dataPointLabel}: {f.sentence}
                  </li>
                ))}
              </ul>
            )}
          </div>
          <div>
            <h3>Basis of evidence</h3>
            <ul className="s1-out-list">
              <li>
                <strong>{evidence.length}</strong> documents uploaded, <strong>{result.documents_considered}</strong> with
                reviewed values
              </li>
              <li>
                <strong>{reviewed.length}</strong> values reviewed, <strong>{corrected}</strong> corrected or entered by the
                reviewer
              </li>
              <li>
                <strong>{openAsks}</strong> requests open, <strong>{resolvedAsks}</strong> resolved
              </li>
              <li>
                <strong>{leftOut.length}</strong> documents or records left out (withdrawn, duplicate, superseded or outside
                the period)
              </li>
              <li>Not calculated yet: {result.not_recalculated.join(", ")}</li>
            </ul>
          </div>
        </section>

        <section className="s1-out-signoff">
          <div>
            <div className="s1-out-signoff__name">Not signed</div>
            <div className="s1-muted">
              A draft working paper for the verifier. The assurance opinion is issued by the verifier, not by this tool.
            </div>
          </div>
        </section>
      </article>
    </section>
  );
}

function Meta({ label, value }: { label: string; value: string }) {
  return (
    <div className="s1-out-meta__item">
      <dt className="s1-label">{label}</dt>
      <dd>{value}</dd>
    </div>
  );
}

function Tile({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="s1-out-tile">
      <div className="s1-out-tile__label">{label}</div>
      <div className="s1-out-tile__value">
        {value} <span className="s1-out-tile__unit">t CO₂e</span>
      </div>
      {sub ? <div className="s1-out-tile__sub">{sub}</div> : null}
    </div>
  );
}
