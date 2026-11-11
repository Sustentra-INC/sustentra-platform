"use client";

import { FileText } from "lucide-react";
import { useEffect, useState } from "react";

import { getLineSchedule, type CoverageStatus, type LineSchedule } from "../api/evidenceTree";
import { resolveFieldKey } from "../utils/resolveFieldKey";
import { userFacingApiError } from "../api/s1Backend";
import { ContainerStateSurface } from "./ContainerStateSurface";

/**
 * One calculation line's supporting schedule: what covers each month of the year, which
 * identifiers the documents agree on, the accepted values and the line's history. Everything is
 * computed by the backend; this only lays it out. Summary first (coverage and identifiers), the
 * values table below it, the history folded.
 */

export interface SupportingScheduleProps {
  engagementId: string;
  lineKey: string;
  onBack: () => void;
  /** Opens a document in the extraction review, at one value when given. */
  onOpenDocument: (documentId: string, valueId?: string) => void;
  /** Goes to the line's calculation. Today that is Verification results; it will focus the line. */
  onOpenCalculationLine: (lineKey: string) => void;
  /** Gives the app a chance to handle an ended session; true when it did. */
  onError?: (error: unknown) => boolean;
}

const SCOPE_LABELS: Record<string, string> = { s1: "Scope 1", s2: "Scope 2", biogenic: "Biogenic" };
const CATEGORY_LABELS: Record<string, string> = {
  stationary: "Stationary combustion",
  mobile: "Mobile combustion",
  fugitive: "Fugitive emissions",
  process: "Process emissions",
  purchased_energy: "Purchased energy",
  contractual: "Contractual instruments",
  biogenic: "Biogenic CO₂",
};

const STATUS_TEXT: Record<CoverageStatus, string> = {
  counted: "Counted",
  counted_in_part: "Counted in part",
  not_reviewed: "Not reviewed",
  no_document: "No document",
};
const STATUS_ROLE: Record<CoverageStatus, string> = {
  counted: "resolved",
  counted_in_part: "active",
  not_reviewed: "open",
  no_document: "na",
};

export function SupportingSchedule({ engagementId, lineKey, onBack, onOpenDocument, onOpenCalculationLine, onError }: SupportingScheduleProps) {
  const [schedule, setSchedule] = useState<LineSchedule | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let live = true;
    getLineSchedule(engagementId, lineKey)
      .then((next) => {
        if (!live) return;
        setSchedule(next);
        setProblem(null);
      })
      .catch((error: unknown) => {
        if (!live || onError?.(error)) return;
        setProblem(userFacingApiError(error));
      });
    return () => {
      live = false;
    };
    // onError changes every render of the app; the schedule loads when the line changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [engagementId, lineKey, attempt]);

  if (problem) {
    return (
      <section className="s1-content s1-sch">
        <button className="s1-linklike" type="button" onClick={onBack}>
          ‹ Back to Evidence
        </button>
        <div className="s1-system-banner" role="alert">
          <strong>Couldn&apos;t load this schedule</strong>
          <span>{problem} </span>
          <button className="s1-button" type="button" onClick={() => setAttempt((n) => n + 1)}>
            Try again
          </button>
        </div>
      </section>
    );
  }
  if (!schedule) {
    return (
      <section className="s1-content s1-sch">
        <ContainerStateSurface state="loading" />
      </section>
    );
  }

  const { line } = schedule;
  const year = reportingYear(schedule.reporting_period);
  const fileNames = new Map(schedule.values.map((v) => [v.document_id, v.file_name]));
  const crumbs = [SCOPE_LABELS[line.scope] ?? line.scope, CATEGORY_LABELS[line.category] ?? line.category, line.level2_label, line.label];

  return (
    <section className="s1-content s1-sch">
      <header className="s1-sch-head">
        <div className="s1-sch-head__id">
          <nav className="s1-sch-crumbs" aria-label="Breadcrumb">
            <button className="s1-linklike" type="button" onClick={onBack}>
              Evidence
            </button>
            {crumbs.map((c, i) => (
              <span key={`${i}:${c}`}>
                <span aria-hidden> › </span>
                {c}
              </span>
            ))}
          </nav>
          <p className="s1-sch-eyebrow">Supporting schedule</p>
          {/* "<Line> · <Level 2>", unless the server's label already names the fuel. */}
          <h1>{line.label.toLowerCase().includes(line.level2_label.toLowerCase()) ? line.label : `${line.label} · ${line.level2_label}`}</h1>
          {year ? <p className="s1-muted">Reporting year {year}</p> : null}
        </div>
        <div className="s1-sch-head__actions">
          <button className="s1-linklike" type="button" onClick={onBack}>
            ‹ Back to Evidence
          </button>
          <button className="s1-button s1-button--pri" type="button" onClick={() => onOpenCalculationLine(line.key)}>
            Open calculation line ›
          </button>
        </div>
      </header>

      <div className="s1-sch-top">
        <section className="s1-panel s1-sch-cov" aria-label="Coverage by month">
          <h2>Coverage by month</h2>
          {schedule.coverage.length ? (
            <ul className="s1-sch-months">
              {schedule.coverage.map((m) => {
                const doc = m.document_ids[0];
                const body = (
                  <>
                    <span className="s1-sch-month__name">{monthName(m.month)}</span>
                    <span className="s1-sch-month__status">
                      {STATUS_TEXT[m.status]}
                      {m.flags?.includes("unconverted") ? " · units differ" : ""}
                    </span>
                    {m.quantity !== null ? (
                      <span className="s1-sch-month__qty">
                        {formatQuantity(m.quantity)} {m.unit ?? ""}
                      </span>
                    ) : null}
                  </>
                );
                const cls = `s1-sch-month s1-sch-month--${STATUS_ROLE[m.status]}`;
                return (
                  <li key={m.month}>
                    {m.document_ids.length > 1 ? (
                      // Several documents cover the month: each one opens from a short list.
                      <div className={cls}>
                        {body}
                        <span className="s1-sch-month__docs">
                          {m.document_ids.map((id, i) => (
                            <button
                              key={id}
                              className="s1-linklike"
                              type="button"
                              aria-label={`${monthName(m.month)}: open ${fileNames.get(id) ?? `document ${i + 1}`}`}
                              onClick={() => onOpenDocument(id)}
                            >
                              {fileNames.get(id) ?? `Document ${i + 1}`}
                            </button>
                          ))}
                        </span>
                      </div>
                    ) : doc ? (
                      <button
                        className={`s1-sch-month s1-sch-month--${STATUS_ROLE[m.status]}`}
                        type="button"
                        aria-label={`${monthName(m.month)}: ${STATUS_TEXT[m.status]}. Open ${m.document_ids.length === 1 ? "the document" : "the first document"}`}
                        onClick={() => onOpenDocument(doc)}
                      >
                        {body}
                      </button>
                    ) : (
                      <span className={`s1-sch-month s1-sch-month--${STATUS_ROLE[m.status]}`}>{body}</span>
                    )}
                  </li>
                );
              })}
            </ul>
          ) : (
            <p className="s1-muted">No months to show yet.</p>
          )}
          <ul className="s1-sch-legend" aria-label="Legend">
            {(Object.keys(STATUS_TEXT) as CoverageStatus[]).map((s) => (
              <li key={s}>
                <span className={`s1-sch-swatch s1-sch-swatch--${STATUS_ROLE[s]}`} aria-hidden /> {STATUS_TEXT[s]}
              </li>
            ))}
          </ul>
        </section>

        <section className="s1-panel s1-sch-ids" aria-label="Source identifiers">
          <h2>Source identifiers</h2>
          {schedule.identifiers.length ? (
            <ul>
              {schedule.identifiers.map((id) => {
                const all = id.documents_with === id.documents_total;
                return (
                  <li key={id.label} className={all ? "" : "is-partial"}>
                    <span className="s1-sch-ids__label">{id.label}</span>
                    <span className="s1-sch-ids__value">{id.value}</span>
                    <span className="s1-sch-ids__n">
                      {id.documents_with}/{id.documents_total} documents{all ? "" : " · not on all"}
                    </span>
                  </li>
                );
              })}
            </ul>
          ) : (
            <p className="s1-muted">No identifiers were read from these documents.</p>
          )}
        </section>
      </div>

      <section className="s1-panel" aria-label="Accepted values">
        <h2>Accepted values</h2>
        {schedule.values.length ? (
          <div className="s1-table-wrap s1-sch-values">
            <table className="s1-table">
              <thead>
                <tr>
                  <th>Service period</th>
                  <th className="s1-num">Days</th>
                  <th className="s1-num">Quantity</th>
                  <th>Decision</th>
                  <th>Document</th>
                </tr>
              </thead>
              <tbody>
                {schedule.values.map((v, i) => (
                  <tr key={`${v.document_id}:${v.candidate_id ?? i}`}>
                    <td>
                      {formatDate(v.service_period_start)} to {formatDate(v.service_period_end)}
                    </td>
                    <td className="s1-num">{v.days}</td>
                    <td className="s1-num">
                      {formatQuantity(v.quantity)} {v.unit}
                    </td>
                    <td>{decisionText(v.decision, v.decided_by, v.decided_at)}</td>
                    <td>
                      <button
                        className="s1-icon-button"
                        type="button"
                        aria-label={`Open ${v.file_name}${v.page ? `, page ${v.page}` : ""} at this value`}
                        title={v.file_name}
                        onClick={() => onOpenDocument(v.document_id, v.candidate_id ? resolveFieldKey({ candidateId: v.candidate_id, backendFieldId: "" }) : undefined)}
                      >
                        <FileText aria-hidden />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="s1-muted">No values are accepted on this line yet.</p>
        )}
      </section>

      <details className="s1-panel s1-sch-history">
        <summary>Line history ({schedule.history.length})</summary>
        {schedule.history.length ? (
          <ul>
            {schedule.history.map((h, i) => (
              <li key={`${h.at}:${i}`}>
                <span className="s1-muted">{formatDateTime(h.at)}</span> {h.text}
              </li>
            ))}
          </ul>
        ) : (
          <p className="s1-muted">Nothing has happened on this line yet.</p>
        )}
      </details>
    </section>
  );
}

/* =============================== helpers =============================== */

function reportingYear(period: LineSchedule["reporting_period"]): string | null {
  const a = period.start?.slice(0, 4);
  const b = period.end?.slice(0, 4);
  if (!a) return null;
  return b && b !== a ? `${a} to ${b}` : a;
}

function monthName(month: string): string {
  const d = new Date(`${month}-01T00:00:00`);
  return Number.isNaN(d.getTime()) ? month : d.toLocaleDateString(undefined, { month: "short", year: "numeric" });
}

function formatDate(iso: string): string {
  const d = new Date(iso.length === 10 ? `${iso}T00:00:00` : iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

function formatDateTime(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime())
    ? iso
    : d.toLocaleString(undefined, { year: "numeric", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
}

function formatQuantity(n: number): string {
  return n.toLocaleString(undefined, { maximumFractionDigits: 3 });
}

function decisionText(decision: string | null, by: string | null, at: string | null): string {
  const what = decision ? decision.charAt(0).toUpperCase() + decision.slice(1) : "Accepted";
  return [by ? `${what} by ${by}` : what, at ? formatDate(at) : null].filter(Boolean).join(" · ");
}
