"use client";

import { ChevronDown, ChevronRight, FileText } from "lucide-react";
import { useEffect, useState } from "react";

import { getLineSchedule, type CoverageStatus, type IdentifierGroup, type LineSchedule, type ScheduleCell, type ScheduleRow } from "../api/evidenceTree";
import { resolveFieldKey } from "../utils/resolveFieldKey";
import { userFacingApiError } from "../api/s1Backend";
import { ContainerStateSurface } from "./ContainerStateSurface";

/**
 * One calculation line's supporting schedule: what covers each month of the year, which
 * identifiers the documents agree on, the extracted values (read only) and the line's history. Everything is
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
        // The API and web deploy together: a response without the v2 fields is a failed load, not an empty schedule.
        if (!Array.isArray(next.rows) || !Array.isArray(next.columns) || !Array.isArray(next.identifier_groups)) {
          setProblem("The schedule came back incomplete. Try again in a moment.");
          return;
        }
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
  const { rows, columns, identifier_groups: groups } = schedule;
  // Numbers are right-aligned; text (vehicle type, on/off road) and dates are left-aligned.
  const isNumeric = (key: string) =>
    key !== "date" && rows.every((r) => {
      const v = key === "activity_quantity" ? r.activity_quantity.value : r.cells[key]?.value;
      return v === null || v === undefined || typeof v === "number";
    });
  // The date header follows the documents: one label when they all agree, else the column's own.
  const dateLabels = new Set(rows.map((r) => r.date.label).filter(Boolean));
  const headerLabel = (c: { key: string; label: string }) => (c.key === "date" && dateLabels.size === 1 ? [...dateLabels][0] : c.label);
  const fileNames = new Map<string, string>([...schedule.values, ...rows].map((v) => [v.document_id, v.file_name]));
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
          {schedule.calculated === false ? (
            <p className="s1-muted s1-sch-notcalc">Not calculated yet: values on this line are waiting for review.</p>
          ) : (
            <button className="s1-button s1-button--pri" type="button" onClick={() => onOpenCalculationLine(line.key)}>
              Open calculation line ›
            </button>
          )}
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
                    {m.waiting_on?.length ? <span className="s1-sch-month__waiting">Waiting on: {m.waiting_on.join(", ")}</span> : null}
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
          {groups.length ? (
            <ul>
              {groups.map((g) => (
                <IdentifierItem key={g.label} group={g} onOpenDocument={onOpenDocument} />
              ))}
            </ul>
          ) : (
            <p className="s1-muted">No identifiers were read from these documents.</p>
          )}
        </section>
      </div>

      <section className="s1-panel" aria-label="Accepted values">
        <h2>Accepted values</h2>
        {schedule.activity_quantity_note ? <p className="s1-muted">{schedule.activity_quantity_note}</p> : null}
        {rows.length ? (
          <div className="s1-table-wrap s1-sch-values">
            <table className="s1-table">
              <thead>
                <tr>
                  {columns.map((c) => (
                    <th key={c.key} className={isNumeric(c.key) ? "s1-num" : ""}>
                      {headerLabel(c)}
                    </th>
                  ))}
                  <th>Saved by</th>
                  <th>Document</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.record_key} className={isPending(r) ? "s1-sch-row--pending" : ""}>
                    {columns.map((c) => (
                      <td key={c.key} className={isNumeric(c.key) ? "s1-num" : ""}>
                        {c.key === "date" ? (
                          <>
                            {formatSpan(r.date)}
                            {rowFlag(r) ? <span className="s1-sch-row__flag"> {rowFlag(r)}</span> : null}
                          </>
                        ) : (
                          cellText(c.key, r)
                        )}
                      </td>
                    ))}
                    <td className="s1-muted">{savedByText(r)}</td>
                    <td>
                      <button
                        className="s1-icon-button"
                        type="button"
                        aria-label={`Open ${r.file_name}${r.page ? `, page ${r.page}` : ""} at this value`}
                        title={r.file_name}
                        onClick={() => onOpenDocument(r.document_id, r.candidate_id ? resolveFieldKey({ candidateId: r.candidate_id, backendFieldId: "" }) : undefined)}
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
          <p className="s1-muted">No values have been extracted on this line yet.</p>
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

/** MM/DD/YY from an ISO date or timestamp, without a timezone shift. */
function formatDate(iso: string): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso);
  return m ? `${m[2]}/${m[3]}/${m[1].slice(2)}` : iso;
}

/** "start – end · N days" (N from the server), or one date when the record has no span. */
function formatSpan(d: ScheduleRow["date"]): string {
  const from = d.start ?? d.end;
  if (!from) return "";
  const range = d.end && d.start && d.end !== d.start ? `${formatDate(d.start)} – ${formatDate(d.end)}` : formatDate(from);
  return d.days && range.includes(" – ") ? `${range} · ${d.days} ${d.days === 1 ? "day" : "days"}` : range;
}

function formatValue(c: ScheduleCell): string {
  if (c.value === null || c.value === undefined || c.value === "") return "";
  // Shown as the server sent it: the page never rounds or regroups a number.
  const v = String(c.value);
  return c.unit ? `${v} ${c.unit}` : v;
}

function cellText(key: string, r: ScheduleRow): string {
  const cell: ScheduleCell | undefined = key === "activity_quantity" ? r.activity_quantity : r.cells[key];
  return cell ? formatValue(cell) : "";
}

/** A row that is not counted: greyed, with a word. */
function isPending(r: ScheduleRow): boolean {
  return !r.accepted;
}

/** The word on a row: why it is not counted, or "Edited" for a corrected value; null for plain accepted rows. */
function rowFlag(r: ScheduleRow): string | null {
  switch (r.decision) {
    case "accepted":
      return null;
    case "edited":
      return "Edited";
    case "rejected":
      return "Rejected";
    case "needs_more_evidence":
      return "Needs more evidence";
    case "not_reviewed":
      return "Not reviewed";
    case "awaiting_other_fields":
      return `Waiting on: ${r.waiting_on?.join(", ") || "other fields"}`;
    default:
      return r.accepted ? null : "Not reviewed";
  }
}

function savedByText(r: ScheduleRow): string {
  if (!r.saved_by) return "";
  return `Saved by ${r.saved_by.name}${r.saved_by.at ? ` · ${formatDate(r.saved_by.at)}` : ""}`;
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

/** One identifier: "n of N documents"; opens to group the documents by value, with a Not found group. */
function IdentifierItem({ group, onOpenDocument }: { group: IdentifierGroup; onOpenDocument: (documentId: string) => void }) {
  const [open, setOpen] = useState(false);
  const all = group.documents_with === group.documents_total;
  const summary = group.values.length > 1 ? `${group.values.length} values` : (group.values[0]?.value.trim() || "Not found");
  const count = (n: number) => `${n} ${n === 1 ? "document" : "documents"}`;
  const docLink = (d: { document_id: string; file_name: string }) => (
    <button key={d.document_id} className="s1-linklike" type="button" aria-label={`Open ${d.file_name}`} onClick={() => onOpenDocument(d.document_id)}>
      {d.file_name}
    </button>
  );
  return (
    <li className={all ? "" : "is-partial"}>
      <button className="s1-sch-ids__toggle" type="button" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
        {open ? <ChevronDown aria-hidden /> : <ChevronRight aria-hidden />}
        <span className="s1-sch-ids__label">{group.label}</span>
        <span className="s1-sch-ids__value">{summary}</span>
        <span className="s1-sch-ids__n">
          {group.documents_with} of {group.documents_total} documents
        </span>
      </button>
      {group.matched_by?.length ? <p className="s1-muted s1-sch-ids__how">Matched by: {group.matched_by.join("; ")}</p> : null}
      {open ? (
        <ul className="s1-sch-ids__groups">
          {group.values.map((v) => (
            <li key={v.value}>
              <span className="s1-sch-ids__gname">
                {v.value.trim() ? v.value : "Not found"} · {count(v.documents.length)}
              </span>
              <span className="s1-sch-ids__docs">{v.documents.map(docLink)}</span>
            </li>
          ))}
          {group.not_found.length ? (
            <li>
              <span className="s1-sch-ids__gname">Not found · {count(group.not_found.length)}</span>
              <span className="s1-sch-ids__docs">{group.not_found.map(docLink)}</span>
            </li>
          ) : null}
        </ul>
      ) : null}
    </li>
  );
}
