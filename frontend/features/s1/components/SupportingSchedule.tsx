"use client";

import { Fragment, useEffect, useState, type CSSProperties } from "react";

import { getLineSchedule, type CoverageStatus, type IdentifierGroup, type LineSchedule, type ScheduleCell, type ScheduleRow } from "../api/evidenceTree";
import { resolveFieldKey } from "../utils/resolveFieldKey";
import { userFacingApiError } from "../api/s1Backend";
import { ContainerStateSurface } from "./ContainerStateSurface";
import { IconArrowRight, IconChecklist, IconChevronDown, IconChevronLeft, IconChevronRight, IconDocument } from "./icons";

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
/** Count pill per state: shared state chip variant and the words after the number. */
const STATUS_COUNT: Record<CoverageStatus, { chip: string; text: string }> = {
  counted: { chip: "active", text: "counted" },
  counted_in_part: { chip: "partial", text: "in part" },
  not_reviewed: { chip: "open", text: "not reviewed" },
  no_document: { chip: "blocking", text: "no document" },
};
const STATUS_ORDER: CoverageStatus[] = ["counted", "counted_in_part", "not_reviewed", "no_document"];

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
  const showDays = columns.some((c) => c.key === "date") && rows.some((r) => formatDays(r.date));
  const crumbs = [SCOPE_LABELS[line.scope] ?? line.scope, CATEGORY_LABELS[line.category] ?? line.category, line.level2_label, line.label];

  return (
    <section className="s1-content s1-sch">
      <header className="s1-sch-head">
        <div className="s1-sch-head__id">
          <nav className="s1-sch-crumbs" aria-label="Breadcrumb">
            <button className="s1-linklike s1-sch-crumbs__root" type="button" onClick={onBack}>
              Evidence
            </button>
            {crumbs.map((c, i) => (
              <Fragment key={`${i}:${c}`}>
                <span aria-hidden>/</span>
                <span className={i === crumbs.length - 1 ? "s1-sch-crumbs__here" : undefined}>{c}</span>
              </Fragment>
            ))}
          </nav>
          {/* "<Line> · <Level 2>", unless the server's label already names the fuel. */}
          <h1>{line.label.toLowerCase().includes(line.level2_label.toLowerCase()) ? line.label : `${line.label} · ${line.level2_label}`}</h1>
          <p className="s1-sch-meta">
            <span className="s1-sch-meta__kind">Supporting schedule</span>
            {year ? <span>Reporting year {year}</span> : null}
          </p>
        </div>
        <div className="s1-sch-head__actions">
          <button className="s1-button s1-sch-head__back" type="button" onClick={onBack}>
            <IconChevronLeft size={15} aria-hidden />
            Back to Evidence
          </button>
          {schedule.calculated === false ? (
            <p className="s1-muted s1-sch-notcalc">
              {rows.some((r) => r.waiting_on?.length || r.rejected_fields?.length)
                ? "Not calculated yet: values on this line are waiting for review."
                : "No calculation for this line yet."}
            </p>
          ) : (
            <button className="s1-button s1-button--pri s1-sch-head__open" type="button" onClick={() => onOpenCalculationLine(line.key)}>
              Open calculation line
              <IconArrowRight size={15} aria-hidden />
            </button>
          )}
        </div>
      </header>

      <div className="s1-sch-top">
        <CoverageChart coverage={schedule.coverage} fileNames={fileNames} onOpenDocument={onOpenDocument} />

        <section className="s1-sch-ids" aria-labelledby="s1-sch-ids-title">
          <h2 id="s1-sch-ids-title">Source identifiers</h2>
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

      <section className="s1-sch-vals" aria-labelledby="s1-sch-vals-title">
        <div className="s1-sch-vals__head">
          <h2 id="s1-sch-vals-title">Accepted values</h2>
          {schedule.activity_quantity_note ? <p className="s1-sch-vals__note">{schedule.activity_quantity_note}</p> : null}
        </div>
        {rows.length ? (
          <div className="s1-sch-values">
            <table className="s1-table">
              <thead>
                <tr>
                  {columns.map((c) => (
                    <Fragment key={c.key}>
                      <th className={c.key === "date" ? "s1-sch-values__period" : isNumeric(c.key) ? "s1-num" : ""}>{headerLabel(c)}</th>
                      {c.key === "date" && showDays ? <th className="s1-sch-values__days">Days</th> : null}
                    </Fragment>
                  ))}
                  <th>Saved by</th>
                  <th className="s1-sch-values__doc">Document</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => {
                  const flag = rowFlag(r);
                  return (
                    <tr key={r.record_key} className={isPending(r) ? "s1-sch-row--pending" : ""}>
                      {columns.map((c) => (
                        <Fragment key={c.key}>
                          {c.key === "date" ? (
                            <td className="s1-sch-values__period">
                              <span>{formatPeriod(r.date)}</span>
                              {flag ? <span className={isPending(r) ? "s1-state s1-state--open" : "s1-sch-row__flag"}>{flag}</span> : null}
                            </td>
                          ) : (
                            <td className={isNumeric(c.key) ? "s1-num" : ""}>
                              <CellValue cell={c.key === "activity_quantity" ? r.activity_quantity : r.cells[c.key]} />
                            </td>
                          )}
                          {c.key === "date" && showDays ? <td className="s1-sch-values__days">{formatDays(r.date)}</td> : null}
                        </Fragment>
                      ))}
                      <td>{r.saved_by ? <SavedBy row={r} saved={r.saved_by} /> : null}</td>
                      <td className="s1-sch-values__doc">
                        <button
                          className="s1-sch-doclink"
                          type="button"
                          aria-label={`Open ${r.file_name}${r.page ? `, page ${r.page}` : ""} at this value`}
                          title={r.file_name}
                          onClick={() => onOpenDocument(r.document_id, r.candidate_id ? resolveFieldKey({ candidateId: r.candidate_id, backendFieldId: "" }) : undefined)}
                        >
                          <IconDocument size={14} aria-hidden />
                          <span>{r.file_name}</span>
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="s1-sch-vals__empty">No values have been extracted on this line yet.</p>
        )}
      </section>

      <LineHistory history={schedule.history} people={rows.flatMap((r) => (r.saved_by ? [r.saved_by.name] : []))} />
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

function shortMonth(month: string): string {
  const d = new Date(`${month}-01T00:00:00`);
  return Number.isNaN(d.getTime()) ? month : d.toLocaleDateString(undefined, { month: "short" });
}

/** MM/DD/YY from an ISO date or timestamp, without a timezone shift. */
function formatDate(iso: string): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso);
  return m ? `${m[2]}/${m[3]}/${m[1].slice(2)}` : iso;
}

/** "start – end", or one date when the record has no span. */
function formatPeriod(d: ScheduleRow["date"]): string {
  const from = d.start ?? d.end;
  if (!from) return "";
  return d.end && d.start && d.end !== d.start ? `${formatDate(d.start)} – ${formatDate(d.end)}` : formatDate(from);
}

/** "N days" from the server, only for a record with a span. */
function formatDays(d: ScheduleRow["date"]): string {
  const spans = Boolean(d.start && d.end && d.start !== d.end);
  return d.days && spans ? `${d.days} ${d.days === 1 ? "day" : "days"}` : "";
}

/** A cell's value as the server sent it (the page never rounds or regroups a number), with its unit after. */
function CellValue({ cell }: { cell: ScheduleCell | undefined }) {
  if (!cell || cell.value === null || cell.value === undefined || cell.value === "") return null;
  return (
    <>
      <span className="s1-sch-values__qty">{String(cell.value)}</span>
      {cell.unit ? (
        <>
          {" "}
          <span className="s1-sch-values__unit">{cell.unit}</span>
        </>
      ) : null}
    </>
  );
}

const AVATAR_TONES = 4;

/** Same person, same avatar tone: a small hash of the name. */
function avatarTone(name: string): number {
  let n = 0;
  for (const ch of name) n = (n + ch.charCodeAt(0)) % AVATAR_TONES;
  return n;
}

function initials(name: string): string {
  const words = name.replace(/\./g, " ").split(/\s+/).filter(Boolean);
  return ((words[0]?.[0] ?? "") + (words.length > 1 ? words[words.length - 1][0] : "")).toUpperCase();
}

/** Who reviewed the value, labelled the way the design standard says (Accepted by / Corrected by) · date. */
function SavedBy({ row, saved }: { row: ScheduleRow; saved: NonNullable<ScheduleRow["saved_by"]> }) {
  return (
    <span className="s1-sch-who">
      <span className={`s1-team-avatar s1-team-avatar--sm s1-team-avatar--${avatarTone(saved.name)}`} aria-hidden>
        {initials(saved.name)}
      </span>
      <span>
        {row.decision === "edited" ? "Corrected" : "Accepted"} by {saved.name}
        {saved.at ? <span className="s1-sch-who__at"> · {formatDate(saved.at)}</span> : null}
      </span>
    </span>
  );
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
      return [
        r.rejected_fields?.length ? `Rejected: ${r.rejected_fields.join(", ")}` : "",
        r.waiting_on?.length || !r.rejected_fields?.length ? `Waiting on: ${r.waiting_on?.join(", ") || "other fields"}` : "",
      ]
        .filter(Boolean)
        .join(" · ");
    default:
      return r.accepted ? null : "Not reviewed";
  }
}

function formatDateTime(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime())
    ? iso
    : d.toLocaleString(undefined, { year: "numeric", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
}

/** A month's counted quantity, a computed share of its bills: whole units once it is in the hundreds. */
function formatQuantity(n: number): string {
  return n.toLocaleString(undefined, { maximumFractionDigits: Math.abs(n) >= 100 ? 0 : 3 });
}

type CoverageMonth = LineSchedule["coverage"][number];

/** Bar height as a share of the tallest bar: a month with no figure gets a stand-in height, a month with no document a full one. */
function barShare(m: CoverageMonth, max: number): number {
  if (m.status === "no_document") return 1;
  if (m.quantity === null || max <= 0) return 0.4;
  return m.quantity / max;
}

function barValue(m: CoverageMonth): string {
  if (m.quantity !== null) return formatQuantity(m.quantity);
  return m.status === "no_document" ? "None" : "?";
}

/** Coverage as one bar per month, coloured and patterned by state; a month with one document opens it. */
function CoverageChart({
  coverage,
  fileNames,
  onOpenDocument,
}: {
  coverage: CoverageMonth[];
  fileNames: Map<string, string>;
  onOpenDocument: (documentId: string) => void;
}) {
  const max = Math.max(0, ...coverage.map((m) => m.quantity ?? 0));
  const units = [...new Set(coverage.map((m) => m.unit).filter((u): u is string => Boolean(u)))];
  const years = new Set(coverage.map((m) => m.month.slice(0, 4)));
  const label = (m: CoverageMonth) => (years.size > 1 ? monthName(m.month) : shortMonth(m.month));
  const first = coverage[0];
  const last = coverage[coverage.length - 1];
  const range = !first
    ? ""
    : years.size > 1
      ? `${monthName(first.month)} to ${monthName(last.month)}`
      : first === last
        ? monthName(first.month)
        : `${shortMonth(first.month)} to ${shortMonth(last.month)} ${first.month.slice(0, 4)}`;
  const counts = STATUS_ORDER.map((s) => ({ s, n: coverage.filter((m) => m.status === s).length })).filter((c) => c.n > 0);
  const notes = coverage.filter((m) => m.document_ids.length > 1 || m.waiting_on?.length || m.flags?.includes("unconverted"));
  const summary = coverage
    .map((m) => `${monthName(m.month)}: ${STATUS_TEXT[m.status]}${m.quantity !== null ? `, ${formatQuantity(m.quantity)}${m.unit ? ` ${m.unit}` : ""}` : ""}`)
    .join("; ");

  return (
    <section className="s1-sch-cov" aria-labelledby="s1-sch-cov-title">
      <div className="s1-sch-cov__head">
        <h2 id="s1-sch-cov-title">
          Coverage{" "}
          {coverage.length ? <span className="s1-sch-cov__period">Monthly</span> : null}
        </h2>
        {counts.length ? (
          <ul className="s1-sch-cov__counts" aria-label="Coverage counts">
            {counts.map(({ s, n }) => (
              <li key={s} className={`s1-state s1-state--${STATUS_COUNT[s].chip}`}>
                {n} {STATUS_COUNT[s].text}
              </li>
            ))}
          </ul>
        ) : null}
      </div>
      {coverage.length ? (
        <>
          <div className="s1-sch-cov__axis">
            <span>{units.join(" / ")}</span>
            <span>{range}</span>
          </div>
          <div
            className={`s1-sch-chart${coverage.length < 6 ? " s1-sch-chart--few" : ""}`}
            role="group"
            aria-label={`Coverage by month, ${range}. ${summary}.`}
            style={{ "--cols": coverage.length } as CSSProperties}
          >
            {coverage.map((m) => {
              const body = (
                <>
                  <span className="s1-sch-bar__plot">
                    <span className="s1-sch-bar__val">{barValue(m)}</span>
                    <span className="s1-sch-bar__fill" style={{ "--bar": barShare(m, max) } as CSSProperties} />
                  </span>
                  <span className="s1-sch-bar__label">{label(m)}</span>
                </>
              );
              const cls = `s1-sch-bar s1-sch-bar--${m.status}`;
              return m.document_ids.length === 1 ? (
                <button
                  key={m.month}
                  className={cls}
                  type="button"
                  aria-label={`${monthName(m.month)}: ${STATUS_TEXT[m.status]}. Open the document`}
                  onClick={() => onOpenDocument(m.document_ids[0])}
                >
                  {body}
                </button>
              ) : (
                <div key={m.month} className={cls}>
                  {body}
                </div>
              );
            })}
          </div>
          {notes.length ? (
            <ul className="s1-sch-cov__notes">
              {notes.map((m) => (
                <li key={m.month}>
                  <span className="s1-sch-cov__note-month">{monthName(m.month)}</span>
                  {m.flags?.includes("unconverted") ? <span>units differ</span> : null}
                  {m.waiting_on?.length ? <span>Waiting on: {m.waiting_on.join(", ")}</span> : null}
                  {m.document_ids.length > 1
                    ? m.document_ids.map((id, i) => (
                        <button
                          key={id}
                          className="s1-linklike"
                          type="button"
                          aria-label={`${monthName(m.month)}: open ${fileNames.get(id) ?? `document ${i + 1}`}`}
                          onClick={() => onOpenDocument(id)}
                        >
                          {fileNames.get(id) ?? `Document ${i + 1}`}
                        </button>
                      ))
                    : null}
                </li>
              ))}
            </ul>
          ) : null}
        </>
      ) : (
        <p className="s1-muted">No months to show yet.</p>
      )}
    </section>
  );
}

const SYSTEM_ACTOR = "System";

/** Who an event's sentence starts with: a reviewer on this line, or the system; null when it names neither. */
function eventActor(text: string, people: string[]): string | null {
  return [SYSTEM_ACTOR, ...people].find((name) => text.startsWith(`${name} `)) ?? null;
}

/** The line's history, folded by default; each event says who did it, then what, then when. */
function LineHistory({ history, people }: { history: LineSchedule["history"]; people: string[] }) {
  const names = [...new Set(people)].sort((a, b) => b.length - a.length);
  return (
    <section className="s1-sch-hist" aria-labelledby="s1-sch-hist-title">
      <details>
        <summary>
          <IconChevronDown size={16} aria-hidden className="s1-sch-hist__chevron" />
          <h2 id="s1-sch-hist-title">Line history</h2>
          <span className="s1-sch-hist__count">{history.length}</span>
        </summary>
        {history.length ? (
          <ol>
            {history.map((h, i) => {
              const actor = eventActor(h.text, names);
              const rest = actor ? h.text.slice(actor.length) : h.text;
              return (
                <li key={`${h.at}:${i}`}>
                  {actor === SYSTEM_ACTOR ? (
                    <span className="s1-team-avatar s1-team-avatar--sm s1-team-avatar--3" aria-hidden>
                      <IconChecklist size={14} />
                    </span>
                  ) : (
                    <span className={`s1-team-avatar s1-team-avatar--sm s1-team-avatar--${actor ? avatarTone(actor) : 3}`} aria-hidden>
                      {actor ? initials(actor) : null}
                    </span>
                  )}
                  <span className="s1-sch-hist__text">
                    {actor ? <strong>{actor}</strong> : null}
                    {rest}
                  </span>
                  <span className="s1-sch-hist__at">{formatDateTime(h.at)}</span>
                </li>
              );
            })}
          </ol>
        ) : (
          <p className="s1-sch-hist__empty">Nothing has happened on this line yet.</p>
        )}
      </details>
    </section>
  );
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
        <span className="s1-sch-ids__top">
          <span className="s1-sch-ids__label">
            {open ? <IconChevronDown size={14} aria-hidden /> : <IconChevronRight size={14} aria-hidden />}
            {group.label}
          </span>
          <span className="s1-sch-ids__n">
            {group.documents_with} of {group.documents_total} documents
          </span>
        </span>
        <span className="s1-sch-ids__value" title={summary}>
          {summary}
        </span>
        <span className="s1-sch-ids__bar" aria-hidden>
          <span style={{ "--share": group.documents_total ? group.documents_with / group.documents_total : 0 } as CSSProperties} />
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
