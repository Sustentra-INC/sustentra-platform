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
  revertField,
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
  quote_not_on_document: "Quote not found in the document",
  ambiguous_quote: "Quote appears in more than one place",
  value_not_in_quote: "Value isn't in the quoted text",
  unknown_document: "Cited a document that wasn't read",
  invalid_value: "Value isn't one of the allowed options",
  unknown_field: "Not a methodology field",
};

/** Button words for the row groups the API lists (it gives codes only); any other code gets a general label. */
const ADD_ROW_LABEL: Record<string, string> = {
  entities: "Add entity",
  "factor:scope1": "Add Scope 1 factor row",
  "factor:scope2": "Add Scope 2 factor row",
};

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
  if (Array.isArray(value)) return value.join(", ");
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
  return data.fields.flatMap((record) =>
    record.history.map((h) => ({
      at: h.at,
      who: h.by?.name ?? "Reviewer",
      what: `${h.action.replaceAll("_", " ")} on methodology: ${label.get(record.fieldId) ?? record.fieldId}`,
    }))
  );
}

// The server's limits on what a reviewer can type (docs/api_contract.md).
const TEXT_MAX = 2000;
const LIST_MAX_ITEMS = 20;
const LIST_ITEM_MAX = 100;

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

  function save() {
    setProblem(null);
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
      else if (p.kind === "percent") out[p.key] = text.trim() === "" ? null : Number(text);
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
      {parts
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
  const current = decided ? valueText(decision?.value) : "";
  const finish = (run: () => Promise<unknown>) => {
    setMode("view");
    setReason("");
    onAct(run);
  };

  return (
    <li className="s1-mb-row" data-status={status}>
      <div className="s1-mb-main">
        <span className="s1-mr-label">{def.label}</span>
        <span className="s1-mr-value">{current || <span className="s1-mr-none">{status === "rejected" ? "Rejected, no value" : "Not set"}</span>}</span>
        <span className="s1-mb-status">{statusWord(status)}</span>
        {decision && status !== "pending" ? (
          <span className="s1-mr-muted">
            {decision.by.name} · {when(decision.at)}
          </span>
        ) : null}
        {status === "rejected" && decision?.reason ? <span className="s1-mr-muted">Reason: {decision.reason}</span> : null}
      </div>

      {suggestion ? (
        <div className="s1-mb-suggest">
          <span className="s1-chip s1-mb-chip">Suggested by Claude</span>
          <span className="s1-mr-value">{valueText(suggestion.value)}</span>
          <q className="s1-mb-quote">{suggestion.quote}</q>
          <button type="button" className="s1-mr-link" onClick={() => onOpenDocument(suggestion.document_id)}>
            {suggestion.file_name}
            {suggestion.source_reference ? `, ${suggestion.source_reference}` : ""}
          </button>
        </div>
      ) : null}

      {mode === "edit" ? (
        <ValueEditor
          def={def}
          start={(decided ? decision?.value : suggestion?.value) ?? {}}
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
          {pendingStatus ? (
            <button
              type="button"
              className="s1-button s1-button--compact"
              disabled={busy || !suggestion}
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
      if (!onError?.(error)) setNotice(userFacingApiError(error));
    } finally {
      setBusy(false);
    }
  }

  async function runPrefill() {
    setConfirming(false);
    setBusy(true);
    setNotice(null);
    try {
      setResult(await prefillMethodology(engagementId));
      await load();
    } catch (error) {
      if (!onError?.(error)) setNotice(userFacingApiError(error));
    } finally {
      setBusy(false);
    }
  }

  const records = useMemo(() => new Map((data?.fields ?? []).map((r) => [r.fieldId, r])), [data]);
  // Headings and their order come from the API's groups; rows come in catalog order.
  const groups = useMemo(
    () =>
      (data?.groups ?? [])
        .map((g) => ({ ...g, defs: (data?.catalog ?? []).filter((d) => d.group === g.group && records.has(d.fieldId)) }))
        .filter((g) => g.defs.length > 0),
    [data, records]
  );

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
          <button type="button" className="s1-button s1-button--pri" disabled={busy || aiOff !== null} onClick={() => setConfirming(true)}>
            Read the client&apos;s reports with Claude
          </button>
          {aiOff ? <span className="s1-mb-ai">{aiOff}</span> : null}
        </span>
      </header>

      {confirming ? (
        <div className="s1-mb-confirm" role="alertdialog" aria-label="Read the client's reports">
          <p>
            Claude will read this engagement&apos;s report documents (the GHG inventory report, boundary statement and methodology documents, up to five) and suggest values with quotes. Suggestions need your review before they count.
          </p>
          <span className="s1-mr-actions">
            <button type="button" className="s1-button s1-button--pri" onClick={() => void runPrefill()}>
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
            ? `, ${droppedEntries.reduce((n, [, c]) => n + c, 0)} dropped (${droppedEntries.map(([code, n]) => `${n}: ${dropReasonWords(code)}`).join("; ")})`
            : ", none dropped"}
          {result.kept_reviewer_decision
            ? `, ${result.kept_reviewer_decision} ${result.kept_reviewer_decision === 1 ? "field kept" : "fields kept"} your decision`
            : ""}
          . Read {suggestedDocs.length}{" "}
          {suggestedDocs.length === 1 ? "document" : "documents"}: {suggestedDocs.map((d) => d.file_name + (d.truncated ? " (only the start was read)" : "")).join(", ")}. Cost ${result.cost_usd.toFixed(2)}.
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
