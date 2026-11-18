"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { userFacingApiError } from "../api/s1Backend";
import {
  acceptField,
  addRow,
  editField,
  getMethodologyReview,
  prefillMethodology,
  rejectField,
  removeRow,
  revealField,
  revertField,
  sourceLocation,
  type AiStatus,
  type CatalogField,
  type MethodologyRecord,
  type MethodologyReviewData,
  type MethodologyValue,
  type PrefillResult,
} from "../api/methodologyReview";
import { InfoTip } from "./InfoTip";

/**
 * Methodology review in backend mode: what the client's reports state about the inventory
 * boundary and methods, as Claude's suggestions with their quotes, and the reviewer's
 * decision on each. Fields, groups and allowed values all come from the API's catalog.
 * Claude only suggests; nothing counts until a reviewer accepts or edits it.
 */

const STATUS_WORD: Record<string, string> = { pending: "Pending", accepted: "Accepted", edited: "Edited", rejected: "Rejected" };

/** Plain words for why a suggestion batch was dropped; an unknown code shows as its own words. */
const DROP_REASON: Record<string, string> = {
  empty_value: "No value given",
  unknown_line: "Cited a line that isn't in the document",
  quote_not_on_document: "Quote not found in the document, or shorter than 8 characters",
  ambiguous_quote: "Quote appears in more than one place",
  value_not_in_quote: "Value isn't in the quoted text",
  unknown_document: "Cited a document that wasn't read",
  invalid_value: "Value isn't one of the allowed options",
  unknown_field: "Not a methodology field",
};

const ACTION_WORD: Record<string, string> = {
  accept: "Accepted",
  edit: "Edited",
  reject: "Rejected",
  revert: "Reverted",
  add_row: "Row added",
  remove_row: "Row removed",
};

/** Button words for the row groups the API lists (it gives codes only); any other code gets a general label. */
const ADD_ROW_LABEL: Record<string, string> = {
  entities: "Add entity",
  "factor:scope1": "Add Scope 1 factor row",
  "factor:scope2": "Add Scope 2 factor row",
};

/** What an empty row reads, by the server's display state. Never "Not set". */
export function emptyWords(status: string, displayState: string | undefined): string {
  if (status === "rejected") return "Rejected, no value";
  if (displayState === "not_detected") return "Not detected";
  if (displayState === "has_value") return "Not decided yet";
  return "Not checked yet";
}

export function statusWord(status: string | undefined | null): string {
  if (!status) return "Pending";
  return STATUS_WORD[status] ?? "Status unknown";
}

export function dropReasonWords(code: string): string {
  return DROP_REASON[code] ?? code.replaceAll("_", " ");
}

/** Null when Claude can be asked; otherwise the server's sentence for why not. */
export function aiStatusWords(ai: AiStatus): string | null {
  if (ai.enabled && ai.reason_code === null) return null;
  return ai.reason ?? "AI suggestions are not available";
}

function valueText(value: MethodologyValue | undefined): string {
  if (value === null || value === undefined || value === "") return "";
  if (Array.isArray(value)) {
    // A list of entries ({source_type, method}) reads "Source: method"; a list of names reads as a comma list.
    if (value.some((v) => v !== null && typeof v === "object")) {
      return value
        .map((v) =>
          v !== null && typeof v === "object" && !Array.isArray(v) && typeof v.source_type === "string"
            ? `${v.source_type}: ${valueText(v.method as MethodologyValue)}`
            : valueText(v as MethodologyValue)
        )
        .join("; ");
    }
    return value.join(", ");
  }
  if (typeof value === "object" && typeof value.start === "string" && typeof value.end === "string" && Object.keys(value).length === 2) {
    return `${value.start} to ${value.end}`; // a date range
  }
  if (typeof value === "object") {
    return Object.entries(value)
      .map(([, v]) => valueText(v))
      .filter(Boolean)
      .join(" · ");
  }
  return String(value);
}

function when(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString("en-US", { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
}

/** The change-log lines for the activity drawer, from every field's history. */
export function methodologyActivityFrom(data: MethodologyReviewData): { at: string; who: string; what: string }[] {
  const label = new Map(data.catalog.map((f) => [f.fieldId, f.label]));
  return data.fields.flatMap((record) => {
    const name = label.get(record.fieldId) ?? record.fieldId;
    const entries = record.history.map((h) => ({
      at: h.at,
      who: h.by?.name ?? "Reviewer",
      what: `${ACTION_WORD[h.action] ?? h.action.replaceAll("_", " ")} on methodology: ${name}`,
    }));
    if (record.suggestion) entries.push({ at: record.suggestion.suggested_at, who: "Claude", what: `Suggested by Claude on methodology: ${name}` });
    return entries;
  });
}

// The server's limits on what a reviewer can type (docs/api_contract.md).
const TEXT_MAX = 2000;
const LIST_MAX_ITEMS = 20;
const LIST_ITEM_MAX = 100;
const ENTRY_MAX = 10;
const ENTRY_SOURCE_MAX = 60;
const ENTRY_METHOD_MAX = 300;

/** The label an allowed value shows as, where the catalog gives one. */
const optionLabel = (def: CatalogField, key: string | null, value: string) => (key ? def.allowedLabels?.[key]?.[value] : undefined) ?? value;

/** Editor for one field: an enum select, a text field, or one editor per part, as the catalog's parts say. */
function ValueEditor({
  def,
  start,
  onSave,
  onCancel,
  busy,
}: {
  def: CatalogField;
  start: MethodologyValue;
  onSave: (value: MethodologyValue) => void;
  onCancel: () => void;
  busy: boolean;
}) {
  const parts = def.parts ?? null;
  const current = start !== null && typeof start === "object" && !Array.isArray(start) ? start : {};
  const [draft, setDraft] = useState<Record<string, string>>(() =>
    Object.fromEntries((parts ?? []).map((p) => [p.key, valueText(current[p.key] as MethodologyValue)]))
  );
  const [single, setSingle] = useState(valueText(start));

  const [problem, setProblem] = useState<string | null>(null);
  const range = def.kind === "date_range";
  const listed = def.kind === "entry_list";
  const [entries, setEntries] = useState<{ source_type: string; method: string }[]>(() =>
    Array.isArray(start)
      ? start.map((e) => {
          const o = e !== null && typeof e === "object" && !Array.isArray(e) ? e : {};
          return { source_type: valueText(o.source_type as MethodologyValue), method: valueText(o.method as MethodologyValue) };
        })
      : []
  );
  const [dates, setDates] = useState({ start: typeof current.start === "string" ? current.start : "", end: typeof current.end === "string" ? current.end : "" });

  function save() {
    setProblem(null);
    if (listed) {
      const kept = entries.map((e) => ({ source_type: e.source_type.trim(), method: e.method.trim() })).filter((e) => e.source_type || e.method);
      if (kept.some((e) => !e.source_type || !e.method)) return setProblem("Give every entry a source type and a method, or remove it.");
      return onSave(kept);
    }
    if (range) {
      if (!dates.start || !dates.end) return setProblem("Enter both a start date and an end date.");
      return onSave({ start: dates.start, end: dates.end });
    }
    if (!parts) return onSave(single);
    const out: Record<string, MethodologyValue> = {};
    for (const p of parts) {
      const text = draft[p.key] ?? "";
      if (p.kind === "list") {
        const names = text.split(",").map((s) => s.trim()).filter(Boolean);
        if (names.length > LIST_MAX_ITEMS || names.some((n) => n.length > LIST_ITEM_MAX)) {
          return setProblem(`${p.label}: at most ${LIST_MAX_ITEMS} names of ${LIST_ITEM_MAX} characters each.`);
        }
        out[p.key] = names;
      }
      else if (p.kind === "percent") {
        const t = text.trim();
        if (t !== "" && !Number.isFinite(Number(t))) return setProblem(`${p.label}: enter a number from 0 to 100.`);
        out[p.key] = t === "" ? null : Number(t);
      }
      else out[p.key] = text;
    }
    onSave(out);
  }

  const control = (label: string, value: string, set: (v: string) => void, options: string[] | undefined, key: string | null) =>
    options ? (
      <select className="s1-mr-select" aria-label={label} value={value} onChange={(e) => set(e.target.value)}>
        <option value="">Choose</option>
        {options.map((o) => (
          <option key={o} value={o}>
            {optionLabel(def, key, o)}
          </option>
        ))}
      </select>
    ) : (
      <input className="s1-mr-input" aria-label={label} maxLength={TEXT_MAX} value={value} onChange={(e) => set(e.target.value)} />
    );

  return (
    <div className="s1-mb-edit">
      {listed ? (
        <div className="s1-mb-list-edit">
          {entries.map((entry, index) => (
            <span key={index} className="s1-mr-actions">
              <input
                className="s1-mr-input"
                aria-label={`Source type ${index + 1}: ${def.label}`}
                maxLength={ENTRY_SOURCE_MAX}
                value={entry.source_type}
                onChange={(e) => setEntries((all) => all.map((x, i) => (i === index ? { ...x, source_type: e.target.value } : x)))}
              />
              <input
                className="s1-mr-input"
                aria-label={`Method ${index + 1}: ${def.label}`}
                maxLength={ENTRY_METHOD_MAX}
                value={entry.method}
                onChange={(e) => setEntries((all) => all.map((x, i) => (i === index ? { ...x, method: e.target.value } : x)))}
              />
              <button type="button" className="s1-mr-link" aria-label={`Remove entry ${index + 1}: ${def.label}`} onClick={() => setEntries((all) => all.filter((_, i) => i !== index))}>
                Remove
              </button>
            </span>
          ))}
          {entries.length < ENTRY_MAX ? (
            <button type="button" className="s1-button s1-button--compact" onClick={() => setEntries((all) => [...all, { source_type: "", method: "" }])}>
              Add entry
            </button>
          ) : null}
        </div>
      ) : range ? (
        <>
          <label className="s1-mb-part">
            <span className="s1-mr-muted">Start date</span>
            <input className="s1-mr-input" type="date" aria-label={`Start date: ${def.label}`} value={dates.start} onChange={(e) => setDates((d) => ({ ...d, start: e.target.value }))} />
          </label>
          <label className="s1-mb-part">
            <span className="s1-mr-muted">End date</span>
            <input className="s1-mr-input" type="date" aria-label={`End date: ${def.label}`} value={dates.end} onChange={(e) => setDates((d) => ({ ...d, end: e.target.value }))} />
          </label>
        </>
      ) : parts
        ? parts.map((p) => {
            const options = p.allowed ?? (def.allowed && !Array.isArray(def.allowed) ? def.allowed[p.key] : undefined);
            return (
              <label key={p.key} className="s1-mb-part">
                <span className="s1-mr-muted">{p.label}</span>
                {control(`${def.label}: ${p.label}`, draft[p.key] ?? "", (v) => setDraft((d) => ({ ...d, [p.key]: v })), options, p.key)}
              </label>
            );
          })
        : control(`Value: ${def.label}`, single, setSingle, Array.isArray(def.allowed) ? def.allowed : undefined, null)}
      <span className="s1-mr-actions">
        {problem ? <span className="s1-mb-notice" role="alert">{problem}</span> : null}
        <button type="button" className="s1-button s1-button--compact s1-button--pri" disabled={busy} onClick={save}>
          Save
        </button>
        <button type="button" className="s1-button s1-button--compact" onClick={onCancel}>
          Cancel
        </button>
      </span>
    </div>
  );
}

function FieldRow({
  engagementId,
  def,
  record,
  busy,
  onAct,
  onOpenDocument,
}: {
  engagementId: string;
  def: CatalogField;
  record: MethodologyRecord;
  busy: boolean;
  onAct: (run: () => Promise<unknown>) => void;
  onOpenDocument: (documentId: string) => void;
}) {
  const [mode, setMode] = useState<"view" | "edit" | "reject">("view");
  const [reason, setReason] = useState("");
  const { suggestion, decision } = record;
  const status = decision?.status ?? "pending";
  const pendingStatus = status === "pending";
  const decided = status === "accepted" || status === "edited";
  const current = decided ? (Array.isArray(decision?.value) && decision.value.length === 0 ? "No entries" : valueText(decision?.value)) : "";
  // A period saved before it became two dates is kept as the text it was; the reviewer re-enters it as dates.
  const oldText = def.kind === "date_range" && typeof decision?.value === "string" && decision.value ? decision.value : null;
  const suggestionIsOldText = def.kind === "date_range" && typeof suggestion?.value === "string";
  const finish = (run: () => Promise<unknown>) => {
    setMode("view");
    setReason("");
    onAct(run);
  };

  return (
    <li className="s1-mb-row" data-status={status}>
      <div className="s1-mb-main">
        <span className="s1-mr-label">{def.label}</span>
        <span className="s1-mr-value">{oldText ? <span>Recorded as: {oldText}</span> : current || <span className="s1-mr-none">{emptyWords(status, record.displayState)}</span>}</span>
        <span className="s1-mb-status">{statusWord(status)}</span>
        {decision && status !== "pending" ? (
          <span className="s1-mr-muted">
            {decision.by.name} · {when(decision.at)}
          </span>
        ) : null}
        {oldText ? <span className="s1-mr-muted">Enter the start and end dates with Edit.</span> : null}
        {status === "rejected" && decision?.reason ? <span className="s1-mr-muted">Reason: {decision.reason}</span> : null}
      </div>

      {suggestion ? (
        <div className="s1-mb-suggest">
          <span className="s1-chip s1-mb-chip">Suggested by Claude</span>
          <span className="s1-mr-value">{valueText(suggestion.value)}</span>
          {suggestion.evidence?.length ? (
            <ul className="s1-mb-evidence">
              {suggestion.evidence.map((item, index) => (
                <li key={index} className="s1-mb-suggest">
                  <span className="s1-mr-muted">{item.label}</span>
                  <q className="s1-mb-quote">{item.quote}</q>
                  <button type="button" className="s1-mr-link" onClick={() => onOpenDocument(item.document_id)}>
                    {item.file_name}
                    {sourceLocation(item.source_reference) ? `, ${sourceLocation(item.source_reference)}` : ""}
                  </button>
                </li>
              ))}
            </ul>
          ) : (
            <>
              <q className="s1-mb-quote">{suggestion.quote}</q>
              {suggestion.quote_truncated ? <span className="s1-mr-muted">(quote shortened)</span> : null}
              <button type="button" className="s1-mr-link" onClick={() => onOpenDocument(suggestion.document_id)}>
                {suggestion.file_name}
                {sourceLocation(suggestion.source_reference) ? `, ${sourceLocation(suggestion.source_reference)}` : ""}
              </button>
            </>
          )}
        </div>
      ) : null}

      {mode === "edit" ? (
        <ValueEditor
          def={def}
          start={(oldText || suggestionIsOldText ? {} : decided ? decision?.value : suggestion?.value) ?? {}}
          busy={busy}
          onCancel={() => setMode("view")}
          onSave={(value) => finish(() => editField(engagementId, def.fieldId, value))}
        />
      ) : mode === "reject" ? (
        <div className="s1-mb-edit">
          <input
            className="s1-mr-input"
            aria-label={`Reason: ${def.label}`}
            maxLength={500}
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            placeholder="Why is this wrong?"
          />
          <span className="s1-mr-actions">
            <button
              type="button"
              className="s1-button s1-button--compact s1-button--pri"
              disabled={busy || !reason.trim()}
              onClick={() => finish(() => rejectField(engagementId, def.fieldId, reason.trim()))}
            >
              Reject
            </button>
            <button type="button" className="s1-button s1-button--compact" onClick={() => setMode("view")}>
              Cancel
            </button>
          </span>
        </div>
      ) : (
        <span className="s1-mr-actions">
          {pendingStatus && suggestion && !suggestionIsOldText ? (
            <button
              type="button"
              className="s1-button s1-button--compact"
              disabled={busy}
              aria-label={`Accept: ${def.label}`}
              onClick={() => finish(() => acceptField(engagementId, def.fieldId))}
            >
              Accept
            </button>
          ) : null}
          <button type="button" className="s1-button s1-button--compact" disabled={busy} aria-label={`Edit: ${def.label}`} onClick={() => setMode("edit")}>
            Edit
          </button>
          {pendingStatus ? (
            <button type="button" className="s1-button s1-button--compact" disabled={busy} aria-label={`Reject: ${def.label}`} onClick={() => setMode("reject")}>
              Reject
            </button>
          ) : null}
          {!pendingStatus ? (
            <button type="button" className="s1-mr-link" disabled={busy} aria-label={`Revert: ${def.label}`} onClick={() => finish(() => revertField(engagementId, def.fieldId))}>
              Revert
            </button>
          ) : null}
          {record.userAdded ? (
            <button type="button" className="s1-mr-link" disabled={busy} aria-label={`Remove row: ${def.label}`} onClick={() => finish(() => removeRow(engagementId, def.fieldId))}>
              Remove row
            </button>
          ) : null}
        </span>
      )}
    </li>
  );
}

export function BackendMethodologyReview({
  engagementId,
  onOpenDocument,
  onError,
  onActivity,
}: {
  engagementId: string;
  onOpenDocument: (documentId: string) => void;
  onError?: (error: unknown) => boolean;
  onActivity?: (entries: { at: string; who: string; what: string }[]) => void;
}) {
  const [data, setData] = useState<MethodologyReviewData | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [prefilling, setPrefilling] = useState(false);
  const prefillRunning = useRef(false);
  const [result, setResult] = useState<PrefillResult | null>(null);

  const load = useCallback(async () => {
    try {
      const next = await getMethodologyReview(engagementId);
      setData(next);
      setLoadError(null);
      onActivity?.(methodologyActivityFrom(next));
    } catch (error) {
      if (onError?.(error)) return;
      setLoadError(userFacingApiError(error));
    }
  }, [engagementId, onError, onActivity]);

  const onErrorRef = useRef(onError);
  const onActivityRef = useRef(onActivity);
  useEffect(() => {
    onErrorRef.current = onError;
    onActivityRef.current = onActivity;
  });

  useEffect(() => {
    let live = true;
    getMethodologyReview(engagementId)
      .then((next) => {
        if (!live) return;
        setData(next);
        setLoadError(null);
        onActivityRef.current?.(methodologyActivityFrom(next));
      })
      .catch((error: unknown) => {
        if (!live || onErrorRef.current?.(error)) return;
        setLoadError(userFacingApiError(error));
      });
    return () => {
      live = false;
    };
  }, [engagementId]);

  async function act(run: () => Promise<unknown>) {
    setBusy(true);
    setNotice(null);
    try {
      await run();
      await load();
    } catch (error) {
      if (!onError?.(error)) {
        setNotice(userFacingApiError(error));
        await load();
      }
    } finally {
      setBusy(false);
    }
  }

  async function runPrefill() {
    if (prefillRunning.current) return;
    prefillRunning.current = true;
    setConfirming(false);
    setPrefilling(true);
    setBusy(true);
    setNotice(null);
    try {
      setResult(await prefillMethodology(engagementId));
      await load();
    } catch (error) {
      if (!onError?.(error)) setNotice(userFacingApiError(error));
    } finally {
      prefillRunning.current = false;
      setPrefilling(false);
      setBusy(false);
    }
  }

  const records = useMemo(() => new Map((data?.fields ?? []).map((r) => [r.fieldId, r])), [data]);
  // Headings and their order come from the API's groups; rows come in catalog order.
  const groups = useMemo(
    () =>
      (data?.groups ?? [])
        .map((g) => ({ ...g, defs: (data?.catalog ?? []).filter((d) => d.group === g.group && records.get(d.fieldId)?.shown !== false && records.has(d.fieldId)) }))
        .filter((g) => g.defs.length > 0),
    [data, records]
  );

  // Optional rows with nothing on them stay off the page until "Add an item" brings one on.
  const hiddenOptional = (data?.catalog ?? []).filter((d) => records.get(d.fieldId)?.shown === false);

  if (!data) {
    return (
      <section className="s1-content">
        <p role={loadError ? "alert" : "status"}>{loadError ?? "Loading the methodology review."}</p>
      </section>
    );
  }

  const suggestedDocs = result?.documents_read ?? [];
  const aiOff = aiStatusWords(data.ai);
  const droppedEntries = result ? Object.entries(result.dropped).filter(([, n]) => n > 0) : [];
  const pending = data.fields.filter((r) => r.suggestion && (!r.decision || r.decision.status === "pending")).length;

  return (
    <section className="s1-content s1-mb">
      <header className="s1-mb-top">
        <h2 className="s1-mr-card__title">
          Methodology review
          <InfoTip label="Methodology review">
            Claude reads the client&apos;s reports and suggests what they state, each with a quote. Nothing counts until you accept or edit it.
          </InfoTip>
        </h2>
        <span className="s1-mr-muted">{pending} suggested, waiting for review</span>
        <span className="s1-mr-actions">
          <button type="button" className="s1-button s1-button--pri" disabled={busy || prefilling || aiOff !== null} onClick={() => setConfirming(true)}>
            {prefilling ? "Reading the reports…" : "Read the client's reports with Claude"}
          </button>
          {aiOff ? <span className="s1-mb-ai">{aiOff}</span> : null}
        </span>
      </header>

      {confirming ? (
        <div className="s1-mb-confirm" role="alertdialog" aria-label="Read the client's reports">
          <p>
            Claude will read this engagement&apos;s report documents (the GHG inventory report, boundary statement and methodology documents, up to five) and suggest values with quotes. Suggestions need your review before they count. The result will list the documents it read.
          </p>
          <span className="s1-mr-actions">
            <button type="button" className="s1-button s1-button--pri" disabled={prefilling} onClick={() => void runPrefill()}>
              Read the reports
            </button>
            <button type="button" className="s1-button" onClick={() => setConfirming(false)}>
              Cancel
            </button>
          </span>
        </div>
      ) : null}

      {notice ? (
        <p className="s1-mb-notice" role="alert">
          {notice}
        </p>
      ) : null}

      {result ? (
        <p className="s1-mb-result" role="status">
          {result.suggested} suggested
          {droppedEntries.length
            ? `, dropped: ${droppedEntries.map(([code, n]) => `${n}: ${dropReasonWords(code)}`).join("; ")}`
            : ", none dropped"}
          {result.kept_reviewer_decision
            ? `, ${result.kept_reviewer_decision} ${result.kept_reviewer_decision === 1 ? "field kept" : "fields kept"} your decision`
            : ""}
          . Read {suggestedDocs.length}{" "}
          {suggestedDocs.length === 1 ? "document" : "documents"}: {suggestedDocs.map((d) => d.file_name + (d.truncated ? " (only the start was read)" : "")).join(", ")}. Cost ${result.cost_usd.toFixed(result.cost_usd < 0.01 ? 4 : 2)} ({result.model}).
        </p>
      ) : null}

      {data.rowGroups.length ? (
        <span className="s1-mr-actions">
          {data.rowGroups.map((rowGroup) => (
            <button key={rowGroup} type="button" className="s1-button s1-button--compact" disabled={busy} onClick={() => void act(() => addRow(engagementId, rowGroup))}>
              {ADD_ROW_LABEL[rowGroup] ?? "Add row"}
            </button>
          ))}
        </span>
      ) : null}

      {hiddenOptional.length ? (
        <select
          className="s1-mr-input"
          aria-label="Add an item"
          disabled={busy}
          value=""
          onChange={(event) => {
            const fieldId = event.target.value;
            if (fieldId) void act(() => revealField(engagementId, fieldId));
          }}
        >
          <option value="">Add an item</option>
          {hiddenOptional.map((d) => (
            <option key={d.fieldId} value={d.fieldId}>
              {d.label}
            </option>
          ))}
        </select>
      ) : null}

      {groups.map(({ group, label, defs }) => (
        <section key={group} className="s1-mr-card">
          <div className="s1-mr-card__head">
            <h3 className="s1-mr-card__title">{label}</h3>
          </div>
          <ul className="s1-mb-list">
            {defs.map((def) => (
              <FieldRow key={def.fieldId} engagementId={engagementId} def={def} record={records.get(def.fieldId)!} busy={busy} onAct={(run) => void act(run)} onOpenDocument={onOpenDocument} />
            ))}
          </ul>
        </section>
      ))}
    </section>
  );
}
