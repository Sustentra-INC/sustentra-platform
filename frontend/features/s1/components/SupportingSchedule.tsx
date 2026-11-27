"use client";

import { ChevronDown, ChevronRight, FileText } from "lucide-react";
import { cloneElement, isValidElement, useEffect, useLayoutEffect, useRef, useState, type ReactElement, type ReactNode } from "react";

import { useWindowedRows } from "../hooks/useWindowedRows";

import { getLineSchedule, type CoverageStatus, type IdentifierGroup, type LineSchedule, type ScheduleCell, type ScheduleHistoryEntry, type ScheduleRow, type ValueSource } from "../api/evidenceTree";
import { resolveFieldKey } from "../utils/resolveFieldKey";
import { ApiError } from "../../../lib/api";
import { userFacingApiError } from "../api/s1Backend";
import { AI_VALUE } from "../constants/copy";
import { useAssignTask } from "../../tasks/AssignTaskContext";
import { ContainerStateSurface } from "./ContainerStateSurface";

/**
 * One calculation line's data point review: what covers each month of the year, which
 * identifiers the documents agree on, the extracted values (read only) and the line's history. Everything is
 * computed by the backend; this only lays it out. Sections stack in a fixed order: header, coverage,
 * source identifiers, accepted values, line history (folded).
 */

export interface SupportingScheduleProps {
  engagementId: string;
  lineKey: string;
  onBack: () => void;
  /** Where the back link goes ("evidence", "dashboard", ...); defaults to evidence. */
  backLabel?: string;
  /** The "Evidence" crumb always opens Evidence (default: the back link's action). */
  onOpenEvidence?: () => void;
  /** The line isn't in this engagement (the API answered 404). */
  onMissing?: () => void;
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

type DisplayStatus = CoverageStatus | "rejected";
const STATUS_TEXT: Record<DisplayStatus, string> = {
  rejected: "Rejected",
  counted: "Counted",
  counted_in_part: "Counted in part",
  not_reviewed: "Not reviewed",
  no_document: "No document",
};
const STATUS_ROLE: Record<DisplayStatus, string> = {
  rejected: "na",
  counted: "resolved",
  counted_in_part: "active",
  not_reviewed: "open",
  no_document: "na",
};

export function SupportingSchedule({ engagementId, lineKey, onBack, backLabel = "evidence", onOpenEvidence, onMissing, onOpenDocument, onOpenCalculationLine, onError }: SupportingScheduleProps) {
  const assign = useAssignTask();
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
          setProblem("The data point review came back incomplete. Try again in a moment.");
          return;
        }
        setSchedule(next);
        setProblem(null);
      })
      .catch((error: unknown) => {
        if (!live || onError?.(error)) return;
        if (error instanceof ApiError && error.status === 404 && onMissing) {
          onMissing();
          return;
        }
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
        <button className="s1-linklike s1-backlink" type="button" onClick={onBack}>
          ‹ Back to {backLabel}
        </button>
        <div className="s1-system-banner" role="alert">
          <strong>Couldn&apos;t load this data point review</strong>
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
        <ContainerStateSurface state="loading" label="Loading the data point review" />
      </section>
    );
  }

  const { line } = schedule;
  const year = reportingYear(schedule.reporting_period);
  const { columns, identifier_groups: groups } = schedule;
  // Accepted values only (Claire, C-S1): unreviewed and rejected values do not appear. Documents with values
  // still waiting are counted in the coverage strip, so nothing disappears silently.
  const allRows = schedule.rows;
  const rows = allRows.filter(isShown);
  const waitingDocuments = countWaitingDocuments(allRows);
  // Numbers are right-aligned; text (vehicle type, on/off road) and dates are left-aligned.
  const isNumeric = (key: string) =>
    key !== "date" && rows.every((r) => {
      const v = key === "activity_quantity" ? r.activity_quantity.value : r.cells[key]?.value;
      return v === null || v === undefined || typeof v === "number";
    });
  // The date header follows the documents: one label when they all agree, else the column's own.
  const dateLabels = new Set(rows.map((r) => r.date.label).filter(Boolean));
  const headerLabel = (c: { key: string; label: string }) => (c.key === "date" && dateLabels.size === 1 ? [...dateLabels][0] : c.label);
  const fileNames = new Map<string, string>([...schedule.values, ...allRows].map((v) => [v.document_id, v.file_name]));
  const crumbs = [SCOPE_LABELS[line.scope] ?? line.scope, CATEGORY_LABELS[line.category] ?? line.category, line.level2_label, line.label];

  return (
    <section className="s1-content s1-sch">
      {/* The back link sits first, left-aligned, like on the other screens. */}
      <button className="s1-linklike s1-backlink" type="button" onClick={onBack}>
        ‹ Back to {backLabel}
      </button>
      <header className="s1-sch-head">
        <div className="s1-sch-head__id">
          <nav className="s1-sch-crumbs" aria-label="Breadcrumb">
            <button className="s1-linklike" type="button" onClick={onOpenEvidence ?? onBack}>
              Evidence
            </button>
            {crumbs.map((c, i) => (
              <span key={`${i}:${c}`}>
                <span aria-hidden> › </span>
                {c}
              </span>
            ))}
          </nav>
          <p className="s1-sch-eyebrow">Data point review</p>
          {/* "<Line> · <Level 2>", unless the server's label already names the fuel. */}
          <h1>{line.label.toLowerCase().includes(line.level2_label.toLowerCase()) ? line.label : `${line.label} · ${line.level2_label}`}</h1>
          {year ? <p className="s1-muted">Reporting year {year}</p> : null}
        </div>
        <div className="s1-sch-head__actions">
          {/* Always present. A line with no calculation yet shows it disabled, with the reason beside it. */}
          <button
            className="s1-button s1-button--pri"
            type="button"
            disabled={schedule.calculated === false}
            aria-describedby={schedule.calculated === false ? "s1-sch-notcalc" : undefined}
            onClick={() => onOpenCalculationLine(line.key)}
          >
            Open calculation line ›
          </button>
          {assign ? (
            <button
              className="s1-button"
              type="button"
              onClick={() => {
                const name = line.label.toLowerCase().includes(line.level2_label.toLowerCase()) ? line.label : `${line.label} · ${line.level2_label}`;
                assign({ kind: "Data point line", label: name, target: { kind: "line", item_id: line.key }, title: `Review ${name}` });
              }}
            >
              Assign to…
            </button>
          ) : null}
          {schedule.calculated === false ? (
            <p id="s1-sch-notcalc" className="s1-muted s1-sch-notcalc">
              {schedule.calculation_blocked
                ? `Not calculated: ${schedule.calculation_blocked}`
                : allRows.some(isWaiting)
                ? "Not calculated yet: values on this line are waiting for review."
                : "No calculation for this line yet."}
            </p>
          ) : null}
        </div>
      </header>

      <section className="s1-panel s1-sch-cov" aria-label="Coverage by month">
        <h2>Coverage by month</h2>
        <p className="s1-muted s1-sch-cov__basis">Counts accepted values only.</p>
        {waitingDocuments > 0 ? (
          <p className="s1-sch-waiting" role="status">
            {plural(waitingDocuments, "document", "documents")} on this line {waitingDocuments === 1 ? "has" : "have"} values not yet reviewed.{" "}
            <button className="s1-linklike" type="button" onClick={onOpenEvidence ?? onBack}>
              Review in Evidence
            </button>
          </p>
        ) : null}
        {schedule.coverage.length ? (
          <ul className="s1-sch-months">
            {schedule.coverage.map((m) => {
              const doc = m.document_ids[0];
              const status = displayStatus(m, allRows);
              const waitingOn = (m.waiting_on ?? []).filter((f) => !decidedFields(m, allRows).has(f));
              const body = (
                <>
                  <span className="s1-sch-month__name">{monthName(m.month)}</span>
                  <span className="s1-sch-month__status">
                    {STATUS_TEXT[status]}
                    {m.flags?.includes("unconverted") ? " · units differ" : ""}
                  </span>
                  {waitingOn.length ? <span className="s1-sch-month__waiting">Waiting on: {waitingOn.join(", ")}</span> : null}
                  {m.quantity !== null ? (
                    <span className="s1-sch-month__qty">
                      {formatQuantity(m.quantity)} {m.unit ?? ""}
                    </span>
                  ) : null}
                </>
              );
              const cls = `s1-sch-month s1-sch-month--${STATUS_ROLE[status]}`;
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
                      className={`s1-sch-month s1-sch-month--${STATUS_ROLE[status]}`}
                      type="button"
                      aria-label={`${monthName(m.month)}: ${STATUS_TEXT[status]}. Open ${m.document_ids.length === 1 ? "the document" : "the first document"}`}
                      onClick={() => onOpenDocument(doc)}
                    >
                      {body}
                    </button>
                  ) : (
                    <span className={`s1-sch-month s1-sch-month--${STATUS_ROLE[status]}`}>{body}</span>
                  )}
                </li>
              );
            })}
          </ul>
        ) : (
          <p className="s1-muted">No months to show yet.</p>
        )}
        <ul className="s1-sch-legend" aria-label="Legend">
          {(Object.keys(STATUS_TEXT) as DisplayStatus[]).map((s) => (
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
              <WindowedBody rows={rows} columns={columns.length + 2} render={(r) => (

                  <tr key={r.record_key}>
                    {columns.map((c) => (
                      <td key={c.key} className={isNumeric(c.key) ? "s1-num" : ""}>
                        {c.key === "date" ? (
                          <>
                            {formatSpan(r.date)}
                            {rowFlag(r) ? <span className="s1-sch-row__flag"> {rowFlag(r)}</span> : null}
                          </>
                        ) : (
                          <ValueLink column={headerLabel(c)} row={r} text={cellText(c.key, r)} source={sourceOf(c.key, r)} onOpenDocument={onOpenDocument} />
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
              )} />
            </table>
          </div>
        ) : (
          <p className="s1-muted">No accepted values on this line yet.</p>
        )}
      </section>

      <details className="s1-panel s1-sch-history">
        <summary>Line history ({schedule.history_total ?? schedule.history.length})</summary>
        {schedule.history.length ? (
          <>
            {(schedule.history_total ?? 0) > schedule.history.length ? <p className="s1-muted">Showing the latest {schedule.history.length}</p> : null}
            <ul>
              {schedule.history.map((h, i) => (
                <li key={`${h.at ?? "none"}:${i}`}>
                  {h.at ? <span className="s1-muted">{formatDateTime(h.at)}</span> : null} {historySentence(h)}
                </li>
              ))}
            </ul>
          </>
        ) : (
          <p className="s1-muted">Nothing has happened on this line yet.</p>
        )}
      </details>
    </section>
  );
}

/* =============================== helpers =============================== */

const plural = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`;
const ACTION_WORDS: Record<Exclude<ScheduleHistoryEntry["action"], "extracted">, string> = {
  accepted: "accepted",
  corrected: "corrected",
  added: "added",
  rejected: "rejected",
  asked_for_more_evidence: "asked for more evidence on",
};

/** The history sentence: who, what, the value, and where it came from. The server sends the parts. */
export function historySentence(h: ScheduleHistoryEntry): string {
  if (h.action === "extracted") {
    return `System extracted ${plural(h.count ?? 0, "value", "values")} from ${plural(h.documents ?? 0, "document", "documents")} placed in this line`;
  }
  const who = h.actor_name || "A reviewer";
  const verb = ACTION_WORDS[h.action] ?? h.action;
  if ((h.count ?? 1) > 1) return `${who} ${verb} ${h.count} values`;
  const value = h.value ? `${h.value}${h.unit ? ` ${h.unit}` : ""}` : "";
  const what = [h.field, value].filter(Boolean).join(" ");
  const from = h.file_name ? ` from ${h.file_name}${h.page ? `, page ${h.page}` : ""}` : "";
  const sentence = `${who} ${verb}${what ? ` ${what}` : " a value"}${from}`;
  return h.superseded_by_reread ? `${sentence} (no longer applies: the document was re-read)` : sentence;
}

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

type CoverageMonth = LineSchedule["coverage"][number];

/** The records read from this month's documents (by date when the record has one). */
function monthRows(m: CoverageMonth, rows: ScheduleRow[]): ScheduleRow[] {
  return rows.filter((r) => {
    if (!m.document_ids.includes(r.document_id)) return false;
    const a = r.date.start?.slice(0, 7);
    const b = r.date.end?.slice(0, 7) ?? a;
    return !a || (a <= m.month && (b ?? a) >= m.month);
  });
}

/** A month whose only values were rejected reads "Rejected", not "Not reviewed". */
function displayStatus(m: CoverageMonth, rows: ScheduleRow[]): DisplayStatus {
  if (m.status !== "not_reviewed") return m.status;
  // Every document of the month must have rows in it, and all of them rejected; otherwise the server's status stands.
  const here = monthRows(m, rows);
  const allRejected = m.document_ids.length > 0 && m.document_ids.every((id) => {
    const mine = here.filter((r) => r.document_id === id);
    return mine.length > 0 && mine.every((r) => r.decision === "rejected");
  });
  return allRejected ? "rejected" : m.status;
}

/** Fields a reviewer rejected on some record of the month, that no record of the month still waits on. Checked per record, not pooled. */
function decidedFields(m: CoverageMonth, rows: ScheduleRow[]): Set<string> {
  const here = monthRows(m, rows);
  const stillWaiting = new Set(here.flatMap((r) => r.waiting_on ?? []));
  return new Set(here.flatMap((r) => r.rejected_fields ?? []).filter((f) => !stillWaiting.has(f)));
}

/** A value the reviewer accepted or corrected. An older server sends no decision; then `accepted` decides. */
export function isAccepted(r: ScheduleRow): boolean {
  return r.decision ? r.decision === "accepted" || r.decision === "edited" : r.accepted;
}

/** The reviewer accepted this record's values but rejected a sibling field, so the record is not counted. Every field is decided. */
function isAcceptedWithRejectedSibling(r: ScheduleRow): boolean {
  return r.decision === "awaiting_other_fields" && !!r.rejected_fields?.length && !r.waiting_on?.length;
}

/** Shown on the page: accepted or corrected values, and accepted values whose record is not counted because a sibling was rejected. */
export function isShown(r: ScheduleRow): boolean {
  return isAccepted(r) || isAcceptedWithRejectedSibling(r);
}

/** A row still has an undecided field: unreviewed, asked for more evidence, or with other fields to decide. Fully decided rows do not wait. */
export function isWaiting(r: ScheduleRow): boolean {
  if (isShown(r) || r.decision === "rejected") return false;
  return r.decision === "not_reviewed" || r.decision === "needs_more_evidence" || !!r.waiting_on?.length || !r.decision;
}

/** Documents that have at least one value still waiting for review. */
export function countWaitingDocuments(rows: ScheduleRow[]): number {
  return new Set(rows.filter(isWaiting).map((r) => r.document_id)).size;
}

/** The word on a shown row: "Edited" for a corrected value, "Not counted" when a sibling field was rejected; null for plain accepted rows. */
export function rowFlag(r: ScheduleRow): string | null {
  if (r.value_changed_since_review) return `${r.decision === "edited" ? "Edited" : "Accepted"} · Value changed since review`;
  if (r.decision === "edited") return "Edited";
  if (isAcceptedWithRejectedSibling(r)) return `Not counted — ${r.rejected_fields?.join(", ")} rejected`;
  return null;
}

function savedByText(r: ScheduleRow): string {
  if (!r.saved_by) return "";
  return `Saved by ${r.saved_by.name}${r.saved_by.at ? ` · ${formatLocal(r.saved_by.at, false)}` : ""}`;
}

function formatDateTime(iso: string): string {
  return formatLocal(iso, true);
}

/** One formatter for every timestamp on the page (Saved by, line history): the reader's local day, so the two never disagree. */
function formatLocal(iso: string, withTime: boolean): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const two = (n: number) => String(n).padStart(2, "0");
  const day = `${two(d.getMonth() + 1)}/${two(d.getDate())}/${two(d.getFullYear() % 100)}`;
  return withTime ? `${day}, ${two(d.getHours())}:${two(d.getMinutes())}` : day;
}

/** Where one cell's value was read; the quantity falls back to the row's own candidate and page. */
function sourceOf(key: string, r: ScheduleRow): ValueSource {
  if (key === "activity_quantity") {
    const q = r.activity_quantity;
    return { candidate_id: q.candidate_id ?? r.candidate_id, page: q.page ?? r.page, sheet: q.sheet, cell: q.cell };
  }
  return r.cells[key] ?? {};
}

/** A value that opens its own source: the review opens at that value, or at the document when nothing says where. */
function ValueLink({ column, row, text, source, onOpenDocument }: { column: string; row: ScheduleRow; text: string; source: ValueSource; onOpenDocument: (documentId: string, valueId?: string) => void }) {
  if (!text) return null;
  const where = source.sheet ? `sheet ${source.sheet}${source.cell ? `, cell ${source.cell}` : ""}` : source.page ? `page ${source.page}` : null;
  const label = `Open ${row.file_name}, ${where ?? "page 1, no page was recorded"} at ${column} ${text}`;
  return (
    <>
      <button
        className="s1-linklike"
        type="button"
        aria-label={label}
        title={where ?? "No page was recorded for this value; the document opens at page 1."}
        onClick={() => onOpenDocument(row.document_id, source.candidate_id ? resolveFieldKey({ candidateId: source.candidate_id, backendFieldId: "" }) : undefined)}
      >
        {text}
      </button>
      {where ? null : <span className="s1-muted s1-sch-nopage"> (no page recorded, opens at page 1)</span>}
    </>
  );
}

/** A month's counted quantity, a computed share of its bills: whole units once it is in the hundreds. */
function formatQuantity(n: number): string {
  return n.toLocaleString(undefined, { maximumFractionDigits: Math.abs(n) >= 100 ? 0 : 3 });
}

/** One identifier: "n of N documents"; opens to group the documents by value, with a Not found group. */
function IdentifierItem({ group, onOpenDocument }: { group: IdentifierGroup; onOpenDocument: (documentId: string) => void }) {
  const [open, setOpen] = useState(false);
  const all = group.documents_with === group.documents_total;
  const summary = group.values.length > 1 ? `${group.values.length} values` : (group.values[0]?.value.trim() || "Not found");
  const count = (n: number) => `${n} ${n === 1 ? "document" : "documents"}`;
  const docLink = (d: { document_id: string; file_name: string; read_by_claude?: boolean }) => (
    <span key={d.document_id} className="s1-sch-ids__doc">
      <button className="s1-linklike" type="button" aria-label={`Open ${d.file_name}`} onClick={() => onOpenDocument(d.document_id)}>
        {d.file_name}
      </button>
      {d.read_by_claude ? <span className="s1-muted"> · {AI_VALUE.readBy}</span> : null}
    </span>
  );
  return (
    <li className={all ? "" : "is-partial"}>
      <button className="s1-sch-ids__toggle" type="button" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
        {open ? <ChevronDown aria-hidden /> : <ChevronRight aria-hidden />}
        <span className="s1-sch-ids__label">{group.label}</span>
        <span className={`s1-sch-ids__value${summary.length <= 24 ? " s1-sch-ids__value--short" : ""}`}>{summary}</span>
        <span className="s1-sch-ids__n">
          {group.documents_with} of {group.documents_total} {group.documents_total === 1 ? "document" : "documents"}
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

/** The table body: every row when there are 100 or fewer, else a window of the rows near the screen (an empty row
 *  stands in for the rest). A windowed table keeps the column widths its first rows gave it (as shares of the table),
 *  so they do not shift as the window moves; below 100 rows the table lays itself out as it always did. */
function WindowedBody({ rows, columns, render }: { rows: ScheduleRow[]; columns: number; render: (row: ScheduleRow) => ReactNode }) {
  const { host, ...win } = useWindowedRows(rows.length);
  const body = useRef<HTMLTableSectionElement | null>(null);
  const frozen = useRef(false);
  const hostRef = (el: HTMLTableSectionElement | null) => {
    body.current = el;
    host(el);
  };
  useLayoutEffect(() => {
    const table = body.current?.closest("table");
    if (!win.enabled || frozen.current || !table) return;
    const heads = [...table.querySelectorAll<HTMLElement>("thead th")];
    const whole = table.getBoundingClientRect().width;
    if (!heads.length || whole <= 0) return;
    heads.forEach((th) => (th.style.width = `${(th.getBoundingClientRect().width / whole) * 100}%`));
    table.style.tableLayout = "fixed";
    frozen.current = true;
  });
  const spacer = (key: string, height: number) => (
    <tr aria-hidden key={`spacer-${key}`}>
      <td colSpan={columns} style={{ height, padding: 0, border: 0 }} />
    </tr>
  );
  return (
    <tbody ref={hostRef} onKeyDown={win.onKeyDown}>
      {win.enabled
        ? win.parts.map((p) =>
            p.type === "spacer" ? (
              spacer(p.key, p.height)
            ) : (
              <WindowRow key={rows[p.index].record_key} props={win.rowProps(p.index)}>
                {render(rows[p.index])}
              </WindowRow>
            ),
          )
        : rows.map((r) => <WindowRow key={r.record_key} props={{}}>{render(r)}</WindowRow>)}
    </tbody>
  );
}

/** The caller's `<tr>` given the window's marker, so the row can be measured and found. */
function WindowRow({ children, props }: { children: ReactNode; props: { "data-win-index"?: number } }) {
  return isValidElement(children) ? cloneElement(children as ReactElement<Record<string, unknown>>, props) : children;
}
