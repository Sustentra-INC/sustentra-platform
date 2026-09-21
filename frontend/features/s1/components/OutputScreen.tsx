"use client";

import { useState } from "react";

import type { EngagementConfig } from "../types";

/**
 * Output (screen 7). A preview of the assurance deliverable the engagement
 * produces: the independent limited-assurance statement, the verified emissions
 * summary, the corrections register and the evidence basis. Figures here are an
 * illustrative assembly of the workpaper for the demo.
 */
export function OutputScreen({ engagement }: { engagement?: EngagementConfig }) {
  const [toast, setToast] = useState<string | null>(null);
  function flash(m: string) {
    setToast(m);
    window.setTimeout(() => setToast(null), 2400);
  }

  const client = engagement?.clientName ?? "Cascade Provisions Co.";
  const period = engagement
    ? `${engagement.reportingPeriod.start} to ${engagement.reportingPeriod.end}`
    : "2025-01-01 to 2025-12-31";
  const year = (engagement?.reportingPeriod.start ?? "2025").slice(0, 4);
  const regulation = engagement?.regulation ?? "California Senate Bill 253";
  const boundary = engagement?.boundaryApproach ?? "Operational control";
  const assurance = engagement?.assuranceLevel ?? "Limited assurance";

  return (
    <section className="s1-content s1-output">
      <header className="s1-ws-header">
        <div className="s1-ws-header__id">
          <h1>Output</h1>
          <span className="s1-muted">The assurance deliverable this engagement produces.</span>
        </div>
        <div className="s1-out-actions">
          <span className="s1-state s1-state--open s1-out-status">Draft · not issued</span>
          <button className="s1-button" type="button" onClick={() => flash("Register exported (CSV)")}>
            <CsvIcon /> Corrections register
          </button>
          <button className="s1-button" type="button" onClick={() => flash("Evidence index exported")}>
            <ListIcon /> Evidence index
          </button>
          <button className="s1-button s1-button--pri" type="button" onClick={() => flash("Statement prepared for issue")}>
            <DocIcon /> Download statement
          </button>
        </div>
      </header>

      {/* the deliverable, as a document */}
      <article className="s1-out-doc">
        <div className="s1-out-doc__band">
          <div className="s1-out-brand">Sustentra</div>
          <div className="s1-out-eyebrow">Independent limited assurance report</div>
        </div>

        <div className="s1-out-titleblock">
          <h2>{client}</h2>
          <p className="s1-muted">Greenhouse gas emissions statement · Scope 1 and Scope 2</p>
        </div>

        <dl className="s1-out-meta">
          <MetaItem label="Reporting period" value={period} />
          <MetaItem label="Regulation" value={regulation} />
          <MetaItem label="Assurance level" value={assurance} />
          <MetaItem label="Boundary approach" value={boundary} />
          <MetaItem label="Methodology" value={engagement?.methodology ?? "GHG Protocol Corporate Standard"} />
          <MetaItem label="Verifier" value="Meridian Assurance LLP" />
        </dl>

        <section className="s1-out-section">
          <h3>Conclusion</h3>
          <p className="s1-out-lead">
            Based on the procedures performed and the evidence obtained, nothing has come to our attention that causes us
            to believe that {client}&rsquo;s Scope 1 and Scope 2 greenhouse gas emissions for the year ended {year}, as set
            out below, are not prepared, in all material respects, in accordance with the {engagement?.methodology ??
              "GHG Protocol Corporate Standard"}{" "}
            and the reporting requirements of {regulation}.
          </p>
        </section>

        <section className="s1-out-section">
          <h3>Verified emissions</h3>
          <div className="s1-out-tiles">
            <BigTile label="Total (location-based)" value="6,537.6" unit="tCO2e" tone="accent" />
            <BigTile label="Total (market-based)" value="6,832.3" unit="tCO2e" />
            <BigTile label="Uncorrected misstatement" value="118.4" unit="tCO2e" sub="1.8% of total" />
            <BigTile label="Materiality threshold" value="5.0" unit="%" sub="327 tCO2e" />
          </div>

          <div className="s1-table-wrap s1-out-tablewrap">
            <table className="s1-table s1-out-table">
              <thead>
                <tr>
                  <th>Emissions category</th>
                  <th>Basis</th>
                  <th className="s1-out-num">Reported</th>
                  <th className="s1-out-num">Verified</th>
                  <th>Outcome</th>
                </tr>
              </thead>
              <tbody>
                <ScopeRow cat="Scope 1 · stationary combustion (natural gas)" basis="Meter + invoice" reported="2,140.3" verified="2,140.3" outcome="held" />
                <ScopeRow cat="Scope 1 · mobile combustion (fleet)" basis="Fuel records" reported="486.9" verified="486.9" outcome="held" />
                <ScopeRow cat="Scope 2 · purchased electricity" basis="Location-based" reported="3,880.1" verified="3,910.4" outcome="corrected" />
                <ScopeRow cat="Scope 2 · purchased electricity" basis="Market-based" reported="4,205.1" verified="4,205.1" outcome="held" />
              </tbody>
              <tfoot>
                <tr className="s1-out-total">
                  <td colSpan={3}>Total location-based Scope 1 + Scope 2</td>
                  <td className="s1-out-num">6,537.6</td>
                  <td />
                </tr>
              </tfoot>
            </table>
          </div>
          <p className="s1-muted s1-out-foot">
            Scope 2 location-based uses eGRID 2024 subregion factors. One correction posted (+30.3 tCO2e) for a
            transposed meter read at Kent Cannery.
          </p>
        </section>

        <section className="s1-out-section s1-out-split">
          <div>
            <h3>Corrections register</h3>
            <ul className="s1-out-list">
              <li><span className="s1-state s1-state--resolved">Corrected</span> Kent Cannery electricity, Feb 2025 — meter read transposition</li>
              <li><span className="s1-state s1-state--resolved">Corrected</span> Modesto Bottling diesel, Q2 — unit conversion</li>
              <li><span className="s1-state s1-state--open">Uncorrected</span> Tualatin refrigerant estimate — below materiality</li>
            </ul>
          </div>
          <div>
            <h3>Basis of evidence</h3>
            <ul className="s1-out-list">
              <li><strong>34</strong> data points with inputs present and verified</li>
              <li><strong>12</strong> data points requested from the client and resolved</li>
              <li><strong>148</strong> source documents across 3 facilities</li>
              <li><strong>5</strong> assertions out of scope for this engagement</li>
            </ul>
          </div>
        </section>

        <section className="s1-out-signoff">
          <div>
            <div className="s1-out-signoff__name">M. Osei</div>
            <div className="s1-muted">Lead verifier · Meridian Assurance LLP</div>
          </div>
          <div className="s1-out-signoff__date">
            <div className="s1-label">Date of report</div>
            <div>08 Apr {year}</div>
          </div>
        </section>
      </article>

      {toast ? <div className="s1-ws-toast">{toast}</div> : null}
    </section>
  );
}

function MetaItem({ label, value }: { label: string; value: string }) {
  return (
    <div className="s1-out-meta__item">
      <dt className="s1-label">{label}</dt>
      <dd>{value}</dd>
    </div>
  );
}

function BigTile({ label, value, unit, sub, tone }: { label: string; value: string; unit: string; sub?: string; tone?: "accent" }) {
  return (
    <div className={`s1-out-tile${tone === "accent" ? " s1-out-tile--accent" : ""}`}>
      <div className="s1-out-tile__label">{label}</div>
      <div className="s1-out-tile__value">
        {value} <span className="s1-out-tile__unit">{unit}</span>
      </div>
      {sub ? <div className="s1-out-tile__sub">{sub}</div> : null}
    </div>
  );
}

function ScopeRow({ cat, basis, reported, verified, outcome }: { cat: string; basis: string; reported: string; verified: string; outcome: "held" | "corrected" }) {
  return (
    <tr>
      <td>{cat}</td>
      <td className="s1-muted">{basis}</td>
      <td className="s1-out-num">{reported}</td>
      <td className="s1-out-num">{verified}</td>
      <td>
        <span className={`s1-state s1-state--${outcome === "held" ? "resolved" : "active"}`}>
          {outcome === "held" ? "Held" : "Corrected"}
        </span>
      </td>
    </tr>
  );
}

const SVG = { fill: "none", stroke: "currentColor", strokeWidth: 1.7, strokeLinecap: "round" as const, strokeLinejoin: "round" as const };

function DocIcon() {
  return (
    <svg viewBox="0 0 24 24" {...SVG} aria-hidden="true">
      <path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z" />
      <path d="M14 3v5h5M9 13h6M9 17h6" />
    </svg>
  );
}
function CsvIcon() {
  return (
    <svg viewBox="0 0 24 24" {...SVG} aria-hidden="true">
      <rect x="4" y="4" width="16" height="16" rx="2" />
      <path d="M4 10h16M10 4v16" />
    </svg>
  );
}
function ListIcon() {
  return (
    <svg viewBox="0 0 24 24" {...SVG} aria-hidden="true">
      <path d="M8 6h12M8 12h12M8 18h12M4 6h.01M4 12h.01M4 18h.01" />
    </svg>
  );
}
