"use client";

import { useState } from "react";

import type { EngagementConfig } from "../types";
import type { ResultLine } from "../types/verificationResults";
import type { DashboardFigures } from "../utils/engagementActivity";
import { statementFigures } from "../utils/outputStatement";
import { formatPercent, formatSignedTonnes, formatTonnes } from "../utils/verificationTable";

/**
 * Output (screen 7). A preview of the assurance deliverable the engagement
 * produces: the independent limited-assurance statement, the verified emissions
 * summary, the corrections register and the evidence basis. Its figures come from the
 * same results as Verification results, and its counts from the engagement, so the
 * statement never says something the workpaper does not.
 */
export function OutputScreen({
  engagement,
  lines,
  figures,
}: {
  engagement?: EngagementConfig;
  /** The verification results the statement reports. */
  lines: ResultLine[];
  /** The engagement's counts, for the basis of evidence. */
  figures?: DashboardFigures;
}) {
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
  const methodology = engagement?.methodology ?? "GHG Protocol Corporate Standard";
  const statement = statementFigures(lines, engagement?.materialityThreshold);
  const material = statement.materialBoxes;

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
          {material.length ? (
            <p className="s1-out-draftnote" role="note">
              Draft: {material.map((b) => `${b.title} differs from the evidence by ${formatPercent(b.pctMaterial, true)} of its reported total`).join("; ")},
              {" "}at or above the {formatPercent(statement.materiality)} materiality threshold. The conclusion below can be issued only once
              the client corrects it or the difference is explained.
            </p>
          ) : null}
          <p className="s1-out-lead">
            Based on the procedures performed and the evidence obtained, nothing has come to our attention that causes us
            to believe that {client}&rsquo;s Scope 1 and Scope 2 greenhouse gas emissions for the year ended {year}, as set
            out below, are not prepared, in all material respects, in accordance with the {methodology} and the reporting
            requirements of {regulation}.
          </p>
        </section>

        <section className="s1-out-section">
          <h3>Verified emissions</h3>
          <div className="s1-out-tiles">
            <BigTile label="Total (location-based)" value={formatTonnes(statement.location.verified)} unit="tCO2e" tone="accent" sub={`Reported ${formatTonnes(statement.location.reported)}`} />
            <BigTile label="Total (market-based)" value={formatTonnes(statement.market.verified)} unit="tCO2e" sub={`Reported ${formatTonnes(statement.market.reported)}`} />
            <BigTile
              label="Uncorrected misstatement"
              value={formatSignedTonnes(statement.misstatement)}
              unit="tCO2e"
              sub={`${formatPercent(statement.misstatementPct, true)} of the reported total`}
            />
            <BigTile
              label="Materiality threshold"
              value={formatPercent(statement.materiality).replace("%", "")}
              unit="%"
              sub={`${formatTonnes(statement.materialityTonnes)} tCO2e`}
            />
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
                {statement.rows.map((row) => (
                  <ScopeRow key={`${row.label}|${row.basis}`} row={row} />
                ))}
              </tbody>
              <tfoot>
                <tr className="s1-out-total">
                  <td colSpan={2}>Total location-based Scope 1 + Scope 2</td>
                  <td className="s1-out-num">{formatTonnes(statement.location.reported)}</td>
                  <td className="s1-out-num">{formatTonnes(statement.location.verified)}</td>
                  <td />
                </tr>
              </tfoot>
            </table>
          </div>
          <p className="s1-muted s1-out-foot">
            Figures in tCO2e, as on Verification results. Scope 2 location-based uses eGRID subregion factors; biogenic CO₂ is
            reported outside the scopes.
          </p>
        </section>

        <section className="s1-out-section s1-out-split">
          <div>
            <h3>Differences found</h3>
            {statement.findings.length ? (
              <ul className="s1-out-list">
                {statement.findings.slice(0, 5).map((f) => (
                  <li key={`${f.facility}|${f.activity}`}>
                    <span className="s1-state s1-state--open">Uncorrected</span> {f.facility} {f.activity.toLowerCase()},{" "}
                    {formatSignedTonnes(f.difference)} tCO2e: {f.cause}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="s1-muted">No differences between the reported figures and the evidence.</p>
            )}
          </div>
          <div>
            <h3>Basis of evidence</h3>
            {figures ? (
              <ul className="s1-out-list">
                <li>
                  <strong>{figures.documents}</strong> source documents
                </li>
                <li>
                  <strong>{figures.valuesReviewed}</strong> of {figures.valuesReviewed + figures.valuesToReview} values reviewed
                </li>
                {figures.coverage ? (
                  <li>
                    <strong>{figures.coverage.present}</strong> of {figures.coverage.present + figures.coverage.missing} in-scope data
                    points with their inputs present
                  </li>
                ) : null}
                <li>
                  <strong>{figures.requestsResolved}</strong> of {figures.requestsRaised} requests to the client resolved
                </li>
              </ul>
            ) : null}
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

const OUTCOME: Record<"agrees" | "differs" | "material", { label: string; state: string }> = {
  agrees: { label: "Agrees", state: "resolved" },
  differs: { label: "Differs", state: "open" },
  material: { label: "Above materiality", state: "blocking" },
};

function ScopeRow({ row }: { row: ReturnType<typeof statementFigures>["rows"][number] }) {
  const outcome = OUTCOME[row.outcome];
  return (
    <tr>
      <td>{row.label}</td>
      <td className="s1-muted">{row.basis}</td>
      <td className="s1-out-num">{formatTonnes(row.reported)}</td>
      <td className="s1-out-num">{formatTonnes(row.verified)}</td>
      <td>
        <span className={`s1-state s1-state--${outcome.state}`}>{outcome.label}</span>
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
