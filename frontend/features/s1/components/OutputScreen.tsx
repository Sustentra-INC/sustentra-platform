"use client";

import { Cpu } from "lucide-react";
import { useState } from "react";

import type { EngagementConfig } from "../types";
import type { Finding } from "../types/verification";
import type { ResultLine, ResultState } from "../types/verificationResults";
import type { DashboardFigures } from "../utils/engagementActivity";
import { formatReportingPeriod } from "../utils/formatPeriod";
import {
  statementFigures,
  type InventoryTotal,
  type LiveStatementFigures,
  type LiveStatementRow,
  type StatementRow,
} from "../utils/outputStatement";
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
  live,
}: {
  engagement?: EngagementConfig;
  /** The verification results the statement reports. */
  lines: ResultLine[];
  /** The engagement's counts, for the basis of evidence. */
  figures?: DashboardFigures;
  /** Backend mode: the statement from the live results, as a draft working paper. */
  live?: LiveOutput;
}) {
  const [toast, setToast] = useState<string | null>(null);
  function flash(m: string) {
    setToast(m);
    window.setTimeout(() => setToast(null), 2400);
  }
  if (live) return <LiveOutputScreen engagement={engagement} figures={figures} live={live} />;

  const client = engagement?.clientName ?? "Cascade Provisions Co.";
  const period = engagement
    ? formatReportingPeriod(engagement.reportingPeriod.start, engagement.reportingPeriod.end)
    : formatReportingPeriod("2025-01-01", "2025-12-31");
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

/** Output in backend mode: what the live statement needs beyond the demo's props. */
export interface LiveOutput {
  statement: LiveStatementFigures;
  /** The whole workpaper as an Excel workbook (the one real export). */
  exportHref: string;
  /** "AR5 (EPA Hub Table 11)". */
  gwpBasis: string;
  /** The findings the verifier registered. */
  findings: Finding[];
  /** More lines for Basis of evidence: fully reviewed documents, records left out, what is not calculated. */
  basisLines: string[];
}

const NOT_SET = "Not set in Setup";

/**
 * The demo's statement on live data. Only what exists is shown: the one real export, a
 * draft band (no opinion is issued here), recalculated rather than verified figures, a
 * reported value only where one is entered, and states where a total is still open.
 */
function LiveOutputScreen({
  engagement,
  figures,
  live,
}: {
  engagement?: EngagementConfig;
  figures?: DashboardFigures;
  live: LiveOutput;
}) {
  const { statement } = live;
  const client = engagement?.clientName || engagement?.engagementName || "Engagement";
  const period = engagement ? formatReportingPeriod(engagement.reportingPeriod.start, engagement.reportingPeriod.end) : NOT_SET;
  const team = engagement?.engagementTeam?.map((m) => m.name).filter(Boolean).join(", ");
  const threshold = formatPercent(statement.materiality);
  const { location, market } = statement;
  const reportedSub = (total: InventoryTotal) =>
    [total.reported === null ? "Reported total not entered" : `Reported ${formatTonnes(total.reported)}`, total.partial ? "partial: at least this" : ""]
      .filter(Boolean)
      .join(" · ");

  return (
    <section className="s1-content s1-output">
      <header className="s1-ws-header">
        <div className="s1-ws-header__id">
          <h1>Output</h1>
          <span className="s1-muted">The assurance deliverable this engagement produces, from the reviewed evidence.</span>
        </div>
        <div className="s1-out-actions">
          <span className="s1-state s1-state--open s1-out-status">Draft · not issued</span>
          <a className="s1-button s1-button--pri" href={live.exportHref} download>
            <CsvIcon /> Download workpaper (Excel)
          </a>
        </div>
      </header>

      <article className="s1-out-doc">
        <div className="s1-out-doc__band">
          <div className="s1-out-brand">Sustentra</div>
          <div className="s1-out-eyebrow">Draft working paper · not an assurance opinion</div>
        </div>

        <div className="s1-out-titleblock">
          <h2>{client}</h2>
          <p className="s1-muted">Greenhouse gas emissions statement · Scope 1 and Scope 2 · recalculated from reviewed evidence</p>
        </div>

        <dl className="s1-out-meta">
          <MetaItem label="Reporting period" value={period} />
          <MetaItem label="Regulation" value={engagement?.regulation || NOT_SET} />
          <MetaItem label="Assurance level" value={engagement?.assuranceLevel || NOT_SET} />
          <MetaItem label="Boundary approach" value={engagement?.boundaryApproach || NOT_SET} />
          <MetaItem label="Methodology" value={engagement?.methodology || "GHG Protocol Corporate Standard"} />
          <MetaItem label="Emission factors" value="EPA GHG Emission Factors Hub 2025" />
          <MetaItem label="GWP basis" value={live.gwpBasis} />
          {team ? <MetaItem label="Engagement team" value={team} /> : null}
        </dl>

        <section className="s1-out-section">
          <h3>Conclusion</h3>
          {statement.materialBoxes.length ? (
            <p className="s1-out-draftnote" role="note">
              Draft:{" "}
              {statement.materialBoxes
                .map((b) => `${b.title} differs from the evidence by ${formatPercent(b.pctMaterial, true)} of its reported total`)
                .join("; ")}
              , at or above the {threshold} materiality threshold.
            </p>
          ) : null}
          {statement.openBoxes.length ? (
            <p className="s1-out-draftnote" role="note">
              Not compared yet: {statement.openBoxes.map((b) => `${b.title} (${b.state.label.toLowerCase()})`).join("; ")}.
            </p>
          ) : null}
          <p className="s1-out-lead s1-out-placeholder">
            The verifier writes the conclusion when the report is issued. Until then this is a draft working paper, not an
            assurance opinion.
          </p>
        </section>

        <section className="s1-out-section">
          <h3>Recalculated emissions</h3>
          <div className="s1-out-tiles">
            <BigTile
              label="Total (location-based)"
              value={location.recomputed === null ? "Not available" : formatTonnes(location.recomputed)}
              unit="tCO2e"
              tone="accent"
              sub={reportedSub(location)}
            />
            <BigTile
              label="Total (market-based)"
              value={market.recomputed === null ? "Not available" : formatTonnes(market.recomputed)}
              unit="tCO2e"
              sub={reportedSub(market)}
            />
            <BigTile
              label="Uncorrected misstatement"
              value={statement.misstatement === null ? "Not compared" : formatSignedTonnes(statement.misstatement)}
              unit={statement.misstatement === null ? "" : "tCO2e"}
              sub={
                statement.misstatement === null
                  ? "Needs both reported scope totals"
                  : [
                      statement.misstatementPct === null ? "" : `${formatPercent(statement.misstatementPct, true)} of the reported total`,
                      location.partial ? "partial: open items remain" : "",
                    ]
                      .filter(Boolean)
                      .join(" · ")
              }
            />
            <BigTile
              label="Materiality threshold"
              value={threshold.replace("%", "")}
              unit="%"
              sub={
                statement.materialityTonnes === null
                  ? undefined
                  : `${formatTonnes(statement.materialityTonnes)} tCO2e${
                      statement.materialityBase === "recalculated" ? " of the recalculated total" : ""
                    }`
              }
            />
          </div>

          <div className="s1-table-wrap s1-out-tablewrap">
            <table className="s1-table s1-out-table">
              <thead>
                <tr>
                  <th>Emissions category</th>
                  <th>Basis</th>
                  <th className="s1-out-num">Reported</th>
                  <th className="s1-out-num">Recalculated</th>
                  <th>Outcome</th>
                </tr>
              </thead>
              <tbody>
                {statement.rows.map((row) => (
                  <LiveScopeRow key={`${row.label}|${row.basis}`} row={row} />
                ))}
              </tbody>
              <tfoot>
                <tr className="s1-out-total">
                  <td colSpan={2}>Total location-based Scope 1 + Scope 2</td>
                  <td className="s1-out-num">{location.reported === null ? "Not entered" : formatTonnes(location.reported)}</td>
                  <td className="s1-out-num">{location.recomputed === null ? "Not available" : formatTonnes(location.recomputed)}</td>
                  <td>{location.partial ? <span className="s1-state s1-state--open">Partial</span> : null}</td>
                </tr>
              </tfoot>
            </table>
          </div>
          <p className="s1-muted s1-out-foot">
            Figures in tCO2e, as on Verification results: recalculated from reviewed evidence on the EPA GHG Emission Factors
            Hub 2025. Reported figures are the client&rsquo;s totals entered under Recalculation inputs. Biogenic CO₂ is reported
            outside the scopes.
          </p>
        </section>

        <section className="s1-out-section s1-out-split">
          <div>
            <h3>Differences found</h3>
            {statement.differences.length ? (
              <>
                <span className="s1-out-by">
                  <Cpu className="s1-out-by__icon" aria-hidden /> Checked by system
                </span>
                <ul className="s1-out-list">
                  {statement.differences.slice(0, 5).map((d) => (
                    <li key={d.label}>
                      <LiveOutcome outcome={d.outcome} state={d.state} />
                      <span className="s1-out-list__text">
                        {d.label}, {formatSignedTonnes(d.difference)} tCO2e
                        {d.pct === null ? "" : ` (${formatPercent(d.pct, true)})`}
                        {d.state
                          ? `: ${d.state.label.toLowerCase()}, so not compared yet`
                          : d.outcome === "material"
                            ? `: at or above the ${threshold} materiality threshold`
                            : ""}
                      </span>
                    </li>
                  ))}
                </ul>
              </>
            ) : (
              <p className="s1-muted">No difference between a reported figure and the evidence yet.</p>
            )}
            {live.findings.length ? (
              <>
                <h4 className="s1-out-subhead">Findings registered by the verifier</h4>
                <ul className="s1-out-list">
                  {live.findings.map((f) => (
                    <li key={f.id}>
                      <span className="s1-state s1-state--open">{f.status}</span> {f.dataPointLabel}: {f.sentence}
                      {f.registeredBy ? <span className="s1-muted"> · {f.registeredBy}</span> : null}
                    </li>
                  ))}
                </ul>
              </>
            ) : null}
          </div>
          <div>
            <h3>Basis of evidence</h3>
            <ul className="s1-out-list">
              {figures ? (
                <>
                  <li>
                    <strong>{figures.documents}</strong> source documents
                  </li>
                  <li>
                    <strong>{figures.valuesReviewed}</strong> of {figures.valuesReviewed + figures.valuesToReview} values reviewed
                  </li>
                  {figures.coverage ? (
                    <li>
                      <strong>{figures.coverage.present}</strong> of {figures.coverage.present + figures.coverage.missing} in-scope
                      data points with their inputs present
                    </li>
                  ) : null}
                  <li>
                    <strong>{figures.requestsResolved}</strong> of {figures.requestsRaised} requests to the client resolved
                  </li>
                </>
              ) : null}
              {live.basisLines.map((line) => (
                <li key={line}>{line}</li>
              ))}
            </ul>
          </div>
        </section>

        <section className="s1-out-signoff">
          <div>
            {/* The system drafts this page; no one has signed it, whoever is viewing it. */}
            <div className="s1-out-signoff__name">Not signed</div>
            <div className="s1-muted">
              Draft working paper for the verifier. The assurance opinion is issued by the verifier, not by this tool.
            </div>
          </div>
          <div className="s1-out-signoff__date">
            <div className="s1-label">Date of report</div>
            <div>Not issued</div>
          </div>
        </section>
      </article>
    </section>
  );
}

function LiveOutcome({ outcome, state }: { outcome: StatementRow["outcome"] | null; state: ResultState | null }) {
  if (state) return <span className={`s1-state s1-state--${state.tone}`}>{state.label}</span>;
  if (!outcome) return null;
  return <span className={`s1-state s1-state--${OUTCOME[outcome].state}`}>{OUTCOME[outcome].label}</span>;
}

function LiveScopeRow({ row }: { row: LiveStatementRow }) {
  return (
    <tr className={row.total ? "s1-out-subtotal" : undefined}>
      <td>{row.label}</td>
      <td className="s1-muted">{row.basis}</td>
      <td className="s1-out-num">{row.reported === null ? <span className="s1-muted">{row.reportedNote}</span> : formatTonnes(row.reported)}</td>
      <td className="s1-out-num">{row.verified === null ? <span className="s1-muted">Not available</span> : formatTonnes(row.verified)}</td>
      <td>
        <LiveOutcome outcome={row.outcome} state={row.state} />
      </td>
    </tr>
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
